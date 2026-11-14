# AGENTS.md

Petit outil autonome (Bash + Python) qui transforme un export CSV de mots de passe en QR codes imprimés, et gère un coffre-fort USB chiffré à froid (LUKS2 durci + partition de secours exFAT + exécution isolée en RAM anti-rémanence). Permet d'extraire une entrée ciblée ou de restaurer le CSV complet.

Les données traitées sont réelles et hautement sensibles : utiliser exclusivement des CSV synthétiques pour les tests, ne jamais afficher un mot de passe sans nécessité ni accord explicite.

Pas de manifeste, lockfile, CI, linter ni suite de tests automatisés. Les scripts et messages sont en français ; conserver ce choix.
Documentation utilisateur détaillée : `README.md`.
Documentation coffre USB : `docs/GUIDE_OPERATOIRE_COFFRE_USB.md` et `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md`.
Audit cryptographique et d'intégrité : `docs/Audit-technique-cryptographique-et-dintegrite-complet.md` (diagnostic initial et statut des remédiations).
Audit de sécurité de l'interface web : `docs/Rapport-daudit-de-securite-frontend-web.md` (constats SEC/ARCH/USB/A11Y résolus en v1.0.1).

## Commandes

- **Génération QR autonome (hors clé USB)** :
  `./creer_sauvegarde_qr.sh export.csv [dossier_sortie]`
  Dépendances : `split`, `qrencode`, Python 3.10+, paquet Python `weasyprint` (PDF). `SANS_PLANCHES=1` saute les planches ; sans WeasyPrint, les scripts continuent et produisent le HTML.
  Sources prises en charge : Bitwarden (`name`, `folder`, `login_uri`, `login_username`), KeePassXC (`Title`, `Group`, `URL`, `Username`) et colonnes génériques. Limite : 338 000 octets / 676 morceaux (`split -a 2`).
- **Extraction ciblée (depuis la racine d'une sauvegarde)** :
  `python3 scripts/extraire_entree.py R123 --scans ./scans`
  `python3 scripts/extraire_entree.py --nom example.com --scans ./scans`
- **Restauration complète (depuis la racine d'une sauvegarde)** :
  `python3 scripts/restaurer_sauvegarde.py --scans ./scans`
- **Coffre USB — Initialisation du disque (DESTRUCTIF)** :
  `sudo ./init_usb_coffre.sh [--argon2-mib 2048] [--argon2-threads 4] [--allow-loopback] /dev/sdX`
  `--argon2-mib` : 256–8192 MiB (défaut 2048, réduit à 1024 ou 512 MiB selon `MemAvailable`) ; `--argon2-threads` : 1–32. Périphérique ≥ 1 Gio, non monté.
  Dépendances : `parted`, `cryptsetup`, `e2fsprogs` (`mkfs.ext4`), `exfatprogs` (`mkfs.exfat`), `age`, `util-linux` (`wipefs`, `blockdev`, `runuser`), `coreutils` (`shred`), `udev`.
- **Coffre USB — Orchestration de sauvegarde en RAM hermétique** :
  `sudo ./executer_sauvegarde_ram.sh [--device /dev/sdX] [--csv export.csv] [--ram-size 2G] [--no-print] [--garder-source] [--allow-loopback] /dev/sdX [export.csv]`
  `--ram-size` : défaut `2G`, minimum `256M`, plafonné par `MemAvailable`. `--garder-source` ne préserve que le CSV externe ; la copie de travail en RAM est toujours détruite.
  Dépendances : `cryptsetup`, `age`, `par2` (`par2cmdline`), `zstd`, `qrencode`, `weasyprint` (sauf `SANS_PLANCHES=1`), `rsync`, `diffutils`, `cups-client` (impression facultative), `systemd` (isolation CUPS).
- **Coffre USB — Consultation ou restauration en lecture seule** :
  `sudo ./consulter_coffre_ro.sh [--device /dev/sdX] [--id R123 | --nom TEXTE | --restaurer] [--export scans.json] [--afficher] [--ram-size 512M] [--allow-loopback] /dev/sdX`
  `--ram-size` : défaut `512M`, minimum `128M`. `--id`, `--nom` et `--restaurer` sont incompatibles.
- **Lancement des scripts USB** : toujours via `sudo` depuis un compte non-root (`SUDO_USER`) ; `sudo -i` est refusé.
- **Interface web locale optionnelle** :
  `./lancer_interface.sh [--strict-ram] [--no-browser]` ou double-clic sur le lanceur graphique portable `sauvegarde_qr_web.desktop` à la racine (FreeDesktop standard, `Terminal=true` pour garantir l'arrêt propre et la purge tmpfs à la fermeture de la fenêtre).
  Écoute uniquement `127.0.0.1:5100`, jeton dans le fragment d'URL échangé contre un cookie local, expiration des données après 60 min d'inactivité. Dépendances isolées dans `.venv/` (`requirements.txt`, Flask 3.1), créé avec `--system-site-packages` pour conserver WeasyPrint/Pango/Cairo système. Le pipeline QR et les scripts d'extraction utilisent le Python système capturé par le lanceur, pas le `.venv`.
- **Contrôle syntaxique** :
  `python3 -m py_compile *.py && python3 -m compileall -q web && bash -n *.sh && desktop-file-validate sauvegarde_qr_web.desktop`

## Flux et architecture

### 1. Génération QR (`creer_sauvegarde_qr.sh`)
- Découpage par `split -a 2 -b 500` → `morceaux/morceau_aa…`.
- Génération d'un QR code haute densité par morceau (`qrencode -s 16 -d 600`, format validé, ne pas réduire), préfixé de l'en-tête `LQR1 <suffixe> <n>/<total>\n` + octets bruts du payload.
- Appel de `generer_index_qr.py --chunk-size 500 --qr-header --organise` : calcule les offsets d'octets, écrit `csv/index_enregistrements.csv`, `csv/index_morceaux.csv`, `json/index_meta.json`, HTML/PDF. Vérifie que chaque enregistrement se reconstruit exactement (code 2 sinon).
- Appel de `generer_planches_qr.py` : produit `pdf/planches_qr.pdf` (compact 4×5/38 mm), `pdf/planches_qr_grand.pdf` (confort 3×4/54 mm) et `pdf/test_grand_8qr.pdf` (page de test 8 QR). Exige WeasyPrint pour le PDF, écrit toujours le HTML.
- `extraire_entree.py` et `restaurer_sauvegarde.py` sont copiés dans `scripts/` du dossier de sauvegarde généré. Le second importe le premier (ils doivent rester dans le même dossier).
- `restaurer_sauvegarde.py` s'appuie sur `index_morceaux.csv` (ordre/tailles) et `index_meta.json` (en-tête, `sha256`, `sha256_sans_nbsp`, `record_count`, `line_ending`, `final_newline`, `quote_all`). Il teste CRLF/LF, avec ou sans saut de ligne final, et sort en code 1 si le résultat est `DIFFÉRENT`.

### 2. Coffre USB chiffré et enclave RAM
- **Structure bi-partitionnée de la clé USB** :
  - Partition 1 `COFFRE_LUKS` (~99 % de la clé) : conteneur LUKS2 durci (Argon2id 2048 Mio par défaut, ajusté à 1024 ou 512 Mio si la RAM disponible est insuffisante, 4 threads, AES-XTS 512 bits) formaté en ext4 (mode 0700). Contient les sauvegardes horodatées complètes et la capsule autonome.
  - Partition 2 `URGENCE_QR` (256 MiB) : partition exFAT lisible sans outil sous Linux, macOS et Windows. Contient la capsule autonome `sauvegarde_qr_<nom>_<date>.tar.zst.age`, les fichiers de parité Reed-Solomon `sauvegarde_qr_<nom>_<date>.tar.zst.age.par2` (15 % de redondance), le manifeste SHA-256, la sauvegarde chiffrée de l'en-tête LUKS2 (`luks_header_qr.bak.age`) et `README.md`. Les binaires `age`, `zstd` et `par2` n'y sont pas copiés : les prévoir hors ligne.
- **Anti-rémanence stricte en mémoire vive (`init_usb_coffre.sh`, `executer_sauvegarde_ram.sh` / `consulter_coffre_ro.sh`)** :
  - Désactivation du Swap système (`swapoff -a`) et désactivation des core dumps (`ulimit -c 0`) pour les trois scripts, avec restauration du swap à la sortie.
  - Montage d'un `tmpfs` dédié `/mnt/ram_sec` avec `-o noswap,nodev,nosuid,noexec,mode=0700` (`noswap` est ajouté sur noyau ≥ 6.4 ; le swap est désactivé globalement sinon). `init_usb_coffre.sh` monte en plus un tmpfs dédié éphémère pour l'extraction de l'en-tête LUKS2 avant son chiffrement `age`.
  - Redirection de tous les fichiers temporaires et caches (`TMPDIR`, `XDG_CACHE_HOME`, etc.) dans le tmpfs.
  - Toute la génération QR et la manipulation de secrets se fait exclusivement en RAM.
  - À la clôture, écrasement sécurisé par `shred` / démontage de l'enclave et réactivation du swap.
- **Consultation en lecture seule (`consulter_coffre_ro.sh`)** :
  - Déverrouille LUKS2 et monte la partition en lecture seule stricte (`mount -o ro,noatime,nodev,nosuid,noload`).
  - Déploie une enclave RAM pour importer les scans (`binary_eye_all_qr.json`), exécuter l'extraction ou la restauration, puis nettoie la RAM à la sortie sans jamais écrire sur la clé ni sur le SSD hôte.

### 3. Interface web locale (`web/`, `lancer_interface.sh`)
- Serveur Flask/Werkzeug lié à `127.0.0.1:5100`, sans debug ni reloader ; frontend HTML/CSS/JS vanilla sans npm ni CDN.
- Modules : `web/services/generation.py` (préflight CSV et orchestration de `creer_sauvegarde_qr.sh`), `web/services/consultation.py` (sources session/dossier/ZIP, scans Binary Eye, extraction, restauration), `web/services/usb.py` (lecture seule `lsblk`, démontage non privilégié `udisksctl`, génération de commandes `sudo`).
- Le générateur USB n'exécute aucune commande privilégiée et ne reçoit aucune phrase de passe LUKS2/age : il produit des commandes à copier manuellement, avec `set +o history`. Seule exception contrôlée : `POST /api/usb/demonter` exécute `udisksctl unmount --no-user-interaction -b /dev/sdXN` avec les droits de l'utilisateur, après revalidation que la partition appartient à un disque amovible sûr et que le montage est le seul obstacle. Jamais de `sudo`, ni d'option `-f`/`-l`.
- Étape 2 USB : récapitulatif cible/état reconstruit depuis l'état `lsblk` du serveur. Les opérations non destructives (`sauvegarde`, `consulter`, `restaurer`) n'exigent ni numéro de série ni case à cocher. Seule `init` conserve une confirmation explicite, acceptant le nom court (`sde`), le chemin complet (`/dev/sde`) ou le numéro de série ; le bouton « Insérer » pré-remplit le champ. `generer_commandes()` revalide systématiquement l'absence de montage et refuse en `409 partition_montee` si une partition a été remontée.
- Données exclusivement en tmpfs (`$XDG_RUNTIME_DIR/qrcode_web_5100` ou `/dev/shm/qrcode_web_5100_<uid>`), `umask 077`, core dumps désactivés, expiration des tâches/sessions après 60 min et purge à l'arrêt. Le bouton « Purger la session » force le nettoyage immédiat.
- Jeton aléatoire par lancement dans le fragment d'URL (`#jeton=…`), cookie `HttpOnly`/`SameSite=Strict`, en-tête `X-QR-Web` sur `/api`, contrôle `Host` et `Origin` des requêtes mutantes, CSP stricte, `Cache-Control: no-store`, journal HTTP sans query string ni secret.
- Les archives ZIP importées ne fournissent que les trois index ; les scripts exécutés sont toujours ceux du dépôt, jamais ceux de l'archive. Téléversements CSV limités à 338 000 octets, scans à 16 Mio, ZIP à 256 Mio, index à 64 Mio et métadonnées à 1 Mio, avec protections zip-slip et zip-bomb.
- Les règles de développement et d'audit du frontend (CSP stricte, zéro dépendance JavaScript, hygiène des secrets, accessibilité, assistant USB) sont décrites dans `.agents/skills/interface-web-locale/SKILL.md`.

## Pièges vérifiés

- **DANGER PÉRIPHÉRIQUE /dev/sdX** : Ne JAMAIS exécuter `init_usb_coffre.sh` ou `executer_sauvegarde_ram.sh` sans vérifier formellement la lettre du disque cible (`lsblk -o NAME,MODEL,SIZE,TRAN,RM,FSTYPE`). `init_usb_coffre.sh` détruit irrémédiablement toutes les données du disque cible !
- **Mémoire Argon2id** : `init_usb_coffre.sh` part de 2048 MiB mais réduit automatiquement à 512 MiB si `MemAvailable` est inférieur à 2 Gio, ou à 1024 MiB s'il est inférieur à 3 Gio, lorsque `--argon2-mib` n'est pas fourni. Les scripts de sauvegarde et de consultation vérifient aussi la RAM avant d'ouvrir le coffre.
- **Sauvegarde d'en-tête existante** : `init_usb_coffre.sh` refuse de démarrer si `~/luks_header_qr.bak.age` existe. Déplacer l'ancienne sauvegarde avant toute réinitialisation. Le chemin est résolu via `getent passwd "$SUDO_USER"`, pas via la variable `HOME`.
- **Auto-montage de la partition exFAT** : Sous les environnements de bureau (ex. GNOME / Ubuntu), `URGENCE_QR` (`/dev/sdX2`) est monté automatiquement à l'insertion. Toujours le démonter (`udisksctl unmount -b /dev/sdX2` ou `umount`) avant de lancer les scripts du coffre USB.
- **Formats de portefeuille** : Bitwarden et KeePassXC sont supportés nativement. Les colonnes `Title`/`Group`/`URL`/`Username` de KeePassXC sont mappées vers les champs internes de l'index ; les exports `QUOTE_ALL` sont restaurés octet pour octet. La recherche `--nom` porte sur `name`/`Title`, pas sur l'URL.
- **Export Binary Eye** : **JSON global uniquement**, `scans/binary_eye_all_qr.json`. Le CSV global aplatit les sauts de ligne des champs ; le TXT perd certains espaces de bord.
- **Normalisation NBSP** : Binary Eye normalise les espaces insécables U+00A0 en espaces standards. `IDENTIQUE APRÈS NORMALISATION NBSP` est un succès ; `DIFFÉRENT` ne l'est pas. Le SHA sans NBSP est conservé dans `index_meta.json`.
- **Encodage et Mojibake** : Le JSON peut contenir du Latin-1/CP1252 : les scripts essaient UTF-8, Latin-1 et CP1252. Ne pas réécrire les fichiers de scan à la main.
- **Traductions automatiques** : Les scans traduits automatiquement (Google Lens, navigateurs) altèrent les identifiants et mots de passe et sont refusés : exporter directement depuis l'application de scan sans traduction.
- **Affichage des secrets** : `extraire_entree.py` et `consulter_coffre_ro.sh` n'affichent pas le mot de passe sans le drapeau `--afficher`. Ne jamais ajouter de logging ou d'écho de secrets en clair.
- **Options de secours (extraction/restauration)** : `--export` impose un fichier JSON précis, `--individuels` ignore le JSON global et lit les fichiers individuels (morceaux bruts ou exports texte), `--sortie` choisit le CSV de sortie. `--index` (extraction seulement), `--morceaux` et `--meta` forcent les chemins d'index. Ce sont des options de secours ou de diagnostic.
- **Pérennité des formats** : Modifier `--chunk-size` (500 octets) invalide les index et scans existants ; modifier la taille des QR impose une réimpression complète.
- **Plafond de segmentation** : Le pipeline gère exactement ≤ 676 morceaux (338 000 octets, suffixes `aa`…`zz`, glob `morceau_??`). `split -a 2` est obligatoire ; au-delà, le script refuse le CSV au lieu de tronquer silencieusement.
- **Permissions POSIX** : L'index ne contient pas les mots de passe, mais les noms, URL et identifiants restent des métadonnées sensibles. Permissions attendues : scripts 700 (`rwx------`), fichiers 600 (`rw-------`).
- **Fichiers de documentation** : `README.md` est la documentation utilisateur racine. Le `LISEZMOI.txt` généré dans chaque sauvegarde est produit par un heredoc dans `creer_sauvegarde_qr.sh`. Maintenir la cohérence entre `README.md`, `LISEZMOI.txt` et `AGENTS.md` si le flux évolue ; la procédure de contrôle tripartite est décrite dans `.agents/skills/sync-docs-tripartite/SKILL.md`.
- **Interface web — port et jeton** : ne jamais exposer `127.0.0.1:5100` via un proxy, un tunnel ou une écoute `0.0.0.0`. Le jeton change à chaque lancement et n'est valide que pour l'instance courante ; relancer le serveur invalide les liens et cookies précédents. Ne pas journaliser l'URL complète dans un fichier persistant.
- **Interface web — périmètre des secrets** : les téléchargements (PDF, archive ZIP, CSV extrait/restauré) sortent volontairement du tmpfs et contiennent des données en clair. Les scans et index en RAM sont purgés à l'arrêt, mais un téléchargement déjà écrit sur disque reste. Le web ne remplace pas le flux USB anti-rémanence pour les secrets critiques.
- **Interface web — USB** : `web/services/usb.py` lit `lsblk`, peut démonter une partition montée d'un disque amovible sûr avec `udisksctl unmount --no-user-interaction -b` (sans `sudo`, sans `-f`/`-l`), puis génère des commandes. Ne jamais y ajouter d'appel à `sudo`, de réception de phrase de passe ou d'exécution privilégiée. La cible de `POST /api/usb/demonter` et celle de `POST /api/usb/commandes` doivent être revalidées à chaque appel contre l'état `lsblk` courant, jamais contre la seule entrée envoyée par le navigateur. Ne pas réintroduire de cases à cocher « vérifié/démonté » : la confirmation est réservée à `init` et le backend contrôle lui-même le montage. Un périphérique `/dev/loopX` exige la case « mode test » ; une taille RAM `2G` doit être convertie en MiB avant comparaison au minimum.
- **Interface web — Python des sous-processus** : le pipeline QR et les scripts d'extraction doivent utiliser le Python système (`QRCODE_PYTHON_SYSTEM` capturé par `lancer_interface.sh`) et non `.venv/bin/python`, sinon WeasyPrint et ses liaisons C peuvent manquer. Le `.venv` doit rester créé avec `--system-site-packages`.
- **Lanceur de bureau (.desktop)** : `sauvegarde_qr_web.desktop` est configuré avec `Terminal=true` pour garantir l'arrêt ordonné et la purge systématique de l'enclave tmpfs par `espace_ram.arreter_ram()`. La commande `Exec` explore dynamiquement les cibles (`%k`, `$GIO_LAUNCHED_DESKTOP_FILE`, `$PWD`, `Path=`), et `lancer_interface.sh` maintient la directive `Path=` alignée avec le dossier courant. Permissions attendues : 700 (`rwx------`).

## Vérification d'un changement

Pas de suite de tests automatisés.

1. **Test unitaire QR et restauration (sans USB)** :
   Créer un CSV synthétique dans `/tmp/opencode`, lancer `creer_sauvegarde_qr.sh`, fabriquer un faux export JSON (`[{"content": "LQR1 aa 1/N\n" + contenu_brut}, …]`), puis vérifier :
   - `restaurer_sauvegarde.py` affiche `Résultat : IDENTIQUE` et le SHA-256 correspond ;
   - une extraction `--nom` retrouve la ligne attendue ;
   - tester CRLF et LF, avec et sans saut de ligne final.
2. **Test des scripts USB / RAM** :
   Utiliser impérativement des fichiers images temporaires loopback (`dd` ou `fallocate` + `losetup`) avec `--allow-loopback` pour valider les scripts partitionnés et LUKS2 sans risquer un disque physique. Isoler le répertoire personnel avec un utilisateur de test dédié : les scripts résolvent `REAL_HOME` via `getent passwd "$SUDO_USER"` et ignorent la variable `HOME`. Ne jamais lancer un test loopback depuis le compte qui possède une vraie sauvegarde d'en-tête : utilisez un utilisateur dédié ou déplacez temporairement `~/luks_header_qr.bak.age` avant le test.
3. **Contrôle de syntaxe obligatoire** :
   `python3 -m py_compile *.py && python3 -m compileall -q web && bash -n *.sh`
4. **Test de l'interface web (sans USB, données synthétiques uniquement)** :
   - lancer `./lancer_interface.sh --no-browser`, vérifier l'URL et le jeton affichés, puis `ss -ltnp | grep 5100` : seule l'adresse `127.0.0.1:5100` doit écouter ;
   - vérifier qu'un accès à `/api/etat` sans cookie renvoie 401, et que `/` répond avec la CSP ;
   - générer un petit CSV synthétique (Bitwarden ou KeePassXC), contrôler `IDENTIQUE` puis simuler la normalisation NBSP de Binary Eye pour obtenir `IDENTIQUE APRÈS NORMALISATION NBSP` ;
   - tester l'extraction masquée, la révélation explicite et le téléchargement du CSV extrait/restauré ;
   - vérifier les plafonds de téléversement : un CSV de plus de 338 000 octets, un export de scans de plus de 16 Mio et une archive ZIP de plus de 256 Mio doivent être refusés sans écriture disque ;
   - simuler une clé amovible montée avec un faux `lsblk` placé en tête de `PATH` (jamais de disque physique) : la clé doit apparaître en ambre avec « Partition montée (accès verrouillé) », rester hors des périphériques écartés, et un clic sur « Démonter la partition » doit appeler `udisksctl unmount --no-user-interaction -b /dev/sdXN` sans `sudo` ni option `-f`/`-l` ; après démontage simulé, la carte doit passer en vert « Prête / Sûre » et ouvrir l'étape 2 ;
   - vérifier qu'une partition du disque système est refusée en 403 sans appel à `udisksctl`, puis simuler un échec « busy » : l'encadré doit afficher la commande exacte, un bouton « Copier » et un bouton « Rafraîchir » ; simuler `udisksctl` absent et vérifier que seule la commande `sudo umount /dev/sdXN` est proposée à la copie ;
   - vérifier l'étape 2 : récapitulatif « Cible » et « Partitions démontées » ; aucune case à cocher ; `sauvegarde`, `consulter` et `restaurer` génèrent les commandes sans confirmation. Pour `init`, vérifier la présence du champ, du bouton « Insérer » et de `lsblk -o NAME,MODEL,SERIAL /dev/sdX` ; le backend doit accepter `sde`, `/dev/sde` et le numéro de série, refuser une valeur erronée, et renvoyer `409 partition_montee` si le faux `lsblk` remonte une partition entre-temps ;
   - vérifier que « Purger la session » détruit les fichiers du tmpfs et que l'arrêt du serveur retire le répertoire de travail.
   Le contrôle E2E peut s'appuyer sur le client de test Flask, mais l'écoute réelle et les en-têtes doivent être vérifiés avec le lanceur. Ne jamais utiliser un export réel pour ces tests.

Ne jamais lancer la génération, la restauration ou l'initialisation sur un export réel ou un support physique sans accord explicite.
