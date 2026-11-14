---
description: Mettre à jour la documentation du projet (README.md, AGENTS.md, docs/*.md, LISEZMOI.txt) à partir du code Bash/Python et des contraintes cryptographiques
---

# Workflow Docs Updater — Sauvegarde QR & Coffre USB

> Ce workflow harmonise la documentation du projet (Sauvegarde QR autonome et Coffre-fort USB chiffré)
> à partir du code réel, des options CLI (`argparse` et `usage`), des contraintes d'isolation en RAM
> et des spécifications cryptographiques. Il ne remplace pas la relecture humaine.

## Protocoles critiques

1. **Périmètre** : Documentation utilisateur et technique (`README.md`, `AGENTS.md`, `docs/GUIDE_OPERATOIRE_COFFRE_USB.md`, `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md`, `docs/Audit-technique-cryptographique-et-dintegrite-complet.md`, et le heredoc `LISEZMOI.txt` généré dans `creer_sauvegarde_qr.sh`). Ne pas altérer la logique opérationnelle des scripts sans demande expresse.
2. **Outils autorisés** : `read`, `grep`, `glob`, `edit`, `write`, `shell` (limité aux audits `git`, `python3 -m py_compile`, `bash -n`, `rg`, `wc`, `--help`, etc.).
3. **Contexte initial** : Lire `README.md`, `AGENTS.md`, et les scripts concernés par les sections à mettre à jour.
4. **Source de vérité** :
   - Code Bash et Python (`*.sh`, `*.py`) > Documentation existante > Historique git.
   - Les options CLI effectives (`argparse` Python, `usage` / flags Bash), les valeurs par défaut et les constantes architecturales font autorité :
     - **Taille de segment** : 500 octets (`--chunk-size 500`).
     - **Plafond de segmentation** : maximum 676 morceaux / 338 000 octets (`split -a 2`, suffixes `aa`..`zz`, glob `morceau_??`).
     - **Format QR haute densité** : `qrencode -s 16 -d 600`, préfixe obligatoire `LQR1 <suffixe> <n>/<total>\n` + charge brute.
     - **Planches PDF/HTML** : compact 4×5 (38 mm), confort 3×4 (54 mm), test 8 QR (54 mm).
     - **Coffre USB bi-partitionné** : partition 1 `COFFRE_LUKS` (LUKS2 Argon2id 2048 MiB par défaut, 4 threads, AES-XTS 512 bits) + ext4 (`mode 0700`) ; partition 2 `URGENCE_QR` (256 MiB exFAT lisible sans outil sous Linux/macOS/Windows).
     - **Redondance & Résilience** : capsule `tar` compressée `zstd -19` et chiffrée `age -p`, parité Reed-Solomon 15 % (`par2cmdline`), sauvegarde chiffrée de l'en-tête LUKS2 (`luks_header_qr.bak.age`).
     - **Anti-rémanence en RAM** : enclave `tmpfs` dédiée `/mnt/ram_sec` (`noswap,nodev,nosuid,noexec,mode=0700`), désactivation du swap (`swapoff -a`), interdiction des core dumps (`ulimit -c 0`), redirection temporaires/caches, écrasement sécurisé par `shred`.
     - **Consultation RO** : `cryptsetup open --readonly`, montage ext4 `-o ro,noatime,nodev,nosuid,noload`, enclave RAM pour sorties éphémères.
     - **Interopérabilité** : Bitwarden, KeePassXC (mapping colonnes et `QUOTE_ALL`), exports Binary Eye au format **JSON global unique** (`scans/binary_eye_all_qr.json`), normalisation NBSP (`U+00A0`), encodages UTF-8 / Latin-1 / CP1252, rejet des scans traduits (Google Lens).
5. **Sécurité et confidentialité** : Ne JAMAIS inclure d'identifiants réels, mots de passe de production, clés privées ou phrases de passe réelles dans la documentation. Utiliser exclusivement des exemples synthétiques (ex. `R123`, `example.com`, `user@example.com`).
6. **Cohérence tripartite obligatoire** : Tout changement de flux, de commande ou de comportement doit être synchronisé simultanément dans `README.md`, `AGENTS.md` et le heredoc `LISEZMOI.txt` de `creer_sauvegarde_qr.sh`.

## Étape 1 — Audit structurel, métrique et contractuel

### Cartographie

```sh
git ls-files '*.py' '*.sh' '*.md' 'docs/*.md'
```

### Volumétrie et constantes de dimensionnement

```sh
wc -l README.md AGENTS.md docs/*.md *.py *.sh
rg -n 'CHUNK_SIZE|chunk-size|676|338000|ARGON2|URGENCE|500' *.py *.sh
```

### Contrôles de syntaxe préalables

```sh
python3 -m py_compile *.py
bash -n *.sh
```

### Vérification des commandes CLI et flags réels

Inspecter les analyseurs d'options réels :
- **Python** (`argparse`) :
  - `extraire_entree.py` (`record_id`, `--id`, `--nom`, `--scans`, `--export`, `--individuels`, `--sortie`, `--afficher`, etc.)
  - `restaurer_sauvegarde.py` (`--scans`, `--export`, `--individuels`, `--sortie`, etc.)
  - `generer_index_qr.py` (`csv`, `--chunk-size`, `--out-dir`, `--qr-header`, `--organise`)
  - `generer_planches_qr.py` (`--qr-dir`, `--labels`, `--meta`, `--out`, `--html`, `--cols`, `--rows`, `--qr-mm`, `--limit`)
- **Bash** (`usage` / arguments positionnels et options) :
  - `creer_sauvegarde_qr.sh` (`export.csv`, `[dossier_sortie]`, `SANS_PLANCHES=1`)
  - `init_usb_coffre.sh` (`/dev/sdX`, `--argon2-mib`, `--argon2-threads`, `--allow-loopback`)
  - `executer_sauvegarde_ram.sh` (`/dev/sdX`, `[export.csv]`, `--device`, `--csv`, `--ram-size`, `--no-print`, `--garder-source`, `--allow-loopback`)
  - `consulter_coffre_ro.sh` (`/dev/sdX`, `--id`, `--nom`, `--restaurer`, `--export`, `--afficher`, `--ram-size`, `--allow-loopback`)

## Étape 2 — Diagnostic triangulé

| Source | Rôle | Outil |
| --- | --- | --- |
| **Intention** | Le « pourquoi » | Demande utilisateur, principes d'anti-rémanence, règles de sécurité de `AGENTS.md` |
| **Réalité** | Le « quoi » et le « comment » | Code réel Python (`*.py`) et Bash (`*.sh`), constantes, comportements en cas d'erreur |
| **Existant** | L'état documenté | `README.md`, `AGENTS.md`, `docs/GUIDE_OPERATOIRE_COFFRE_USB.md`, `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md`, heredoc `LISEZMOI.txt` |

Identifier les divergences :
- Un drapeau CLI ou une option documentée qui n'existe plus ou dont la syntaxe diffère ;
- Une valeur par défaut désynchronisée (ex. mémoire Argon2id, taille de tmpfs, dimensions de planches) ;
- Un chemin de point de montage erroné (ex. `/mnt/ram_sec`, `/mnt/usb_vault`, `/mnt/usb_urgence`) ;
- Une incohérence entre `README.md`, `AGENTS.md` et le `LISEZMOI.txt` généré ;
- Une omission sur les risques matériels (ex. rappel du danger de `/dev/sdX`, démontage requis de la partition exFAT auto-montée par le bureau).

## Étape 3 — Sélection du standard de rédaction

- **Commandes CLI** : Commandes shell copiables, flags documentés avec leur rôle exact et valeurs par défaut.
- **Protocoles de sécurité** :
  - Dangers matériels clairement encadrés par des avertissements `> [!CAUTION]`.
  - Anti-rémanence : tmpfs hermétique, absence d'accès disque, swap désactivé, écrasement par shred.
  - Sauvegarde à froid : distinction nette entre la partition chiffrée LUKS2 principale et la partition de secours exFAT.
- **Formatage** : Markdown GitHub Flavored avec alertes (`> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`, `> [!CAUTION]`).
- **Langue** : Français soigné, rigoureux et précis pour toute la documentation.

## Étape 4 — Proposition de mise à jour

Produire un plan structuré avant d'appliquer :

```markdown
## Plan de mise à jour de la documentation

### Audit
- Cibles : `README.md` (Section 5.3) et `AGENTS.md`
- Constat : l'option `--garder-source` de `executer_sauvegarde_ram.sh` n'est pas décrite dans le guide récapitulatif.

### Modifications
- Type : synchronisation CLI
- Diagnostic : option opérationnelle manquante dans la documentation
- Correction : mise à jour de la syntaxe et des exemples dans `README.md` et synchronisation dans `AGENTS.md`.

### Vérification
- Validation de la syntaxe avec `bash -n executer_sauvegarde_ram.sh`
- `git diff --check`
```

## Étape 5 — Application et finalisation

1. Appliquer avec `edit` (modification ciblée) ou `write` (mise à jour complète).
2. Vérifier la cohérence de la syntaxe des commandes citées avec le code effectif.
3. Vérifier la synchronisation tripartite obligatoire : `README.md`, `AGENTS.md` et heredoc `LISEZMOI.txt` dans `creer_sauvegarde_qr.sh`.
4. Lancer les contrôles syntaxiques :
   ```sh
   python3 -m py_compile *.py
   bash -n *.sh
   git diff --check
   ```
5. Vérifier `git status` : seuls les documents prévus doivent être modifiés, aucun secret ni fichier de test ne doit être stagé.

## Checkpoints

Avant :
- [ ] Public cible et documents concernés identifiés.
- [ ] Code source inspecté (`*.py`, `*.sh`).
- [ ] Cohérence des arguments CLI et des valeurs par défaut relevée.

Pendant :
- [ ] Commandes shell testées et copiables.
- [ ] Formatage GitHub Alerts (`[!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]`, `[!CAUTION]`).
- [ ] Exemples exclusivement fictifs et sans secrets.

Après :
- [ ] Synchronisation tripartite parfaite (`README.md`, `AGENTS.md`, `LISEZMOI.txt`).
- [ ] Aucun secret ni fichier temporaire dans le diff.
- [ ] `git diff --check` passe sans erreur d'espace ou de fin de ligne.
