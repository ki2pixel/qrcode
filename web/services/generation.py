"""Préflight et orchestration du pipeline QR existant."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import generer_index_qr as gi

from web import config
from web.erreurs import ErreurUtilisateur
from web.espace_ram import EspaceRam
from web.registre import REGISTRE
from web.utilitaires import (
    env_sous_processus,
    lignes_utiles,
    lire_fichier_limite,
    mime_pour_nom,
    sanitiser_base,
    sha256,
    tuer_groupe,
)

LIBELLES_CHAMPS = {
    "nom": "Nom du service",
    "dossier": "Dossier",
    "uri": "URL",
    "identifiant": "Identifiant",
}

_VERROU_DEMARRAGE = threading.Lock()


def _format_detecte(entete: list[str]) -> str:
    valeurs = {str(v).lstrip("\ufeff").strip().casefold() for v in entete}
    if valeurs & {"login_password", "login_uri", "login_username"}:
        return "Bitwarden"
    if "title" in valeurs and valeurs & {"group", "url", "username"}:
        return "KeePassXC"
    if valeurs & {"name", "folder"}:
        return "Bitwarden (variante)"
    if valeurs & {"nom", "dossier", "uri", "identifiant"}:
        return "Générique"
    return "Inconnu"


def analyser_donnees(donnees: bytes, nom_fichier: str) -> dict:
    """Analyse un CSV sans le conserver, avec les fonctions du CLI."""
    if not donnees:
        raise ErreurUtilisateur("Le fichier CSV est vide.", 400, "csv_vide")
    if len(donnees) > config.LIMITE_CSV:
        raise ErreurUtilisateur(
            "Le CSV dépasse la limite de 338 000 octets (676 morceaux de 500 octets).",
            400,
            "csv_trop_volumineux",
        )

    base = sanitiser_base(nom_fichier)
    espace = EspaceRam("apercu")
    try:
        chemin = espace.ecrire(f"{base}.csv", donnees, secret=True)
        try:
            raw, entete, enregistrements = gi.charger_enregistrements(chemin)
        except SystemExit as exc:
            message = exc.code if isinstance(exc.code, str) else "CSV invalide."
            raise ErreurUtilisateur(message, 400, "csv_invalide") from exc
        except Exception as exc:
            raise ErreurUtilisateur(
                "Impossible de lire le CSV. Vérifiez qu'il est en UTF-8 valide.",
                400,
                "csv_invalide",
            ) from exc

        if not enregistrements:
            raise ErreurUtilisateur(
                "Le CSV ne contient aucune entrée après l'en-tête.",
                400,
                "csv_sans_entree",
            )
        if not any(
            gi.indice_champ(entete, champ) is not None for champ in gi.ALIASES_CHAMPS
        ):
            raise ErreurUtilisateur(
                "Aucune colonne d'identification reconnue. Formats acceptés : "
                "Bitwarden, KeePassXC ou colonnes génériques (nom, dossier, url, identifiant).",
                400,
                "colonnes_inconnues",
            )

        try:
            total_morceaux, _morceaux = gi.construire_index(
                raw, entete, enregistrements, 500
            )
        except SystemExit as exc:
            message = exc.code if isinstance(exc.code, str) else "CSV invalide."
            raise ErreurUtilisateur(message, 400, "csv_invalide") from exc

        texte = raw.decode("utf-8", errors="replace")
        fin_ligne = gi.detecter_fin_de_ligne(texte)
        quote_all = (raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw).startswith(b'"')
        nb_nbsp = raw.count(b"\xc2\xa0")
        colonnes = [
            LIBELLES_CHAMPS[champ]
            for champ in gi.ALIASES_CHAMPS
            if gi.indice_champ(entete, champ) is not None
        ]
        pages_compact = (total_morceaux + 19) // 20
        pages_confort = (total_morceaux + 11) // 12
        avertissements: list[str] = []
        if nb_nbsp:
            avertissements.append(
                "Le CSV contient des espaces insécables (U+00A0). Binary Eye les "
                "normalisera : une restauration affichera « IDENTIQUE APRÈS "
                "NORMALISATION NBSP »."
            )
        if quote_all:
            avertissements.append(
                "Guillemets systématiques détectés : la restauration préservera ce format."
            )
        if not raw.endswith((b"\r\n", b"\n", b"\r")):
            avertissements.append(
                "Le CSV ne se termine pas par un saut de ligne ; ce détail sera conservé."
            )
        if total_morceaux >= 600:
            avertissements.append(
                f"{total_morceaux} QR codes : l'impression sera longue, mais la limite "
                "de 676 morceaux reste respectée."
            )
        if fin_ligne == "crlf":
            avertissements.append("Fins de ligne CRLF détectées (compatibles).")
        if not shutil.which("qrencode") or not shutil.which("split"):
            avertissements.append(
                "qrencode ou split est absent : la génération échouera tant que ces "
                "outils ne seront pas installés."
            )

        return {
            "base": base,
            "nom_fichier": f"{base}.csv",
            "format": _format_detecte(entete),
            "colonnes_reconnues": colonnes,
            "nombre_colonnes": len(entete),
            "enregistrements": len(enregistrements),
            "morceaux": total_morceaux,
            "taille": len(raw),
            "limite": config.LIMITE_CSV,
            "pages_compact": pages_compact,
            "pages_confort": pages_confort,
            "fin_ligne": fin_ligne,
            "saut_final": raw.endswith((b"\r\n", b"\n", b"\r")),
            "quote_all": quote_all,
            "nb_nbsp": nb_nbsp,
            "sha256": sha256(raw),
            "avertissements": avertissements,
        }
    finally:
        espace.detruire()


@dataclass
class TacheGeneration:
    id: str
    espace: EspaceRam
    stats: dict
    mise_en_page: str
    base: str
    etat: str = "attente"
    etape: str = "En attente"
    progression: int = 0
    messages: list[str] = field(default_factory=list)
    erreur: str | None = None
    resultat: dict | None = None
    derniere_activite: float = field(default_factory=time.time)
    csv_relatif: str = ""
    sortie: Path | None = None
    processus: subprocess.Popen | None = None
    fichiers_internes: dict[str, Path] = field(default_factory=dict)
    _annule: bool = False
    _detruit: bool = False
    _verrou: threading.RLock = field(default_factory=threading.RLock)

    def ajouter_message(self, ligne: str) -> None:
        ligne = (ligne or "").replace("\x1b", "").rstrip()
        if not ligne:
            return
        if len(ligne) > 240:
            ligne = ligne[:239] + "…"
        with self._verrou:
            self.messages.append(ligne)
            if len(self.messages) > 100:
                del self.messages[:-100]

    def instantane(self) -> dict:
        with self._verrou:
            return {
                "id": self.id,
                "etat": self.etat,
                "etape": self.etape,
                "progression": self.progression,
                "messages": list(self.messages[-60:]),
                "erreur": self.erreur,
                "stats": self.stats,
                "resultat": self.resultat,
            }

    def annuler(self) -> None:
        with self._verrou:
            self._annule = True
            processus = self.processus
        if processus is not None:
            tuer_groupe(processus)

    def detruire(self) -> None:
        with self._verrou:
            if self._detruit:
                return
            self._detruit = True
        self.espace.detruire()


def _horodatage() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def demarrer_generation(donnees: bytes, nom_fichier: str, mise_en_page: str) -> TacheGeneration:
    if mise_en_page not in {"compact", "confort", "aucune"}:
        raise ErreurUtilisateur(
            "Mise en page inconnue. Choisissez compact, confort ou aucune.",
            400,
            "mise_en_page_invalide",
        )
    if REGISTRE.generation_active():
        raise ErreurUtilisateur(
            "Une génération est déjà en cours. Attendez sa fin ou annulez-la.",
            409,
            "generation_deja_active",
        )

    with _VERROU_DEMARRAGE:
        if REGISTRE.generation_active():
            raise ErreurUtilisateur(
                "Une génération est déjà en cours. Attendez sa fin ou annulez-la.",
                409,
                "generation_deja_active",
            )
        stats = analyser_donnees(donnees, nom_fichier)
        espace = EspaceRam("gen")
        base = stats["base"]
        csv_relatif = f"travail/{base}.csv"
        espace.ecrire(csv_relatif, donnees, secret=True)
        espace.sous_dossier("sortie")
        sortie = espace.chemin("sortie", f"sauvegarde_qr_{base}_{_horodatage()}")

        tache = TacheGeneration(
            id=_identifiant(),
            espace=espace,
            stats=stats,
            mise_en_page=mise_en_page,
            base=base,
            csv_relatif=csv_relatif,
            sortie=sortie,
        )
        REGISTRE.ajouter_job(tache)
        REGISTRE.soumettre(_executer_generation, tache)
    return tache


def _identifiant() -> str:
    import secrets

    return secrets.token_hex(16)


def _compter_png(sortie: Path) -> int:
    dossier = sortie / "qrcodes"
    if not dossier.is_dir():
        return 0
    return sum(1 for _ in dossier.glob("morceau_??.png"))


def _maj_progression(tache: TacheGeneration) -> None:
    sortie = tache.sortie
    if sortie is None or not sortie.exists():
        tache.etape = "Préparation"
        return
    total = max(1, int(tache.stats.get("morceaux", 1)))
    nombre = _compter_png(sortie)
    if nombre:
        tache.etape = f"QR codes {nombre}/{total}"
        tache.progression = max(tache.progression, 10 + int(70 * nombre / total))
    else:
        tache.etape = "Découpage du CSV"
        tache.progression = max(tache.progression, 6)

    if (sortie / "csv" / "index_enregistrements.csv").is_file():
        tache.etape = "Construction de l'index"
        tache.progression = max(tache.progression, 84)

    if tache.mise_en_page == "aucune":
        if (sortie / "LISEZMOI.txt").is_file():
            tache.etape = "Assemblage de la sauvegarde"
            tache.progression = max(tache.progression, 94)
    elif (sortie / "pdf").is_dir() and any((sortie / "pdf").glob("*.pdf")):
        tache.etape = "Composition des planches"
        tache.progression = max(tache.progression, 94)
    if (sortie / "LISEZMOI.txt").is_file():
        tache.etape = "Finalisation"
        tache.progression = max(tache.progression, 96)


def _lire_meta(sortie: Path) -> dict:
    chemin = sortie / "json" / "index_meta.json"
    donnees = lire_fichier_limite(chemin, config.LIMITE_META)
    try:
        meta = json.loads(donnees.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErreurUtilisateur(
            "Les métadonnées générées sont illisibles.", 500, "meta_invalide"
        ) from exc
    if not isinstance(meta, dict):
        raise ErreurUtilisateur(
            "Les métadonnées générées sont invalides.", 500, "meta_invalide"
        )
    return meta


def _verifier_resultat(tache: TacheGeneration) -> dict:
    sortie = tache.sortie
    assert sortie is not None
    obligatoires = (
        sortie / "LISEZMOI.txt",
        sortie / "csv" / "index_enregistrements.csv",
        sortie / "csv" / "index_morceaux.csv",
        sortie / "json" / "index_meta.json",
    )
    for chemin in obligatoires:
        if not chemin.is_file():
            raise ErreurUtilisateur(
                f"Sortie incomplète : {chemin.name} absent.", 500, "sortie_incomplete"
            )

    meta = _lire_meta(sortie)
    comparaisons = (
        ("sha256", tache.stats["sha256"]),
        ("total_chunks", tache.stats["morceaux"]),
        ("record_count", tache.stats["enregistrements"]),
    )
    for cle, attendu in comparaisons:
        if meta.get(cle) != attendu:
            raise ErreurUtilisateur(
                "La vérification d'intégrité de la génération a échoué "
                f"({cle}). Ne supprimez pas votre CSV d'origine.",
                500,
                "integrite_generation",
            )
    nombre_png = _compter_png(sortie)
    if nombre_png != int(tache.stats["morceaux"]):
        raise ErreurUtilisateur(
            "Le nombre de QR générés ne correspond pas au nombre attendu.",
            500,
            "integrite_generation",
        )

    weasyprint = any(
        (sortie / "pdf" / nom).is_file()
        for nom in ("planches_qr.pdf", "planches_qr_grand.pdf", "index_qr.pdf")
    )
    fichiers: list[dict] = []
    mapping: dict[str, Path] = {}

    def ajouter(cle: str, chemin: Path, libelle: str, type_fichier: str) -> None:
        if chemin.is_file():
            mapping[cle] = chemin
            fichiers.append(
                {
                    "cle": cle,
                    "nom": chemin.name,
                    "libelle": libelle,
                    "taille": chemin.stat().st_size,
                    "type": type_fichier,
                }
            )

    ajouter("pdf-compact", sortie / "pdf" / "planches_qr.pdf", "Planches compactes 4×5", "pdf")
    ajouter("pdf-grand", sortie / "pdf" / "planches_qr_grand.pdf", "Planches confort 3×4", "pdf")
    ajouter("pdf-test", sortie / "pdf" / "test_grand_8qr.pdf", "Page de test 8 QR", "pdf")
    ajouter("pdf-index", sortie / "pdf" / "index_qr.pdf", "Index de recherche", "pdf")
    ajouter("html-index", sortie / "html" / "index_qr.html", "Index HTML", "html")
    if not weasyprint:
        ajouter("html-compact", sortie / "html" / "planches_qr.html", "Planches compactes (HTML)", "html")
        ajouter("html-grand", sortie / "html" / "planches_qr_grand.html", "Planches confort (HTML)", "html")
        ajouter("html-test", sortie / "html" / "test_grand_8qr.html", "Page de test (HTML)", "html")
    ajouter("lisezmoi", sortie / "LISEZMOI.txt", "LISEZMOI de la sauvegarde", "txt")

    archive_erreur: str | None = None
    archive = _creer_archive(tache, sortie)
    if archive is None:
        archive_erreur = "Archive ZIP non créée : espace RAM insuffisant."
    else:
        ajouter("archive", archive, "Archive ZIP complète (non chiffrée)", "zip")

    tache.fichiers_internes = mapping
    for chemin in sortie.rglob("*"):
        if chemin.is_file() and not chemin.is_symlink():
            tache.espace.marquer_secret(chemin)
    return {
        "nom_dossier": sortie.name,
        "sha256": meta.get("sha256", tache.stats["sha256"]),
        "taille_csv": int(meta.get("size", tache.stats["taille"])),
        "enregistrements": int(meta.get("record_count", tache.stats["enregistrements"])),
        "morceaux": int(meta.get("total_chunks", tache.stats["morceaux"])),
        "mise_en_page": tache.mise_en_page,
        "weasyprint": weasyprint,
        "fichiers": fichiers,
        "archive_erreur": archive_erreur,
    }


def _creer_archive(tache: TacheGeneration, sortie: Path) -> Path | None:
    cible = tache.espace.chemin("sortie", f"{sortie.name}.zip")
    try:
        total = sum(
            chemin.stat().st_size
            for chemin in sortie.rglob("*")
            if chemin.is_file() and not chemin.is_symlink()
        )
        libre = shutil.disk_usage(cible.parent).free
        if libre < total + 16 * 1024 * 1024:
            return None
        if cible.exists():
            cible.unlink()
        with zipfile.ZipFile(cible, "w", allowZip64=True) as archive:
            for racine, dossiers, noms in os.walk(sortie, followlinks=False):
                dossiers.sort()
                for nom in sorted(noms):
                    chemin = Path(racine) / nom
                    if chemin.is_symlink() or not chemin.is_file():
                        continue
                    relatif = chemin.relative_to(sortie).as_posix()
                    compression = (
                        zipfile.ZIP_STORED
                        if chemin.suffix.lower() in {".png", ".pdf", ".zip"}
                        else zipfile.ZIP_DEFLATED
                    )
                    archive.write(chemin, relatif, compress_type=compression)
                    info = archive.getinfo(relatif)
                    info.external_attr = (
                        stat.S_IMODE(chemin.stat().st_mode) | stat.S_IFREG
                    ) << 16
        os.chmod(cible, 0o600)
        tache.espace.marquer_secret(cible)
        return cible
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        try:
            cible.unlink()
        except OSError:
            pass
        return None


def _executer_generation(tache: TacheGeneration) -> None:
    processus: subprocess.Popen | None = None
    fil_lecture: threading.Thread | None = None
    try:
        tache.etat = "en_cours"
        tache.etape = "Préparation"
        tache.progression = 2
        assert tache.sortie is not None
        env = env_sous_processus(
            tache.espace,
            {
                "SANS_PLANCHES": "1" if tache.mise_en_page == "aucune" else "0",
            },
        )
        csv_path = tache.espace.chemin(tache.csv_relatif)
        processus = subprocess.Popen(
            [
                str(config.RACINE / "creer_sauvegarde_qr.sh"),
                str(csv_path),
                str(tache.sortie),
            ],
            cwd=str(tache.espace.base),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        tache.processus = processus

        def lire_sortie() -> None:
            if processus is None or processus.stdout is None:
                return
            for ligne in iter(processus.stdout.readline, b""):
                tache.ajouter_message(ligne.decode("utf-8", errors="replace"))

        fil_lecture = threading.Thread(target=lire_sortie, daemon=True)
        fil_lecture.start()

        debut = time.monotonic()
        annule = False
        expire = False
        while processus.poll() is None:
            if tache._annule:
                annule = True
                tuer_groupe(processus)
                break
            if time.monotonic() - debut > config.DUREE_MAX_GENERATION:
                expire = True
                tuer_groupe(processus)
                break
            _maj_progression(tache)
            time.sleep(0.4)

        code = processus.poll()
        if code is None:
            try:
                code = processus.wait(timeout=10)
            except subprocess.TimeoutExpired:
                tuer_groupe(processus)
                code = processus.poll()
        if fil_lecture is not None:
            fil_lecture.join(timeout=2)

        tache.espace.supprimer(tache.csv_relatif, ecraser=True)

        if annule:
            tache.etat = "annule"
            tache.etape = "Annulé"
            tache.progression = 0
            tache.messages.append("Génération annulée par l'utilisateur.")
            tache.detruire()
            return
        if expire:
            tache.etat = "erreur"
            tache.erreur = "La génération a dépassé 30 minutes et a été arrêtée."
            tache.etape = "Délai dépassé"
            tache.detruire()
            return
        if code != 0:
            tache.etat = "erreur"
            tache.etape = "Échec"
            details = lignes_utiles("\n".join(tache.messages[-12:]), maximum=12)
            tache.erreur = (
                f"Le pipeline QR a échoué (code {code}).\n" + "\n".join(details)
            ).strip()
            tache.detruire()
            return

        tache.progression = 98
        tache.etape = "Vérification d'intégrité"
        tache.resultat = _verifier_resultat(tache)
        tache.etat = "succes"
        tache.etape = "Terminé"
        tache.progression = 100
        tache.derniere_activite = time.time()
    except ErreurUtilisateur as exc:
        tache.etat = "erreur"
        tache.etape = "Échec"
        tache.erreur = exc.message
        tache.detruire()
    except Exception as exc:  # pragma: no cover - filet de sécurité
        tache.etat = "erreur"
        tache.etape = "Échec"
        tache.erreur = f"Erreur interne pendant la génération ({type(exc).__name__})."
        tache.detruire()
    finally:
        if processus is not None and processus.poll() is None:
            tuer_groupe(processus)
        tache.processus = None


def obtenir_job(identifiant: str) -> TacheGeneration:
    job = REGISTRE.obtenir_job(identifiant)
    if job is None:
        raise ErreurUtilisateur("Génération introuvable ou expirée.", 404, "job_inconnu")
    return job


def annuler_generation(identifiant: str) -> dict:
    job = obtenir_job(identifiant)
    job.annuler()
    job.derniere_activite = time.time()
    return job.instantane()


def detruire_generation(identifiant: str) -> None:
    if not REGISTRE.supprimer_job(identifiant):
        raise ErreurUtilisateur("Génération introuvable ou expirée.", 404, "job_inconnu")


def fichier_generation(identifiant: str, cle: str) -> tuple[Path, str, str]:
    job = obtenir_job(identifiant)
    if job.etat != "succes" or job.resultat is None:
        raise ErreurUtilisateur(
            "Les fichiers ne sont pas encore disponibles.", 409, "job_non_termine"
        )
    chemin = job.fichiers_internes.get(cle)
    if chemin is None or not chemin.is_file():
        raise ErreurUtilisateur("Fichier introuvable.", 404, "fichier_inconnu")
    return chemin, chemin.name, mime_pour_nom(chemin.name)


def lister_jobs() -> list[dict]:
    resultat = []
    for job in REGISTRE.lister_jobs():
        resultat.append(
            {
                "id": job.id,
                "etat": job.etat,
                "etape": job.etape,
                "progression": job.progression,
                "base": job.base,
                "mise_en_page": job.mise_en_page,
                "nom_dossier": (job.resultat or {}).get("nom_dossier"),
            }
        )
    return resultat
