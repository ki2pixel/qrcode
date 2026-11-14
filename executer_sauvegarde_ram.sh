#!/usr/bin/env bash
#
# Orchestre la génération d'une sauvegarde QR entièrement en RAM, puis
# transfère le résultat sur le coffre LUKS2 et la partition d'urgence.
#
# Usage :
#   sudo ./executer_sauvegarde_ram.sh [options] /dev/sdX [export.csv]
#
# Sans export.csv, le script monte l'enclave RAM et attend que le fichier
# /mnt/ram_sec/travail/export.csv soit exporté directement depuis le
# gestionnaire de mots de passe.

set -Eeuo pipefail
umask 077

unset HISTFILE || true
HISTFILE=/dev/null
HISTSIZE=0
HISTFILESIZE=0
set +o history || true

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin${PATH:+:$PATH}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_BLUE=$'\033[1;34m'
  C_GREEN=$'\033[1;32m'
  C_YELLOW=$'\033[1;33m'
  C_RED=$'\033[1;31m'
else
  C_RESET=""
  C_BOLD=""
  C_BLUE=""
  C_GREEN=""
  C_YELLOW=""
  C_RED=""
fi

section() { printf '\n%s== %s ==%s\n' "$C_BOLD" "$*" "$C_RESET"; }
info()    { printf '%s[INFO]%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()      { printf '%s[OK]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()    { printf '%s[ATTENTION]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()     { printf '%s[ERREUR]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }
die()     { err "$*"; exit 1; }

usage() {
  cat <<'EOF'
Usage : sudo ./executer_sauvegarde_ram.sh [options] /dev/sdX [export.csv]

Options :
  --device /dev/sdX    Périphérique USB (équivalent au premier argument)
  --csv CHEMIN         Export CSV source
  --ram-size TAILLE    Taille maximale du tmpfs (défaut : 2G)
  --no-print           Ne pas proposer l'impression
  --garder-source      Ne pas détruire le CSV source externe
  --allow-loopback     Autorise un périphérique /dev/loopX (tests uniquement)
  -h, --help           Affiche cette aide

Sans chemin CSV, le script attend que le fichier soit exporté dans :
  /mnt/ram_sec/travail/export.csv

Le pipeline QR, les caches WeasyPrint et les fichiers temporaires restent
dans le tmpfs. Le swap est désactivé pendant l'opération et restauré à la fin.
EOF
}

VAULT_MNT="/mnt/usb_vault"
URGENCE_MNT="/mnt/usb_urgence"
RAM_MNT="/mnt/ram_sec"
MAPPER="qr_vault"
CUPS_SPOOL="/var/spool/cups"
CUPS_CACHE="/var/cache/cups"
CUPS_LOG="/var/log/cups"

DEV_ARG=""
CSV_ARG=""
RAM_SIZE="2G"
NO_PRINT=0
KEEP_SOURCE=0
ALLOW_LOOPBACK=0

RAM_MOUNTED=0
VAULT_MOUNTED=0
URGENCE_MOUNTED=0
MAPPER_OPEN=0
CUPS_SPOOL_MOUNTED=0
CUPS_CACHE_MOUNTED=0
CUPS_LOG_MOUNTED=0
CUPS_SERVICES_STOPPED=0
CUPS_WAS_ACTIVE=0
CUPS_SOCKET_WAS_ACTIVE=0
CUPS_PATH_WAS_ACTIVE=0
CUPS_BROWSED_WAS_ACTIVE=0
SWAP_DISABLED=0
SWAP_LIST=()

DEV=""
P1=""
P2=""
REAL_USER=""
REAL_UID=""
REAL_GID=""
REAL_HOME=""
REAL_PATH=""
RAM_TMP=""
RAM_CACHE=""
RAM_DATA=""
RAM_CONFIG=""
RAM_HOME=""
RAM_RUNTIME=""
TRAVAIL=""
OUT_DIR=""
NOM=""
CAPSULE=""
MANIFEST=""
AGE_HDR=""
PAR2_FILES=()
CSV_SOURCE=""
CSV_WORK=""
CSV_LABEL=""
SOURCE_TO_SHRED=""
HAVE_AGE_HDR=0
URGENCE_COPIED=0

cleanup() {
  local rc=$?
  trap - EXIT INT TERM HUP
  set +e +u

  if declare -F stop_cups_spool >/dev/null 2>&1; then
    stop_cups_spool
  fi

  sync 2>/dev/null || true
  if (( URGENCE_MOUNTED )); then
    if ! umount "$URGENCE_MNT" 2>/dev/null; then
      warn "$URGENCE_MNT est occupé ; tentative de démontage différé."
      umount -l "$URGENCE_MNT" 2>/dev/null || warn "Impossible de démonter $URGENCE_MNT."
    fi
    URGENCE_MOUNTED=0
  fi
  if (( VAULT_MOUNTED )); then
    if ! umount "$VAULT_MNT" 2>/dev/null; then
      warn "$VAULT_MNT est occupé ; tentative de démontage différé."
      umount -l "$VAULT_MNT" 2>/dev/null || warn "Impossible de démonter $VAULT_MNT."
    fi
    VAULT_MOUNTED=0
  fi
  if (( MAPPER_OPEN )); then
    if ! cryptsetup close "$MAPPER" 2>/dev/null; then
      err "ATTENTION : le conteneur LUKS $MAPPER n'a pas pu être fermé (encore occupé) !"
      rc=1
    fi
    MAPPER_OPEN=0
  fi

  cd / 2>/dev/null || true
  if (( RAM_MOUNTED )) && [[ "${RAM_MNT:-}" == "/mnt/ram_sec" && -d "$RAM_MNT" ]]; then
    find "$RAM_MNT" -xdev -type f -exec shred -u -z -n 1 -- {} + >/dev/null 2>&1 || true
    find "$RAM_MNT" -xdev -type l -delete >/dev/null 2>&1 || true
    umount "$RAM_MNT" 2>/dev/null || umount -l "$RAM_MNT" 2>/dev/null || true
    RAM_MOUNTED=0
  fi

  sync 2>/dev/null || true
  echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true

  if (( SWAP_DISABLED )); then
    if (( ${#SWAP_LIST[@]} > 0 )); then
      for swapdev in "${SWAP_LIST[@]}"; do
        swapon -- "$swapdev" 2>/dev/null || warn "Impossible de réactiver le swap $swapdev."
      done
    fi
    SWAP_DISABLED=0
  fi

  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

on_error() {
  local rc=$? line=$1
  trap - ERR
  err "Erreur inattendue (ligne $line, code $rc). Nettoyage en cours..."
  exit "$rc"
}
trap 'on_error $? $LINENO' ERR

require_root() {
  (( EUID == 0 )) || die "Ce script doit être lancé avec sudo : sudo $0 [options] /dev/sdX [export.csv]"
}

resolve_real_user() {
  REAL_USER="${SUDO_USER:-}"
  if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    die "Lancez le script via sudo depuis votre compte utilisateur (pas sudo -i)."
  fi
  REAL_UID="$(id -u "$REAL_USER")"
  REAL_GID="$(id -g "$REAL_USER")"
  REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
  [[ -n "$REAL_HOME" && -d "$REAL_HOME" ]] || die "Répertoire personnel introuvable pour $REAL_USER."
  REAL_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$REAL_HOME/.local/bin"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Commande requise absente : $1"
}

lsblk_field() {
  local field="$1" dev="$2"
  lsblk -dn -o "$field" "$dev" 2>/dev/null | head -n1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' || true
}

part_path() {
  local dev="$1" n="$2"
  if [[ "$dev" =~ [0-9]$ ]]; then
    printf '%sp%s\n' "$dev" "$n"
  else
    printf '%s%s\n' "$dev" "$n"
  fi
}

is_system_disk() {
  local dev="$1" mp src top
  for mp in / /boot /boot/efi /home /var /usr /var/lib; do
    src="$(findmnt -n -v -o SOURCE --target "$mp" 2>/dev/null || true)"
    [[ -n "$src" ]] || continue
    top="$(lsblk -sno NAME "$src" 2>/dev/null | tail -n1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' || true)"
    [[ "$top" == "$(basename "$dev")" ]] && return 0
  done

  while IFS= read -r src; do
    [[ -n "$src" ]] || continue
    top="$(lsblk -sno NAME "$src" 2>/dev/null | tail -n1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' || true)"
    [[ "$top" == "$(basename "$dev")" ]] && return 0
  done < <(swapon --show=NAME --noheadings 2>/dev/null || true)

  return 1
}

validate_usb_device() {
  local dev="$1" type rm tran ro size_bytes bloc

  [[ -b "$dev" ]] || die "Périphérique bloc introuvable : $dev"
  type="$(lsblk_field TYPE "$dev")"
  if (( ALLOW_LOOPBACK )) && [[ "$type" == "loop" ]]; then
    info "Mode test loopback activé sur $dev."
  else
    [[ "$type" == "disk" ]] || die "Passez le disque entier (ex. /dev/sdX), pas une partition."
    rm="$(lsblk_field RM "$dev")"
    tran="$(lsblk_field TRAN "$dev")"
    if [[ "$rm" != "1" && "$tran" != "usb" ]]; then
      die "Le périphérique n'est pas identifié comme amovible/USB (RM=$rm, TRAN=$tran)."
    fi
  fi

  ro="$(lsblk_field RO "$dev")"
  [[ "$ro" == "0" ]] || die "Le périphérique est protégé en écriture."

  is_system_disk "$dev" && die "Refus : ce périphérique contient le système en cours d'exécution."

  if lsblk -nr -o MOUNTPOINTS "$dev" 2>/dev/null | grep -q '[^[:space:]]'; then
    die "Refus : une partition de $dev est montée. Démontez-la d'abord."
  fi

  if lsblk -nr -o TYPE "$dev" 2>/dev/null | grep -Eq '^(lvm|md|raid[0-9]*|linear|dm|crypt|multipath)$'; then
    die "Refus : le périphérique participe à un volume LVM/RAID/dm. Vérifiez avec lsblk."
  fi

  while IFS= read -r bloc; do
    bloc="$(printf '%s' "$bloc" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [[ -n "$bloc" && -d "/sys/class/block/$bloc/holders" ]] || continue
    if [[ -n "$(ls -A "/sys/class/block/$bloc/holders" 2>/dev/null || true)" ]]; then
      die "Refus : le périphérique ou l'une de ses partitions a des dépendances noyau (holders)."
    fi
  done < <(lsblk -nrno NAME "$dev" 2>/dev/null || true)

  size_bytes="$(lsblk -bdn -o SIZE "$dev" 2>/dev/null | xargs || true)"
  [[ "$size_bytes" =~ ^[0-9]+$ ]] || die "Impossible de lire la taille de $dev."
  (( size_bytes >= 1024 * 1024 * 1024 )) || die "Taille insuffisante (minimum 1 Gio)."
}

kernel_ge_6_4() {
  local rel major minor
  rel="$(uname -r)"
  IFS=. read -r major minor _ <<<"$rel"
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
  (( major > 6 || (major == 6 && minor >= 4) ))
}

check_luks_memory() {
  local luks_mem_kib mem_available_kib
  luks_mem_kib="$(LC_ALL=C cryptsetup luksDump "$1" 2>/dev/null | awk '/Memory:/ {print $2; exit}' || true)"
  [[ "$luks_mem_kib" =~ ^[0-9]+$ ]] || return 0
  mem_available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  [[ "$mem_available_kib" =~ ^[0-9]+$ ]] || return 0
  if (( luks_mem_kib + 256 * 1024 > mem_available_kib )); then
    die "Mémoire insuffisante pour ouvrir le coffre : Argon2id demande $((luks_mem_kib / 1024)) MiB, MemAvailable=${mem_available_kib} KiB."
  fi
}

run_as_user() {
  runuser -u "$REAL_USER" -- env \
    HOME="$RAM_HOME" \
    PATH="$REAL_PATH" \
    TMPDIR="$RAM_TMP" \
    TMP="$RAM_TMP" \
    TEMP="$RAM_TMP" \
    XDG_CACHE_HOME="$RAM_CACHE" \
    XDG_DATA_HOME="$RAM_DATA" \
    XDG_CONFIG_HOME="$RAM_CONFIG" \
    XDG_RUNTIME_DIR="$RAM_RUNTIME" \
    PYTHONUSERBASE="$REAL_HOME/.local" \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    "$@"
}

cups_tmpfs_options() {
  local taille="$1" mode="$2"
  local opts="size=$taille,mode=$mode,uid=0,gid=$(id -g lp),nodev,nosuid,noexec"
  if kernel_ge_6_4; then
    opts+=",noswap"
  fi
  printf '%s\n' "$opts"
}

stop_cups_spool() {
  if (( CUPS_SPOOL_MOUNTED )); then
    cancel -a -x >/dev/null 2>&1 || true
    systemctl stop cups.path cups.socket cups.service cups-browsed.service >/dev/null 2>&1 || true
    CUPS_SERVICES_STOPPED=1
    find "$CUPS_SPOOL" -xdev -type f -exec shred -u -z -n 1 -- {} + >/dev/null 2>&1 || warn "Impossible d'écraser certains fichiers du spoule CUPS."
    if ! umount "$CUPS_SPOOL" 2>/dev/null; then
      warn "$CUPS_SPOOL est occupé ; tentative de démontage différé."
      umount -l "$CUPS_SPOOL" 2>/dev/null || warn "Impossible de démonter $CUPS_SPOOL."
    fi
    CUPS_SPOOL_MOUNTED=0
  fi

  if (( CUPS_CACHE_MOUNTED )); then
    if ! umount "$CUPS_CACHE" 2>/dev/null; then
      warn "$CUPS_CACHE est occupé ; tentative de démontage différé."
      umount -l "$CUPS_CACHE" 2>/dev/null || warn "Impossible de démonter $CUPS_CACHE."
    fi
    CUPS_CACHE_MOUNTED=0
  fi
  if (( CUPS_LOG_MOUNTED )); then
    if ! umount "$CUPS_LOG" 2>/dev/null; then
      warn "$CUPS_LOG est occupé ; tentative de démontage différé."
      umount -l "$CUPS_LOG" 2>/dev/null || warn "Impossible de démonter $CUPS_LOG."
    fi
    CUPS_LOG_MOUNTED=0
  fi

  if (( CUPS_SERVICES_STOPPED )); then
    if (( CUPS_SOCKET_WAS_ACTIVE )); then
      systemctl start cups.socket >/dev/null 2>&1 || warn "Impossible de redémarrer cups.socket."
    fi
    if (( CUPS_PATH_WAS_ACTIVE )); then
      systemctl start cups.path >/dev/null 2>&1 || warn "Impossible de redémarrer cups.path."
    fi
    if (( CUPS_WAS_ACTIVE )); then
      systemctl start cups.service >/dev/null 2>&1 || warn "Impossible de redémarrer CUPS."
    fi
    if (( CUPS_BROWSED_WAS_ACTIVE )); then
      systemctl start cups-browsed.service >/dev/null 2>&1 || warn "Impossible de redémarrer cups-browsed."
    fi
    CUPS_SERVICES_STOPPED=0
  fi
}

print_plates() {
  local out="$1" choice answer

  if (( NO_PRINT )); then
    info "Impression ignorée (--no-print)."
    return 0
  fi

  if [[ "${SANS_PLANCHES:-0}" == "1" ]]; then
    info "Planches désactivées (SANS_PLANCHES=1) : impression ignorée."
    return 0
  fi
  if [[ ! -f "$out/pdf/test_grand_8qr.pdf" ]]; then
    warn "PDF de test absent : impression ignorée."
    return 0
  fi
  if ! command -v lp >/dev/null 2>&1 || ! command -v lpstat >/dev/null 2>&1 || ! command -v cancel >/dev/null 2>&1; then
    warn "CUPS (lp/lpstat/cancel) absent : impression ignorée."
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl absent : impossible d'isoler le spoule CUPS. Impression ignorée."
    return 0
  fi
  if ! getent group lp >/dev/null 2>&1; then
    warn "Groupe lp absent : impression ignorée."
    return 0
  fi
  if mountpoint -q "$CUPS_SPOOL" || mountpoint -q "$CUPS_CACHE" || mountpoint -q "$CUPS_LOG"; then
    warn "Un répertoire CUPS est déjà un point de montage : impression ignorée par prudence."
    return 0
  fi
  for repertoire in "$CUPS_SPOOL" "$CUPS_CACHE" "$CUPS_LOG"; do
    if [[ ! -d "$repertoire" ]]; then
      warn "$repertoire n'existe pas : impression ignorée."
      return 0
    fi
  done

  read -r -p "Imprimer les planches maintenant ? [o/N] " answer || answer=""
  [[ "$answer" =~ ^[oOyY]$ ]] || { info "Impression ignorée."; return 0; }

  CUPS_WAS_ACTIVE=0
  CUPS_SOCKET_WAS_ACTIVE=0
  CUPS_PATH_WAS_ACTIVE=0
  CUPS_BROWSED_WAS_ACTIVE=0
  if systemctl is-active --quiet cups.service; then
    CUPS_WAS_ACTIVE=1
  fi
  if systemctl is-active --quiet cups.socket; then
    CUPS_SOCKET_WAS_ACTIVE=1
  fi
  if systemctl is-active --quiet cups.path; then
    CUPS_PATH_WAS_ACTIVE=1
  fi
  if systemctl is-active --quiet cups-browsed.service; then
    CUPS_BROWSED_WAS_ACTIVE=1
  fi

  info "Isolation des spoules, caches et journaux CUPS en RAM..."
  systemctl stop cups.path cups.socket cups.service cups-browsed.service 2>/dev/null || true
  CUPS_SERVICES_STOPPED=1

  if ! mount -t tmpfs -o "$(cups_tmpfs_options 512M 0710)" tmpfs "$CUPS_SPOOL"; then
    warn "Impossible de monter le tmpfs du spoule CUPS : impression ignorée."
    stop_cups_spool
    return 0
  fi
  CUPS_SPOOL_MOUNTED=1
  install -d -m 1770 -o root -g lp "$CUPS_SPOOL/tmp"
  install -d -m 0770 -o root -g lp "$CUPS_SPOOL/cache"

  if ! mount -t tmpfs -o "$(cups_tmpfs_options 128M 0750)" tmpfs "$CUPS_CACHE"; then
    warn "Impossible de monter le tmpfs du cache CUPS : impression ignorée."
    stop_cups_spool
    return 0
  fi
  CUPS_CACHE_MOUNTED=1

  if ! mount -t tmpfs -o "$(cups_tmpfs_options 64M 0750)" tmpfs "$CUPS_LOG"; then
    warn "Impossible de monter le tmpfs des journaux CUPS : impression ignorée."
    stop_cups_spool
    return 0
  fi
  CUPS_LOG_MOUNTED=1

  if ! systemctl start cups.service; then
    warn "Impossible de démarrer CUPS : impression ignorée."
    stop_cups_spool
    return 0
  fi

  for _ in {1..20}; do
    if lpstat -r >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
  if ! lpstat -r >/dev/null 2>&1; then
    warn "Le planificateur CUPS ne répond pas : impression ignorée."
    stop_cups_spool
    return 0
  fi
  if [[ -z "$(lpstat -p 2>/dev/null || true)" ]]; then
    warn "Aucune imprimante configurée : impression ignorée."
    stop_cups_spool
    return 0
  fi

  info "Impression de la planche de test (100 %, sans ajustement)..."
  if ! lp -o fit-to-page=false -o scaling=100 "$out/pdf/test_grand_8qr.pdf"; then
    warn "Échec de l'envoi de la planche de test."
    stop_cups_spool
    return 0
  fi

  read -r -p "Scanne les 8 QR. Entrée si tout est lisible, q pour arrêter l'impression : " answer || answer=""
  if [[ "$answer" == "q" ]]; then
    stop_cups_spool
    return 0
  fi

  while true; do
    printf '\n'
    printf '  1) planches_qr_grand.pdf (confort, 3×4)\n'
    printf '  2) planches_qr.pdf (compact, 4×5)\n'
    printf '  3) les deux planches\n'
    printf '  4) index_qr.pdf\n'
    printf "  0) terminer l'impression\n"
    read -r -p "Choix : " choice || break
    case "$choice" in
      1) lp -o fit-to-page=false -o scaling=100 "$out/pdf/planches_qr_grand.pdf" || warn "Échec de l'envoi des planches grand." ;;
      2) lp -o fit-to-page=false -o scaling=100 "$out/pdf/planches_qr.pdf" || warn "Échec de l'envoi des planches compactes." ;;
      3)
        lp -o fit-to-page=false -o scaling=100 "$out/pdf/planches_qr_grand.pdf" || warn "Échec de l'envoi des planches grand."
        lp -o fit-to-page=false -o scaling=100 "$out/pdf/planches_qr.pdf" || warn "Échec de l'envoi des planches compactes."
        ;;
      4) lp -o fit-to-page=false -o scaling=100 "$out/pdf/index_qr.pdf" || warn "Échec de l'envoi de l'index." ;;
      0) break ;;
      *) warn "Choix invalide." ;;
    esac
  done

  read -r -p "Appuie sur Entrée une fois les impressions terminées... " _ || true
  stop_cups_spool
}

proposer_suppression_anciennes_capsules() {
  local mount_dir="$1" capsule_courante="$2"
  local fichier base manifeste par2 answer
  local -a anciennes=()

  shopt -s nullglob
  for fichier in "$mount_dir"/sauvegarde_qr_*.tar.zst.age; do
    [[ -f "$fichier" ]] || continue
    [[ "$(basename -- "$fichier")" == "$capsule_courante" ]] && continue
    anciennes+=("$fichier")
  done
  shopt -u nullglob

  if (( ${#anciennes[@]} == 0 )); then
    return 0
  fi

  printf '\nAnciennes capsules présentes sur URGENCE_QR :\n'
  for fichier in "${anciennes[@]}"; do
    printf '  - %s\n' "$(basename -- "$fichier")"
  done
  warn "Le shred sur exFAT ne garantit pas l'effacement physique des cellules flash."
  read -r -p "Supprimer ces anciennes capsules ? [o/N] " answer || answer=""
  [[ "$answer" =~ ^[oOyY]$ ]] || { info "Anciennes capsules conservées."; return 0; }

  for fichier in "${anciennes[@]}"; do
    base="$(basename -- "$fichier")"
    if ! shred -u -z -n 1 -- "$fichier"; then
      warn "Impossible d'écraser $base."
    fi
    par2="${fichier}.par2"
    if [[ -f "$par2" ]] && ! shred -u -z -n 1 -- "$par2"; then
      warn "Impossible d'écraser $(basename -- "$par2")."
    fi
    for par2 in "$fichier".vol*.par2; do
      [[ -f "$par2" ]] || continue
      if ! shred -u -z -n 1 -- "$par2"; then
        warn "Impossible d'écraser $(basename -- "$par2")."
      fi
    done
    manifeste="${fichier%.tar.zst.age}.sha256"
    if [[ -f "$manifeste" ]] && ! shred -u -z -n 1 -- "$manifeste"; then
      warn "Impossible d'écraser $(basename -- "$manifeste")."
    fi
  done
  ok "Anciennes capsules traitées."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --device."
      DEV_ARG="$2"
      shift 2
      ;;
    --csv)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --csv."
      CSV_ARG="$2"
      shift 2
      ;;
    --ram-size)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --ram-size."
      RAM_SIZE="$2"
      shift 2
      ;;
    --no-print)
      NO_PRINT=1
      shift
      ;;
    --garder-source)
      KEEP_SOURCE=1
      shift
      ;;
    --allow-loopback)
      ALLOW_LOOPBACK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        if [[ -z "$DEV_ARG" ]]; then
          DEV_ARG="$1"
        elif [[ -z "$CSV_ARG" ]]; then
          CSV_ARG="$1"
        else
          die "Trop d'arguments positionnels."
        fi
        shift
      done
      ;;
    -*)
      die "Option inconnue : $1"
      ;;
    *)
      if [[ -z "$DEV_ARG" ]]; then
        DEV_ARG="$1"
      elif [[ -z "$CSV_ARG" ]]; then
        CSV_ARG="$1"
      else
        die "Trop d'arguments positionnels."
      fi
      shift
      ;;
  esac
done

[[ -n "$DEV_ARG" ]] || { usage; exit 1; }

case "$RAM_SIZE" in
  *[Gg])
    RAM_NUM="${RAM_SIZE%[Gg]}"
    [[ "$RAM_NUM" =~ ^[0-9]+$ ]] || die "--ram-size invalide (ex. 2G, 512M)."
    RAM_SIZE_MIB=$(( RAM_NUM * 1024 ))
    ;;
  *[Mm])
    RAM_NUM="${RAM_SIZE%[Mm]}"
    [[ "$RAM_NUM" =~ ^[0-9]+$ ]] || die "--ram-size invalide (ex. 2G, 512M)."
    RAM_SIZE_MIB="$RAM_NUM"
    ;;
  *)
    die "--ram-size invalide (ex. 2G, 512M)."
    ;;
esac
(( RAM_SIZE_MIB >= 256 )) || die "--ram-size doit être au moins 256M."

require_root
resolve_real_user

section "Vérification des dépendances"
for cmd in cryptsetup age zstd par2 shred rsync qrencode python3 tar \
  sha256sum lsblk findmnt mount umount mountpoint swapoff swapon \
  runuser mktemp install cp chown chmod find sync df du diff cmp stat blkid; do
  require_cmd "$cmd"
done

if [[ "${SANS_PLANCHES:-0}" != "1" ]]; then
  info "Vérification de WeasyPrint sous l'utilisateur $REAL_USER..."
  if ! runuser -u "$REAL_USER" -- env HOME="$REAL_HOME" PATH="$REAL_PATH" \
    python3 -c 'import weasyprint' >/dev/null 2>&1; then
    die "WeasyPrint n'est pas importable par python3 pour $REAL_USER. Installez-le ou utilisez SANS_PLANCHES=1."
  fi
fi

MEM_AVAILABLE_KIB="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$MEM_AVAILABLE_KIB" =~ ^[0-9]+$ ]] || die "Impossible de lire MemAvailable."
MEM_AVAILABLE_MIB=$(( MEM_AVAILABLE_KIB / 1024 ))
if (( RAM_SIZE_MIB > MEM_AVAILABLE_MIB )); then
  die "La taille du tmpfs (${RAM_SIZE_MIB} MiB) dépasse la RAM disponible (${MEM_AVAILABLE_MIB} MiB)."
elif (( RAM_SIZE_MIB > MEM_AVAILABLE_MIB / 2 )); then
  warn "Le tmpfs (${RAM_SIZE_MIB} MiB) utilise plus de la moitié de la RAM disponible."
fi

DEV="$(readlink -f -- "$DEV_ARG")"
validate_usb_device "$DEV"
P1="$(part_path "$DEV" 1)"
P2="$(part_path "$DEV" 2)"

[[ -b "$P1" ]] || die "Partition 1 introuvable : $P1"
[[ -b "$P2" ]] || die "Partition 2 introuvable : $P2"
cryptsetup isLuks "$P1" >/dev/null 2>&1 || die "$P1 n'est pas un volume LUKS."
FSTYPE2="$(blkid -o value -s TYPE "$P2" 2>/dev/null || true)"
[[ "$FSTYPE2" == "exfat" ]] || warn "La partition 2 n'est pas détectée comme exFAT (type=$FSTYPE2)."
check_luks_memory "$P1"

if cryptsetup status "$MAPPER" >/dev/null 2>&1; then
  die "Le mapper $MAPPER est déjà actif. Fermez-le avant de relancer."
fi
if mountpoint -q "$VAULT_MNT" || mountpoint -q "$URGENCE_MNT"; then
  die "Un point de montage USB est déjà utilisé. Démontez-le avant de relancer."
fi
if mountpoint -q "$RAM_MNT"; then
  die "$RAM_MNT est déjà monté. Nettoyez l'enclave précédente avant de relancer."
fi
if [[ -e "$RAM_MNT" && ! -d "$RAM_MNT" ]]; then
  die "$RAM_MNT existe mais n'est pas un répertoire."
fi
if [[ -d "$RAM_MNT" ]] && [[ -n "$(ls -A "$RAM_MNT" 2>/dev/null || true)" ]]; then
  die "$RAM_MNT n'est pas vide. Refus d'écraser des données existantes."
fi

AGE_HDR="$REAL_HOME/luks_header_qr.bak.age"
if [[ -s "$AGE_HDR" ]]; then
  HAVE_AGE_HDR=1
else
  warn "En-tête LUKS chiffré absent : $AGE_HDR. La partition d'urgence n'aura pas de copie d'en-tête."
fi

section "Hygiène système"
ulimit -c 0 || die "Impossible de désactiver les core dumps."
[[ "$(ulimit -c)" == "0" ]] || die "Les core dumps ne sont pas désactivés."
info "Core dumps désactivés."

mapfile -t SWAP_LIST < <(swapon --show=NAME --noheadings 2>/dev/null | awk 'NF {print $1}')
if (( ${#SWAP_LIST[@]} > 0 )); then
  info "Désactivation du swap (${SWAP_LIST[*]})..."
  SWAP_DISABLED=1
  swapoff -a
  if swapon --show --noheadings 2>/dev/null | grep -q '[^[:space:]]'; then
    die "Le swap est toujours actif après swapoff -a."
  fi
  ok "Swap désactivé ; il sera restauré à la sortie."
else
  warn "Aucun swap actif."
fi

section "Création de l'enclave RAM"
install -d -m 0700 "$RAM_MNT"
RAM_OPTS="size=$RAM_SIZE,mode=0700,uid=$REAL_UID,gid=$REAL_GID,nodev,nosuid,noexec"
if kernel_ge_6_4; then
  RAM_OPTS+=",noswap"
else
  warn "Noyau antérieur à 6.4 : l'option noswap n'est pas disponible ; le swap est désactivé globalement."
fi
mount -t tmpfs -o "$RAM_OPTS" tmpfs "$RAM_MNT"
RAM_MOUNTED=1

install -d -m 0700 -o "$REAL_UID" -g "$REAL_GID" \
  "$RAM_MNT"/tmp "$RAM_MNT"/cache "$RAM_MNT"/data "$RAM_MNT"/config \
  "$RAM_MNT"/home "$RAM_MNT"/runtime "$RAM_MNT"/travail "$RAM_MNT"/pycache
install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$RAM_MNT/.nomedia"
install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$RAM_MNT/.trackerignore"

RAM_TMP="$RAM_MNT/tmp"
RAM_CACHE="$RAM_MNT/cache"
RAM_DATA="$RAM_MNT/data"
RAM_CONFIG="$RAM_MNT/config"
RAM_HOME="$RAM_MNT/home"
RAM_RUNTIME="$RAM_MNT/runtime"
TRAVAIL="$RAM_MNT/travail"
export TMPDIR="$RAM_TMP" TMP="$RAM_TMP" TEMP="$RAM_TMP"
export XDG_CACHE_HOME="$RAM_CACHE" XDG_DATA_HOME="$RAM_DATA" XDG_CONFIG_HOME="$RAM_CONFIG"
export XDG_RUNTIME_DIR="$RAM_RUNTIME" PYTHONDONTWRITEBYTECODE=1
ok "Enclave RAM montée sur $RAM_MNT (TMPDIR, caches et HOME redirigés)."

section "Acquisition du CSV"
CSV_WORK="$TRAVAIL/export.csv"
if [[ -n "$CSV_ARG" ]]; then
  [[ -f "$CSV_ARG" ]] || die "Fichier CSV introuvable : $CSV_ARG"
  CSV_SOURCE="$(readlink -f -- "$CSV_ARG")"
  [[ -f "$CSV_SOURCE" ]] || die "Fichier CSV introuvable après résolution : $CSV_SOURCE"
  [[ -s "$CSV_SOURCE" ]] || die "Le fichier CSV est vide : $CSV_SOURCE"
  CSV_LABEL="$(basename -- "$CSV_SOURCE" .csv)"

  if [[ "$CSV_SOURCE" != "$CSV_WORK" ]]; then
    cp -- "$CSV_SOURCE" "$CSV_WORK"
  fi
  chown "$REAL_UID:$REAL_GID" "$CSV_WORK"
  chmod 600 "$CSV_WORK"
  cmp -s -- "$CSV_SOURCE" "$CSV_WORK" || die "La copie du CSV dans l'enclave RAM est différente de la source."

  if [[ "$CSV_SOURCE" == "$RAM_MNT"/* ]]; then
    if [[ "$CSV_SOURCE" != "$CSV_WORK" ]]; then
      SOURCE_TO_SHRED="$CSV_SOURCE"
    fi
    info "CSV lu depuis l'enclave RAM."
  else
    warn "Le CSV source est sur le disque : des copies peuvent subsister malgré shred."
    warn "L'idéal est d'exporter directement dans $TRAVAIL/export.csv."
    if (( KEEP_SOURCE )); then
      info "Option --garder-source : l'original ne sera pas détruit."
    else
      read -r -p "Détruire l'original $CSV_SOURCE après vérification ? [o/N] " answer || answer=""
      if [[ "$answer" =~ ^[oOyY]$ ]]; then
        SOURCE_TO_SHRED="$CSV_SOURCE"
      else
        warn "L'original ne sera pas détruit."
      fi
    fi
  fi
else
  info "Exportez votre portefeuille directement dans :"
  printf '\n  %s\n\n' "$CSV_WORK"
  warn "N'enregistrez pas le CSV dans ~/Téléchargements ni dans /tmp."
  while true; do
    read -r -p "Appuie sur Entrée quand le fichier est prêt (q pour annuler) : " answer || die "Entrée interrompue."
    [[ "$answer" == "q" ]] && die "Annulé par l'utilisateur."
    if [[ -s "$CSV_WORK" ]]; then
      break
    fi
    warn "Fichier absent ou vide : $CSV_WORK"
  done
  chown "$REAL_UID:$REAL_GID" "$CSV_WORK"
  chmod 600 "$CSV_WORK"
  CSV_SOURCE="$CSV_WORK"
  CSV_LABEL="export"
fi
ok "CSV prêt dans l'enclave RAM."

section "Génération de la sauvegarde QR"
BASE_RAW="${CSV_LABEL:-export}"
BASE_SAFE="$(printf '%s' "$BASE_RAW" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_')"
NOM="sauvegarde_qr_${BASE_SAFE}_$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$TRAVAIL/$NOM"
if [[ -e "$OUT_DIR" ]]; then
  NOM="${NOM}_$$"
  OUT_DIR="$TRAVAIL/$NOM"
fi

info "Lancement de creer_sauvegarde_qr.sh sous $REAL_USER..."
if ! run_as_user "$SCRIPT_DIR/creer_sauvegarde_qr.sh" "$CSV_WORK" "$OUT_DIR"; then
  die "Le pipeline de génération a échoué."
fi

[[ -f "$OUT_DIR/LISEZMOI.txt" ]] || die "Sortie incomplète : LISEZMOI.txt absent."
[[ -f "$OUT_DIR/csv/index_enregistrements.csv" ]] || die "Sortie incomplète : index des enregistrements absent."
[[ -f "$OUT_DIR/json/index_meta.json" ]] || die "Sortie incomplète : index_meta.json absent."
QR_COUNT="$(find "$OUT_DIR/qrcodes" -maxdepth 1 -name 'morceau_??.png' | wc -l)"
(( QR_COUNT > 0 )) || die "Aucun QR code généré."
ok "Sauvegarde générée : $OUT_DIR ($QR_COUNT QR)."

info "Destruction du CSV de travail en RAM..."
shred -u -z -n 1 -- "$CSV_WORK" || die "Impossible de détruire le CSV de travail."
if [[ -n "$SOURCE_TO_SHRED" ]]; then
  info "Destruction de la source : $SOURCE_TO_SHRED"
  shred -u -z -n 1 -- "$SOURCE_TO_SHRED" || warn "Impossible de détruire complètement $SOURCE_TO_SHRED."
fi

section "Impression éventuelle"
print_plates "$OUT_DIR"

section "Capsule de survie"
CAPSULE="$TRAVAIL/$NOM.tar.zst.age"
MANIFEST="$TRAVAIL/$NOM.sha256"
info "Création de l'archive tar.zst.age (phrase de passe age demandée)..."
warn "Si tu laisses la phrase vide, age en génère une : note-la immédiatement."
install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$CAPSULE"
if ! tar --numeric-owner -C "$TRAVAIL" -cf - "$NOM" \
  | zstd -19 -T0 \
  | runuser -u "$REAL_USER" -- env HOME="$RAM_HOME" PATH="$REAL_PATH" \
      TMPDIR="$RAM_TMP" TMP="$RAM_TMP" TEMP="$RAM_TMP" \
      age -p -o "$CAPSULE"; then
  die "Échec de la création de la capsule age."
fi
[[ -s "$CAPSULE" ]] || die "La capsule age est vide."
chmod 600 "$CAPSULE"
if [[ -t 0 ]]; then
  read -r -p "Si age a affiché une phrase auto-générée, note-la maintenant. Entrée pour continuer... " _ || true
fi

info "Création de 15 % de redondance par2..."
par2 create -r15 -n1 "$CAPSULE"

shopt -s nullglob
PAR2_FILES=("$CAPSULE"*.par2)
shopt -u nullglob
(( ${#PAR2_FILES[@]} > 0 )) || die "Aucun fichier par2 généré."
chmod 600 "${PAR2_FILES[@]}"

(
  cd "$TRAVAIL"
  sha256sum "$(basename -- "$CAPSULE")" "${PAR2_FILES[@]##*/}" > "$(basename -- "$MANIFEST")"
)
chmod 600 "$MANIFEST"
chown "$REAL_UID:$REAL_GID" "$MANIFEST" "${PAR2_FILES[@]}"
ok "Capsule et manifeste SHA-256 créés."

TOTAL_URGENCE_BYTES=0
for f in "$CAPSULE" "${PAR2_FILES[@]}"; do
  fsize="$(stat -c %s -- "$f")"
  TOTAL_URGENCE_BYTES=$(( TOTAL_URGENCE_BYTES + fsize ))
done
if (( HAVE_AGE_HDR )); then
  TOTAL_URGENCE_BYTES=$(( TOTAL_URGENCE_BYTES + $(stat -c %s -- "$AGE_HDR") ))
fi

if (( TOTAL_URGENCE_BYTES > 220 * 1024 * 1024 )); then
  warn "La capsule + par2 + en-tête pèsent $((TOTAL_URGENCE_BYTES / 1024 / 1024)) MiB."
  warn "La partition URGENCE_QR de 256 MiB risque d'être insuffisante."
  read -r -p "Continuer le transfert (la partition d'urgence pourra être ignorée) ? [o/N] " answer || answer=""
  [[ "$answer" =~ ^[oOyY]$ ]] || die "Abandon avant transfert."
fi

section "Transfert vers le coffre LUKS2"
info "Ouverture de $P1..."
cryptsetup open "$P1" "$MAPPER"
MAPPER_OPEN=1
install -d -m 0700 "$VAULT_MNT"
mount -o rw,noatime,nodev,nosuid "/dev/mapper/$MAPPER" "$VAULT_MNT"
VAULT_MOUNTED=1

OUT_BYTES="$(du -sb -- "$OUT_DIR" | awk '{print $1}')"
VAULT_AVAIL="$(df -B1 --output=avail "$VAULT_MNT" | tail -n1 | awk '{print $1}')"
NEED_BYTES=$(( OUT_BYTES + TOTAL_URGENCE_BYTES + 64 * 1024 * 1024 ))
if (( NEED_BYTES > VAULT_AVAIL )); then
  die "Espace insuffisant dans le coffre : besoin ~$((NEED_BYTES / 1024 / 1024)) MiB, disponible $((VAULT_AVAIL / 1024 / 1024)) MiB."
fi

info "Synchronisation du dossier, de la capsule et des fichiers de contrôle..."
rsync -aAX --info=progress2 -- "$OUT_DIR" "$CAPSULE" "${PAR2_FILES[@]}" "$MANIFEST" "$VAULT_MNT/"
sync

info "Vérification de la copie..."
diff -r --no-dereference -- "$OUT_DIR" "$VAULT_MNT/$(basename -- "$OUT_DIR")" >/dev/null || die "La copie du dossier dans le coffre diffère de la source."
(
  cd "$VAULT_MNT"
  sha256sum -c "$(basename -- "$MANIFEST")"
) || die "La vérification SHA-256 de la capsule a échoué dans le coffre."
ok "Coffre synchronisé et vérifié."

section "Copie sur la partition d'urgence"
install -d -m 0700 "$URGENCE_MNT"
if mount -o rw,noatime,nodev,nosuid,uid="$REAL_UID",gid="$REAL_GID",umask=077 "$P2" "$URGENCE_MNT"; then
  URGENCE_MOUNTED=1
  URGENCE_AVAIL="$(df -B1 --output=avail "$URGENCE_MNT" | tail -n1 | awk '{print $1}')"
  if (( TOTAL_URGENCE_BYTES + 8 * 1024 * 1024 > URGENCE_AVAIL )); then
    warn "Espace insuffisant sur URGENCE_QR : copie ignorée."
    warn "Le coffre LUKS2 contient déjà la capsule et les fichiers par2."
  else
    cp -- "$CAPSULE" "${PAR2_FILES[@]}" "$MANIFEST" "$URGENCE_MNT/"
    if (( HAVE_AGE_HDR )); then
      cp -- "$AGE_HDR" "$URGENCE_MNT/"
    fi
    if [[ -f "$SCRIPT_DIR/README.md" ]]; then
      cp -- "$SCRIPT_DIR/README.md" "$URGENCE_MNT/"
    elif [[ -f "$SCRIPT_DIR/LISEZMOI.md" ]]; then
      cp -- "$SCRIPT_DIR/LISEZMOI.md" "$URGENCE_MNT/"
    fi
    sync
    (
      cd "$URGENCE_MNT"
      sha256sum -c "$(basename -- "$MANIFEST")"
    ) || die "La vérification SHA-256 de la copie d'urgence a échoué."
    if (( HAVE_AGE_HDR )); then
      cmp -s -- "$AGE_HDR" "$URGENCE_MNT/$(basename -- "$AGE_HDR")" || die "La copie de l'en-tête LUKS sur URGENCE_QR diffère."
    fi
    URGENCE_COPIED=1
    ok "Partition d'urgence copiée et vérifiée."
    proposer_suppression_anciennes_capsules \
      "$URGENCE_MNT" "$(basename -- "$CAPSULE")"
  fi
  sync
  umount "$URGENCE_MNT"
  URGENCE_MOUNTED=0
else
  warn "Impossible de monter URGENCE_QR : copie d'urgence ignorée."
fi

section "Fermeture"
sync
umount "$VAULT_MNT"
VAULT_MOUNTED=0
cryptsetup close "$MAPPER"
MAPPER_OPEN=0
ok "Coffre refermé."

section "Sauvegarde terminée"
printf 'Dossier coffre   : %s/%s/\n' "$VAULT_MNT" "$NOM"
printf 'Capsule coffre   : %s/%s\n' "$VAULT_MNT" "$(basename -- "$CAPSULE")"
printf 'Manifeste coffre : %s/%s\n' "$VAULT_MNT" "$(basename -- "$MANIFEST")"
if (( URGENCE_COPIED )); then
  printf 'Capsule secours  : %s/%s\n' "$URGENCE_MNT" "$(basename -- "$CAPSULE")"
  if (( HAVE_AGE_HDR )); then
    printf 'En-tête secours  : %s/%s\n' "$URGENCE_MNT" "$(basename -- "$AGE_HDR")"
  else
    printf "En-tête secours  : absent (sauvegarde d'en-tête introuvable)\n"
  fi
else
  printf 'Partition secours: copie ignorée ou indisponible\n'
fi
printf '\n'
warn "Le CSV source en RAM a été détruit. Vérifiez une restauration avant toute suppression supplémentaire."
warn "Les fichiers en RAM ont été effacés ; seule la copie du coffre subsiste."
warn "Vous pouvez retirer la clé USB après le démontage."
