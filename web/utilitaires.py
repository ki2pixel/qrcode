"""Petits utilitaires partagés par les services web."""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Iterable, TYPE_CHECKING
from urllib.parse import unquote, urlsplit, urlunsplit

from flask import request

from web import config
from web.erreurs import ErreurUtilisateur

if TYPE_CHECKING:  # pragma: no cover
    from web.espace_ram import EspaceRam


def maintenant() -> float:
    return time.time()


def sanitiser_base(nom: str) -> str:
    """Retourne un nom de base sûr, sans répertoire ni caractère exotique."""
    nom = unquote(nom or "").replace("\\", "/").split("/")[-1]
    nom = nom.replace("\x00", "").strip()
    base = Path(nom).stem if nom else ""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    return (base[:80] or "export")


def nom_fichier_depuis_entete() -> str:
    return sanitiser_base(request.headers.get("X-QR-Fichier", ""))


def lire_corps_limite(max_octets: int) -> bytes:
    """Lit le corps brut de la requête, sans jamais dépasser la limite."""
    longueur = request.content_length
    if longueur is not None and longueur > max_octets:
        raise ErreurUtilisateur(
            f"Fichier trop volumineux (maximum {max_octets:,} octets).",
            413,
            "fichier_trop_volumineux",
        )

    morceaux: list[bytes] = []
    total = 0
    while True:
        bloc = request.stream.read(64 * 1024)
        if not bloc:
            break
        total += len(bloc)
        if total > max_octets:
            raise ErreurUtilisateur(
                f"Fichier trop volumineux (maximum {max_octets:,} octets).",
                413,
                "fichier_trop_volumineux",
            )
        morceaux.append(bloc)
    return b"".join(morceaux)


def decoder_sortie(brut: bytes, limite: int = 200_000) -> str:
    return brut[:limite].decode("utf-8", errors="replace")


def lignes_utiles(texte: str, maximum: int = 80, longueur_max: int = 240) -> list[str]:
    """Nettoie une sortie de commande pour affichage, sans données de secret."""
    lignes: list[str] = []
    for ligne in (texte or "").splitlines():
        ligne = ligne.replace("\x1b", "").rstrip()
        if not ligne:
            continue
        if len(ligne) > longueur_max:
            ligne = ligne[: longueur_max - 1] + "…"
        lignes.append(ligne)
    return lignes[-maximum:]


def executer(
    args: Iterable[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    limite_sortie: int = 200_000,
) -> tuple[int, str, str]:
    """Exécute une commande sans shell et retourne (code, stdout, stderr)."""
    try:
        processus = subprocess.run(
            list(args),
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ErreurUtilisateur(
            f"Commande introuvable : {Path(str(args[0])).name}.",
            500,
            "commande_introuvable",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ErreurUtilisateur(
            "Le traitement a dépassé le temps maximal autorisé.",
            504,
            "delai_depasse",
        ) from exc
    return (
        processus.returncode,
        decoder_sortie(processus.stdout, limite_sortie),
        decoder_sortie(processus.stderr, limite_sortie),
    )


def tuer_groupe(processus: subprocess.Popen, delai: float = 5.0) -> None:
    """Termine un processus et ses enfants, puis force si nécessaire."""
    if processus.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(processus.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            processus.terminate()
        except OSError:
            return
    try:
        processus.wait(timeout=delai)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(processus.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                processus.kill()
            except OSError:
                pass


def env_sous_processus(
    espace: "EspaceRam", extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Environnement hermétique : caches, HOME et temporaires dans le tmpfs."""
    ram_home = espace.sous_dossier("home")
    ram_tmp = espace.sous_dossier("tmp")
    ram_cache = espace.sous_dossier("cache")
    ram_data = espace.sous_dossier("data")
    ram_config = espace.sous_dossier("config")
    ram_runtime = espace.sous_dossier("runtime")
    os.chmod(ram_runtime, 0o700)

    vrai_home = Path.home()
    python_dir = str(Path(config.PYTHON_SYSTEME).resolve().parent)
    paths = []
    if config.PATH_SYSTEME:
        paths.extend(config.PATH_SYSTEME.split(os.pathsep))
    paths.extend(
        [
            python_dir,
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
            str(vrai_home / ".local" / "bin"),
        ]
    )
    vus: set[str] = set()
    path_final: list[str] = []
    for element in paths:
        if element and element not in vus:
            vus.add(element)
            path_final.append(element)

    env = {
        "PATH": os.pathsep.join(path_final),
        "HOME": str(ram_home),
        "TMPDIR": str(ram_tmp),
        "TMP": str(ram_tmp),
        "TEMP": str(ram_tmp),
        "XDG_CACHE_HOME": str(ram_cache),
        "XDG_DATA_HOME": str(ram_data),
        "XDG_CONFIG_HOME": str(ram_config),
        "XDG_RUNTIME_DIR": str(ram_runtime),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    if (vrai_home / ".local").is_dir():
        env["PYTHONUSERBASE"] = str(vrai_home / ".local")
    if os.environ.get("TZ"):
        env["TZ"] = os.environ["TZ"]
    if extra:
        env.update({cle: str(valeur) for cle, valeur in extra.items()})
    return env


def chemin_sur(base: Path, *parties: str) -> Path:
    """Construit un chemin et refuse toute sortie de l'espace de travail."""
    base_resolue = base.resolve()
    candidat = base.joinpath(*parties).resolve(strict=False)
    try:
        if os.path.commonpath([str(base_resolue), str(candidat)]) != str(base_resolue):
            raise ErreurUtilisateur("Chemin de fichier invalide.", 400, "chemin_invalide")
    except ValueError as exc:
        raise ErreurUtilisateur(
            "Chemin de fichier invalide.", 400, "chemin_invalide"
        ) from exc
    return candidat


def lire_fichier_limite(chemin: Path, max_octets: int) -> bytes:
    """Lit un fichier régulier, sans suivre les liens symboliques."""
    try:
        fd = os.open(chemin, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ErreurUtilisateur(
            f"Fichier illisible : {chemin.name}.", 400, "fichier_illisible"
        ) from exc
    try:
        taille = os.fstat(fd).st_size
        if taille > max_octets:
            raise ErreurUtilisateur(
                f"Fichier trop volumineux : {chemin.name}.", 413, "fichier_trop_volumineux"
            )
        with os.fdopen(fd, "rb") as flux:
            fd = -1
            return flux.read(max_octets + 1)
    finally:
        if fd >= 0:
            os.close(fd)


def copier_fichier_limite(source: Path, destination: Path, max_octets: int) -> int:
    """Copie un fichier régulier dans un espace contrôlé, avec plafond."""
    try:
        fd_source = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ErreurUtilisateur(
            f"Fichier source illisible : {source.name}.", 400, "fichier_illisible"
        ) from exc

    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd_dest = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        os.close(fd_source)
        raise ErreurUtilisateur(
            "Impossible de préparer l'espace de travail.", 500, "ecriture_impossible"
        ) from exc

    total = 0
    try:
        with os.fdopen(fd_source, "rb") as src, os.fdopen(fd_dest, "wb") as dst:
            fd_source = -1
            fd_dest = -1
            while True:
                bloc = src.read(64 * 1024)
                if not bloc:
                    break
                total += len(bloc)
                if total > max_octets:
                    raise ErreurUtilisateur(
                        f"Fichier trop volumineux : {source.name}.",
                        413,
                        "fichier_trop_volumineux",
                    )
                dst.write(bloc)
        os.chmod(destination, 0o600)
        return total
    finally:
        if fd_source >= 0:
            os.close(fd_source)
        if fd_dest >= 0:
            os.close(fd_dest)


def normaliser_nbsp(texte: str) -> str:
    return (texte or "").replace("\u00a0", " ")


def rediger_uri(uri: str) -> str:
    """Masque un éventuel couple utilisateur:motdepasse dans une URL."""
    uri = uri or ""
    if "://" not in uri or "@" not in uri:
        return uri
    try:
        parties = urlsplit(uri)
        if not parties.username and not parties.password:
            return uri
        hote = parties.hostname or ""
        if ":" in hote and not hote.startswith("["):
            hote = f"[{hote}]"
        port = f":{parties.port}" if parties.port else ""
        return urlunsplit(
            (parties.scheme, f"•••@{hote}{port}", parties.path, parties.query, parties.fragment)
        )
    except ValueError:
        return uri


def sha256(donnees: bytes) -> str:
    return hashlib.sha256(donnees).hexdigest()


def mime_pour_nom(nom: str) -> str:
    suffixe = Path(nom).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".zip": "application/zip",
        ".csv": "text/csv; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
        ".png": "image/png",
        ".txt": "text/plain; charset=utf-8",
    }.get(suffixe, "application/octet-stream")
