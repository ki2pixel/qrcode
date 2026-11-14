"""Espace de travail exclusivement en mémoire vive (tmpfs)."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from web import config

_RACINE_RAM: Path | None = None
_FD_VERROU: int | None = None


def type_systeme(chemin: Path) -> str:
    """Retourne le type de système de fichiers via findmnt."""
    try:
        resultat = subprocess.run(
            ["findmnt", "-n", "-o", "FSTYPE", "-T", str(chemin)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return resultat.stdout.strip()


def _dossier_prive(chemin: Path) -> bool:
    try:
        stats = chemin.stat()
    except OSError:
        return False
    return (
        chemin.is_dir()
        and stats.st_uid == os.getuid()
        and (stats.st_mode & 0o077) == 0
    )


def _choisir_base() -> Path:
    uid = os.getuid()
    candidats: list[Path] = []
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        candidats.append(Path(xdg) / "qrcode_web_5100")
    candidats.append(Path("/dev/shm") / f"qrcode_web_5100_{uid}")

    raisons: list[str] = []
    for base in candidats:
        try:
            base.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(base, 0o700)
        except OSError as exc:
            raisons.append(f"{base}: {exc.strerror or exc}")
            continue
        if not _dossier_prive(base):
            raisons.append(f"{base}: permissions ou propriétaire incorrects")
            continue
        fs = type_systeme(base)
        if fs != "tmpfs":
            raisons.append(f"{base}: système de fichiers {fs or 'inconnu'}, tmpfs requis")
            continue
        libre = shutil.disk_usage(base).free
        if libre < config.ESPACE_RAM_MINIMUM:
            raisons.append(
                f"{base}: seulement {libre // (1024 * 1024)} Mio libres"
            )
            continue
        return base

    detail = " ; ".join(raisons) if raisons else "aucun candidat"
    raise RuntimeError(
        "Impossible de trouver un espace tmpfs privé pour l'interface web. "
        "Vérifiez /dev/shm et XDG_RUNTIME_DIR. Détail : " + detail
    )


def _verrouiller(base: Path) -> int:
    chemin = base / ".verrou"
    fd = os.open(chemin, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise RuntimeError(
            "Une autre instance de l'interface web utilise déjà l'espace RAM. "
            "Fermez-la avant de relancer."
        ) from exc
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    return fd


def _supprimer_arbre(base: Path, secrets: set[str] | None = None) -> None:
    secrets = secrets or set()
    try:
        if base.is_symlink() or not base.is_dir():
            if base.is_symlink():
                base.unlink()
            return
        avec = os.scandir(base)
    except OSError:
        return
    with avec:
        for entree in avec:
            try:
                if entree.is_dir(follow_symlinks=False):
                    _supprimer_arbre(Path(entree.path), secrets)
                else:
                    chemin = Path(entree.path)
                    if str(chemin) in secrets:
                        _ecraser_fichier(chemin)
                    os.unlink(entree.path)
            except OSError:
                continue
    try:
        if base.name != ".verrou":
            os.rmdir(base)
    except OSError:
        pass


def _ecraser_fichier(chemin: Path, limite: int = 16 * 1024 * 1024) -> None:
    """Écrase un petit fichier secret avant suppression (best effort)."""
    try:
        fd = os.open(chemin, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return
    try:
        taille = os.fstat(fd).st_size
        if taille < 0 or taille > limite:
            return
        reste = taille
        bloc = b"\x00" * (64 * 1024)
        while reste > 0:
            ecrit = os.write(fd, bloc[: min(len(bloc), reste)])
            if ecrit <= 0:
                break
            reste -= ecrit
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _nettoyer_base(base: Path) -> None:
    for entree in base.iterdir():
        if entree.name == ".verrou":
            continue
        _supprimer_arbre(entree)


def initialiser_ram() -> Path:
    """Crée, verrouille et nettoie l'espace tmpfs global."""
    global _RACINE_RAM, _FD_VERROU
    if _RACINE_RAM is not None:
        return _RACINE_RAM
    base = _choisir_base()
    fd = _verrouiller(base)
    _nettoyer_base(base)
    _RACINE_RAM = base
    _FD_VERROU = fd
    tempfile.tempdir = str(base)
    return base


def racine_ram() -> Path:
    if _RACINE_RAM is None:
        raise RuntimeError("L'espace RAM n'est pas initialisé.")
    return _RACINE_RAM


def purger_racine() -> None:
    if _RACINE_RAM is not None:
        _nettoyer_base(_RACINE_RAM)


def arreter_ram() -> None:
    global _RACINE_RAM, _FD_VERROU
    if _RACINE_RAM is not None:
        _nettoyer_base(_RACINE_RAM)
    if _FD_VERROU is not None:
        try:
            fcntl.flock(_FD_VERROU, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(_FD_VERROU)
        _FD_VERROU = None
    if _RACINE_RAM is not None:
        try:
            (_RACINE_RAM / ".verrou").unlink()
        except OSError:
            pass
        try:
            _RACINE_RAM.rmdir()
        except OSError:
            pass
    _RACINE_RAM = None
    tempfile.tempdir = None


class EspaceRam:
    """Répertoire de travail privé sous la racine tmpfs."""

    def __init__(self, prefixe: str) -> None:
        self.base = Path(tempfile.mkdtemp(prefix=f"{prefixe}_", dir=str(racine_ram())))
        os.chmod(self.base, 0o700)
        self._secrets: set[str] = set()

    def sous_dossier(self, nom: str) -> Path:
        if not nom or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in nom):
            raise ValueError(f"Nom de sous-dossier invalide : {nom!r}")
        chemin = self.base / nom
        chemin.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(chemin, 0o700)
        return chemin

    def chemin(self, *parties: str) -> Path:
        from web.utilitaires import chemin_sur

        return chemin_sur(self.base, *parties)

    def ecrire(
        self, chemin_relatif: str, donnees: bytes, *, secret: bool = False
    ) -> Path:
        chemin = self.chemin(chemin_relatif)
        chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            chemin,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb") as flux:
            flux.write(donnees)
        os.chmod(chemin, 0o600)
        if secret:
            self.marquer_secret(chemin)
        return chemin

    def ouvrir_flux(self, chemin_relatif: str, *, secret: bool = False):
        chemin = self.chemin(chemin_relatif)
        chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            chemin,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        if secret:
            self.marquer_secret(chemin)
        return os.fdopen(fd, "wb")

    def marquer_secret(self, chemin: Path) -> None:
        try:
            resolu = chemin.resolve()
            if os.path.commonpath([str(self.base.resolve()), str(resolu)]) == str(
                self.base.resolve()
            ):
                self._secrets.add(str(resolu))
        except (OSError, ValueError):
            return

    def recreer_dossier(self, chemin_relatif: str) -> Path:
        chemin = self.chemin(chemin_relatif)
        if chemin.exists():
            _supprimer_arbre(chemin, self._secrets)
        chemin.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(chemin, 0o700)
        return chemin

    def supprimer(self, chemin_relatif: str, *, ecraser: bool = False) -> None:
        chemin = self.chemin(chemin_relatif)
        if not chemin.exists() and not chemin.is_symlink():
            return
        if chemin.is_dir() and not chemin.is_symlink():
            _supprimer_arbre(chemin, self._secrets if ecraser else set())
            return
        if ecraser or str(chemin.resolve()) in self._secrets:
            _ecraser_fichier(chemin)
        try:
            chemin.unlink()
        except OSError:
            pass

    def detruire(self) -> None:
        _supprimer_arbre(self.base, self._secrets)
        self._secrets.clear()
