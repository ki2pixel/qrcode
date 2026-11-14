# Sauvegarde QR d’un portefeuille de mots de passe

Deux commandes suffisent :

```bash
# 1. Créer la sauvegarde complète à partir du CSV
./creer_sauvegarde_qr.sh export.csv

# 2. Récupérer une entrée, depuis la racine du dossier créé
cd sauvegarde_qr_export_*
python3 scripts/extraire_entree.py R123 --scans ./scans
```

Pour un stockage à froid sur clé USB, voir la section 5
« Coffre USB chiffré » : initialisation LUKS2, génération en RAM et
consultation en lecture seule.

## 1. Créer la sauvegarde

```bash
./creer_sauvegarde_qr.sh export.csv [dossier_sortie]
```

Le script :

- découpe le CSV en morceaux de 500 octets ;
- génère un QR par morceau ;
- ajoute dans chaque QR une ligne d’identification
  `LQR1 xx n/total` (par exemple `LQR1 aa 1/100`) ;
- produit l’index de recherche, les étiquettes et les métadonnées ;
- compose `pdf/planches_qr.pdf` (compact, 4×5 QR par page A4) et
  `pdf/planches_qr_grand.pdf` (confort, 3×4 QR par page, QR de 54 mm) ;
- compose une page de test `pdf/test_grand_8qr.pdf` avec les 8 premiers QR
  en grand ;
- copie `extraire_entree.py` et `restaurer_sauvegarde.py` dans `scripts/` ;
- écrit un `LISEZMOI.txt` spécifique à la sauvegarde.

### Arborescence

```text
sauvegarde_qr_<export>_<date>/
├── LISEZMOI.txt
├── csv/
│   ├── index_enregistrements.csv
│   ├── index_morceaux.csv
│   ├── etiquettes_qr.csv
│   └── etiquettes_qr.txt
├── json/
│   └── index_meta.json
├── morceaux/
│   ├── morceau_aa
│   └── ...
├── qrcodes/
│   ├── morceau_aa.png
│   └── ...
├── pdf/
│   ├── planches_qr.pdf
│   ├── planches_qr_grand.pdf
│   ├── test_grand_8qr.pdf
│   └── index_qr.pdf
├── html/
│   ├── index_qr.html
│   ├── planches_qr.html
│   ├── planches_qr_grand.html
│   └── test_grand_8qr.html
├── scripts/
│   ├── extraire_entree.py
│   └── restaurer_sauvegarde.py
└── scans/
    ├── LISEZMOI.txt
    └── binary_eye_all_qr.json   (après export)
```

| Élément | Rôle |
|---|---|
| `pdf/planches_qr.pdf` | QR codes avec étiquettes, format compact 4×5 |
| `pdf/planches_qr_grand.pdf` | QR codes en 3×4, modules plus grands, plus faciles à scanner |
| `pdf/test_grand_8qr.pdf` | page de test : les 8 premiers QR en grand |
| `pdf/index_qr.pdf` | index de recherche (page de garde + index par morceau + par nom) |
| `csv/index_enregistrements.csv` | index complet, sans mots de passe |
| `json/index_meta.json` | en-tête CSV, taille, SHA-256 exact et sans NBSP, format QR |
| `scripts/extraire_entree.py` | script de récupération d’une entrée |
| `scripts/restaurer_sauvegarde.py` | restauration complète + vérification SHA-256 |
| `morceaux/` | morceaux texte du CSV |
| `qrcodes/` | QR individuels |
| `scans/` | dossier où déposer les scans ou l’export JSON global |

### Impression

Deux formats sont fournis :

| Format | Disposition | Taille du QR | Pages (exemple 100 morceaux) |
|---|---|---|---|
| `planches_qr.pdf` | 4×5 | 38 mm | 5 |
| `planches_qr_grand.pdf` | 3×4 | 54 mm | 9 |

Le format grand augmente la taille des modules d’environ 42 % (0,45 mm → 0,64 mm)
et double presque leur surface. Il est plus tolérant si l’imprimante ou le
papier manque de netteté. Le nombre de pages augmente d’environ 67 % : à
arbitrer selon la qualité de l’impression.

1. Imprime d’abord `pdf/test_grand_8qr.pdf` à **100 %** (sans « ajuster à la
   page »), en 600 dpi si possible.
2. Scanne les 8 QR avec **Binary Eye** et vérifie qu’ils sont reconnus.
3. Si le test est bon, imprime le format choisi, puis `pdf/index_qr.pdf`.
4. Papier mat 80–100 g et imprimante laser de préférence ; évite le papier
   brillant (reflets).

## 2. Récupérer une entrée

Depuis la racine du dossier de sauvegarde :

```bash
python3 scripts/extraire_entree.py R123 --scans ./scans
python3 scripts/extraire_entree.py --nom example.com --scans ./scans
```

Le script détecte automatiquement `csv/`, `json/` et `scans/`, que tu le lances
depuis la racine ou depuis `scripts/`.

Le script utilise l’export JSON global `scans/binary_eye_all_qr.json`. Il
reconnaît les morceaux par leur en-tête `LQR1` et gère les encodages
UTF-8/Latin-1/CP1252 de Binary Eye.

Il gère automatiquement :

- le préfixe `LQR1` ;
- la conversion Latin-1/CP1252 → UTF-8 de Binary Eye, et les exports déjà en
  UTF-8 : le script essaie les deux et garde celui qui correspond à l’index ;
- la normalisation CRLF → LF ;
- les caractères accentués coupés entre deux morceaux.

### Format d’export Binary Eye

Le seul format utilisé est l’export **JSON** global de Binary Eye, déposé dans
`scans/binary_eye_all_qr.json`. Les exports CSV et TXT ne sont pas conservés :
le CSV remplace les sauts de ligne du QR par des espaces, et le TXT normalise
certains espaces.

Binary Eye normalise les espaces insécables (U+00A0) en espaces simples. La
restauration le signale et reste vérifiable via `sha256_sans_nbsp`.

Le script détecte aussi les scans **traduits automatiquement** (Google Lens,
etc.) et refuse de les utiliser : une traduction remplace les en-têtes anglais
(`folder`, `login`…) et casse les octets. Réexporte-les avec Binary Eye, sans
traduction.

Le résultat est écrit dans `entree_R123.csv`, avec l’en-tête CSV. Le mot de passe
n’est pas affiché par défaut ; ajoute `--afficher` si tu veux le voir dans le
terminal.

## 3. Restauration complète

Après avoir scanné tous les QR et déposé l’export JSON dans `scans/` :

```bash
python3 scripts/restaurer_sauvegarde.py --scans ./scans
```

Le script :

- utilise `scans/binary_eye_all_qr.json` s’il est présent ;
- reconnaît les morceaux par leur en-tête `LQR1` ;
- essaie les encodages UTF-8 et Latin-1/CP1252 de Binary Eye ;
- reconstitue le CSV complet ;
- essaie les fins de ligne CRLF et LF ;
- compare le SHA-256 exact et le SHA-256 sans NBSP à ceux de
  `json/index_meta.json`.

Il écrit `restauration.csv` et doit afficher :

- `Résultat : IDENTIQUE` si tout est identique octet pour octet ;
- `Résultat : IDENTIQUE APRÈS NORMALISATION NBSP` si seuls des espaces
  insécables (U+00A0) ont été remplacés par des espaces par Binary Eye. Le
  script indique alors le nombre d’espaces concernés : ce sont des caractères
  de présentation, pas des mots de passe.

C’est ce test qui autorise la suppression de l’export CSV d’origine.

## 4. Avant de supprimer le CSV et les PNG

1. Imprime `pdf/test_grand_8qr.pdf` et scanne les 8 QR avec Binary Eye.
2. Si le test est bon, imprime `pdf/planches_qr_grand.pdf` (ou le format
   compact) et `pdf/index_qr.pdf`.
3. Scanne tous les QR, lance une restauration complète et vérifie le SHA-256.
4. Ne supprime l’export CSV et les fichiers numériques qu’après ce test.

## 5. Coffre USB chiffré (stockage à froid)

Le workflow des sections 1 à 4 reste valable. Cette section ajoute un coffre
USB LUKS2 destiné à un stockage hors ligne, avec une petite partition exFAT
de secours pour les situations d’urgence.

### 5.1 Dépendances

Debian / Ubuntu :

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository -y universe
sudo apt update
sudo apt install -y \
  cryptsetup-bin age zstd par2 rsync qrencode python3 \
  parted exfatprogs e2fsprogs util-linux coreutils findutils tar udev \
  cups cups-client weasyprint fonts-dejavu-core
```

Fedora :

```bash
sudo dnf install -y \
  cryptsetup age zstd par2cmdline rsync qrencode python3 \
  parted exfatprogs e2fsprogs util-linux coreutils findutils tar \
  cups cups-client cups-filters weasyprint dejavu-sans-fonts
```

Arch Linux :

```bash
sudo pacman -S --needed \
  cryptsetup age zstd par2cmdline rsync qrencode python \
  parted exfatprogs e2fsprogs util-linux coreutils findutils tar \
  cups cups-filters python-weasyprint ttf-dejavu
```

### 5.2 Initialiser la clé USB (une seule fois)

```bash
sudo ./init_usb_coffre.sh /dev/sdX
```

Le script vérifie que le périphérique est bien USB/amovible, qu’il ne contient
pas le système en cours, et affiche son modèle, sa taille et son numéro de
série. Il faut taper `EFFACER` puis le numéro de série exact : **toutes les
données de la clé sont détruites**.

Il crée ensuite :

- une partition GPT `COFFRE_LUKS` en LUKS2 (AES-XTS 512 bits, Argon2id,
  2 Gio de mémoire par défaut, 4 threads, secteurs de 4096 octets) ;
- un système ext4 `QR_DATA` sans espace réservé root, monté en `0700`, avec
  `.nomedia` et `.trackerignore` ;
- une partition `URGENCE_QR` de 256 Mio en exFAT ;
- une sauvegarde chiffrée de l’en-tête LUKS2 dans
  `~/luks_header_qr.bak.age`, et une copie sur `URGENCE_QR`.

Options utiles :

```bash
sudo ./init_usb_coffre.sh --argon2-mib 4096 /dev/sdX
sudo ./init_usb_coffre.sh --argon2-mib 1024 --argon2-threads 2 /dev/sdX
```

Conserve `luks_header_qr.bak.age` **hors de la clé**, avec une phrase de passe
distincte de celle du coffre. Refais cette sauvegarde après tout changement
de phrase de passe ou de keyslot LUKS : restaurer un ancien en-tête annule les
changements.

### 5.3 Générer une sauvegarde en RAM

Avec un CSV déjà prêt :

```bash
sudo ./executer_sauvegarde_ram.sh /dev/sdX ~/chemin/export.csv
```

Sans CSV, le script monte d’abord l’enclave et attend :

```bash
sudo ./executer_sauvegarde_ram.sh /dev/sdX
# puis exporter directement vers :
#   /mnt/ram_sec/travail/export.csv
```

N’enregistre pas le CSV dans `~/Téléchargements`, `/tmp` ou `/var/tmp` : le but
est qu’il ne touche jamais le disque. Le script désactive le swap, les core
dumps, redirige `TMPDIR`, les caches XDG et `HOME` vers `/mnt/ram_sec`, puis
appelle `creer_sauvegarde_qr.sh`. Le CSV de travail est détruit dès que le
pipeline a réussi.

Options :

```bash
sudo ./executer_sauvegarde_ram.sh --no-print /dev/sdX export.csv
sudo ./executer_sauvegarde_ram.sh --garder-source /dev/sdX export.csv
sudo ./executer_sauvegarde_ram.sh --ram-size 1G /dev/sdX
```

Si le CSV vient du disque, le script demande confirmation avant de tenter de
le détruire ; `shred` n’est pas une garantie sur SSD/NVMe à cause du wear
leveling. L’export direct dans l’enclave reste la seule méthode réellement
sûre.

L’impression est proposée interactivement. Le script isole `/var/spool/cups`
dans un tmpfs (`root:lp`, `0710`, sous-dossiers `tmp` `1770` et `cache`
`0770`), imprime d’abord `pdf/test_grand_8qr.pdf` à 100 %, puis les planches
choisies. Après impression, le spoule est purgé, démonté et CUPS redémarré
seulement s’il l’était avant. Les travaux déjà présents dans la file CUPS sont
masqués par le tmpfs et réapparaissent après démontage : le script ne les
annule pas.

Le script crée ensuite en RAM :

- `sauvegarde_qr_<nom>_<date>.tar.zst.age` : archive `tar --numeric-owner`
  compressée avec `zstd -19` et chiffrée avec `age -p` ;
- les fichiers `.par2` correspondants, avec 15 % de redondance ;
- un manifeste `.sha256`.

Le dossier complet, la capsule et les fichiers de contrôle sont synchronisés
sur la partition LUKS2, puis vérifiés par `diff -r` et `sha256sum -c`. La
capsule, les `.par2`, le manifeste et l’en-tête chiffré sont copiés sur
`URGENCE_QR`, puis vérifiés.

La partition d’urgence ne fait que 256 Mio : pour un très gros portefeuille,
la capsule et ses 15 % de redondance peuvent ne pas tenir. Le script prévient
et permet d’ignorer la copie d’urgence ; le coffre LUKS2 reste complet.
La partition d’urgence conserve aussi les capsules des sauvegardes
précédentes : pense à supprimer les anciennes avant qu’elle ne sature.

### 5.4 Consulter ou restaurer en lecture seule

```bash
sudo ./consulter_coffre_ro.sh /dev/sdX --id R123
sudo ./consulter_coffre_ro.sh /dev/sdX --nom example.com
sudo ./consulter_coffre_ro.sh /dev/sdX --restaurer
```

Sans action, un menu interactif est proposé. Le script monte une enclave RAM,
ouvre LUKS2 avec `cryptsetup open --readonly`, puis monte ext4 avec
`-o ro,noatime,nodev,nosuid,noload`. Aucune écriture n’est faite sur la clé.

Dépose l’export JSON global de Binary Eye dans :

```text
/mnt/ram_sec/scans/binary_eye_all_qr.json
```

ou utilise `--export /chemin/binary_eye_all_qr.json`. Les sorties sont écrites
exclusivement dans `/mnt/ram_sec/sorties/`. Le script affiche leur nom et
attend que tu appuies sur Entrée : **copie le fichier dont tu as besoin avant
de continuer**, il sera effacé avec l’enclave.

`--afficher` affiche la ligne extraite, mot de passe compris, dans le
terminal. À utiliser avec prudence : le contenu peut rester dans le scrollback
du terminal.

Si le montage `ro,noload` échoue à cause d’un journal ext4 non vide, le script
s’arrête sans monter en écriture. Démonte proprement la clé après une
utilisation en écriture, ou monte-la une fois en lecture-écriture pour
réparer, puis relance la consultation.

### 5.5 Récupération d’urgence

La partition `URGENCE_QR` est lisible sans LUKS sur Windows, macOS ou Linux.
Elle contient la capsule, les `.par2`, le manifeste SHA-256, l’en-tête LUKS
chiffré et ce `LISEZMOI.md`.

Vérifier et réparer la capsule, depuis la partition `URGENCE_QR` :

```bash
sha256sum -c sauvegarde_qr_<nom>.sha256
par2 verify sauvegarde_qr_<nom>.tar.zst.age.par2
par2 repair sauvegarde_qr_<nom>.tar.zst.age.par2
sha256sum -c sauvegarde_qr_<nom>.sha256
```

Déchiffrer et extraire la capsule sur un système disposant de `age`, `zstd`
et `tar` :

```bash
age -d sauvegarde_qr_<nom>.tar.zst.age | zstd -d | tar -xf -
```

Restaurer l’en-tête LUKS2 si les premiers secteurs de la clé sont corrompus :

```bash
age -d -o /dev/shm/luks_header_qr.bak ~/luks_header_qr.bak.age
sudo cryptsetup luksHeaderRestore /dev/sdX1 \
  --header-backup-file /dev/shm/luks_header_qr.bak
shred -u -z -n 3 /dev/shm/luks_header_qr.bak
```

Cette opération écrase l’en-tête actuel : ne la fais que sur la bonne
partition et après avoir vérifié la sauvegarde. Si la phrase de passe du
coffre a changé depuis la sauvegarde de l’en-tête, l’ancien en-tête restauré
annule ce changement.

Depuis un Live USB Linux, le coffre principal reste accessible :

```bash
sudo cryptsetup open --readonly /dev/sdX1 qr_vault_ro
sudo mount -o ro,noatime,nodev,nosuid,noload \
  /dev/mapper/qr_vault_ro /mnt/usb_vault
```

### 5.6 Limites de sécurité

- Les QR imprimés contiennent le CSV en clair, mots de passe compris. Le
  chiffrement LUKS2 protège les fichiers numériques, pas le papier.
- `shred` sur SSD/NVMe n’est pas garanti : il ne contrôle pas la couche de
  traduction Flash. Exporte le CSV directement dans `/mnt/ram_sec`.
- `swapoff -a` et l’arrêt de CUPS sont globaux au système. Le script restaure
  le swap et CUPS à la sortie ; un `SIGKILL` ou une coupure laisse le swap
  désactivé.
- `drop_caches` ne garantit pas l’effacement physique de la RAM ; seule
  l’extinction de la machine le garantit.
- N’ouvre jamais `/mnt/ram_sec` ni le point de montage du coffre dans un
  gestionnaire de fichiers graphique : les miniatures et l’historique récent
  peuvent écrire des secrets sur le SSD.
- Teste toujours une restauration complète avant de supprimer l’export CSV
  d’origine ou les planches papier.

## Sécurité

Les QR codes contiennent le CSV en clair, mots de passe compris. Un QR code
n’est pas un chiffrement. Conserve les planches et l’index dans un coffre, et
imprime sur une imprimante de confiance.

L’index ne contient aucun mot de passe, mais il contient des noms de services,
dossiers, URL et identifiants.


