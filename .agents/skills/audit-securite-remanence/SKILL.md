---
name: audit-securite-remanence
description: "Use when il faut auditer l'exposition des secrets, la gestion swap/core dumps/tmpfs/shred, les permissions POSIX, les paramètres Argon2id/LUKS2, les montages lecture seule ou le nettoyage de l'enclave RAM avant une release, une revue de sécurité ou après une modification des scripts USB."
---

# Audit sécurité et rémanence

## Vue d'ensemble

Audit **statique et non destructif** du dépôt : secrets, rémanence mémoire,
permissions, cryptographie, montages lecture seule et nettoyage des enclaves.
Le skill lit le code et l'état système ; il n'exécute jamais
`init_usb_coffre.sh`, `executer_sauvegarde_ram.sh` ou
`consulter_coffre_ro.sh`.

Les contrôles qui exigent une exécution réelle sont délégués à
`test-coffre-loopback`. Un audit statique ne prouve pas à lui seul qu'un
`tmpfs` est monté, que le swap est restauré ou qu'un montage est réellement
`ro` : ces points restent `À VÉRIFIER` s'ils n'ont pas de preuve dynamique.

## Quand l'utiliser

- Avant une release ou une diffusion du dépôt.
- Après une modification de `init_usb_coffre.sh`,
  `executer_sauvegarde_ram.sh`, `consulter_coffre_ro.sh` ou des scripts
  Python de récupération.
- Après un incident de sécurité, une fuite suspectée ou un changement de
  permissions.
- Pour préparer une revue de code axée secrets et rémanence.

Ne pas utiliser ce skill pour tester le pipeline QR : utiliser
`test-sauvegarde-qr`. Pour exécuter le coffre, utiliser
`test-coffre-loopback`.

## Prérequis

Les commandes utilisent `rg` (ripgrep). À défaut, remplacer par
`grep -RIn` ou `grep -n`. Les commandes d'état système (`swapon`,
`losetup`, `cryptsetup status`, `mount`, `findmnt`, `stat`) sont en lecture
seule et peuvent nécessiter `sudo` selon la configuration.

## Règles d'audit

1. **Lecture seule** : aucune exécution des scripts du coffre, aucun
   `cryptsetup open`, aucun montage, aucun `swapoff`.
2. **Aucun secret dans le rapport** : ne jamais coller une ligne extraite,
   un en-tête LUKS déchiffré ou une sortie de `--afficher`.
3. **Preuve obligatoire** : chaque constat cite un fichier et une ligne, ou
   une commande d'état système.
4. **Statuts** : `PASS`, `FAIL`, `À VÉRIFIER`.
5. **Sévérités** : `Bloquant`, `Majeur`, `Mineur`, `Info`.
6. Un `FAIL` bloquant interdit la release tant qu'il n'est pas corrigé ou
   explicitement accepté.

## Grille des contrôles critiques

| ID | Contrôle | Preuve attendue |
|---|---|---|
| A1 | Absence de `set -x` | Aucun `set -x` dans les scripts sensibles |
| A2 | Historique désactivé | `HISTFILE=/dev/null`, `HISTSIZE=0`, `HISTFILESIZE=0`, `set +o history` |
| A3 | Aucun mot de passe logué ou affiché par défaut | `--afficher` absent des valeurs par défaut ; message « non affiché » |
| A4 | `--afficher` strictement explicite | Option opt-in, jamais ajoutée automatiquement |
| A5 | `umask 077` | Shell et Python |
| B1 | Core dumps désactivés | `ulimit -c 0` + vérification |
| B2 | Swap coupé puis restauré | `swapoff -a` avant le travail, `swapon` dans le trap |
| B3 | Shred avant démontage | `shred` des fichiers RAM/temporaires avant `umount` |
| B4 | `tmpfs` durci | `noswap,nodev,nosuid,noexec,mode=0700` |
| B5 | Environnement redirigé | `TMPDIR`, `TMP`, `TEMP`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `XDG_RUNTIME_DIR` |
| B6 | CUPS isolé | Spoule, cache et logs dans des tmpfs dédiés |
| B7 | `drop_caches` | Appelé après démontage, avant restauration du swap |
| C1 | Scripts `700` | `stat -c '%a'` |
| C2 | Documents/index/métadonnées `600` | `README.md`, `AGENTS.md`, `docs/*.md`, index générés |
| C3 | Sorties générées `600` | `umask 077`, `os.umask(0o077)`, `chmod 600` |
| D1 | LUKS2 durci | `luks2`, AES-XTS 512, SHA-512, secteur 4096 |
| D2 | Argon2id | 2048 MiB / 4 threads par défaut, bornes explicites |
| D3 | En-tête `age` | `luksHeaderBackup`, `age -p`, fichier `600` |
| D4 | Parité `par2` | `par2 create -r15` |
| E1 | Ouverture LUKS en lecture seule | `cryptsetup open --readonly` |
| E2 | Montage `ro,noload` | `mount -o ro,noatime,nodev,nosuid,noload` |
| E3 | Aucune bascule en écriture | Échec du montage ro = arrêt, pas de repli rw |

Périmètre des contrôles B5 à B7 :

- `init_usb_coffre.sh` : B5 partiel (tmpfs dédié à l'en-tête, pas de
  redirection globale), B6 et B7 `N/A` (pas d'enclave `/mnt/ram_sec`, pas
  d'impression).
- `executer_sauvegarde_ram.sh` : B5, B6 et B7 applicables.
- `consulter_coffre_ro.sh` : B5 et B7 applicables ; B6 `N/A` (pas
  d'impression).

## Procédure

### 1. Délimiter le périmètre et figer les preuves

```bash
git status --short
git diff --stat
ls -l *.sh *.py README.md AGENTS.md docs/*.md
```

Noter le commit ou l'état de travail audité. Ne pas modifier les fichiers
pendant l'audit.

### 2. Contrôler l'exposition des secrets

```bash
rg -n 'set -x|HISTFILE|HISTSIZE|HISTFILESIZE|umask|PYTHONDONTWRITEBYTECODE' *.sh *.py
rg -n -- '--afficher|Mot de passe non affiché|password|mot de passe' *.sh *.py README.md AGENTS.md
rg -n 'login_password|Password|password' generer_index_qr.py
```

Vérifier :
- aucun `set -x` ;
- `HISTFILE=/dev/null` dans les scripts privilégiés ;
- `--afficher` explicite et jamais activé par défaut ;
- l'index ne référence que nom, dossier, URL et identifiant, sans mot de passe ;
- aucun `echo`/`print` de secret.

`creer_sauvegarde_qr.sh` est un script utilisateur non privilégié : son absence
de `HISTFILE=/dev/null` est un point `N/A`, pas un `FAIL`, tant qu'il
n'affiche ni ne journalise de secret.

### 3. Contrôler la rémanence et les traps

```bash
rg -n 'ulimit -c|swapoff -a|swapon|shred|drop_caches|noswap|nodev,nosuid,noexec|TMPDIR|XDG_CACHE_HOME|XDG_DATA_HOME|XDG_CONFIG_HOME|XDG_RUNTIME_DIR|CUPS' \
  init_usb_coffre.sh executer_sauvegarde_ram.sh consulter_coffre_ro.sh
rg -n 'trap .*cleanup|cleanup\(\)' init_usb_coffre.sh executer_sauvegarde_ram.sh consulter_coffre_ro.sh
```

Vérifier l'ordre :
1. `ulimit -c 0` et `swapoff -a` avant les secrets ;
2. travail ;
3. `shred` des fichiers RAM/temporaires ;
4. démontage des tmpfs et fermeture du mapper ;
5. `drop_caches` ;
6. restauration du swap dans le trap.

La restauration par `swapon -- "$swapdev"` pour chaque périphérique est
équivalente à `swapon -a` et plus précise ; la noter `PASS`.

`init_usb_coffre.sh` n'isole pas CUPS et n'appelle pas `drop_caches` : c'est
`N/A`, car il ne monte pas l'enclave `/mnt/ram_sec` et ne génère pas de
planches. `executer_sauvegarde_ram.sh` porte l'isolation CUPS ; les deux
scripts d'enclave portent `drop_caches`.

### 4. Contrôler les permissions POSIX

```bash
stat -c '%a %n' *.sh *.py README.md AGENTS.md docs docs/*.md
stat -c '%a %n' .agents/skills .agents/skills/*/SKILL.md .agents/skills/*/scripts 2>/dev/null || true
find . -maxdepth 4 -type f \( -name '*.md' -o -name 'index_*.csv' -o -name 'index_meta.json' \) \
  -printf '%m %p\n'
```

Attendu : scripts `700`, documents/index/métadonnées `600`. Les répertoires de
skills projet doivent être `700`. Les assets existants non sensibles, comme
`.agents/skills/writing-skills`, sont hors périmètre mais à signaler s'ils
sont plus permissifs.

### 5. Contrôler les paramètres cryptographiques

```bash
rg -n -- '--type luks2|--cipher aes-xts-plain64|--key-size 512|--hash sha512|--pbkdf argon2id|--pbkdf-memory|--pbkdf-parallel|--iter-time 4000|--sector-size 4096' \
  init_usb_coffre.sh
rg -n 'luksHeaderBackup|age -p|chmod 600.*AGE_HDR|par2 create -r15' \
  init_usb_coffre.sh executer_sauvegarde_ram.sh
```

Vérifier :
- LUKS2, AES-XTS 512 bits, SHA-512, Argon2id, secteur 4096 ;
- `ARGON2_MIB=2048` et `ARGON2_THREADS=4` par défaut ;
- réduction automatique éventuelle à 512/1024 MiB si la RAM est insuffisante :
  la signaler comme `À VÉRIFIER` sur la machine cible, ou exiger
  `--argon2-mib 2048` pour garantir la valeur ;
- en-tête `age` en `600`, copié sur `URGENCE_QR` ;
- `par2 create -r15`.

### 6. Contrôler la lecture seule

```bash
rg -n -- 'cryptsetup open --readonly|mount -o ro,noatime,nodev,nosuid,noload|mount -o rw' \
  consulter_coffre_ro.sh
```

Vérifier :
- `cryptsetup open --readonly` ;
- montage `ro,noatime,nodev,nosuid,noload` (le noyau peut afficher
  `norecovery`) ;
- en cas d'échec du montage ro, `die` immédiat, aucun repli en écriture.

### 7. Relever l'état système sans exécuter les scripts

```bash
swapon --show
mount | rg 'ram_sec|usb_vault|usb_urgence' || true
cryptsetup status qr_vault 2>/dev/null || true
losetup -a
```

Ces commandes sont en lecture seule. Ne pas déverrouiller le coffre.

### 8. Produire le rapport

Modèle :

```text
ID | Contrôle | Preuve (fichier:ligne ou commande) | Statut | Sévérité | Action
```

Règles de statut :
- `PASS` : preuve statique conforme, ou preuve dynamique explicitement citée.
- `FAIL` : écart avéré. Indiquer la correction et la sévérité.
- `À VÉRIFIER` : contrôle non prouvable statiquement, ou dépendant de la
  machine cible.

Sont bloquants : secret en clair, `--afficher` par défaut, absence de
`swapoff`/`noswap`, absence de `shred` avant démontage, montage de
consultation en écriture, LUKS affaibli, index ou document sensible lisible
par tous.

Sont majeurs : documents groupe-lisibles, réduction Argon2id non justifiée,
CUPS non isolé alors que l'impression est active, `shred` présenté comme une
garantie physique sur flash/SSD.

Sont mineurs ou `N/A` : absence de `drop_caches` dans un script qui ne monte
pas d'enclave, absence de `HISTFILE` dans un script non privilégié qui
n'affiche pas de secret.

## Remédiation

Figer le rapport initial, appliquer les corrections, puis rejouer la grille.
Exemple pour des documents et des skills projet trop permissifs :

```bash
chmod 700 docs
chmod 600 docs/*.md
chmod 700 .agents/skills/* .agents/skills/*/scripts 2>/dev/null || true
chmod 600 .agents/skills/*/SKILL.md
```

Adapter au périmètre réel : ne jamais élargir les permissions du dépôt pour
faire passer un test, et ne pas modifier un asset hors périmètre sans accord
du propriétaire. Les permissions POSIX ne suivent pas une partition exFAT :
le `umask=077` au montage ne protège pas `URGENCE_QR` sur un autre système ;
la confidentialité de la capsule et de l'en-tête repose sur `age`.

## Pièges et anti-patrons

- Exécuter `init_usb_coffre.sh` ou `executer_sauvegarde_ram.sh` pour
  « vérifier » : interdit, ce n'est plus un audit statique.
- Déverrouiller le coffre ou lire un en-tête LUKS réel.
- Copier une sortie de `--afficher` dans le rapport.
- Se contenter de `grep swapoff` sans vérifier l'ordre du trap et la
  restauration.
- Oublier CUPS, les caches, les logs ou `drop_caches`.
- Considérer `shred` comme une garantie physique sur SSD/NVMe ou flash.
- Vérifier les permissions avec `ls -l` sur un lien symbolique : utiliser
  `stat`.
- Confondre `PASS` statique et preuve dynamique : déléguer explicitement à
  `test-coffre-loopback`.
- Modifier les fichiers pendant l'audit.

## Vérification

```bash
python3 -m py_compile *.py
bash -n *.sh
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
```

Le rapport est valide lorsque chaque ligne de la grille a une preuve, un
statut et une action, que les secrets n'apparaissent nulle part et que les
contrôles dynamiques sont soit prouvés par un rapport `test-coffre-loopback`,
soit marqués `À VÉRIFIER`.
