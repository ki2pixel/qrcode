# Guide Opératoire : Coffre USB Chiffré & Sauvegardes QR

Ce guide résume la procédure exacte pour exploiter, mettre à jour et consulter votre coffre-fort USB hors-ligne (stockage à froid) en toute sécurité et sans risque de fuite de données.

---

## Architecture de la clé USB

La clé USB est organisée en deux partitions distinctes :
1. **Partition 1 (`COFFRE_LUKS` - ~99 % de la clé, ext4 hermétique 0700) :**
   * Chiffrement LUKS2 durci (Argon2id 2 Gio RAM, 4 threads, AES-XTS 512 bits).
   * Contient les sauvegardes horodatées complètes (dossiers de QR codes, PDF pour impression, index CSV/HTML).
   * Contient la capsule autonome de secours `tar.zst.age` et ses blocs de réparation Reed-Solomon `par2` (15 % de redondance).
2. **Partition 2 (`URGENCE_QR` - 255 Mo, exFAT lisible partout) :**
   * Lisible nativement sous Linux, macOS et Windows sans nécessiter LUKS.
   * Contient la capsule de secours chiffrée, les fichiers de réparation `.par2`, le fichier `README.md` et l'en-tête LUKS2 chiffré (`luks_header_qr.bak.age`).

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

---

## 1. Faire une nouvelle sauvegarde (Procédure périodique)

Cette procédure génère l'ensemble des QR codes et PDF en mémoire vive (RAM isolée `noswap`), coupe le swap système temporairement pour qu'aucun mot de passe ne fuite sur SSD, puis synchronise le coffre USB.

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
Ouvrez un **deuxième terminal** (ou `Ctrl+Shift+T`) et copiez votre export :
```bash
cp ~/Documents/qrcode/export.csv /mnt/ram_sec/travail/export.csv
```
*(Ou exportez directement depuis votre gestionnaire de mots de passe vers `/mnt/ram_sec/travail/export.csv`).*

### Étape 4 : Valider et saisir les phrases secrètes
1. Revenez sur le premier terminal et appuyez sur **Entrée**.
2. **Phrase age :** Définissez la phrase secrète protégeant la capsule autonome `tar.zst.age`.
3. **Phrase LUKS2 :** Saisissez la phrase de passe de votre coffre USB pour permettre le montage et la copie.
4. Le script synchronise les fichiers, vérifie les empreintes SHA-256, nettoie la RAM par `shred`, réactive le swap système et referme le coffre.
5. Vous pouvez retirer la clé USB en toute sécurité.

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

### Étape 3 : Déverrouillage et scans
1. Saisissez votre phrase de passe LUKS2. Le coffre est monté en **lecture seule stricte** (`mount -o ro,noload`).
2. Déposez l'export JSON de l'application mobile **Binary Eye** dans l'enclave :
   ```bash
   cp /chemin/vers/binary_eye_all_qr.json /mnt/ram_sec/scans/binary_eye_all_qr.json
   ```
3. Appuyez sur **Entrée**.
4. Choisissez dans le menu interactif :
   * `1` : Extraire par identifiant (ex. `R042`)
   * `2` : Extraire par nom (ex. `banque`, `google`)
   * `3` : Restauration complète du fichier CSV
5. Le script écrit le résultat dans `/mnt/ram_sec/sorties/` et se met en pause (*« Appuie sur Entrée pour tout effacer... »*).

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

* **Copier le fichier sur votre machine (pour réimport ou usage) :**
  ```bash
  cp /mnt/ram_sec/sorties/restauration.csv ~/Documents/mon_export_restaure.csv
  ```

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
2. Copiez les fichiers `sauvegarde_qr_*.tar.zst.age` et les fichiers `.par2`.
3. Avec les utilitaires multiplateformes `par2` et `age` :
   ```bash
   # Réparer l'archive si des secteurs flash sont défectueux
   par2 r sauvegarde_qr_*.tar.zst.age.par2

   # Déchiffrer et décompresser
   age -d sauvegarde_qr_*.tar.zst.age | tar --zstd -xvf -
   ```

### B. En cas d'en-tête LUKS2 endommagé sur Linux
Si le début de la partition LUKS2 est corrompu, restaurez l'en-tête depuis la sauvegarde chiffrée :
```bash
# Déchiffrer l'en-tête sauvegardé
age -d -o /dev/shm/luks_header.bak ~/luks_header_qr.bak.age

# Restaurer l'en-tête sur la partition 1
sudo cryptsetup luksHeaderRestore /dev/sde1 --header-backup-file /dev/shm/luks_header.bak

# Détruire immédiatement l'image temporaire en RAM
shred -u -z -n 3 /dev/shm/luks_header.bak
```

---

## 4. Règles d'hygiène cryptographique

* **Suppression du CSV source :** Une fois votre sauvegarde vérifiée et/ou imprimée, détruisez `~/Documents/qrcode/export.csv` avec `shred -u -z -n 3 export.csv` pour éviter toute persistance sur SSD.
* **Mise à jour de mot de passe :** Si vous modifiez la phrase de passe LUKS2 de la clé, vous **devez** régénérer la sauvegarde d'en-tête chiffrée (`luks_header_qr.bak.age`), sinon restaurer un ancien en-tête réactiverait l'ancienne phrase.

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

