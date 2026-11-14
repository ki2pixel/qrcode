"""Constantes de l'interface web locale."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_WEB = Path(__file__).resolve().parent

HOTE = "127.0.0.1"
PORT = 5100
VERSION = "1.0.0"

# Hôtes acceptés dans l'en-tête Host : protection contre le DNS rebinding.
HOTES_AUTORISES = frozenset(
    {
        "127.0.0.1:5100",
        "localhost:5100",
        "[::1]:5100",
    }
)
ORIGINES_AUTORISEES = frozenset(
    {
        "http://127.0.0.1:5100",
        "http://localhost:5100",
        "http://[::1]:5100",
    }
)

NOM_COOKIE = "qr_web_session"
ENTETE_API = "X-QR-Web"

# Limites de téléversement.
LIMITE_CSV = 676 * 500  # 338 000 octets, plafond historique du pipeline.
LIMITE_JSON_SCANS = 16 * 1024 * 1024
LIMITE_ZIP = 256 * 1024 * 1024
LIMITE_INDEX = 64 * 1024 * 1024
LIMITE_META = 1024 * 1024
LIMITE_NOM_FICHIER = 120
LIMITE_COLONNES = 500
MAX_ENTREES_INDEX = 200_000
MAX_RESULTATS_RECHERCHE = 50

# Durée de vie des données en mémoire vive.
TTL_SECONDES = 60 * 60
INTERVALLE_NETTOYAGE = 60
DUREE_MAX_GENERATION = 30 * 60
DUREE_MAX_EXTRACTION = 5 * 60
DUREE_MAX_RESTAURATION = 10 * 60
ESPACE_RAM_MINIMUM = 256 * 1024 * 1024

# Le Python utilisé par le pipeline QR (WeasyPrint système), capturé par le
# lanceur avant la création du .venv. Il ne doit pas être le Python du .venv.
PYTHON_SYSTEME = os.environ.get("QRCODE_PYTHON_SYSTEM") or shutil.which("python3") or "/usr/bin/python3"
PATH_SYSTEME = os.environ.get("QRCODE_PATH_SYSTEM") or ""

MONTAGES_SYSTEME = ("/", "/boot", "/boot/efi", "/home", "/var", "/usr", "/var/lib")
