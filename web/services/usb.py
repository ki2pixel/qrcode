"""Assistance coffre USB : détection, démontage non privilégié et commandes."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from web import config
from web.erreurs import ErreurUtilisateur
from web.utilitaires import lignes_utiles

TYPES_DANGEREUX = {
    "lvm",
    "raid0",
    "raid1",
    "raid5",
    "raid6",
    "raid10",
    "crypt",
    "dm",
    "mpath",
    "linear",
    "multipath",
}
FSTYPES_DANGEREUX = {
    "lvm2_member",
    "linux_raid_member",
    "isw_raid_member",
    "ddf_raid_member",
    "mpath_member",
    "bcache",
}
DEPENDANCES = (
    ("cryptsetup", "Chiffrement LUKS2"),
    ("age", "Chiffrement de l'en-tête et des capsules"),
    ("zstd", "Compression des capsules"),
    ("par2", "Redondance Reed-Solomon"),
    ("qrencode", "Génération des QR"),
    ("python3", "Scripts Python"),
    ("parted", "Partitionnement GPT"),
    ("mkfs.ext4", "Système de fichiers du coffre"),
    ("mkfs.exfat", "Partition de secours URGENCE_QR"),
    ("wipefs", "Effacement des signatures"),
    ("rsync", "Synchronisation vers le coffre"),
    ("sha256sum", "Vérification d'intégrité"),
    ("shred", "Effacement des fichiers temporaires"),
    ("lsblk", "Identification des supports"),
    ("findmnt", "Contrôle des montages"),
    ("mount", "Montage"),
    ("umount", "Démontage"),
    ("runuser", "Exécution sous l'utilisateur réel"),
    ("systemctl", "Isolation de CUPS"),
    ("lp", "Impression"),
)


def _lsblk() -> list[dict]:
    try:
        resultat = subprocess.run(
            [
                "lsblk",
                "--json",
                "--bytes",
                "--output",
                "NAME,TYPE,MODEL,SERIAL,SIZE,TRAN,RM,RO,FSTYPE,MOUNTPOINTS,LABEL,PTTYPE,PARTLABEL",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
            text=True,
            env={**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErreurUtilisateur(
            "Impossible de lire la liste des périphériques avec lsblk.",
            500,
            "lsblk_indisponible",
        ) from exc
    if resultat.returncode != 0:
        raise ErreurUtilisateur(
            "lsblk n'a pas pu lister les périphériques.",
            500,
            "lsblk_indisponible",
        )
    try:
        data = json.loads(resultat.stdout)
    except json.JSONDecodeError as exc:
        raise ErreurUtilisateur(
            "La sortie de lsblk est illisible.", 500, "lsblk_invalide"
        ) from exc
    blockdevices = data.get("blockdevices")
    if not isinstance(blockdevices, list):
        return []
    return blockdevices


def _swaps() -> tuple[set[str], list[dict], bool]:
    noms: set[str] = set()
    details: list[dict] = []
    disque_actif = False
    try:
        with open("/proc/swaps", encoding="utf-8") as flux:
            lignes = flux.readlines()
    except OSError:
        return noms, details, False
    for ligne in lignes[1:]:
        elements = ligne.split()
        if not elements:
            continue
        nom = elements[0]
        noms.add(nom)
        disque = not Path(nom).name.startswith("zram")
        if disque:
            disque_actif = True
        details.append(
            {
                "nom": nom,
                "type": elements[1] if len(elements) > 1 else "",
                "taille": int(elements[2]) if len(elements) > 2 and elements[2].isdigit() else 0,
                "disque": disque,
            }
        )
    return noms, details, disque_actif


def swap_disque_actif() -> bool:
    return _swaps()[2]


def _monter_arbre(noeud: dict):
    yield noeud
    for enfant in noeud.get("children") or []:
        yield from _monter_arbre(enfant)


def _points_montage(noeuds: list[dict]) -> list[str]:
    points: list[str] = []
    for noeud in noeuds:
        valeurs = noeud.get("mountpoints")
        if valeurs is None:
            valeurs = [noeud.get("mountpoint")]
        elif isinstance(valeurs, str):
            valeurs = [valeurs]
        for point in valeurs or []:
            if point:
                points.append(str(point))
    return points


def _a_des_holders(nom: str) -> bool:
    if not nom or "/" in nom:
        return False
    dossier = Path("/sys/class/block") / nom / "holders"
    try:
        return dossier.is_dir() and any(dossier.iterdir())
    except OSError:
        return False


def _bool(valeur) -> bool:
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, str):
        return valeur.strip().lower() in {"1", "true", "yes", "oui"}
    return bool(valeur)


def _entier(valeur) -> int:
    try:
        return int(valeur or 0)
    except (TypeError, ValueError):
        return 0


def _analyser(noeud: dict, swaps: set[str]) -> dict:
    noeuds = list(_monter_arbre(noeud))
    noms = [str(item.get("name") or "") for item in noeuds]
    types = {str(item.get("type") or "") for item in noeuds}
    fstypes = {str(item.get("fstype") or "").casefold() for item in noeuds}
    points = _points_montage(noeuds)
    taille = _entier(noeud.get("size"))
    ro = _bool(noeud.get("ro"))
    rm = _bool(noeud.get("rm"))
    tran = str(noeud.get("tran") or "")
    type_principal = str(noeud.get("type") or "")
    systeme = any(point in config.MONTAGES_SYSTEME for point in points)
    monte = bool(points)
    swap = any(nom in swaps for nom in noms)
    holders = any(_a_des_holders(nom) for nom in noms)
    danger = bool(types & TYPES_DANGEREUX) or bool(fstypes & FSTYPES_DANGEREUX)
    amovible = rm or tran == "usb"
    est_loop = type_principal == "loop"

    raisons: list[str] = []
    if est_loop:
        pass
    elif type_principal != "disk":
        raisons.append("Ce n'est pas un disque entier (/dev/sdX).")
    if taille < 1024 * 1024 * 1024:
        raisons.append("Taille inférieure à 1 Gio.")
    if ro:
        raisons.append("Le périphérique est protégé en écriture.")
    if not est_loop and not amovible:
        raisons.append("Le périphérique n'est pas identifié comme amovible/USB.")
    if monte:
        raisons.append("Une partition est montée : démontez-la d'abord.")
    if systeme:
        raisons.append("Ce périphérique contient le système en cours d'exécution.")
    if swap:
        raisons.append("Une partition de ce disque est utilisée comme swap.")
    if holders:
        raisons.append("Le périphérique a des dépendances noyau (holders).")
    if danger:
        raisons.append("Le périphérique participe à un volume LVM/RAID/dm/crypt.")

    candidat = (
        not est_loop
        and type_principal == "disk"
        and taille >= 1024 * 1024 * 1024
        and not ro
        and amovible
        and not monte
        and not systeme
        and not swap
        and not holders
        and not danger
    )
    sur_sans_montage = (
        taille >= 1024 * 1024 * 1024
        and not ro
        and (amovible or est_loop)
        and not systeme
        and not swap
        and not holders
        and not danger
    )
    a_demonter = sur_sans_montage and monte
    test = (
        est_loop
        and taille >= 1024 * 1024 * 1024
        and not ro
        and not monte
        and not systeme
        and not swap
        and not holders
        and not danger
    )

    partitions = []
    for item in noeuds[1:]:
        partitions.append(
            {
                "nom": str(item.get("name") or ""),
                "chemin": f"/dev/{item.get('name')}",
                "type": item.get("type"),
                "label": item.get("label"),
                "partlabel": item.get("partlabel"),
                "fstype": item.get("fstype"),
                "taille": _entier(item.get("size")),
                "mountpoints": _points_montage([item]),
            }
        )
    partitions_montees = [part for part in partitions if part["mountpoints"]]
    # Clé sans table de partition (superfloppy) montée directement : traiter
    # le disque entier comme la cible de démontage, sans élargir les règles.
    if not partitions and points:
        partitions_montees = [
            {
                "nom": str(noeud.get("name") or ""),
                "chemin": f"/dev/{noeud.get('name')}",
                "type": type_principal,
                "label": noeud.get("label"),
                "partlabel": None,
                "fstype": noeud.get("fstype"),
                "taille": taille,
                "mountpoints": points,
                "disque_entier": True,
            }
        ]

    return {
        "nom": str(noeud.get("name") or ""),
        "chemin": f"/dev/{noeud.get('name')}",
        "type": type_principal,
        "modele": str(noeud.get("model") or "Modèle inconnu"),
        "serie": str(noeud.get("serial") or ""),
        "taille": taille,
        "transport": tran or ("loopback" if est_loop else "inconnu"),
        "amovible": amovible,
        "ro": ro,
        "monte": monte,
        "systeme": systeme,
        "swap": swap,
        "holders": holders,
        "danger": danger,
        "partitions": partitions,
        "partitions_montees": partitions_montees,
        "raisons": raisons,
        "candidat": candidat,
        "a_demonter": a_demonter,
        "test": test,
        "statut": (
            "test"
            if test
            else "candidat"
            if candidat
            else "a_demonter"
            if a_demonter
            else "ecarte"
        ),
        "confirmation": str(noeud.get("serial") or noeud.get("name") or "").strip(),
    }


def _dependances() -> list[dict]:
    resultat = []
    for commande, description in DEPENDANCES:
        resultat.append(
            {
                "commande": commande,
                "description": description,
                "disponible": shutil.which(commande) is not None,
            }
        )
    return resultat


def peripheriques() -> dict:
    noeuds = _lsblk()
    swaps, swap_details, swap_disque = _swaps()
    analyses = []
    for noeud in noeuds:
        if str(noeud.get("type") or "") not in {"disk", "loop"}:
            continue
        analyses.append(_analyser(noeud, swaps))
    candidats = [item for item in analyses if item["candidat"]]
    tests = [item for item in analyses if item["test"]]
    a_demonter = [item for item in analyses if item["a_demonter"]]
    autres = [
        item
        for item in analyses
        if not item["candidat"] and not item["test"] and not item["a_demonter"]
    ]
    maison = Path.home()
    return {
        "candidats": candidats,
        "tests": tests,
        "a_demonter": a_demonter,
        "autres": autres[:20],
        "swap_disque_actif": swap_disque,
        "swaps": swap_details,
        "dependances": _dependances(),
        "header_age_existe": (maison / "luks_header_qr.bak.age").exists(),
        "montages_actifs": {
            chemin: os.path.ismount(chemin)
            for chemin in ("/mnt/usb_vault", "/mnt/usb_urgence", "/mnt/ram_sec")
        },
        "mappeurs_actifs": {
            nom: Path(f"/dev/mapper/{nom}").exists()
            for nom in ("qr_vault", "qr_vault_ro")
        },
    }


def _texte(valeur, nom: str, maximum: int = 4096) -> str:
    if not isinstance(valeur, str) or not valeur.strip():
        raise ErreurUtilisateur(f"Le champ {nom} est vide.", 400, "champ_vide")
    valeur = valeur.strip()
    if len(valeur) > maximum:
        raise ErreurUtilisateur(f"Le champ {nom} est trop long.", 400, "champ_trop_long")
    if any(caractere in valeur for caractere in ("\x00", "\n", "\r")):
        raise ErreurUtilisateur(f"Le champ {nom} contient un caractère interdit.", 400, "champ_invalide")
    return valeur


def _message_demontage(code: int, sortie: str) -> str:
    texte = (sortie or "").casefold()
    if "not mounted" in texte or "not found" in texte or "no such" in texte:
        return "Cette partition n'est plus montée. Rafraîchissez la détection."
    if "busy" in texte or "in use" in texte or "utilisé" in texte or "occup" in texte:
        return (
            "Le démontage a échoué : un fichier ou une application utilise encore "
            "cette partition. Fermez le gestionnaire de fichiers et les applications "
            "ouvertes sur la clé, puis réessayez."
        )
    if (
        "not authorized" in texte
        or "polkit" in texte
        or "authentication" in texte
        or "permission" in texte
        or "accès refusé" in texte
    ):
        return (
            "udisks2 a refusé le démontage (autorisation insuffisante). "
            "Utilisez la commande manuelle dans un terminal."
        )
    return f"Le démontage a échoué (code {code})."


def demonter_partition(donnees: dict) -> dict:
    """Démonte une partition d'une clé amovible via udisksctl, sans sudo.

    La cible est revalidée à partir de l'état lsblk courant : seules les
    partitions d'un disque amovible sûr, dont le montage est le seul obstacle,
    sont acceptées.
    """
    if not isinstance(donnees, dict):
        raise ErreurUtilisateur("Requête invalide.", 400, "requete_invalide")
    partition = _texte(donnees.get("partition"), "partition", 200)
    if not re.fullmatch(r"/dev/[A-Za-z0-9._/-]+", partition) or ".." in partition:
        raise ErreurUtilisateur("Chemin de partition invalide.", 400, "partition_invalide")

    etat = peripheriques()
    appareil = None
    for candidat in etat.get("a_demonter", []):
        for element in candidat.get("partitions_montees", []):
            if element.get("chemin") == partition:
                appareil = candidat
                break
        if appareil is not None:
            break

    if appareil is None:
        for groupe in ("candidats", "a_demonter"):
            for candidat in etat.get(groupe, []):
                if any(
                    element.get("chemin") == partition
                    for element in candidat.get("partitions", [])
                ):
                    return {
                        "ok": False,
                        "code": "partition_non_montee",
                        "message": (
                            "Cette partition n'est pas (ou plus) montée. "
                            "Rafraîchissez la détection."
                        ),
                        "partition": partition,
                        "disque": candidat.get("chemin"),
                        "commande": None,
                        "commande_alternative": None,
                        "details": [],
                    }
        raise ErreurUtilisateur(
            "Démontage refusé : cette partition n'appartient pas à un disque "
            "amovible sûr et non système.",
            403,
            "partition_non_autorisee",
        )

    disque = str(appareil.get("chemin") or "")
    commande_udisks = f"udisksctl unmount -b {shlex.quote(partition)}"
    commande_secours = f"sudo umount {shlex.quote(partition)}"
    executable_udisks = shutil.which("udisksctl")

    if executable_udisks is None:
        return {
            "ok": False,
            "code": "udisksctl_absent",
            "message": (
                "udisksctl n'est pas installé sur ce système. Aucun démontage "
                "n'a été tenté côté serveur. Copiez la commande manuelle dans "
                "un terminal."
            ),
            "partition": partition,
            "disque": disque,
            "commande": commande_secours,
            "commande_alternative": None,
            "details": [],
        }

    try:
        processus = subprocess.run(
            [executable_udisks, "unmount", "--no-user-interaction", "-b", partition],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
            text=True,
            env={**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"},
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "code": "udisksctl_absent",
            "message": (
                "udisksctl n'est pas disponible. Aucun démontage n'a été "
                "tenté. Utilisez la commande manuelle."
            ),
            "partition": partition,
            "disque": disque,
            "commande": commande_secours,
            "commande_alternative": None,
            "details": [],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "code": "demonter_delai",
            "message": (
                "udisksctl n'a pas répondu dans le délai imparti. "
                "Utilisez la commande manuelle si nécessaire."
            ),
            "partition": partition,
            "disque": disque,
            "commande": commande_udisks,
            "commande_alternative": commande_secours,
            "details": [],
        }
    except OSError as exc:
        return {
            "ok": False,
            "code": "demonter_impossible",
            "message": (
                "Impossible de lancer udisksctl. "
                "Utilisez la commande manuelle dans un terminal."
            ),
            "partition": partition,
            "disque": disque,
            "commande": commande_udisks,
            "commande_alternative": commande_secours,
            "details": [type(exc).__name__],
        }

    sortie = ((processus.stdout or "") + "\n" + (processus.stderr or "")).strip()
    details = lignes_utiles(sortie, maximum=8)
    if processus.returncode == 0:
        return {
            "ok": True,
            "code": "demonte",
            "message": f"{partition} a été démontée. La clé peut être sélectionnée.",
            "partition": partition,
            "disque": disque,
            "methode": "udisksctl",
            "commande": None,
            "commande_alternative": None,
            "details": details,
        }

    return {
        "ok": False,
        "code": "demonter_echoue",
        "message": _message_demontage(processus.returncode, sortie),
        "partition": partition,
        "disque": disque,
        "methode": "udisksctl",
        "commande": commande_udisks,
        "commande_alternative": commande_secours,
        "details": details,
    }


def _chemin_absolu(valeur, nom: str) -> str:
    valeur = _texte(valeur, nom)
    chemin = Path(valeur).expanduser()
    if not chemin.is_absolute():
        raise ErreurUtilisateur(
            f"Le champ {nom} doit être un chemin absolu.", 400, "chemin_non_absolu"
        )
    return str(chemin)


def _ram_size(valeur, minimum_mio: int) -> str:
    if valeur is None or valeur == "":
        return "2G" if minimum_mio == 256 else "512M"
    if not isinstance(valeur, str) or not re.fullmatch(r"\d+[MGmg]", valeur.strip()):
        raise ErreurUtilisateur(
            "La taille RAM doit ressembler à 2G ou 512M.", 400, "ram_size_invalide"
        )
    valeur = valeur.strip().upper()
    nombre = int(valeur[:-1])
    mib = nombre * 1024 if valeur.endswith("G") else nombre
    if mib < minimum_mio:
        raise ErreurUtilisateur(
            f"La taille RAM doit être au minimum de {minimum_mio}M.",
            400,
            "ram_size_invalide",
        )
    if mib > 65536:
        raise ErreurUtilisateur("La taille RAM est déraisonnable.", 400, "ram_size_invalide")
    return valeur


def _entier_borne(valeur, nom: str, minimum: int, maximum: int) -> int | None:
    if valeur is None or valeur == "":
        return None
    try:
        nombre = int(valeur)
    except (TypeError, ValueError) as exc:
        raise ErreurUtilisateur(
            f"Le champ {nom} doit être un entier.", 400, "entier_invalide"
        ) from exc
    if nombre < minimum or nombre > maximum:
        raise ErreurUtilisateur(
            f"Le champ {nom} doit être entre {minimum} et {maximum}.",
            400,
            "entier_invalide",
        )
    return nombre


def _trouver_appareil(etat: dict, chemin: str) -> dict:
    for groupe in ("candidats", "tests", "a_demonter", "autres"):
        for appareil in etat.get(groupe, []):
            if appareil.get("chemin") == chemin:
                return appareil
    raise ErreurUtilisateur(
        "Périphérique introuvable. Rafraîchissez la liste avant de générer la commande.",
        400,
        "peripherique_introuvable",
    )


def _confirmation_valide(valeur: str, appareil: dict) -> bool:
    """Accepte le nom court, le chemin complet ou le numéro de série."""
    normalisee = valeur.strip().casefold()
    if not normalisee:
        return False
    attendues = {
        str(appareil.get("nom") or "").strip().casefold(),
        str(appareil.get("chemin") or "").strip().casefold(),
        str(appareil.get("serie") or "").strip().casefold(),
        str(appareil.get("confirmation") or "").strip().casefold(),
    }
    attendues.discard("")
    return normalisee in attendues


def generer_commandes(donnees: dict) -> dict:
    if not isinstance(donnees, dict):
        raise ErreurUtilisateur("Requête invalide.", 400, "requete_invalide")
    operation = donnees.get("operation")
    if operation not in {"init", "sauvegarde", "consulter", "restaurer"}:
        raise ErreurUtilisateur("Opération inconnue.", 400, "operation_inconnue")
    chemin = _texte(donnees.get("peripherique"), "périphérique", 200)
    if not re.fullmatch(r"/dev/[A-Za-z0-9._/-]+", chemin) or ".." in chemin:
        raise ErreurUtilisateur("Chemin de périphérique invalide.", 400, "peripherique_invalide")

    etat = peripheriques()
    appareil = _trouver_appareil(etat, chemin)
    mode_test = donnees.get("mode_test") is True
    if appareil["type"] == "loop":
        if not mode_test:
            raise ErreurUtilisateur(
                "Le mode test loopback doit être coché explicitement pour un périphérique /dev/loopX.",
                400,
                "mode_test_requis",
            )
        if not appareil["test"]:
            raise ErreurUtilisateur(
                "Ce périphérique loopback ne peut pas être utilisé : "
                + " ".join(appareil["raisons"]),
                400,
                "peripherique_non_sur",
            )
    else:
        if mode_test:
            raise ErreurUtilisateur(
                "Le mode test loopback est réservé aux images /dev/loopX.",
                400,
                "mode_test_interdit",
            )
        if appareil.get("a_demonter"):
            raise ErreurUtilisateur(
                "Une partition de ce disque est montée. Démontez-la, "
                "rafraîchissez la détection, puis recommencez.",
                409,
                "partition_montee",
            )
        if not appareil["candidat"]:
            raise ErreurUtilisateur(
                "Ce périphérique n'est pas sûr : " + " ".join(appareil["raisons"]),
                400,
                "peripherique_non_sur",
            )

    # L'initialisation est la seule opération destructive : elle conserve une
    # confirmation explicite. Les opérations non destructives s'appuient sur
    # la sélection de l'étape 1 et sur la revalidation d'état ci-dessus.
    if operation == "init":
        try:
            confirmation = _texte(donnees.get("confirmation"), "confirmation", 200)
        except ErreurUtilisateur as exc:
            raise ErreurUtilisateur(
                "Confirmation obligatoire. Saisissez le nom du disque (sde), "
                "son chemin complet (/dev/sde) ou son numéro de série.",
                400,
                "confirmation_incorrecte",
            ) from exc
        if not _confirmation_valide(confirmation, appareil):
            raise ErreurUtilisateur(
                "Confirmation incorrecte. Saisissez le nom du disque (sde), "
                "son chemin complet (/dev/sde) ou son numéro de série.",
                400,
                "confirmation_incorrecte",
            )

    args: list[str] = []
    avertissements: list[str] = []
    checklist: list[str] = []
    if operation == "init":
        if etat.get("header_age_existe"):
            raise ErreurUtilisateur(
                "Une sauvegarde ~/luks_header_qr.bak.age existe déjà. "
                "Déplacez-la avant toute réinitialisation.",
                409,
                "header_age_existant",
            )
        script = config.RACINE / "init_usb_coffre.sh"
        args = ["sudo", str(script)]
        argon2 = _entier_borne(donnees.get("argon2_mib"), "argon2_mib", 256, 8192)
        threads = _entier_borne(donnees.get("argon2_threads"), "argon2_threads", 1, 32)
        if argon2 is not None:
            args += ["--argon2-mib", str(argon2)]
        if threads is not None:
            args += ["--argon2-threads", str(threads)]
        if appareil["type"] == "loop":
            args.append("--allow-loopback")
            avertissements.append(
                "MODE TEST LOOPBACK : cette commande ne doit jamais viser un disque physique."
            )
        else:
            avertissements.append(
                "OPÉRATION DESTRUCTIVE : toutes les données du disque seront effacées."
            )
        args.append(chemin)
        checklist.extend(
            [
                "Le serveur a contrôlé la cible et l'absence de partition montée.",
                "Vérifiez une dernière fois le modèle et la taille avec lsblk.",
                "Le script vous demandera de taper EFFACER puis le numéro de série.",
                "La phrase de passe age de l'en-tête doit être conservée hors de la clé.",
            ]
        )
    elif operation == "sauvegarde":
        script = config.RACINE / "executer_sauvegarde_ram.sh"
        args = ["sudo", str(script)]
        ram = _ram_size(donnees.get("ram_size"), 256)
        args += ["--ram-size", ram]
        if donnees.get("no_print") is True:
            args.append("--no-print")
        if donnees.get("garder_source") is True:
            args.append("--garder-source")
        if appareil["type"] == "loop":
            args.append("--allow-loopback")
            avertissements.append("MODE TEST LOOPBACK activé.")
        csv_path = donnees.get("csv_path")
        sans_csv = donnees.get("sans_csv") is True
        if csv_path and sans_csv:
            raise ErreurUtilisateur(
                "Choisissez soit un CSV externe, soit l'export direct en RAM.",
                400,
                "csv_incompatible",
            )
        csv_absolu: str | None = None
        if csv_path:
            csv_absolu = _chemin_absolu(csv_path, "csv_path")
            if not csv_absolu.startswith(("/mnt/ram_sec/", "/run/user/")):
                avertissements.append(
                    "Ce CSV est sur le disque : le script proposera de le détruire, "
                    "mais des traces peuvent subsister. L'export direct en RAM est préférable."
                )
        elif not sans_csv:
            avertissements.append(
                "Aucun CSV fourni : le script attendra un fichier dans "
                "/mnt/ram_sec/travail/export.csv. Exportez-le directement dans l'enclave RAM."
            )
        args.append(chemin)
        if csv_absolu:
            args.append(csv_absolu)
        checklist.extend(
            [
                "Démontez la partition URGENCE_QR si le bureau l'a montée automatiquement.",
                "Le script désactive temporairement le swap et les core dumps.",
                "Ne copiez pas le CSV depuis ~/Téléchargements ou /tmp.",
            ]
        )
    else:
        script = config.RACINE / "consulter_coffre_ro.sh"
        args = ["sudo", str(script)]
        ram = _ram_size(donnees.get("ram_size"), 128)
        args += ["--ram-size", ram]
        if appareil["type"] == "loop":
            args.append("--allow-loopback")
            avertissements.append("MODE TEST LOOPBACK activé.")
        action = donnees.get("action") or ("restaurer" if operation == "restaurer" else "menu")
        if action not in {"menu", "id", "nom", "restaurer"}:
            raise ErreurUtilisateur("Action de consultation inconnue.", 400, "action_inconnue")
        if operation == "restaurer":
            action = "restaurer"
        if action == "id":
            identifiant = _texte(donnees.get("record_id"), "identifiant", 32)
            if not re.fullmatch(r"R\d{1,9}", identifiant, flags=re.IGNORECASE):
                raise ErreurUtilisateur("Identifiant invalide. Exemple : R123.", 400, "id_invalide")
            args += ["--id", identifiant.upper()]
        elif action == "nom":
            nom = _texte(donnees.get("nom"), "nom", 200)
            args += ["--nom", nom]
            avertissements.append(
                "Le nom saisi peut apparaître dans l'historique du shell. "
                "Préférez --id R123 et désactivez l'historique avec set +o history."
            )
        elif action == "restaurer":
            args.append("--restaurer")
        export_path = donnees.get("export_path")
        if export_path:
            export_absolu = _chemin_absolu(export_path, "export_path")
            args += ["--export", export_absolu]
            if not export_absolu.startswith(("/mnt/ram_sec/", "/run/user/")):
                avertissements.append(
                    "L'export de scans est sur le disque : il contient tous les QR, "
                    "donc des secrets. Le script proposera de le détruire après copie."
                )
        if donnees.get("afficher") is True and action in {"id", "nom"}:
            args.append("--afficher")
            avertissements.append(
                "L'option --afficher fera apparaître le mot de passe dans le terminal. "
                "Le scrollback peut le conserver."
            )
        args.append(chemin)
        checklist.extend(
            [
                "Le coffre sera ouvert en lecture seule (cryptsetup --readonly, mount -o ro).",
                "Déposez l'export JSON Binary Eye dans /mnt/ram_sec/scans/ après le montage.",
                "Les sorties restent dans /mnt/ram_sec/sorties et sont détruites à la sortie.",
            ]
        )

    commande_principale = shlex.join(args)
    commandes = [
        {
            "titre": "1. Désactiver l'historique du shell",
            "texte": "set +o history",
            "description": "À exécuter en premier dans le terminal, pour ne pas enregistrer la commande.",
        },
        {
            "titre": "2. Vérifier le périphérique",
            "texte": f"lsblk -o NAME,MODEL,SIZE,TRAN,RM,FSTYPE,MOUNTPOINTS,SERIAL {shlex.quote(chemin)}",
            "description": "Vérifiez la lettre, le modèle, la taille et l'absence de montage.",
        },
        {
            "titre": "3. Lancer l'opération",
            "texte": commande_principale,
            "description": "Le terminal demandera les confirmations et les phrases de passe.",
        },
    ]
    if etat.get("swap_disque_actif"):
        avertissements.append(
            "Un swap disque est actif. Les scripts USB le désactivent temporairement, "
            "mais vérifiez qu'aucune autre application ne manipule de secrets pendant l'opération."
        )
    if not etat.get("header_age_existe") and operation in {"sauvegarde", "consulter", "restaurer"}:
        avertissements.append(
            "La sauvegarde ~/luks_header_qr.bak.age est absente : la partition d'urgence "
            "n'aura pas de copie d'en-tête."
        )
    return {
        "operation": operation,
        "appareil": appareil,
        "controle": {
            "cible": appareil["chemin"],
            "modele": appareil["modele"],
            "taille": appareil["taille"],
            "partitions_demontees": not appareil["monte"],
            "source": "lsblk au moment de la génération",
        },
        "commandes": commandes,
        "avertissements": avertissements,
        "checklist": checklist,
        "execution": "manuelle",
    }
