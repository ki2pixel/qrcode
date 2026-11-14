"""Consultation, extraction ciblée et restauration depuis les scans."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import stat
import threading
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import extraire_entree as ee

from web import config
from web.erreurs import ErreurUtilisateur
from web.espace_ram import EspaceRam
from web.registre import REGISTRE
from web.services import generation
from web.utilitaires import (
    copier_fichier_limite,
    env_sous_processus,
    executer,
    lignes_utiles,
    lire_fichier_limite,
    mime_pour_nom,
    normaliser_nbsp,
    rediger_uri,
)

CHAMPS_SURS = ("nom", "dossier", "uri", "identifiant")
LIBELLES_SURS = {
    "nom": "Nom du service",
    "dossier": "Dossier",
    "uri": "URL",
    "identifiant": "Identifiant",
}
LIBELLES_MASQUES = {
    "login_password": "Mot de passe",
    "password": "Mot de passe",
    "mot_de_passe": "Mot de passe",
    "login_totp": "TOTP (secret)",
    "totp": "TOTP (secret)",
    "otp": "OTP (secret)",
    "notes": "Notes",
    "note": "Notes",
    "fields": "Champs personnalisés",
    "champs": "Champs personnalisés",
    "reprompt": "Demande de confirmation",
}
FICHIERS_REQUIS = (
    "csv/index_enregistrements.csv",
    "csv/index_morceaux.csv",
    "json/index_meta.json",
)


@dataclass
class SessionConsultation:
    id: str
    espace: EspaceRam
    source_nom: str
    meta: dict = field(default_factory=dict)
    index: list[dict] = field(default_factory=list)
    index_path: Path | None = None
    morceaux_path: Path | None = None
    meta_path: Path | None = None
    scans_path: Path | None = None
    scans_info: dict | None = None
    extraction: dict | None = None
    restauration: dict | None = None
    derniere_activite: float = field(default_factory=time.time)
    verrou: threading.RLock = field(default_factory=threading.RLock)

    def instantane(self) -> dict:
        with self.verrou:
            resume_meta = {
                "source": self.meta.get("source"),
                "sha256": self.meta.get("sha256"),
                "size": self.meta.get("size"),
                "record_count": self.meta.get("record_count"),
                "total_chunks": self.meta.get("total_chunks"),
                "chunk_size": self.meta.get("chunk_size"),
            }
            extraction = None
            if self.extraction:
                public = self.extraction.get("public", {})
                extraction = {
                    "id": self.extraction.get("id"),
                    "record_id": self.extraction.get("record_id"),
                    "nb_lignes": len(public.get("lignes", [])),
                }
            restauration = None
            if self.restauration:
                restauration = self.restauration.get("public")
            return {
                "id": self.id,
                "source_nom": self.source_nom,
                "meta": resume_meta,
                "scans": self.scans_info,
                "extraction": extraction,
                "restauration": restauration,
            }

    def detruire(self) -> None:
        self.espace.detruire()


def _identifiant() -> str:
    return secrets.token_hex(16)


def _nouvelle_session(source_nom: str) -> SessionConsultation:
    return SessionConsultation(
        id=_identifiant(),
        espace=EspaceRam("consult"),
        source_nom=source_nom,
    )


# ----------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------
def _source_valide(base: Path) -> bool:
    try:
        for relatif in FICHIERS_REQUIS:
            chemin = base / relatif
            if not chemin.is_file() or chemin.is_symlink():
                return False
        return True
    except OSError:
        return False


def _verifier_source(base: Path) -> None:
    if not base.is_dir():
        raise ErreurUtilisateur(
            "Le dossier de sauvegarde est introuvable.", 400, "source_introuvable"
        )
    for relatif in FICHIERS_REQUIS:
        chemin = base / relatif
        if not chemin.is_file():
            raise ErreurUtilisateur(
                "Ce dossier ne contient pas les index d'une sauvegarde QR "
                f"({relatif} manquant).",
                400,
                "source_invalide",
            )
        try:
            if chemin.is_symlink():
                raise ErreurUtilisateur(
                    "Les liens symboliques ne sont pas acceptés dans une sauvegarde.",
                    400,
                    "source_invalide",
                )
            stats = chemin.stat()
            if not stat.S_ISREG(stats.st_mode):
                raise ErreurUtilisateur(
                    f"{relatif} n'est pas un fichier régulier.", 400, "source_invalide"
                )
            limite = config.LIMITE_META if relatif.endswith(".json") else config.LIMITE_INDEX
            if stats.st_size > limite:
                raise ErreurUtilisateur(
                    f"{relatif} dépasse la taille maximale autorisée.",
                    413,
                    "source_trop_volumineuse",
                )
        except OSError as exc:
            raise ErreurUtilisateur(
                f"Impossible de lire {relatif}.", 400, "source_illisible"
            ) from exc


def detecter_dossiers() -> list[dict]:
    home = Path.home()
    racines = [
        config.RACINE,
        home,
        home / "Documents",
        home / "Téléchargements",
        home / "Downloads",
        home / "Bureau",
        home / "Desktop",
    ]
    vus: set[str] = set()
    resultats: list[tuple[float, dict]] = []
    for racine in racines:
        try:
            if not racine.is_dir():
                continue
            with os.scandir(racine) as entrees:
                for entree in entrees:
                    if not entree.name.startswith("sauvegarde_qr_"):
                        continue
                    if not entree.is_dir(follow_symlinks=False):
                        continue
                    base = Path(entree.path)
                    if not _source_valide(base):
                        continue
                    try:
                        resolu = str(base.resolve())
                    except OSError:
                        continue
                    if resolu in vus:
                        continue
                    vus.add(resolu)
                    try:
                        mtime = base.stat().st_mtime
                    except OSError:
                        mtime = 0.0
                    resultats.append(
                        (mtime, {"nom": base.name, "chemin": resolu})
                    )
        except OSError:
            continue
    resultats.sort(key=lambda item: item[0], reverse=True)
    return [element for _mtime, element in resultats[:40]]


def sources_disponibles() -> dict:
    sessions = []
    for job in REGISTRE.lister_jobs():
        if job.etat == "succes" and job.resultat:
            sessions.append(
                {
                    "id": job.id,
                    "nom": job.resultat.get("nom_dossier") or job.base,
                    "base": job.base,
                    "morceaux": job.resultat.get("morceaux"),
                }
            )
    return {"dossiers": detecter_dossiers(), "sessions": sessions}


def _chemin_dossier(chemin: str) -> Path:
    if not isinstance(chemin, str) or not chemin.strip():
        raise ErreurUtilisateur(
            "Indiquez le chemin d'un dossier de sauvegarde.", 400, "chemin_vide"
        )
    if "\x00" in chemin or "\n" in chemin or "\r" in chemin:
        raise ErreurUtilisateur("Chemin invalide.", 400, "chemin_invalide")
    base = Path(chemin).expanduser()
    if not base.is_absolute():
        base = config.RACINE / base
    try:
        base = base.resolve(strict=True)
    except OSError as exc:
        raise ErreurUtilisateur(
            "Le dossier de sauvegarde est introuvable.", 400, "source_introuvable"
        ) from exc
    _verifier_source(base)
    return base


def _copier_index(session: SessionConsultation, base: Path) -> None:
    sauvegarde = session.espace.sous_dossier("sauvegarde")
    (sauvegarde / "csv").mkdir(parents=True, exist_ok=True, mode=0o700)
    (sauvegarde / "json").mkdir(parents=True, exist_ok=True, mode=0o700)
    mapping = {
        "csv/index_enregistrements.csv": config.LIMITE_INDEX,
        "csv/index_morceaux.csv": config.LIMITE_INDEX,
        "json/index_meta.json": config.LIMITE_META,
    }
    for relatif, limite in mapping.items():
        source = base / relatif
        destination = sauvegarde / relatif
        copier_fichier_limite(source, destination, limite)
        session.espace.marquer_secret(destination)
    session.index_path = sauvegarde / "csv" / "index_enregistrements.csv"
    session.morceaux_path = sauvegarde / "csv" / "index_morceaux.csv"
    session.meta_path = sauvegarde / "json" / "index_meta.json"


def creer_depuis_dossier(chemin: str) -> SessionConsultation:
    base = _chemin_dossier(chemin)
    session = _nouvelle_session(base.name)
    try:
        _copier_index(session, base)
        _charger_index(session)
        REGISTRE.ajouter_consultation(session)
        return session
    except Exception:
        session.detruire()
        raise


def creer_depuis_job(job_id: str) -> SessionConsultation:
    job = generation.obtenir_job(job_id)
    if job.etat != "succes" or job.sortie is None or job.resultat is None:
        raise ErreurUtilisateur(
            "Cette génération n'est pas terminée avec succès.",
            409,
            "generation_non_terminee",
        )
    base = job.sortie
    _verifier_source(base)
    session = _nouvelle_session(job.resultat.get("nom_dossier") or job.base)
    try:
        _copier_index(session, base)
        _charger_index(session)
        REGISTRE.ajouter_consultation(session)
        return session
    except Exception:
        session.detruire()
        raise


def creer_depuis_flux(flux: BinaryIO, max_octets: int) -> SessionConsultation:
    session = _nouvelle_session("archive ZIP")
    try:
        total = 0
        with session.espace.ouvrir_flux("archive.zip", secret=True) as destination:
            while True:
                bloc = flux.read(64 * 1024)
                if not bloc:
                    break
                total += len(bloc)
                if total > max_octets:
                    raise ErreurUtilisateur(
                        "Archive trop volumineuse (maximum 256 Mio).",
                        413,
                        "archive_trop_volumineuse",
                    )
                destination.write(bloc)
        if total < 4:
            raise ErreurUtilisateur("Archive ZIP vide ou invalide.", 400, "zip_invalide")
        _extraire_index_zip(session)
        _charger_index(session)
        REGISTRE.ajouter_consultation(session)
        return session
    except Exception:
        session.detruire()
        raise


def _extraire_index_zip(session: SessionConsultation) -> None:
    archive_path = session.espace.chemin("archive.zip")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > 10_000:
                raise ErreurUtilisateur(
                    "L'archive contient trop de fichiers.", 400, "zip_invalide"
                )
            noms: dict[str, zipfile.ZipInfo] = {}
            compteur: Counter[str] = Counter()
            for info in infos:
                if info.is_dir():
                    continue
                nom = info.filename.replace("\\", "/")
                while nom.startswith("./"):
                    nom = nom[2:]
                nom = nom.lstrip("/")
                if not nom or nom.startswith("__MACOSX/"):
                    continue
                if "/../" in f"/{nom}/" or nom.startswith("../"):
                    raise ErreurUtilisateur(
                        "Archive ZIP invalide (chemin interdit).", 400, "zip_invalide"
                    )
                noms[nom] = info
                compteur[nom] += 1

            candidats: list[str] = []
            for nom in noms:
                if not nom.endswith("json/index_meta.json"):
                    continue
                prefixe = nom[: -len("json/index_meta.json")]
                if (
                    f"{prefixe}csv/index_enregistrements.csv" in noms
                    and f"{prefixe}csv/index_morceaux.csv" in noms
                ):
                    candidats.append(prefixe)
            if not candidats:
                raise ErreurUtilisateur(
                    "L'archive ne contient pas les index d'une sauvegarde QR.",
                    400,
                    "zip_sans_sauvegarde",
                )
            if len(candidats) > 1:
                raise ErreurUtilisateur(
                    "L'archive contient plusieurs sauvegardes. Importez-en une seule.",
                    400,
                    "zip_multiple",
                )
            prefixe = candidats[0]
            mapping = {
                "csv/index_enregistrements.csv": config.LIMITE_INDEX,
                "csv/index_morceaux.csv": config.LIMITE_INDEX,
                "json/index_meta.json": config.LIMITE_META,
            }
            sauvegarde = session.espace.sous_dossier("sauvegarde")
            (sauvegarde / "csv").mkdir(parents=True, exist_ok=True, mode=0o700)
            (sauvegarde / "json").mkdir(parents=True, exist_ok=True, mode=0o700)
            for relatif, limite in mapping.items():
                nom = f"{prefixe}{relatif}"
                if compteur[nom] != 1:
                    raise ErreurUtilisateur(
                        "L'archive contient des index en double.", 400, "zip_invalide"
                    )
                info = noms[nom]
                if info.flag_bits & 0x1:
                    raise ErreurUtilisateur(
                        "Les archives ZIP chiffrées ne sont pas prises en charge.",
                        400,
                        "zip_chiffre",
                    )
                if info.file_size > limite:
                    raise ErreurUtilisateur(
                        f"{relatif} est trop volumineux dans l'archive.",
                        413,
                        "zip_trop_volumineux",
                    )
                try:
                    with archive.open(info) as source:
                        donnees = source.read(limite + 1)
                except (RuntimeError, zipfile.BadZipFile) as exc:
                    raise ErreurUtilisateur(
                        "Impossible de lire l'archive ZIP.", 400, "zip_invalide"
                    ) from exc
                if len(donnees) > limite:
                    raise ErreurUtilisateur(
                        f"{relatif} est trop volumineux dans l'archive.",
                        413,
                        "zip_trop_volumineux",
                    )
                destination = sauvegarde / relatif
                destination.write_bytes(donnees)
                os.chmod(destination, 0o600)
                session.espace.marquer_secret(destination)
            session.index_path = sauvegarde / "csv" / "index_enregistrements.csv"
            session.morceaux_path = sauvegarde / "csv" / "index_morceaux.csv"
            session.meta_path = sauvegarde / "json" / "index_meta.json"
    except zipfile.BadZipFile as exc:
        raise ErreurUtilisateur("Archive ZIP invalide.", 400, "zip_invalide") from exc
    except OSError as exc:
        raise ErreurUtilisateur("Archive ZIP illisible.", 400, "zip_invalide") from exc
    finally:
        session.espace.supprimer("archive.zip", ecraser=True)


def _charger_index(session: SessionConsultation) -> None:
    assert session.meta_path is not None
    assert session.index_path is not None
    assert session.morceaux_path is not None
    try:
        meta = json.loads(
            lire_fichier_limite(session.meta_path, config.LIMITE_META).decode(
                "utf-8-sig"
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErreurUtilisateur(
            "Les métadonnées de la sauvegarde sont illisibles.",
            400,
            "meta_invalide",
        ) from exc
    if not isinstance(meta, dict):
        raise ErreurUtilisateur(
            "Les métadonnées de la sauvegarde sont invalides.", 400, "meta_invalide"
        )
    entete = meta.get("header")
    if not isinstance(entete, list) or not entete or len(entete) > config.LIMITE_COLONNES:
        raise ErreurUtilisateur(
            "L'en-tête CSV est absent ou invalide dans les métadonnées.",
            400,
            "meta_invalide",
        )
    if not all(isinstance(valeur, str) and len(valeur) <= 500 for valeur in entete):
        raise ErreurUtilisateur(
            "L'en-tête CSV contient des valeurs invalides.", 400, "meta_invalide"
        )
    try:
        total_chunks = int(meta.get("total_chunks", 0))
        chunk_size = int(meta.get("chunk_size", 0))
        record_count = int(meta.get("record_count", 0))
        taille = int(meta.get("size", 0))
    except (TypeError, ValueError) as exc:
        raise ErreurUtilisateur(
            "Les compteurs des métadonnées sont invalides.", 400, "meta_invalide"
        ) from exc
    if chunk_size != 500:
        raise ErreurUtilisateur(
            "Cette sauvegarde n'utilise pas la segmentation historique de 500 octets.",
            400,
            "segmentation_incompatible",
        )
    if not (1 <= total_chunks <= 676):
        raise ErreurUtilisateur(
            "Le nombre de morceaux est hors limites (1 à 676).",
            400,
            "meta_invalide",
        )
    if record_count < 0 or record_count > config.MAX_ENTREES_INDEX:
        raise ErreurUtilisateur(
            "Le nombre d'enregistrements est invalide.", 400, "meta_invalide"
        )
    if taille <= 0 or taille > config.LIMITE_CSV:
        raise ErreurUtilisateur(
            "La taille du CSV original est invalide.", 400, "meta_invalide"
        )
    sha = str(meta.get("sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ErreurUtilisateur(
            "L'empreinte SHA-256 est absente ou invalide.", 400, "meta_invalide"
        )

    try:
        texte_index = lire_fichier_limite(
            session.index_path, config.LIMITE_INDEX
        ).decode("utf-8-sig")
        lecteur = csv.DictReader(io.StringIO(texte_index, newline=""))
        champs = set(lecteur.fieldnames or [])
        requis = {
            "record_id",
            "nom",
            "dossier",
            "uri",
            "identifiant",
            "morceaux",
            "morceau_debut",
            "morceau_fin",
        }
        if not requis.issubset(champs):
            raise ErreurUtilisateur(
                "L'index des enregistrements est incomplet.",
                400,
                "index_invalide",
            )
        index: list[dict] = []
        for ligne in lecteur:
            index.append(
                {
                    cle: (ligne.get(cle) or "")
                    for cle in (
                        "record_id",
                        "nom",
                        "dossier",
                        "uri",
                        "identifiant",
                        "morceaux",
                        "morceau_debut",
                        "morceau_fin",
                        "debut_octet",
                        "fin_octet_exclue",
                        "longueur_octets",
                    )
                }
            )
            if len(index) > config.MAX_ENTREES_INDEX:
                raise ErreurUtilisateur(
                    "L'index contient trop d'enregistrements.",
                    413,
                    "index_trop_volumineux",
                )
    except csv.Error as exc:
        raise ErreurUtilisateur(
            "L'index des enregistrements est illisible.", 400, "index_invalide"
        ) from exc

    try:
        texte_morceaux = lire_fichier_limite(
            session.morceaux_path, config.LIMITE_INDEX
        ).decode("utf-8-sig")
        morceaux = list(csv.DictReader(io.StringIO(texte_morceaux, newline="")))
    except csv.Error as exc:
        raise ErreurUtilisateur(
            "L'index des morceaux est illisible.", 400, "index_invalide"
        ) from exc
    if len(morceaux) != total_chunks:
        raise ErreurUtilisateur(
            "L'index des morceaux ne correspond pas au nombre de morceaux attendu.",
            400,
            "index_invalide",
        )

    session.meta = meta
    session.index = index
    if not session.source_nom:
        session.source_nom = str(meta.get("source") or "sauvegarde QR")


# ----------------------------------------------------------------------
# Scans
# ----------------------------------------------------------------------
def uploader_scans(
    session: SessionConsultation, donnees: bytes, nom_fichier: str
) -> dict:
    with session.verrou:
        if not donnees:
            raise ErreurUtilisateur("Le fichier de scans est vide.", 400, "scans_vide")
        if len(donnees) > config.LIMITE_JSON_SCANS:
            raise ErreurUtilisateur(
                "Le fichier de scans dépasse 16 Mio.", 413, "scans_trop_volumineux"
            )
        try:
            data = None
            donnees_stockees = donnees
            for encodage in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    texte = donnees.decode(encodage)
                    data = json.loads(texte)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if encodage != "utf-8-sig":
                    donnees_stockees = json.dumps(
                        data, ensure_ascii=False
                    ).encode("utf-8")
                break
        except Exception as exc:  # pragma: no cover - filet de sécurité
            raise ErreurUtilisateur(
                "Export JSON invalide. Utilisez l'export JSON global de Binary Eye.",
                400,
                "scans_invalide",
            ) from exc
        if data is None:
            raise ErreurUtilisateur(
                "Export JSON invalide. Utilisez l'export JSON global de Binary Eye.",
                400,
                "scans_invalide",
            )
        if not isinstance(data, list):
            raise ErreurUtilisateur(
                "Format d'export inattendu. Utilisez l'export JSON global de Binary Eye.",
                400,
                "scans_invalide",
            )

        total_attendu = int(session.meta.get("total_chunks", 0))
        mapping: dict[str, str] = {}
        invalides = 0
        autres = 0
        doublons = 0
        traduits = False
        for element in data:
            if not isinstance(element, dict):
                invalides += 1
                continue
            contenu = element.get("content")
            if not isinstance(contenu, str):
                invalides += 1
                continue
            contenu = contenu.lstrip("\ufeff")
            if not contenu.startswith("LQR1 "):
                invalides += 1
                continue
            entete, separateur, reste = contenu.partition("\n")
            if not separateur:
                invalides += 1
                continue
            analyse = ee.analyser_entete_lqr(entete)
            if analyse is None:
                invalides += 1
                continue
            morceau, _n, total = analyse
            if total != total_attendu:
                autres += 1
                continue
            if ee.semble_traduit(contenu.encode("utf-8", errors="replace")):
                traduits = True
            if morceau in mapping:
                doublons += 1
            mapping[morceau] = contenu

        if traduits:
            raise ErreurUtilisateur(
                "Ces scans semblent avoir été traduits automatiquement. "
                "Réexportez-les avec Binary Eye, sans traduction.",
                400,
                "scans_traduits",
            )
        if not mapping:
            raise ErreurUtilisateur(
                "Aucun morceau LQR1 exploitable dans cet export.",
                400,
                "scans_sans_morceau",
            )

        attendus = {
            f"morceau_{ee.numero_vers_suffixe(numero)}"
            for numero in range(1, total_attendu + 1)
        }
        manquants = sorted(attendus - set(mapping))
        session.espace.ecrire(
            "scans/binary_eye_all_qr.json", donnees_stockees, secret=True
        )
        session.scans_path = session.espace.chemin("scans", "binary_eye_all_qr.json")
        session.espace.recreer_dossier("sorties")
        session.extraction = None
        session.restauration = None
        session.scans_info = {
            "nom_fichier": nom_fichier,
            "entrees": len(data),
            "morceaux_trouves": len(mapping),
            "morceaux_attendus": total_attendu,
            "manquants": manquants[:24],
            "manquants_total": len(manquants),
            "doublons": doublons,
            "invalides": invalides,
            "autres_sauvegardes": autres,
            "traduits": False,
        }
        session.derniere_activite = time.time()
        return session.scans_info


# ----------------------------------------------------------------------
# Recherche et extraction
# ----------------------------------------------------------------------
def rechercher(session: SessionConsultation, requete: str) -> dict:
    with session.verrou:
        requete = (requete or "").strip()
        if not requete:
            return {"resultats": [], "total": 0, "tronque": False}
        recherche = normaliser_nbsp(requete).casefold()
        est_id = re.fullmatch(r"R\d{1,9}", requete, flags=re.IGNORECASE) is not None
        correspondances: list[dict] = []
        for ligne in session.index:
            if est_id:
                if normaliser_nbsp(ligne.get("record_id", "")).casefold() == recherche:
                    correspondances.append(ligne)
            elif recherche in normaliser_nbsp(ligne.get("nom", "")).casefold():
                correspondances.append(ligne)
        total = len(correspondances)
        resultats = []
        for ligne in correspondances[: config.MAX_RESULTATS_RECHERCHE]:
            resultats.append(
                {
                    "record_id": ligne.get("record_id", ""),
                    "nom": ligne.get("nom", ""),
                    "dossier": ligne.get("dossier", ""),
                    "uri": rediger_uri(ligne.get("uri", "")),
                    "identifiant": ligne.get("identifiant", ""),
                    "morceaux": ligne.get("morceaux", ""),
                    "morceau_debut": ligne.get("morceau_debut", ""),
                    "morceau_fin": ligne.get("morceau_fin", ""),
                }
            )
        session.derniere_activite = time.time()
        return {
            "resultats": resultats,
            "total": total,
            "tronque": total > len(resultats),
        }


def _libelle_masque(cle: str) -> str:
    return LIBELLES_MASQUES.get(cle.casefold(), cle)


def _indices_surs(entete: list[str]) -> dict[int, str]:
    resultat: dict[int, str] = {}
    for champ in CHAMPS_SURS:
        index = ee.indice_champ(entete, champ)
        if index is not None:
            resultat[index] = LIBELLES_SURS[champ]
    return resultat


def extraire(session: SessionConsultation, record_id: str) -> dict:
    with session.verrou:
        if not re.fullmatch(r"R\d{1,9}", record_id or "", flags=re.IGNORECASE):
            raise ErreurUtilisateur(
                "Identifiant invalide. Exemple : R123.", 400, "id_invalide"
            )
        record_id = record_id.upper()
        if session.scans_path is None:
            raise ErreurUtilisateur(
                "Importez d'abord l'export JSON de Binary Eye.",
                409,
                "scans_absents",
            )
        if session.index_path is None or session.morceaux_path is None or session.meta_path is None:
            raise ErreurUtilisateur("Sauvegarde incomplète.", 500, "source_invalide")

        sorties = session.espace.recreer_dossier("sorties/extraction")
        travail = session.espace.sous_dossier("travail")
        env = env_sous_processus(session.espace)
        args = [
            config.PYTHON_SYSTEME,
            "-B",
            str(config.RACINE / "extraire_entree.py"),
            "--id",
            record_id,
            "--scans",
            str(session.espace.chemin("scans")),
            "--index",
            str(session.index_path),
            "--morceaux",
            str(session.morceaux_path),
            "--meta",
            str(session.meta_path),
            "--sortie",
            str(sorties / "entree.csv"),
        ]
        code, sortie, erreur = executer(
            args,
            cwd=travail,
            env=env,
            timeout=config.DUREE_MAX_EXTRACTION,
        )
        if code != 0:
            details = lignes_utiles(
                (sortie + "\n" + erreur).strip(), maximum=10
            )
            raise ErreurUtilisateur(
                "Extraction impossible.\n" + "\n".join(details),
                400,
                "extraction_impossible",
            )

        fichiers = sorted(
            sorties.glob("entree*.csv"),
            key=lambda chemin: (
                0
                if chemin.name == "entree.csv"
                else int(re.search(r"_(\d+)\.csv$", chemin.name).group(1))
                if re.search(r"_(\d+)\.csv$", chemin.name)
                else 0
            ),
        )
        if not fichiers:
            raise ErreurUtilisateur(
                "Le script n'a produit aucun fichier d'entrée.", 500, "extraction_vide"
            )
        for chemin in fichiers:
            session.espace.marquer_secret(chemin)

        lignes_internes: list[dict] = []
        lignes_publiques: list[dict] = []
        for fichier in fichiers:
            try:
                texte = lire_fichier_limite(fichier, config.LIMITE_CSV + 4096).decode(
                    "utf-8-sig"
                )
                rows = list(csv.reader(io.StringIO(texte, newline="")))
            except (UnicodeDecodeError, csv.Error) as exc:
                raise ErreurUtilisateur(
                    "Le fichier extrait est illisible.", 500, "extraction_invalide"
                ) from exc
            if len(rows) < 2:
                continue
            entete = rows[0]
            indices_surs = _indices_surs(entete)
            for index_ligne, row in enumerate(rows[1:]):
                visibles = []
                for index, libelle in indices_surs.items():
                    visibles.append(
                        {
                            "cle": entete[index],
                            "libelle": libelle,
                            "valeur": row[index] if index < len(row) else "",
                        }
                    )
                masques = [
                    {"cle": valeur, "libelle": _libelle_masque(valeur)}
                    for index, valeur in enumerate(entete)
                    if index not in indices_surs
                ]
                lignes_internes.append(
                    {
                        "fichier": str(fichier),
                        "index": index_ligne,
                        "entete": entete,
                        "indices_surs": indices_surs,
                    }
                )
                lignes_publiques.append(
                    {
                        "index": len(lignes_publiques),
                        "visibles": visibles,
                        "masques": masques,
                    }
                )

        if not lignes_publiques:
            raise ErreurUtilisateur(
                "Aucune ligne extraite pour cet identifiant.", 404, "entree_introuvable"
            )

        identifiant_extraction = secrets.token_hex(8)
        public = {
            "extraction_id": identifiant_extraction,
            "record_id": record_id,
            "nb_lignes": len(lignes_publiques),
            "lignes": lignes_publiques,
            "fichiers": [chemin.name for chemin in fichiers],
        }
        session.extraction = {
            "id": identifiant_extraction,
            "record_id": record_id,
            "files": [str(chemin) for chemin in fichiers],
            "lignes": lignes_internes,
            "public": public,
        }
        session.derniere_activite = time.time()
        return public


def reveler(session: SessionConsultation, extraction_id: str, ligne: int) -> dict:
    with session.verrou:
        if not session.extraction or session.extraction.get("id") != extraction_id:
            raise ErreurUtilisateur(
                "Extraction introuvable ou remplacée.", 404, "extraction_inconnue"
            )
        lignes = session.extraction.get("lignes", [])
        if not isinstance(ligne, int) or ligne < 0 or ligne >= len(lignes):
            raise ErreurUtilisateur("Ligne invalide.", 400, "ligne_invalide")
        interne = lignes[ligne]
        try:
            texte = lire_fichier_limite(
                Path(interne["fichier"]), config.LIMITE_CSV + 4096
            ).decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(texte, newline="")))
            entete = rows[0]
            row = rows[interne["index"] + 1]
        except (OSError, UnicodeDecodeError, csv.Error, IndexError) as exc:
            raise ErreurUtilisateur(
                "Impossible de relire le fichier extrait.", 500, "extraction_invalide"
            ) from exc
        indices_surs = interne["indices_surs"]
        champs = []
        for index, valeur in enumerate(entete):
            if index in indices_surs:
                continue
            champs.append(
                {
                    "cle": valeur,
                    "libelle": _libelle_masque(valeur),
                    "valeur": row[index] if index < len(row) else "",
                }
            )
        session.derniere_activite = time.time()
        return {"extraction_id": extraction_id, "ligne": ligne, "champs": champs}


def fichier_extraction(session: SessionConsultation) -> tuple[Path, str, str]:
    with session.verrou:
        if not session.extraction:
            raise ErreurUtilisateur(
                "Aucune extraction disponible.", 404, "extraction_inconnue"
            )
        fichiers = [Path(chemin) for chemin in session.extraction.get("files", [])]
        fichiers = [chemin for chemin in fichiers if chemin.is_file()]
        if not fichiers:
            raise ErreurUtilisateur(
                "Les fichiers extraits ont été purgés.", 404, "fichier_inconnu"
            )
        if len(fichiers) == 1:
            chemin = fichiers[0]
            return chemin, chemin.name, mime_pour_nom(chemin.name)
        cible = session.espace.chemin(
            "sorties", f"extraction_{session.extraction['id']}.zip"
        )
        if not cible.exists():
            with zipfile.ZipFile(cible, "w", allowZip64=True) as archive:
                for chemin in fichiers:
                    archive.write(chemin, chemin.name)
            os.chmod(cible, 0o600)
            session.espace.marquer_secret(cible)
        return cible, cible.name, "application/zip"


# ----------------------------------------------------------------------
# Restauration
# ----------------------------------------------------------------------
def _extraire_hash(texte: str, motif: str) -> str | None:
    resultat = re.search(motif, texte)
    return resultat.group(1) if resultat else None


def restaurer(session: SessionConsultation) -> dict:
    with session.verrou:
        if session.scans_path is None:
            raise ErreurUtilisateur(
                "Importez d'abord l'export JSON de Binary Eye.",
                409,
                "scans_absents",
            )
        if session.morceaux_path is None or session.meta_path is None:
            raise ErreurUtilisateur("Sauvegarde incomplète.", 500, "source_invalide")
        sorties = session.espace.sous_dossier("sorties")
        sortie = sorties / "restauration.csv"
        try:
            sortie.unlink()
        except OSError:
            pass
        travail = session.espace.sous_dossier("travail")
        env = env_sous_processus(session.espace)
        args = [
            config.PYTHON_SYSTEME,
            "-B",
            str(config.RACINE / "restaurer_sauvegarde.py"),
            "--scans",
            str(session.espace.chemin("scans")),
            "--morceaux",
            str(session.morceaux_path),
            "--meta",
            str(session.meta_path),
            "--sortie",
            str(sortie),
        ]
        code, stdout, stderr = executer(
            args,
            cwd=travail,
            env=env,
            timeout=config.DUREE_MAX_RESTAURATION,
        )
        texte = (stdout + "\n" + stderr).strip()
        if code not in (0, 1):
            details = lignes_utiles(texte, maximum=12)
            raise ErreurUtilisateur(
                "Restauration impossible.\n" + "\n".join(details),
                500,
                "restauration_impossible",
            )
        resultat = re.search(r"Résultat\s*:\s*(.+)", texte)
        if resultat is None:
            details = lignes_utiles(texte, maximum=12)
            raise ErreurUtilisateur(
                "Le script de restauration n'a pas produit de verdict lisible."
                + ("\n" + "\n".join(details) if details else ""),
                400,
                "restauration_invalide",
            )
        libelle = resultat.group(1).strip()
        if libelle.startswith("IDENTIQUE APRÈS NORMALISATION NBSP"):
            statut = "nbsp"
        elif libelle.startswith("IDENTIQUE"):
            statut = "identique"
        elif libelle.startswith("DIFFÉRENT"):
            statut = "different"
        else:
            raise ErreurUtilisateur(
                f"Verdict de restauration inconnu : {libelle}", 500, "restauration_invalide"
            )

        if not sortie.is_file():
            raise ErreurUtilisateur(
                "Le CSV restauré n'a pas été écrit.", 500, "restauration_invalide"
            )
        session.espace.marquer_secret(sortie)

        sha_generique = _extraire_hash(texte, r"SHA-256\s*:\s*([0-9a-f]{64})")
        sha_restaure = _extraire_hash(texte, r"SHA-256 restauré\s*:\s*([0-9a-f]{64})")
        sha_sans_nbsp = _extraire_hash(
            texte, r"SHA-256 sans NBSP\s*:\s*([0-9a-f]{64})"
        )
        sha_obtenu = sha_restaure or sha_generique
        taille_obtenue = sortie.stat().st_size
        nb_obtenu = None
        match_nb = re.search(r"Enregistrements\s*:\s*(\d+)", texte)
        if match_nb:
            nb_obtenu = int(match_nb.group(1))

        details = [
            ligne
            for ligne in lignes_utiles(texte, maximum=40)
            if ligne.startswith(
                (
                    "Résultat",
                    "SHA-256",
                    "attendu sans NBSP",
                    "Taille",
                    "Enregistrements",
                    "Détail",
                )
            )
        ]
        public = {
            "statut": statut,
            "libelle": "IDENTIQUE APRÈS NORMALISATION NBSP"
            if statut == "nbsp"
            else ("IDENTIQUE" if statut == "identique" else "DIFFÉRENT"),
            "sha_attendu": session.meta.get("sha256"),
            "sha_obtenu": sha_obtenu,
            "sha_sans_nbsp_attendu": session.meta.get("sha256_sans_nbsp"),
            "sha_sans_nbsp_obtenu": sha_sans_nbsp,
            "taille_obtenue": taille_obtenue,
            "taille_attendue": session.meta.get("size"),
            "taille_sans_nbsp": session.meta.get("size_sans_nbsp"),
            "enregistrements_obtenus": nb_obtenu,
            "enregistrements_attendus": session.meta.get("record_count"),
            "details": details,
            "fichier_disponible": True,
        }
        session.restauration = {
            "statut": statut,
            "chemin": str(sortie),
            "public": public,
        }
        session.derniere_activite = time.time()
        return public


def fichier_restauration(session: SessionConsultation) -> tuple[Path, str, str]:
    with session.verrou:
        if not session.restauration:
            raise ErreurUtilisateur(
                "Aucune restauration disponible.", 404, "restauration_inconnue"
            )
        chemin = Path(session.restauration["chemin"])
        if not chemin.is_file():
            raise ErreurUtilisateur(
                "Le CSV restauré a été purgé.", 404, "fichier_inconnu"
            )
        return chemin, chemin.name, "text/csv; charset=utf-8"


def obtenir_session(identifiant: str) -> SessionConsultation:
    session = REGISTRE.obtenir_consultation(identifiant)
    if session is None:
        raise ErreurUtilisateur(
            "Session de consultation introuvable ou expirée.", 404, "session_inconnue"
        )
    return session


def detruire_session(identifiant: str) -> None:
    if not REGISTRE.supprimer_consultation(identifiant):
        raise ErreurUtilisateur(
            "Session de consultation introuvable ou expirée.", 404, "session_inconnue"
        )


def lister_resumees() -> list[dict]:
    return [session.instantane() for session in REGISTRE.lister_consultations()]
