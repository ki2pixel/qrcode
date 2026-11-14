---
name: test-coffre-loopback
description: "Use when il faut exercer init_usb_coffre.sh, executer_sauvegarde_ram.sh ou consulter_coffre_ro.sh sans matériel réel, valider les partitions LUKS2/ext4/exFAT ou reproduire un incident du coffre sur une image loopback jetable avec --allow-loopback."
---

# Test du coffre USB sur loopback

## Vue d'ensemble

Exercer le coffre USB sur une image loopback jetable : initialisation LUKS2,
ext4, exFAT, capsule `age`, parité `par2`, manifeste SHA-256, sauvegarde en
RAM, consultation en lecture seule et restauration. Le test ne cible jamais
un disque physique et n'utilise que des données et des phrases synthétiques.

## Quand l'utiliser

- Après une modification de `init_usb_coffre.sh`,
  `executer_sauvegarde_ram.sh` ou `consulter_coffre_ro.sh`.
- Pour valider les partitions, les labels, les paramètres LUKS2 ou le secours
  exFAT.
- Pour reproduire un incident du coffre sans risquer de matériel réel.
- Pour vérifier le nettoyage swap, mounts, mapper et loop après une erreur.

Ne pas utiliser ce skill pour tester la génération QR seule : utiliser
`test-sauvegarde-qr`. Pour l'audit statique de sécurité, utiliser
`audit-securite-remanence`.

## Règles de sécurité

1. **Aucun disque physique.** Le périphérique doit être `/dev/loopN` et son
   type doit être `loop`. Le harness refuse tout autre chemin.
2. **HOME et SUDO_USER isolés** : créer un utilisateur temporaire avec un
   HOME sous `/dev/shm`. Ne jamais laisser `init_usb_coffre.sh` écrire
   dans le vrai `~/luks_header_qr.bak.age`.
3. **Phrases synthétiques uniquement**, jamais une phrase réelle, jamais dans
   un log ou un argument de commande.
4. **Environnement jetable** : les scripts font `swapoff -a`, montent
   `/mnt/ram_sec`, peuvent isoler CUPS et appellent `drop_caches` à la sortie.
   Utiliser une VM/hôte de test avec accord explicite.
5. **Nettoyage obligatoire** : mapper fermé, mounts démontés, loop détaché,
   image `shred`, utilisateur supprimé, swap restauré.
6. Ne pas utiliser `--afficher` pendant les tests.

## Préflight

```bash
id -u
for cmd in losetup truncate cryptsetup mkfs.ext4 mkfs.exfat age par2 zstd \
  rsync qrencode python3 parted partprobe blkid findmnt; do
  command -v "$cmd" || exit 1
done
swapon --show
mountpoint -q /mnt/ram_sec && echo "ERREUR : enclave déjà montée"
mountpoint -q /mnt/usb_vault && echo "ERREUR : coffre déjà monté"
mountpoint -q /mnt/usb_urgence && echo "ERREUR : secours déjà monté"
cryptsetup status qr_vault 2>/dev/null || true
losetup -f
```

Vérifier qu'aucun périphérique existant n'est utilisé par le test.

## Harness PTY

Le helper `scripts/harness_loopback.py` utilise uniquement la bibliothèque
standard (`pty`, `os`, `select`, `termios`). Il répond aux invites
`EFFACER`, au nom du loop, aux phrases cryptsetup/age et aux pauses, sans
écho des secrets.

```bash
PROJECT_ROOT="$PWD"
HARNESS="$PROJECT_ROOT/.agents/skills/test-coffre-loopback/scripts/harness_loopback.py"
```

Les phrases sont lues dans `QR_LOOP_LUKS_PASS` et `QR_LOOP_AGE_PASS`. Utiliser
`sudo --preserve-env=...` pour ne pas les mettre dans la ligne de commande.
`sudo -n` suppose une entrée sudo sans mot de passe ; sinon retirer `-n` et
s'authentifier une fois. Si la politique sudo refuse `--preserve-env`,
exécuter le harness depuis un shell root déjà initialisé, sans jamais passer
les phrases en argument.

## Procédure complète

### 1. Créer l'utilisateur et le HOME temporaires

```bash
ROOT=/tmp/opencode/coffre-loop-$(date +%s)
TEST_USER="qrloop$(date +%s)"
TEST_HOME="/dev/shm/coffre-home-$TEST_USER"
REPO="/dev/shm/coffre-repo-$TEST_USER"
install -d -m 700 "$ROOT"
id "$TEST_USER" 2>/dev/null && { echo "Utilisateur déjà existant"; exit 1; }
sudo useradd --create-home --home-dir "$TEST_HOME" --shell /bin/bash "$TEST_USER"

install -d -m 755 "$REPO"
cp "$PROJECT_ROOT"/{creer_sauvegarde_qr.sh,init_usb_coffre.sh,executer_sauvegarde_ram.sh,consulter_coffre_ro.sh,extraire_entree.py,restaurer_sauvegarde.py,generer_index_qr.py,generer_planches_qr.py,README.md} "$REPO/"
chmod 755 "$REPO"/*.sh
chmod 644 "$REPO"/*.py "$REPO/README.md"
cd "$REPO"
```

Le HOME est placé dans `/dev/shm` pour que l'utilisateur temporaire puisse y
écrire son en-tête `age`, sans traverser un répertoire `$ROOT` en mode 700.
Les scripts du dépôt étant en `700` et appartenant à l'utilisateur qui lance
`sudo`, une copie temporaire accessible au compte de test est nécessaire.
Ne jamais élargir les permissions du dépôt réel pour contourner ce point.
Si `/dev/shm` est trop petit, utiliser un répertoire dédié dont le parent est
traversable (`chmod 711`) et ne jamais utiliser le vrai HOME.

### 2. Définir les phrases synthétiques

```bash
export QR_LOOP_LUKS_PASS="LUKS-SYNTHETIQUE-$(date +%s)-A"
export QR_LOOP_AGE_PASS="AGE-SYNTHETIQUE-$(date +%s)-B"
```

Ne jamais réutiliser ces valeurs ailleurs.

### 3. Créer l'image loopback

```bash
IMAGE="/dev/shm/coffre-loop-$(date +%s).img"
truncate -s 2G "$IMAGE"
LOOP="$(sudo losetup --find --show --partscan "$IMAGE")"
printf '%s\n' "$LOOP"
[[ "$LOOP" =~ ^/dev/loop[0-9]+$ ]] || { echo "Refus : non-loop"; exit 1; }
[[ "$(lsblk -dn -o TYPE "$LOOP")" == "loop" ]] || { echo "Refus : type non-loop"; exit 1; }
```

La taille minimale exigée par les scripts est 1 Gio ; 2 Gio laisse de la
place pour la partition exFAT de 256 Mio. L'image dans `/dev/shm` est en RAM :
le `shred` final est rapide et aucune donnée synthétique ne touche le disque.

### 4. Initialiser le coffre

```bash
sudo -n --preserve-env=QR_LOOP_LUKS_PASS,QR_LOOP_AGE_PASS \
  env SUDO_USER="$TEST_USER" python3 "$HARNESS" \
  --profile init --device "$LOOP" --timeout 600 -- \
  ./init_usb_coffre.sh --allow-loopback \
  --argon2-mib 256 --argon2-threads 1 "$LOOP"
```

Le harness répond `EFFACER`, le nom du loop, `YES` à cryptsetup, les trois
invites LUKS2, les deux invites age et la pause finale.

### 5. Vérifier les preuves LUKS2/ext4/exFAT

```bash
sudo cryptsetup luksDump "${LOOP}p1" | sed -n '1,40p'
sudo blkid "${LOOP}p1" "${LOOP}p2"
lsblk -o NAME,PARTLABEL,FSTYPE,LABEL,MOUNTPOINTS "$LOOP"
sudo stat -c '%a %n' "$TEST_HOME/luks_header_qr.bak.age"
swapon --show
```

Attendu :
- LUKS2, `aes-xts-plain64`, clé 512 bits, `argon2id`, `Memory: 262144`
  (256 MiB), `Threads: 1`, secteur 4096.
- `PARTLABEL` : `COFFRE_LUKS`, `URGENCE_QR`.
- `LABEL` : `QR_COLD_VAULT`, `URGENCE_QR` ; `QR_DATA` après ouverture ext4.
- En-tête `age` en mode `600`.
- Aucun montage résiduel ; swap identique à l'état initial.

### 6. Créer un CSV et un faux export Binary Eye synthétiques

```bash
python3 - "$ROOT/export.csv" <<'PY'
import csv
import sys
from pathlib import Path

rows = []
for i in range(1, 21):
    rows.append([
        f"Groupe {i:02d}", f"Entree {i:02d}",
        f"user{i:02d}@example.com", f"DEMO-LOOP-{i:03d}",
        f"https://site{i:02d}.example", "note " + ("x" * 40),
    ])
with Path(sys.argv[1]).open("w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow(["Group", "Title", "Username", "Password", "URL", "Notes"])
    writer.writerows(rows)
PY
chmod 600 "$ROOT/export.csv"

python3 - "$ROOT/export.csv" "$ROOT/binary_eye_all_qr.json" <<'PY'
import json
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_bytes()
chunks = [raw[i:i + 500] for i in range(0, len(raw), 500)]
def suffix(n):
    n -= 1
    return chr(ord("a") + n // 26) + chr(ord("a") + n % 26)
items = []
for n, chunk in enumerate(chunks, 1):
    payload = chunk.decode("utf-8")
    items.append({"content": f"LQR1 {suffix(n)} {n}/{len(chunks)}\n{payload}"})
Path(sys.argv[2]).write_text(
    json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY
chmod 600 "$ROOT/binary_eye_all_qr.json"
```

### 7. Sauvegarder en RAM

```bash
export SANS_PLANCHES=1
sudo -n --preserve-env=QR_LOOP_LUKS_PASS,QR_LOOP_AGE_PASS,SANS_PLANCHES \
  env SUDO_USER="$TEST_USER" python3 "$HARNESS" \
  --profile save --device "$LOOP" --timeout 600 -- \
  ./executer_sauvegarde_ram.sh --allow-loopback --no-print \
  --garder-source "$LOOP" "$ROOT/export.csv"
```

Le harness répond à l'invite LUKS, aux deux invites age et à la pause. Il
répond `n` aux suppressions optionnelles d'anciennes capsules.

`SANS_PLANCHES=1` évite d'exiger WeasyPrint dans le `site-packages` du compte
de test. Les QR, index et métadonnées sont générés ; les planches PDF sont
couvertes séparément par `test-sauvegarde-qr`.

### 8. Vérifier le secours exFAT

```bash
sudo mkdir -p "$ROOT/urgence"
sudo mount -o ro,nodev,nosuid "${LOOP}p2" "$ROOT/urgence"
sudo find "$ROOT/urgence" -maxdepth 1 -type f -printf '%f %s\n'
sudo find "$ROOT/urgence" -maxdepth 1 -type f -printf '%f\n' | sort > "$ROOT/exfat_names.txt"
MANIFEST_NAME="$(grep -E '\.sha256$' "$ROOT/exfat_names.txt" | head -n1)"
sudo sh -c "cd '$ROOT/urgence' && sha256sum -c '$MANIFEST_NAME'"
PAR2_INDEX="$(sudo find "$ROOT/urgence" -maxdepth 1 -name '*.par2' | sort | head -n1)"
sudo par2 verify "$PAR2_INDEX"
sudo umount "$ROOT/urgence"
```

L'accès aux fichiers exFAT monte en `uid` du compte de test ; les commandes
de lecture utilisent donc `sudo`, y compris pour `sha256sum` et `par2`.

Attendu : capsule `.tar.zst.age`, fichiers `.par2`, manifeste `.sha256`,
`luks_header_qr.bak.age`, `README.md`.

### 9. Consulter en lecture seule et restaurer

Le helper crée un fichier témoin puis attend avant d'envoyer Entrée, ce qui
permet de vérifier le montage `ro,noload` pendant la pause.

```bash
rm -f "$ROOT/ready_consult" "$ROOT/consult.log" "$ROOT/mount_opts.txt"
sudo -n --preserve-env=QR_LOOP_LUKS_PASS,QR_LOOP_AGE_PASS \
  env SUDO_USER="$TEST_USER" python3 "$HARNESS" \
  --profile consult --device "$LOOP" --timeout 600 \
  --hold-final 5 --ready-file "$ROOT/ready_consult" -- \
  ./consulter_coffre_ro.sh --allow-loopback --restaurer \
  --export "$ROOT/binary_eye_all_qr.json" "$LOOP" \
  >"$ROOT/consult.log" 2>&1 &
HPID=$!

for _ in $(seq 1 100); do
  [[ -f "$ROOT/ready_consult" ]] && break
  sleep 0.2
done
test -f "$ROOT/ready_consult"

findmnt -no OPTIONS /mnt/usb_vault > "$ROOT/mount_opts.txt"
tr ',' '\n' < "$ROOT/mount_opts.txt" | grep -qx 'ro'
tr ',' '\n' < "$ROOT/mount_opts.txt" | grep -Eq '^(noload|norecovery)$'

wait "$HPID"
grep -E 'lecture seule|Résultat|Morceaux|Taille' "$ROOT/consult.log"
grep -q 'Résultat         : IDENTIQUE' "$ROOT/consult.log"
```

Attendu : montage `ro,noatime,nodev,nosuid,noload`, restauration
`IDENTIQUE`, aucune écriture sur le coffre. Le noyau peut afficher
`norecovery` à la place de `noload` ; les deux traduisent le même montage
ext4 sans rejeu du journal.

### 10. Vérifier le nettoyage après sauvegarde/consultation

```bash
swapon --show
mountpoint -q /mnt/ram_sec && echo "ERREUR : enclave montée"
mountpoint -q /mnt/usb_vault && echo "ERREUR : coffre monté"
mountpoint -q /mnt/usb_urgence && echo "ERREUR : secours monté"
cryptsetup status qr_vault 2>/dev/null && echo "ERREUR : mapper ouvert"
lsblk -o NAME,MOUNTPOINTS "$LOOP"
```

### 11. Tests négatifs

```bash
# Sans --allow-loopback : doit refuser le loop.
if sudo -n env SUDO_USER="$TEST_USER" ./init_usb_coffre.sh "$LOOP"; then
  echo "ÉCHEC : loop accepté sans --allow-loopback"
  exit 1
fi

# Image trop petite : doit refuser avant toute écriture.
truncate -s 512M "$ROOT/trop_petit.img"
SMALL="$(sudo losetup --find --show --partscan "$ROOT/trop_petit.img")"
if sudo -n env SUDO_USER="$TEST_USER" ./init_usb_coffre.sh \
    --allow-loopback "$SMALL"; then
  echo "ÉCHEC : image trop petite acceptée"
  exit 1
fi
sudo losetup -d "$SMALL"
shred -u -z -n 1 "$ROOT/trop_petit.img"

# En-tête existant : second init doit refuser sans formater.
if sudo -n env SUDO_USER="$TEST_USER" ./init_usb_coffre.sh \
    --allow-loopback --argon2-mib 256 --argon2-threads 1 "$LOOP"; then
  echo "ÉCHEC : second init accepté"
  exit 1
fi
```

### 12. Nettoyage final

```bash
sudo cryptsetup close qr_vault 2>/dev/null || true
sudo umount /mnt/usb_vault /mnt/usb_urgence /mnt/ram_sec 2>/dev/null || true
sudo umount "$ROOT/urgence" 2>/dev/null || true
sudo losetup -d "$LOOP" 2>/dev/null || true
sudo shred -u -z -n 1 "$IMAGE" 2>/dev/null || rm -f "$IMAGE"
sudo userdel -r "$TEST_USER" 2>/dev/null || sudo rm -rf "$TEST_HOME"
rm -rf "$ROOT" "$REPO"
unset QR_LOOP_LUKS_PASS QR_LOOP_AGE_PASS
```

Contrôler une dernière fois :

```bash
swapon --show
cryptsetup status qr_vault 2>/dev/null || true
mountpoint -q /mnt/ram_sec && echo "ERREUR"
losetup -a | grep -F "$IMAGE" || true
```

## Pièges et anti-patrons

- Cibler un disque physique ou copier un exemple de la documentation
  utilisateur : utiliser exclusivement `$LOOP`.
- Utiliser le vrai HOME : l'en-tête `age` pourrait écraser une sauvegarde
  réelle. Toujours créer un utilisateur temporaire.
- Réutiliser une phrase de passe réelle ou la passer en argument de commande.
- Oublier `--allow-loopback` ou croire qu'il autorise autre chose que `loop`.
- Utiliser Argon2id 2048 MiB sur une VM trop petite et conclure à un bug.
- Tester sur un poste de production : `swapoff`, CUPS et `drop_caches` ont un
  impact système.
- Oublier `losetup -d`, le mapper LUKS, un montage ou la suppression de
  l'utilisateur de test.
- Considérer `shred` sur une image loopback comme une preuve d'effacement
  physique d'une clé flash.
- Répondre `o` à la suppression des anciennes capsules : le test doit rester
  non destructif.
- Utiliser `consulter_coffre_ro.sh` sans vérifier `ro,noload` pendant la
  pause.

## Vérification

```bash
python3 -m py_compile *.py \
  .agents/skills/test-coffre-loopback/scripts/harness_loopback.py
bash -n *.sh
```

Le test est validé lorsque :
- l'initialisation produit les labels et paramètres LUKS2 attendus ;
- la capsule, les `.par2`, le manifeste et l'en-tête sont présents sur exFAT ;
- la restauration affiche `IDENTIQUE` ;
- le montage de consultation est `ro,noload` ;
- les tests négatifs échouent correctement ;
- swap, mounts, mapper, loop et utilisateur de test sont nettoyés.
