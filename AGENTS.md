# AGENTS.md

Petit outil autonome (Bash + Python) qui transforme un export CSV de mots de passe en QR codes imprimés, et gère un coffre-fort USB chiffré à froid (LUKS2 durci + partition de secours exFAT + exécution isolée en RAM anti-rémanence). Permet d'extraire une entrée ciblée ou de restaurer le CSV complet.

Les données traitées sont réelles et hautement sensibles : utiliser exclusivement des CSV synthétiques pour les tests, ne jamais afficher un mot de passe sans nécessité ni accord explicite.

Pas de manifeste, lockfile, CI, linter ni suite de tests automatisés. Les scripts et messages sont en français ; conserver ce choix.
Documentation utilisateur détaillée : `README.md`.
Documentation coffre USB : `docs/GUIDE_OPERATOIRE_COFFRE_USB.md` et `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md`.

## Commandes

- **Génération QR autonome (hors clé USB)** :
  `./creer_sauvegarde_qr.sh export.csv [dossier_sortie]`
  Dépendances : `split`, `qrencode`, Python 3.10+, paquet Python `weasyprint` (PDF). `SANS_PLANCHES=1` saute les planches ; sans WeasyPrint, les PDF ne sont pas produits (le HTML l'est).
- **Extraction ciblée (depuis la racine d'une sauvegarde)** :
  `python3 scripts/extraire_entree.py R123 --scans ./scans`
  `python3 scripts/extraire_entree.py --nom example.com --scans ./scans`
- **Restauration complète (depuis la racine d'une sauvegarde)** :
  `python3 scripts/restaurer_sauvegarde.py --scans ./scans`
- **Coffre USB — Initialisation du disque (DESTRUCTIF)** :
  `sudo ./init_usb_coffre.sh [--argon2-mib 2048] [--argon2-threads 4] /dev/sdX`
  Dépendances : `parted`, `cryptsetup`, `mkfs.ext4`, `mkfs.exfat` (`exfatprogs`), `age`.
- **Coffre USB — Orchestration de sauvegarde en RAM hermétique** :
  `sudo ./executer_sauvegarde_ram.sh [--no-print] /dev/sdX [export.csv]`
  Dépendances : `cryptsetup`, `age`, `par2` (`par2cmdline`), `zstd`, `qrencode`, `weasyprint`.
- **Coffre USB — Consultation ou restauration en lecture seule** :
  `sudo ./consulter_coffre_ro.sh [--id R123 | --nom TEXTE | --restaurer] [--export scans.json] [--afficher] /dev/sdX`
- **Contrôle syntaxique** :
  `python3 -m py_compile *.py && bash -n *.sh`

## Flux et architecture

### 1. Génération QR (`creer_sauvegarde_qr.sh`)
- Découpage par `split -b 500` → `morceaux/morceau_aa…`.
- Génération d'un QR code haute densité par morceau (`qrencode -s 16 -d 600`, format validé, ne pas réduire), préfixé de l'en-tête `LQR1 <suffixe> <n>/<total>\n` + octets bruts du payload.
- Appel de `generer_index_qr.py --chunk-size 500 --qr-header --organise` : calcule les offsets d'octets, écrit `csv/index_enregistrements.csv`, `csv/index_morceaux.csv`, `json/index_meta.json`, HTML/PDF. Vérifie que chaque enregistrement se reconstruit exactement (code 2 sinon).
- Appel de `generer_planches_qr.py` : produit `pdf/planches_qr.pdf` (compact 4×5/38 mm), `pdf/planches_qr_grand.pdf` (confort 3×4/54 mm) et `pdf/test_grand_8qr.pdf` (page de test 8 QR). Exige WeasyPrint pour le PDF, écrit toujours le HTML.
- `extraire_entree.py` et `restaurer_sauvegarde.py` sont copiés dans `scripts/` du dossier de sauvegarde généré. Le second importe le premier (ils doivent rester dans le même dossier).
- `restaurer_sauvegarde.py` s'appuie sur `index_morceaux.csv` (ordre/tailles) et `index_meta.json` (en-tête, `sha256`, `sha256_sans_nbsp`, `record_count`). Il teste CRLF/LF, avec ou sans saut de ligne final, et sort en code 1 si le résultat est `DIFFÉRENT`.

### 2. Coffre USB chiffré et enclave RAM
- **Structure bi-partitionnée de la clé USB** :
  - Partition 1 `COFFRE_LUKS` (~99 % de la clé) : conteneur LUKS2 durci (Argon2id 2048 Mio, 4 threads, AES-XTS 512 bits) formaté en ext4 (mode 0700). Contient les sauvegardes horodatées complètes et la capsule autonome.
  - Partition 2 `URGENCE_QR` (255 Mo) : partition exFAT lisible sans outil sous Linux, macOS et Windows. Contient la capsule autonome `sauvegarde_qr_<nom>.tar.zst.age`, les fichiers de parité Reed-Solomon `sauvegarde_qr_<nom>.tar.zst.age.par2` (15 % de redondance), le manifeste SHA-256, la sauvegarde chiffrée de l'en-tête LUKS2 (`luks_header_qr.bak.age`) et `README.md`.
- **Anti-rémanence stricte en mémoire vive (`executer_sauvegarde_ram.sh` / `consulter_coffre_ro.sh`)** :
  - Désactivation du Swap système (`swapoff -a`) et désactivation des core dumps (`ulimit -c 0`).
  - Montage d'un `tmpfs` dédié `/mnt/ram_sec` avec `-o noswap,nodev,nosuid,noexec,mode=0700`.
  - Redirection de tous les fichiers temporaires et caches (`TMPDIR`, `XDG_CACHE_HOME`, etc.) dans le tmpfs.
  - Toute la génération QR et la manipulation de secrets se fait exclusivement en RAM.
  - À la clôture, écrasement sécurisé par `shred` / démontage de l'enclave et réactivation du swap.
- **Consultation en lecture seule (`consulter_coffre_ro.sh`)** :
  - Déverrouille LUKS2 et monte la partition en lecture seule stricte (`mount -o ro,noload`).
  - Déploie une enclave RAM pour importer les scans (`binary_eye_all_qr.json`), exécuter l'extraction ou la restauration, puis nettoie la RAM à la sortie sans jamais écrire sur la clé ni sur le SSD hôte.

## Pièges vérifiés

- **DANGER PÉRIPHÉRIQUE /dev/sdX** : Ne JAMAIS exécuter `init_usb_coffre.sh` ou `executer_sauvegarde_ram.sh` sans vérifier formellement la lettre du disque cible (`lsblk -o NAME,MODEL,SIZE,TRAN,RM,FSTYPE`). `init_usb_coffre.sh` détruit irrémédiablement toutes les données du disque cible !
- **Auto-montage de la partition exFAT** : Sous les environnements de bureau (ex. GNOME / Ubuntu), `URGENCE_QR` (`/dev/sdX2`) est monté automatiquement à l'insertion. Toujours le démonter (`udisksctl unmount -b /dev/sdX2` ou `umount`) avant de lancer les scripts du coffre USB.
- **Export Binary Eye** : **JSON global uniquement**, `scans/binary_eye_all_qr.json`. Le CSV global aplatit les sauts de ligne des champs ; le TXT perd certains espaces de bord.
- **Normalisation NBSP** : Binary Eye normalise les espaces insécables U+00A0 en espaces standards. `IDENTIQUE APRÈS NORMALISATION NBSP` est un succès ; `DIFFÉRENT` ne l'est pas. Le SHA sans NBSP est conservé dans `index_meta.json`.
- **Encodage et Mojibake** : Le JSON peut contenir du Latin-1/CP1252 : les scripts essaient UTF-8, Latin-1 et CP1252. Ne pas réécrire les fichiers de scan à la main.
- **Traductions automatiques** : Les scans traduits automatiquement (Google Lens, navigateurs) altèrent les identifiants et mots de passe et sont refusés : exporter directement depuis l'application de scan sans traduction.
- **Affichage des secrets** : `extraire_entree.py` et `consulter_coffre_ro.sh` n'affichent pas le mot de passe sans le drapeau `--afficher`. Ne jamais ajouter de logging ou d'écho de secrets en clair.
- **Secours vs flux nominal** : `--individuels` ignore le JSON global ; `--export` impose un fichier JSON précis. Ce sont des options de secours.
- **Pérennité des formats** : Modifier `--chunk-size` (500 octets) invalide les index et scans existants ; modifier la taille des QR impose une réimpression complète.
- **Plafond de segmentation** : Le pipeline actuel gère ≤ 676 morceaux (suffixes de deux lettres `aa`…`zz`, glob `morceau_??`). Au-delà, adapter `split -a` et les globs.
- **Permissions POSIX** : L'index ne contient pas les mots de passe, mais les noms, URL et identifiants restent des métadonnées sensibles. Permissions attendues : scripts 700 (`rwx------`), fichiers 600 (`rw-------`).
- **Fichiers de documentation** : `README.md` est la documentation utilisateur racine. Le `LISEZMOI.txt` généré dans chaque sauvegarde est produit par un heredoc dans `creer_sauvegarde_qr.sh`. Maintenir la cohérence entre `README.md`, `LISEZMOI.txt` et `AGENTS.md` si le flux évolue.

## Vérification d'un changement

Pas de suite de tests automatisés.

1. **Test unitaire QR et restauration (sans USB)** :
   Créer un CSV synthétique dans `/tmp/opencode`, lancer `creer_sauvegarde_qr.sh`, fabriquer un faux export JSON (`[{"content": "LQR1 aa 1/N\n" + contenu_brut}, …]`), puis vérifier :
   - `restaurer_sauvegarde.py` affiche `Résultat : IDENTIQUE` et le SHA-256 correspond ;
   - une extraction `--nom` retrouve la ligne attendue ;
   - tester CRLF et LF, avec et sans saut de ligne final.
2. **Test des scripts USB / RAM** :
   Utiliser impérativement des fichiers images temporaires loopback (`dd` ou `fallocate` + `losetup`) pour valider les scripts partitionnés et LUKS2 sans risquer un disque physique.
3. **Contrôle de syntaxe obligatoire** :
   `python3 -m py_compile *.py && bash -n *.sh`

Ne jamais lancer la génération, la restauration ou l'initialisation sur un export réel ou un support physique sans accord explicite.
