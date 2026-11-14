#!/usr/bin/env bash
#
# Consulte un coffre USB LUKS2 strictement en lecture seule.
# Les scans et les fichiers extraits restent dans une enclave RAM éphémère.
#
# Usage :
#   sudo ./consulter_coffre_ro.sh [options] /dev/sdX
#
# Options :
#   --id R123            Extrait l'entrée R123
#   --nom TEXTE          Extrait l'entrée dont le nom contient TEXTE
#   --restaurer          Restaure le CSV complet et vérifie le SHA-256
#   --export FICHIER     Copie un export JSON Binary Eye dans l'enclave RAM
#   --afficher           Affiche la ligne extraite (mot de passe compris)
#   --ram-size TAILLE    Taille du tmpfs (défaut : 512M)
#   -h, --help           Affiche cette aide

set -Eeuo pipefail
umask 077

unset HISTFILE || true
HISTFILE=/dev/null
HISTSIZE=0
HISTFILESIZE=0
set +o history || true

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin${PATH:+:$PATH}"

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
Usage : sudo ./consulter_coffre_ro.sh [options] /dev/sdX

Options :
  --id R123            Extrait l'entrée R123
  --nom TEXTE          Extrait l'entrée dont le nom contient TEXTE
  --restaurer          Restaure le CSV complet et vérifie le SHA-256
  --export FICHIER     Copie un export JSON Binary Eye dans l'enclave RAM
  --afficher           Affiche la ligne extraite (mot de passe compris)
  --ram-size TAILLE    Taille du tmpfs (défaut : 512M)
  --allow-loopback     Autorise un périphérique /dev/loopX (tests uniquement)
  -h, --help           Affiche cette aide

Sans --id, --nom ou --restaurer, un menu interactif est proposé.
Le coffre est ouvert avec cryptsetup open --readonly et monté avec -o ro.
Les sorties sont écrites uniquement dans /mnt/ram_sec/sorties.
EOF
}

VAULT_MNT="/mnt/usb_vault"
RAM_MNT="/mnt/ram_sec"
MAPPER="qr_vault_ro"

DEV_ARG=""
ID_ARG=""
NOM_ARG=""
EXPORT_ARG=""
AFFICHER=0
RESTAURER=0
RAM_SIZE="512M"
ALLOW_LOOPBACK=0

RAM_MOUNTED=0
VAULT_MOUNTED=0
MAPPER_OPEN=0
SWAP_DISABLED=0
SWAP_LIST=()

DEV=""
P1=""
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
SCANS=""
SORTIES=""
BK=""
BK_NAME=""

cleanup() {
  local rc=$?
  trap - EXIT INT TERM HUP
  set +e +u

  cd / 2>/dev/null || true
  if (( RAM_MOUNTED )) && [[ "${RAM_MNT:-}" == "/mnt/ram_sec" && -d "$RAM_MNT" ]]; then
    find "$RAM_MNT" -xdev -type f -exec shred -u -z -n 1 -- {} + >/dev/null 2>&1 || true
    find "$RAM_MNT" -xdev -type l -delete >/dev/null 2>&1 || true
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
  if (( RAM_MOUNTED )); then
    if ! umount "$RAM_MNT" 2>/dev/null; then
      warn "$RAM_MNT est occupé ; tentative de démontage différé."
      umount -l "$RAM_MNT" 2>/dev/null || warn "Impossible de démonter $RAM_MNT."
    fi
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

choose_backup() {
  local i choice
  if (( ${#BACKUPS[@]} == 0 )); then
    die "Aucun dossier sauvegarde_qr_* trouvé dans $VAULT_MNT."
  fi
  if (( ${#BACKUPS[@]} == 1 )); then
    BK_NAME="${BACKUPS[0]}"
  else
    printf '\nSauvegardes disponibles :\n'
    for i in "${!BACKUPS[@]}"; do
      printf '  %d) %s\n' "$((i + 1))" "${BACKUPS[$i]}"
    done
    while true; do
      read -r -p "Choix : " choice || die "Entrée interrompue."
      [[ "$choice" =~ ^[0-9]+$ ]] || { warn "Choix invalide."; continue; }
      if (( choice >= 1 && choice <= ${#BACKUPS[@]} )); then
        BK_NAME="${BACKUPS[$((choice - 1))]}"
        break
      fi
      warn "Choix hors plage."
    done
  fi
  BK="$VAULT_MNT/$BK_NAME"
  [[ -f "$BK/scripts/extraire_entree.py" ]] || die "Script d'extraction absent dans $BK."
  [[ -f "$BK/csv/index_enregistrements.csv" ]] || die "Index des enregistrements absent dans $BK."
  [[ -f "$BK/csv/index_morceaux.csv" ]] || die "Index des morceaux absent dans $BK."
  [[ -f "$BK/json/index_meta.json" ]] || die "index_meta.json absent dans $BK."
  ok "Sauvegarde sélectionnée : $BK_NAME"
}

extract_entry() {
  local outfile="$1" mode="$2" value="$3"
  local -a cmd

  cmd=(python3 -B "$BK/scripts/extraire_entree.py"
    --scans "$SCANS"
    --index "$BK/csv/index_enregistrements.csv"
    --morceaux "$BK/csv/index_morceaux.csv"
    --meta "$BK/json/index_meta.json"
    --sortie "$outfile")

  if [[ "$mode" == "id" ]]; then
    cmd+=(--id "$value")
  else
    cmd+=(--nom "$value")
  fi
  if (( AFFICHER )); then
    cmd+=(--afficher)
  fi

  info "Extraction en RAM..."
  run_as_user "${cmd[@]}"
}

restore_all() {
  local outfile="$1"
  info "Restauration complète en RAM..."
  run_as_user python3 -B "$BK/scripts/restaurer_sauvegarde.py" \
    --scans "$SCANS" \
    --morceaux "$BK/csv/index_morceaux.csv" \
    --meta "$BK/json/index_meta.json" \
    --sortie "$outfile"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --device."
      DEV_ARG="$2"
      shift 2
      ;;
    --id)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --id."
      ID_ARG="$2"
      shift 2
      ;;
    --nom)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --nom."
      NOM_ARG="$2"
      shift 2
      ;;
    --restaurer)
      RESTAURER=1
      shift
      ;;
    --export)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --export."
      EXPORT_ARG="$2"
      shift 2
      ;;
    --afficher)
      AFFICHER=1
      shift
      ;;
    --ram-size)
      [[ $# -ge 2 ]] || die "Valeur manquante pour --ram-size."
      RAM_SIZE="$2"
      shift 2
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
        [[ -z "$DEV_ARG" ]] || die "Un seul périphérique est accepté."
        DEV_ARG="$1"
        shift
      done
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

[[ -n "$DEV_ARG" ]] || { usage; exit 1; }
ACTION_COUNT=0
if (( RESTAURER )); then ACTION_COUNT=$((ACTION_COUNT + 1)); fi
if [[ -n "$ID_ARG" ]]; then ACTION_COUNT=$((ACTION_COUNT + 1)); fi
if [[ -n "$NOM_ARG" ]]; then ACTION_COUNT=$((ACTION_COUNT + 1)); fi
(( ACTION_COUNT <= 1 )) || die "--id, --nom et --restaurer sont incompatibles."

case "$RAM_SIZE" in
  *[Gg])
    RAM_NUM="${RAM_SIZE%[Gg]}"
    [[ "$RAM_NUM" =~ ^[0-9]+$ ]] || die "--ram-size invalide (ex. 512M, 1G)."
    RAM_SIZE_MIB=$(( RAM_NUM * 1024 ))
    ;;
  *[Mm])
    RAM_NUM="${RAM_SIZE%[Mm]}"
    [[ "$RAM_NUM" =~ ^[0-9]+$ ]] || die "--ram-size invalide (ex. 512M, 1G)."
    RAM_SIZE_MIB="$RAM_NUM"
    ;;
  *)
    die "--ram-size invalide (ex. 512M, 1G)."
    ;;
esac
(( RAM_SIZE_MIB >= 128 )) || die "--ram-size doit être au moins 128M."

require_root
resolve_real_user

section "Vérification des dépendances"
for cmd in cryptsetup lsblk findmnt mount umount mountpoint runuser mktemp \
  install shred python3 sync stat cmp find cp chown chmod swapoff swapon; do
  require_cmd "$cmd"
done

DEV="$(readlink -f -- "$DEV_ARG")"
validate_usb_device "$DEV"
P1="$(part_path "$DEV" 1)"
[[ -b "$P1" ]] || die "Partition 1 introuvable : $P1"
cryptsetup isLuks "$P1" >/dev/null 2>&1 || die "$P1 n'est pas un volume LUKS."
check_luks_memory "$P1"

if cryptsetup status "$MAPPER" >/dev/null 2>&1; then
  die "Le mapper $MAPPER est déjà actif. Fermez-le avant de relancer."
fi
if mountpoint -q "$VAULT_MNT"; then
  die "$VAULT_MNT est déjà monté. Démontez-le avant de relancer."
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

section "Hygiène et enclave RAM"
ulimit -c 0 || die "Impossible de désactiver les core dumps."
[[ "$(ulimit -c)" == "0" ]] || die "Les core dumps ne sont pas désactivés."

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

install -d -m 0700 "$RAM_MNT"
RAM_OPTS="size=$RAM_SIZE,mode=0700,uid=$REAL_UID,gid=$REAL_GID,nodev,nosuid,noexec"
if kernel_ge_6_4; then
  RAM_OPTS+=",noswap"
else
  warn "Noyau antérieur à 6.4 : noswap indisponible. Les pages du tmpfs pourraient être paginées sur disque."
fi
mount -t tmpfs -o "$RAM_OPTS" tmpfs "$RAM_MNT"
RAM_MOUNTED=1

install -d -m 0700 -o "$REAL_UID" -g "$REAL_GID" \
  "$RAM_MNT"/tmp "$RAM_MNT"/cache "$RAM_MNT"/data "$RAM_MNT"/config \
  "$RAM_MNT"/home "$RAM_MNT"/runtime "$RAM_MNT"/scans "$RAM_MNT"/sorties
install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$RAM_MNT/.nomedia"
install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$RAM_MNT/.trackerignore"

RAM_TMP="$RAM_MNT/tmp"
RAM_CACHE="$RAM_MNT/cache"
RAM_DATA="$RAM_MNT/data"
RAM_CONFIG="$RAM_MNT/config"
RAM_HOME="$RAM_MNT/home"
RAM_RUNTIME="$RAM_MNT/runtime"
SCANS="$RAM_MNT/scans"
SORTIES="$RAM_MNT/sorties"
export TMPDIR="$RAM_TMP" TMP="$RAM_TMP" TEMP="$RAM_TMP"
export XDG_CACHE_HOME="$RAM_CACHE" XDG_DATA_HOME="$RAM_DATA" XDG_CONFIG_HOME="$RAM_CONFIG"
export XDG_RUNTIME_DIR="$RAM_RUNTIME" PYTHONDONTWRITEBYTECODE=1
ok "Enclave RAM montée sur $RAM_MNT."

section "Ouverture du coffre en lecture seule"
cryptsetup open --readonly "$P1" "$MAPPER"
MAPPER_OPEN=1
install -d -m 0700 "$VAULT_MNT"
if ! mount -o ro,noatime,nodev,nosuid,noload "/dev/mapper/$MAPPER" "$VAULT_MNT"; then
  warn "Montage strictement lecture seule impossible (journal ext4 non vide ?)."
  warn "Démontez proprement la clé ou montez-la une fois en écriture pour réparer, puis relancez."
  die "Arrêt sans montage en écriture."
fi
VAULT_MOUNTED=1
ok "Coffre monté en lecture seule (ro,noatime,nodev,nosuid,noload)."

section "Sélection de la sauvegarde"
mapfile -t BACKUPS < <(find "$VAULT_MNT" -mindepth 1 -maxdepth 1 -type d -name 'sauvegarde_qr_*' -printf '%f\n' | sort)
choose_backup

section "Dépôt des scans"
if [[ -n "$EXPORT_ARG" ]]; then
  [[ -f "$EXPORT_ARG" ]] || die "Export JSON introuvable : $EXPORT_ARG"
  EXPORT_ABS="$(readlink -f -- "$EXPORT_ARG")"
  cp -- "$EXPORT_ABS" "$SCANS/binary_eye_all_qr.json"
  chown "$REAL_UID:$REAL_GID" "$SCANS/binary_eye_all_qr.json"
  chmod 600 "$SCANS/binary_eye_all_qr.json"
  if [[ "$EXPORT_ABS" != "$RAM_MNT"/* ]]; then
    warn "L'export JSON provient du disque : son contenu contient les QR, donc des secrets."
    read -r -p "Détruire l'original après copie ? [o/N] " answer || answer=""
    if [[ "$answer" =~ ^[oOyY]$ ]]; then
      shred -u -z -n 1 -- "$EXPORT_ABS" || warn "Impossible de détruire $EXPORT_ABS."
    fi
  fi
else
  info "Dépose l'export JSON global de Binary Eye dans :"
  printf '\n  %s\n\n' "$SCANS/binary_eye_all_qr.json"
  while true; do
    read -r -p "Appuie sur Entrée quand le fichier est prêt (q pour annuler) : " answer || die "Entrée interrompue."
    [[ "$answer" == "q" ]] && die "Annulé par l'utilisateur."
    if [[ -s "$SCANS/binary_eye_all_qr.json" ]]; then
      break
    fi
    warn "Fichier absent ou vide."
  done
  chown "$REAL_UID:$REAL_GID" "$SCANS/binary_eye_all_qr.json" 2>/dev/null || true
  chmod 600 "$SCANS/binary_eye_all_qr.json" 2>/dev/null || true
fi
ok "Scans prêts dans $SCANS."

section "Action"
if (( RESTAURER )); then
  OUT_FILE="$SORTIES/restauration.csv"
  if ! restore_all "$OUT_FILE"; then
    warn "La restauration présente une différence d'empreinte SHA-256. Inspecte $OUT_FILE en RAM avant de continuer."
  fi
elif [[ -n "$ID_ARG" ]]; then
  if [[ "$ID_ARG" =~ ^R[0-9]+$ ]]; then
    OUT_FILE="$SORTIES/entree_${ID_ARG}.csv"
  else
    OUT_FILE="$SORTIES/entree_recherche.csv"
  fi
  extract_entry "$OUT_FILE" id "$ID_ARG"
elif [[ -n "$NOM_ARG" ]]; then
  OUT_FILE="$SORTIES/entree_recherche.csv"
  extract_entry "$OUT_FILE" nom "$NOM_ARG"
else
  printf '\n  1) Extraire par identifiant (R123)\n'
  printf '  2) Extraire par nom\n'
  printf '  3) Restauration complète\n'
  printf '  0) Quitter\n'
  read -r -p "Choix : " choice || die "Entrée interrompue."
  case "$choice" in
    1)
      read -r -p "Identifiant (ex. R123) : " ID_ARG || die "Entrée interrompue."
      [[ -n "$ID_ARG" ]] || die "Identifiant vide."
      if [[ "$ID_ARG" =~ ^R[0-9]+$ ]]; then
        OUT_FILE="$SORTIES/entree_${ID_ARG}.csv"
      else
        OUT_FILE="$SORTIES/entree_recherche.csv"
      fi
      extract_entry "$OUT_FILE" id "$ID_ARG"
      ;;
    2)
      read -r -p "Nom ou partie du nom : " NOM_ARG || die "Entrée interrompue."
      [[ -n "$NOM_ARG" ]] || die "Nom vide."
      OUT_FILE="$SORTIES/entree_recherche.csv"
      extract_entry "$OUT_FILE" nom "$NOM_ARG"
      ;;
    3)
      OUT_FILE="$SORTIES/restauration.csv"
      if ! restore_all "$OUT_FILE"; then
        warn "La restauration présente une différence d'empreinte SHA-256. Inspecte $OUT_FILE en RAM avant de continuer."
      fi
      ;;
    0)
      exit 0
      ;;
    *)
      die "Choix invalide."
      ;;
  esac
fi

section "Résultat"
if [[ -d "$SORTIES" ]]; then
  find "$SORTIES" -maxdepth 1 -type f -printf '  %f\n' | sort
fi
warn "Les fichiers ci-dessus sont uniquement en RAM. Copie celui dont tu as besoin MAINTENANT."
warn "Ils seront effacés au démontage de l'enclave."
read -r -p "Appuie sur Entrée pour tout effacer... " _ || true
ok "Nettoyage en cours."
