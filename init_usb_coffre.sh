#!/usr/bin/env bash
#
# Initialise une clé USB comme coffre à froid :
#   - partition 1 : LUKS2 (AES-XTS 512 bits, Argon2id) + ext4
#   - partition 2 : exFAT de secours (URGENCE_QR)
#   - sauvegarde chiffrée de l'en-tête LUKS2 avec age
#
# Usage :
#   sudo ./init_usb_coffre.sh [--argon2-mib 2048] [--argon2-threads 4] /dev/sdX
#
# ATTENTION : cette commande détruit toutes les données du périphérique.

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
Usage : sudo ./init_usb_coffre.sh [options] /dev/sdX

Options :
  --argon2-mib N       Mémoire Argon2id en MiB (défaut : 2048, ajustée à la RAM)
  --argon2-threads N   Threads Argon2id (défaut : 4)
  -h, --help           Affiche cette aide

Exemple :
  sudo ./init_usb_coffre.sh /dev/sdX

Le périphérique doit être une clé USB (RM=1 ou TRAN=usb) et ne doit pas
contenir le système en cours d'exécution. Toutes ses données seront effacées.
EOF
}

ARGON2_MIB=2048
ARGON2_MIB_SET=0
ARGON2_THREADS=4
DEV_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --argon2-mib)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --argon2-mib."
      ARGON2_MIB="$2"
      ARGON2_MIB_SET=1
      shift 2
      ;;
    --argon2-threads)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --argon2-threads."
      ARGON2_THREADS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "Option inconnue : $1"
      ;;
    *)
      [[ -z "$DEV_ARG" ]] || die "Un seul périphérique est accepté."
      DEV_ARG="$1"
      shift
      ;;
  esac
done

while [[ $# -gt 0 ]]; do
  [[ -z "$DEV_ARG" ]] || die "Un seul périphérique est accepté."
  DEV_ARG="$1"
  shift
done

[[ -n "$DEV_ARG" ]] || { usage; exit 1; }
[[ "$ARGON2_MIB" =~ ^[0-9]+$ ]] || die "--argon2-mib doit être un entier."
[[ "$ARGON2_THREADS" =~ ^[0-9]+$ ]] || die "--argon2-threads doit être un entier."
(( ARGON2_MIB >= 256 && ARGON2_MIB <= 8192 )) || die "--argon2-mib doit être entre 256 et 8192."
(( ARGON2_THREADS >= 1 && ARGON2_THREADS <= 32 )) || die "--argon2-threads doit être entre 1 et 32."

VAULT_MNT="/mnt/usb_vault"
URGENCE_MNT="/mnt/usb_urgence"
HDR_DIR=""
HDR_TMP=""
AGE_HDR=""
VAULT_MOUNTED=0
URGENCE_MOUNTED=0
MAPPER_OPEN=0
AGE_HDR_PARTIAL=0
REAL_USER=""
REAL_UID=""
REAL_GID=""
REAL_HOME=""
REAL_PATH=""
DEV=""
P1=""
P2=""

cleanup() {
  local rc=$?
  trap - EXIT INT TERM HUP
  set +e +u

  if (( URGENCE_MOUNTED )); then
    sync 2>/dev/null || true
    umount "$URGENCE_MNT" 2>/dev/null || umount -l "$URGENCE_MNT" 2>/dev/null || true
    URGENCE_MOUNTED=0
  fi
  if (( VAULT_MOUNTED )); then
    sync 2>/dev/null || true
    umount "$VAULT_MNT" 2>/dev/null || umount -l "$VAULT_MNT" 2>/dev/null || true
    VAULT_MOUNTED=0
  fi
  if (( MAPPER_OPEN )); then
    cryptsetup close qr_vault 2>/dev/null || true
    MAPPER_OPEN=0
  fi
  if (( AGE_HDR_PARTIAL )) && [[ -n "${AGE_HDR:-}" && -f "$AGE_HDR" ]]; then
    rm -f -- "$AGE_HDR" 2>/dev/null || true
    AGE_HDR_PARTIAL=0
  fi
  if [[ -n "${HDR_TMP:-}" && -f "$HDR_TMP" ]]; then
    shred -u -z -n 3 -- "$HDR_TMP" 2>/dev/null || rm -f -- "$HDR_TMP"
  fi
  if [[ -n "${HDR_DIR:-}" && -d "$HDR_DIR" ]]; then
    rmdir -- "$HDR_DIR" 2>/dev/null || true
  fi

  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

require_root() {
  (( EUID == 0 )) || die "Ce script doit être lancé avec sudo : sudo $0 [options] /dev/sdX"
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
    src="$(findmnt -n -o SOURCE --target "$mp" 2>/dev/null || true)"
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
  local dev="$1" type rm tran ro size_bytes name

  [[ -b "$dev" ]] || die "Périphérique bloc introuvable : $dev"
  type="$(lsblk_field TYPE "$dev")"
  [[ "$type" == "disk" ]] || die "Passez le disque entier (ex. /dev/sdX), pas une partition."

  rm="$(lsblk_field RM "$dev")"
  tran="$(lsblk_field TRAN "$dev")"
  if [[ "$rm" != "1" && "$tran" != "usb" ]]; then
    die "Le périphérique n'est pas identifié comme amovible/USB (RM=$rm, TRAN=$tran)."
  fi

  ro="$(lsblk_field RO "$dev")"
  [[ "$ro" == "0" ]] || die "Le périphérique est protégé en écriture."

  is_system_disk "$dev" && die "Refus : ce périphérique contient le système en cours d'exécution."

  if lsblk -nr -o MOUNTPOINTS "$dev" 2>/dev/null | grep -q '[^[:space:]]'; then
    die "Refus : une partition de $dev est montée. Démontez-la d'abord."
  fi

  if lsblk -nr -o TYPE "$dev" 2>/dev/null | grep -Eq '^(lvm|md|dm|crypt)$'; then
    die "Refus : le périphérique participe à un volume LVM/MD/dm. Vérifiez avec lsblk."
  fi

  name="$(basename "$dev")"
  if [[ -d "/sys/class/block/$name/holders" ]] && [[ -n "$(ls -A "/sys/class/block/$name/holders" 2>/dev/null || true)" ]]; then
    die "Refus : le périphérique a des dépendances noyau (holders)."
  fi

  size_bytes="$(lsblk -bdn -o SIZE "$dev" 2>/dev/null | xargs || true)"
  [[ "$size_bytes" =~ ^[0-9]+$ ]] || die "Impossible de lire la taille de $dev."
  (( size_bytes >= 1024 * 1024 * 1024 )) || die "Taille insuffisante (minimum 1 Gio)."
}

wait_for_partitions() {
  for _ in {1..40}; do
    if [[ -b "$P1" && -b "$P2" ]]; then
      return 0
    fi
    sleep 0.5
  done
  die "Les partitions $P1 et $P2 ne sont pas apparues. Vérifiez avec lsblk."
}

confirm_destructive() {
  local serial model size answer confirm

  serial="$(lsblk_field SERIAL "$DEV")"
  model="$(lsblk_field MODEL "$DEV")"
  size="$(lsblk_field SIZE "$DEV")"
  [[ -n "$model" ]] || model="(inconnu)"

  printf '\n%sPériphérique cible :%s\n' "$C_BOLD" "$C_RESET"
  lsblk -o NAME,MODEL,SIZE,TRAN,RM,SERIAL,FSTYPE,MOUNTPOINTS "$DEV"
  printf '\n  Modèle : %s\n  Taille : %s\n  Série  : %s\n' "$model" "$size" "${serial:-(indisponible)}"
  printf '\n%sCette opération va EFFACER TOUTES LES DONNÉES de %s.%s\n' "$C_RED" "$DEV" "$C_RESET"

  read -r -p "Tape EFFACER pour continuer : " answer || die "Confirmation interrompue."
  [[ "$answer" == "EFFACER" ]] || die "Confirmation incorrecte. Abandon."

  if [[ -n "$serial" ]]; then
    read -r -p "Tape le numéro de série exact ($serial) : " confirm || die "Confirmation interrompue."
    [[ "$confirm" == "$serial" ]] || die "Numéro de série incorrect. Abandon."
  else
    warn "Numéro de série indisponible : confirmation par nom de périphérique."
    read -r -p "Tape $(basename "$DEV") pour confirmer : " confirm || die "Confirmation interrompue."
    [[ "$confirm" == "$(basename "$DEV")" ]] || die "Confirmation incorrecte. Abandon."
  fi
}

require_root
resolve_real_user

section "Vérification des dépendances"
for cmd in cryptsetup wipefs parted partprobe lsblk findmnt mount umount \
  mkfs.ext4 mkfs.exfat age shred udevadm blockdev getent runuser mktemp \
  install chown chmod sync; do
  require_cmd "$cmd"
done

MEM_AVAILABLE_KIB="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$MEM_AVAILABLE_KIB" =~ ^[0-9]+$ ]] || die "Impossible de lire MemAvailable."

if (( ARGON2_MIB_SET == 0 )); then
  if (( MEM_AVAILABLE_KIB < 2 * 1024 * 1024 )); then
    ARGON2_MIB=512
  elif (( MEM_AVAILABLE_KIB < 3 * 1024 * 1024 )); then
    ARGON2_MIB=1024
  fi
  info "Mémoire Argon2id ajustée à ${ARGON2_MIB} MiB selon la RAM disponible."
fi

if (( ARGON2_MIB * 1024 + 512 * 1024 > MEM_AVAILABLE_KIB )); then
  die "Pas assez de RAM pour Argon2id ${ARGON2_MIB} MiB (MemAvailable=${MEM_AVAILABLE_KIB} KiB)."
fi

DEV="$(readlink -f -- "$DEV_ARG")"
validate_usb_device "$DEV"
P1="$(part_path "$DEV" 1)"
P2="$(part_path "$DEV" 2)"

section "Confirmation"
confirm_destructive

section "Partitionnement GPT"
sync
info "Effacement des signatures existantes..."
wipefs -a "$DEV"
info "Création de la table GPT et des partitions..."
parted -s -a optimal "$DEV" mklabel gpt
parted -s -a optimal "$DEV" -- mkpart COFFRE_LUKS 1MiB -256MiB
parted -s -a optimal "$DEV" -- mkpart URGENCE_QR -256MiB 100%
partprobe "$DEV" 2>/dev/null || true
udevadm settle --timeout=15 2>/dev/null || true
wait_for_partitions
lsblk -o NAME,PARTLABEL,SIZE,FSTYPE,MOUNTPOINTS "$DEV"

section "Formatage LUKS2"
LUKS_MEMORY_KIB=$(( ARGON2_MIB * 1024 ))
cryptsetup luksFormat \
  --type luks2 \
  --cipher aes-xts-plain64 \
  --key-size 512 \
  --hash sha512 \
  --pbkdf argon2id \
  --pbkdf-memory "$LUKS_MEMORY_KIB" \
  --pbkdf-parallel "$ARGON2_THREADS" \
  --iter-time 4000 \
  --sector-size 4096 \
  --label "QR_COLD_VAULT" \
  "$P1"
ok "Volume LUKS2 créé."
cryptsetup luksDump "$P1" | sed -n '1,40p'

section "Création du système de fichiers ext4"
cryptsetup open "$P1" qr_vault
MAPPER_OPEN=1
mkfs.ext4 -L "QR_DATA" -m 0 "/dev/mapper/qr_vault"
install -d -m 0700 "$VAULT_MNT"
mount -o rw,noatime,nodev,nosuid "/dev/mapper/qr_vault" "$VAULT_MNT"
VAULT_MOUNTED=1
chown "$REAL_UID:$REAL_GID" "$VAULT_MNT"
chmod 0700 "$VAULT_MNT"
install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$VAULT_MNT/.nomedia"
install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$VAULT_MNT/.trackerignore"
sync
umount "$VAULT_MNT"
VAULT_MOUNTED=0
cryptsetup close qr_vault
MAPPER_OPEN=0
ok "ext4 créé, permissions 0700, sentinelles .nomedia et .trackerignore en place."

section "Formatage de la partition d'urgence"
mkfs.exfat -n "URGENCE_QR" "$P2"
ok "Partition URGENCE_QR formatée en exFAT."

section "Sauvegarde de l'en-tête LUKS2"
HDR_DIR="$(mktemp -d /dev/shm/luks_header_qr.XXXXXX)"
chown "$REAL_UID:$REAL_GID" "$HDR_DIR"
chmod 700 "$HDR_DIR"
HDR_TMP="$HDR_DIR/header.bak"
info "Extraction de l'en-tête vers /dev/shm..."
cryptsetup luksHeaderBackup "$P1" --header-backup-file "$HDR_TMP"
chmod 600 "$HDR_TMP"
chown "$REAL_UID:$REAL_GID" "$HDR_TMP"
[[ -s "$HDR_TMP" ]] || die "La sauvegarde d'en-tête est vide."

AGE_HDR="$REAL_HOME/luks_header_qr.bak.age"
if [[ -e "$AGE_HDR" ]]; then
  die "Une sauvegarde existe déjà : $AGE_HDR. Déplacez-la avant de relancer."
fi
info "Chiffrement de l'en-tête avec age (phrase de passe demandée)..."
warn "Si tu laisses la phrase vide, age en génère une : note-la immédiatement."
AGE_HDR_PARTIAL=1
runuser -u "$REAL_USER" -- env HOME="$REAL_HOME" PATH="$REAL_PATH" \
  age -p -o "$AGE_HDR" "$HDR_TMP"
[[ -s "$AGE_HDR" ]] || die "Le fichier age de l'en-tête est vide."
AGE_HDR_PARTIAL=0
chmod 600 "$AGE_HDR"
shred -u -z -n 3 -- "$HDR_TMP"
HDR_TMP=""
rmdir -- "$HDR_DIR"
HDR_DIR=""
ok "En-tête chiffré : $AGE_HDR"

section "Copie sur la partition d'urgence"
install -d -m 0700 "$URGENCE_MNT"
if mount -o rw,noatime,nodev,nosuid,uid="$REAL_UID",gid="$REAL_GID",umask=077 "$P2" "$URGENCE_MNT"; then
  URGENCE_MOUNTED=1
  cp -- "$AGE_HDR" "$URGENCE_MNT/"
  if [[ -f "$SCRIPT_DIR/README.md" ]]; then
    cp -- "$SCRIPT_DIR/README.md" "$URGENCE_MNT/"
  elif [[ -f "$SCRIPT_DIR/LISEZMOI.md" ]]; then
    cp -- "$SCRIPT_DIR/LISEZMOI.md" "$URGENCE_MNT/"
  fi
  sync
  umount "$URGENCE_MNT"
  URGENCE_MOUNTED=0
  ok "En-tête chiffré copié sur URGENCE_QR."
else
  warn "Impossible de monter URGENCE_QR. L'en-tête reste disponible dans $AGE_HDR."
fi

section "Initialisation terminée"
lsblk -f "$DEV"
printf '\n'
info "Coffre LUKS2 : $P1"
info "Partition d'urgence : $P2 (exFAT)"
info "En-tête chiffré : $AGE_HDR"
printf '\n'
printf 'Prochaine étape :\n'
printf '  sudo %s/executer_sauvegarde_ram.sh %s\n' "$SCRIPT_DIR" "$DEV"
printf '\n'
warn "Conservez la phrase de passe age de l'en-tête hors de la clé et distincte de celle du coffre."
warn "Testez une restauration complète avant de supprimer l'export CSV d'origine."
