#!/usr/bin/env bash
#
# Lance l'interface web locale (127.0.0.1:5100) dans un .venv dédié.
# Le mode ligne de commande reste utilisable sans activer cet environnement.

set -Eeuo pipefail
umask 077
ulimit -c 0 2>/dev/null || true
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PIP_NO_CACHE_DIR=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$SCRIPT_DIR"

if [[ -f "$SCRIPT_DIR/sauvegarde_qr_web.desktop" ]] && ! grep -qF "Path=$SCRIPT_DIR" "$SCRIPT_DIR/sauvegarde_qr_web.desktop" 2>/dev/null; then
  sed -i "s|^Path=.*|Path=$SCRIPT_DIR|" "$SCRIPT_DIR/sauvegarde_qr_web.desktop" 2>/dev/null || true
fi

die() { printf '[ERREUR] %s\n' "$*" >&2; exit 1; }
info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[ATTENTION] %s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
Usage : ./lancer_interface.sh [options]

Options :
  --strict-ram    Refuser le démarrage si un swap disque est actif
  --no-browser    Ne pas ouvrir automatiquement le navigateur
  -h, --help      Afficher cette aide

L'interface écoute uniquement sur http://127.0.0.1:5100.
EOF
}

STRICT_RAM=0
NO_BROWSER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict-ram) STRICT_RAM=1; shift ;;
    --no-browser) NO_BROWSER=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Option inconnue : $1" ;;
  esac
done

(( EUID != 0 )) || die "Lancez ce script sans sudo, depuis votre compte utilisateur."
[[ -f "$SCRIPT_DIR/requirements.txt" ]] || die "requirements.txt introuvable."
[[ -f "$SCRIPT_DIR/web/serveur.py" ]] || die "web/serveur.py introuvable."

if [[ -n "${QRCODE_PYTHON_SYSTEM:-}" && -x "${QRCODE_PYTHON_SYSTEM}" ]]; then
  PYTHON_SYSTEME="$QRCODE_PYTHON_SYSTEM"
elif [[ -x /usr/bin/python3 ]]; then
  PYTHON_SYSTEME=/usr/bin/python3
else
  PYTHON_SYSTEME="$(command -v python3 2>/dev/null || true)"
fi
[[ -n "$PYTHON_SYSTEME" ]] || die "python3 est introuvable."
"$PYTHON_SYSTEME" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10 ou supérieur est requis."

if ! "$PYTHON_SYSTEME" -c 'import venv' >/dev/null 2>&1; then
  die "Le module venv est absent. Installez python3-venv (Debian/Ubuntu) ou python3 (Fedora/Arch)."
fi

VENV="$SCRIPT_DIR/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  info "Création du .venv (avec accès aux paquets système, notamment WeasyPrint)…"
  "$PYTHON_SYSTEME" -m venv --system-site-packages "$VENV" \
    || die "Impossible de créer .venv. Vérifiez python3-venv."
  touch "$VENV/.qrcode_web"
  chmod 600 "$VENV/.qrcode_web"
elif grep -Eq '^include-system-site-packages = (false|False)' "$VENV/pyvenv.cfg" 2>/dev/null; then
  if [[ -f "$VENV/.qrcode_web" ]]; then
    warn "Le .venv existant n'inclut pas les paquets système ; recréation."
    rm -rf -- "$VENV"
    "$PYTHON_SYSTEME" -m venv --system-site-packages "$VENV" \
      || die "Impossible de recréer .venv."
    touch "$VENV/.qrcode_web"
    chmod 600 "$VENV/.qrcode_web"
  else
    die "Le .venv existant n'inclut pas les paquets système. Déplacez-le ou supprimez-le, puis relancez."
  fi
fi

[[ -x "$VENV/bin/python" ]] || die "Le .venv est incomplet. Supprimez-le et relancez."
chmod 700 "$VENV" 2>/dev/null || true
chmod g-s "$VENV" 2>/dev/null || true

REQ_HASH="$(sha256sum "$SCRIPT_DIR/requirements.txt" | awk '{print $1}')"
STAMP="$VENV/.requirements.sha256"
if ! "$VENV/bin/python" -c 'import flask' >/dev/null 2>&1 \
  || [[ ! -f "$STAMP" ]] \
  || [[ "$(cat -- "$STAMP" 2>/dev/null || true)" != "$REQ_HASH" ]]; then
  info "Installation des dépendances web dans .venv…"
  if ! "$VENV/bin/python" -m pip install --disable-pip-version-check --quiet -r "$SCRIPT_DIR/requirements.txt"; then
    die "Installation impossible. Vérifiez la connexion réseau, ou installez Flask manuellement dans .venv."
  fi
  printf '%s\n' "$REQ_HASH" > "$STAMP"
  chmod 600 "$STAMP"
fi

"$VENV/bin/python" -c 'import flask' >/dev/null 2>&1 \
  || die "Flask n'est pas importable dans .venv. Lancez : .venv/bin/pip install -r requirements.txt"

if ! "$PYTHON_SYSTEME" -c 'import weasyprint' >/dev/null 2>&1; then
  warn "WeasyPrint n'est pas importable par le Python système : les PDF ne seront pas générés (HTML disponible)."
fi
for cmd in qrencode split; do
  command -v "$cmd" >/dev/null 2>&1 || warn "Commande absente : $cmd"
done

PYTHON_DIR="$(dirname -- "$PYTHON_SYSTEME")"
PATH_SYSTEME="$PYTHON_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${HOME:-/tmp}/.local/bin"
export QRCODE_PYTHON_SYSTEM="$PYTHON_SYSTEME"
export QRCODE_PATH_SYSTEM="$PATH_SYSTEME"

if ! "$PYTHON_SYSTEME" - <<'PY'
import socket
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("127.0.0.1", 5100))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
then
  die "Le port 5100 est déjà utilisé. Fermez l'instance existante avant de relancer."
fi

ARGS=()
(( STRICT_RAM )) && ARGS+=(--strict-ram)
(( NO_BROWSER )) && ARGS+=(--no-browser)

info "Lancement de l'interface web locale…"
exec "$VENV/bin/python" -B -m web.serveur "${ARGS[@]}"
