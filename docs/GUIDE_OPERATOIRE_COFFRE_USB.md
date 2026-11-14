# Guide Opératoire : Coffre USB Chiffré & Sauvegardes QR

Ce guide résume la procédure exacte pour exploiter, mettre à jour et consulter votre coffre-fort USB hors-ligne (stockage à froid) en toute sécurité et sans risque de fuite de données.

---

## Architecture de la clé USB

La clé USB est organisée en deux partitions distinctes :
1. **Partition 1 (`COFFRE_LUKS` - ~99 % de la clé, ext4 hermétique 0700) :**
   * Chiffrement LUKS2 durci (Argon2id 2 Gio RAM par défaut, ajusté à 1 Gio ou 512 Mio si la RAM disponible est insuffisante, 4 threads, AES-XTS 512 bits).
   * Contient les sauvegardes horodatées complètes (dossiers de QR codes, PDF pour impression, index CSV/HTML).
   * Contient la capsule autonome de secours `sauvegarde_qr_<nom>_<date>.tar.zst.age` et ses blocs de réparation Reed-Solomon `par2` (15 % de redondance).
2. **Partition 2 (`URGENCE_QR` - 256 MiB, exFAT lisible partout) :**
   * Lisible nativement sous Linux, macOS et Windows sans nécessiter LUKS.
   * Après une sauvegarde complète, contient la capsule de secours chiffrée, les fichiers de réparation `.par2`, le manifeste SHA-256, le fichier `README.md` et l'en-tête LUKS2 chiffré (`luks_header_qr.bak.age`).
   * Ne contient pas les binaires `age`, `zstd` ou `par2` : prévoyez-les hors ligne pour la récupération.

---

## Réflexe indispensable avant toute opération : identifier la lettre et démonter

Sous Linux, la lettre attribuée à une clé USB (`sde`, `sdf`, etc.) n'est **jamais fixe** : elle dépend de l'ordre de branchement et des ports utilisés. De plus, sous Ubuntu / GNOME, la partition 2 (`URGENCE_QR`) au format exFAT est **automatiquement montée** dès l'insertion.

**Avant chaque utilisation :**
1. Repérez la lettre exacte de votre clé (`RM=1`, taille 29,8G) :
   ```bash
   lsblk -o NAME,MODEL,SIZE,TRAN,RM,FSTYPE,MOUNTPOINTS
   ```
   *(Regardez la ligne de la clé USB, par exemple `sdf` avec `sdf1` et `sdf2`).*

2. Démontez la partition d'urgence si elle est montée :
   ```bash
   udisksctl unmount -b /dev/sdX2
   ```
   *(En remplaçant `sdX2` par votre lettre réelle, par ex. `sdf2`).*
   L'interface web locale (section 6 du `README.md`) détecte ce montage
   automatique et propose le même démontage avec `udisksctl`, sans `sudo`.

3. Pour une initialisation, vérifiez aussi que la clé offre au moins 1 Gio,
   qu'aucune de ses partitions n'est montée et que
   `~/luks_header_qr.bak.age` n'existe pas déjà. Le script refuse de démarrer
   dans ces cas ; déplacez l'ancienne sauvegarde d'en-tête avant de
   réinitialiser le disque.

---

## 1. Faire une nouvelle sauvegarde (Procédure périodique)

Cette procédure génère l'ensemble des QR codes et PDF en mémoire vive (RAM isolée `noswap` sur noyau ≥ 6.4, swap désactivé sinon), coupe le swap système temporairement pour qu'aucun mot de passe ne fuite sur SSD, puis synchronise le coffre USB.

### Étape 1 : Identifier et démonter `URGENCE_QR`
Si votre clé est reconnue en `/dev/sdf` :
```bash
udisksctl unmount -b /dev/sdf2
```

### Étape 2 : Lancer l'orchestrateur de sauvegarde
Se placer dans le dossier du projet et utiliser la **lettre exacte** repérée à l'étape 1 (ex. `/dev/sdf`) :
```bash
cd ~/Documents/qrcode
sudo ./executer_sauvegarde_ram.sh --no-print /dev/sdf
```
*(Omettez `--no-print` si vous voulez imprimer les planches immédiatement sur votre imprimante).*

### Étape 3 : Déposer le CSV dans l'enclave RAM
Le script prépare l'enclave et se met en attente :
```text
Appuie sur Entrée quand le fichier est prêt (q pour annuler) :
```
Exportez **directement** votre portefeuille depuis le gestionnaire de mots de passe
vers :
```text
/mnt/ram_sec/travail/export.csv
```
Ne copiez jamais un export en clair depuis `~/Documents`, `~/Téléchargements`
ou `/tmp` : cela réintroduirait une rémanence sur le SSD et contredirait le
modèle de sécurité. Si le CSV existe déjà sur le disque, utilisez
`executer_sauvegarde_ram.sh /dev/sdX /chemin/export.csv` et lisez
attentivement l'avertissement : `shred` ne garantit pas l'effacement sur
SSD/NVMe. Les exports KeePassXC (`Title`, `Group`, `URL`, `Username`) et
Bitwarden sont acceptés.

### Étape 4 : Valider et saisir les phrases secrètes
1. Revenez sur le premier terminal et appuyez sur **Entrée**.
2. **Phrase age :** Définissez la phrase secrète protégeant la capsule autonome `tar.zst.age`. Si `age` affiche une phrase auto-générée, notez-la avant d'appuyer sur Entrée : le script marque une pause exprès.
3. **Phrase LUKS2 :** Saisissez la phrase de passe de votre coffre USB pour permettre le montage et la copie.
4. Le script synchronise les fichiers, vérifie les empreintes SHA-256, nettoie la RAM par `shred`, réactive le swap système et referme le coffre.
5. Après vérification de la nouvelle capsule, le script propose de supprimer les anciennes capsules de `URGENCE_QR` par `shred` (les cellules flash ne peuvent toutefois pas être garanties effacées physiquement).
6. Vous pouvez retirer la clé USB en toute sécurité. Le script démonte et
   referme le coffre mais ne coupe pas l'alimentation du périphérique ; si
   votre distribution le permet, utilisez `udisksctl power-off -b /dev/sdX`
   après la fermeture.

---

## 2. Consulter ou extraire un mot de passe (Lecture seule)

Cette procédure permet de chercher une entrée ou de restaurer le coffre depuis un scan de QR codes, sans jamais altérer la clé USB ni laisser de traces sur votre machine hôte.

### Étape 1 : Démonter la partition exFAT auto-montée
```bash
# Remplacer sdX2 par votre partition réelle (ex: sdf2)
udisksctl unmount -b /dev/sdX2
```

### Étape 2 : Lancer la consultation
```bash
cd ~/Documents/qrcode
# Remplacer sdX par votre périphérique réel (ex: sdf)
sudo ./consulter_coffre_ro.sh /dev/sdX
```

Pour un test sur image loopback uniquement, ajoutez `--allow-loopback` et
utilisez un utilisateur de test doté d'un répertoire personnel isolé : les
scripts résolvent `REAL_HOME` via `getent passwd "$SUDO_USER"` et ignorent la
variable `HOME`. À défaut, déplacez temporairement `~/luks_header_qr.bak.age`
avant le test. Ne testez jamais `init_usb_coffre.sh` sur un disque physique
sans confirmation explicite.

### Étape 3 : Déverrouillage et scans
1. Saisissez votre phrase de passe LUKS2. Le coffre est monté en **lecture seule stricte** (`mount -o ro,noatime,nodev,nosuid,noload`).
2. Déposez l'export JSON de l'application mobile **Binary Eye** dans l'enclave :
   ```bash
   cp /chemin/vers/binary_eye_all_qr.json /mnt/ram_sec/scans/binary_eye_all_qr.json
   ```
   Vous pouvez aussi lancer le script avec
   `--export /chemin/vers/binary_eye_all_qr.json` pour qu'il copie lui-même
   l'export dans l'enclave ; il propose ensuite de détruire l'original.
3. Appuyez sur **Entrée**.
4. Choisissez dans le menu interactif :
   * `1` : Extraire par identifiant (ex. `R042`)
   * `2` : Extraire par nom (ex. `banque`, `google`)
   * `3` : Restauration complète du fichier CSV
5. Le script écrit le résultat dans `/mnt/ram_sec/sorties/` et se met en pause (*« Appuie sur Entrée pour tout effacer... »*).
6. Si la restauration affiche `DIFFÉRENT`, ne supprimez pas le CSV d'origine :
   inspectez les scans et recommencez. `IDENTIQUE APRÈS NORMALISATION NBSP`
   reste un succès.

### Étape 4 : Consulter ou copier le résultat en RAM (dans un 2ᵉ terminal)
Puisque les fichiers sont confinés en mémoire vive et vous appartiennent (`chmod 600`), **aucun `sudo` n'est requis**. Ouvrez un second terminal pour les inspecter :

* **Aperçu rapide des premières lignes :**
  ```bash
  head -n 10 /mnt/ram_sec/sorties/restauration.csv
  # ou pour une entrée ciblée : head -n 10 /mnt/ram_sec/sorties/entree_*.csv
  ```

* **Consulter le fichier complet (avec défilement) :**
  ```bash
  less /mnt/ram_sec/sorties/restauration.csv
  # Appuyer sur 'q' pour quitter less
  ```

* **Vérifier le nombre total de comptes restaurés :**
  ```bash
  wc -l /mnt/ram_sec/sorties/restauration.csv
  ```

* **Persister le résultat :** ne copiez **jamais** ce fichier vers
  `~/Documents` ou un autre support non chiffré. Importez-le directement dans
  votre gestionnaire de mots de passe, ou écrivez-le sur un volume chiffré.
  Sinon, inspectez-le en RAM puis laissez l'enclave le détruire.

### Étape 5 : Clôture et nettoyage
Revenez sur le **premier terminal** et appuyez sur **Entrée** :
* Le script détruit automatiquement les données en RAM avec `shred`.
* Les caches noyau sont purgés (`drop_caches`).
* L'enclave RAM est démontée et le coffre LUKS2 est reverrouillé.

---

## 3. Récupération d'urgence (En cas de panne ou sans Linux)

Si votre machine habituelle n'est plus accessible ou si le premier secteur de la clé USB a subi des avaries :

### A. Sur Windows ou macOS (via la partition `URGENCE_QR`)
1. Insérez la clé USB. La partition `URGENCE_QR` monte automatiquement.
2. Copiez la capsule `sauvegarde_qr_<nom>_<date>.tar.zst.age`, ses fichiers `.par2` et le manifeste `.sha256`.
3. Vérifiez l'intégrité, puis réparez l'archive si des secteurs flash sont défectueux :
   ```bash
   sha256sum -c sauvegarde_qr_<nom>_<date>.sha256
   par2 verify sauvegarde_qr_<nom>_<date>.tar.zst.age.par2
   par2 repair sauvegarde_qr_<nom>_<date>.tar.zst.age.par2
   sha256sum -c sauvegarde_qr_<nom>_<date>.sha256
   ```
4. Déchiffrez et décompressez avec `age`, `zstd` et `tar` :
   ```bash
   age -d sauvegarde_qr_<nom>_<date>.tar.zst.age | zstd -d | tar -xf -
   ```
   Les binaires `age`, `zstd` et `par2` ne sont pas copiés sur la partition
   d'urgence : prévoyez-les hors ligne avant d'en avoir besoin. Sur macOS,
   `shasum -a 256 -c` lit le même manifeste ; sur Windows, utilisez WSL,
   Git Bash ou un outil équivalent.

### B. En cas d'en-tête LUKS2 endommagé sur Linux
Si le début de la partition LUKS2 est corrompu, restaurez l'en-tête depuis la
sauvegarde chiffrée. Déchiffrez-le dans un tmpfs dédié, jamais dans
`/dev/shm` partagé :
```bash
umask 077
sudo install -d -m 0700 /mnt/ram_hdr
sudo mount -t tmpfs -o size=32M,mode=0700,uid="$(id -u)",gid="$(id -g)",nodev,nosuid,noexec,noswap tmpfs /mnt/ram_hdr
age -d -o /mnt/ram_hdr/luks_header.bak ~/luks_header_qr.bak.age
sudo cryptsetup luksHeaderRestore /dev/sdX1 \
  --header-backup-file /mnt/ram_hdr/luks_header.bak
shred -u -z -n 3 /mnt/ram_hdr/luks_header.bak
sudo umount /mnt/ram_hdr
sudo rmdir /mnt/ram_hdr
```
Sur un noyau antérieur à 6.4, retirez `noswap` et désactivez le swap avant
l'opération.

---

## 4. Règles d'hygiène cryptographique

* **Suppression du CSV source :** Exportez directement dans l'enclave RAM. Si un export en clair a déjà été écrit dans `~/Documents`, détruisez-le avec `shred -u -z -n 3 export.csv`, en sachant que `shred` ne garantit pas l'effacement physique sur SSD/NVMe. Ne conservez jamais l'export dans `~/Documents` comme emplacement de travail.
* **Mise à jour de mot de passe :** Si vous modifiez la phrase de passe LUKS2 de la clé, vous **devez** régénérer la sauvegarde d'en-tête chiffrée (`luks_header_qr.bak.age`), sinon restaurer un ancien en-tête réactiverait l'ancienne phrase. Ne relancez pas `init_usb_coffre.sh` pour cela : il est destructif. Extrayez le nouvel en-tête avec `cryptsetup luksHeaderBackup` dans un tmpfs dédié, puis chiffrez-le avec `age -p`.

---

## 5. Dépannage : réinitialiser les montages après une interruption

Si un script précédent a été interrompu brutalement (fermeture de la fenêtre du terminal, coupure, etc.), le coffre en lecture seule ou l'enclave RAM peuvent être restés ouverts. Vous obtiendrez alors :
`[ERREUR] Un point de montage USB est déjà utilisé` ou `qr_vault est déjà actif`.

Pour tout réinitialiser proprement en une seule commande :
```bash
sudo umount /mnt/usb_vault /mnt/usb_urgence /mnt/ram_sec 2>/dev/null || true
sudo cryptsetup close qr_vault_ro 2>/dev/null || true
sudo cryptsetup close qr_vault 2>/dev/null || true
```

