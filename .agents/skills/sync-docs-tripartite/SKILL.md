---
name: sync-docs-tripartite
description: "Use when une commande, un drapeau, un défaut, une limite, un chemin, un format, un paramètre de sécurité ou une procédure de secours change, ou lorsque README.md, AGENTS.md et le heredoc LISEZMOI.txt de creer_sauvegarde_qr.sh risquent de diverger."
---

# Synchronisation documentaire tripartite

## Vue d'ensemble

Le dépôt possède trois sources normatives qui doivent rester cohérentes :

1. `README.md` : guide utilisateur, destiné à l'opérateur humain.
2. `AGENTS.md` : consignes, garde-fous et invariants pour l'IA.
3. Le heredoc `LISEZMOI.txt` dans `creer_sauvegarde_qr.sh` : guide de secours
   autonome, imprimé ou embarqué dans chaque sauvegarde générée.

Sources secondaires :

- `docs/GUIDE_OPERATOIRE_COFFRE_USB.md` et
  `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md` : procédures détaillées.
- `docs/Audit-technique-cryptographique-et-dintegrite-complet.md` : audit
  historique. Il peut décrire des écarts déjà corrigés ; ce n'est pas une
  source normative.
- Le heredoc `scans/LISEZMOI.txt`, volontairement court, qui rappelle le nom
  du JSON global et le format `LQR1`.

Le code et les tests validés sont la source de vérité. Un document ne doit
jamais servir de prétexte pour modifier le code sans test. À l'inverse, un
changement de code validé doit être répercuté dans les trois sources avant
d'être considéré comme terminé.

## Quand l'utiliser

- Après un changement de commande, de drapeau, de valeur par défaut, de
  limite, de chemin, de format, de paramètre de sécurité ou de procédure de
  secours.
- Après une modification de `creer_sauvegarde_qr.sh`,
  `init_usb_coffre.sh`, `executer_sauvegarde_ram.sh`,
  `consulter_coffre_ro.sh` ou des scripts Python de récupération.
- Avant une release, une remise de documentation ou une impression de
  secours.
- Lorsqu'un utilisateur signale qu'une commande du `README.md` ou du
  `LISEZMOI.txt` ne fonctionne pas.

Ne pas utiliser ce skill à la place de `test-sauvegarde-qr` ou de
`test-coffre-loopback` : la synchronisation documentaire ne remplace pas les
tests d'exécution.

## Triangle tripartite

| Source | Public | Rôle | Doit contenir | Ne doit pas contenir |
|---|---|---|---|---|
| `README.md` | Opérateur humain | Guide utilisateur complet | Commandes, drapeaux, défauts, limites, avertissements `lsblk`, notation de disque physique | Instructions de test réservées aux agents |
| `AGENTS.md` | Agent IA | Garde-fous et invariants | Limites exactes, chemins, statuts, règles de test synthétique, `$LOOP` | Commandes destinées à un disque physique réel |
| Heredoc `LISEZMOI.txt` | Opérateur hors ligne | Secours papier/embarqué | Limite QR, en-tête `LQR1`, JSON global, statuts, masquage des mots de passe, rappel web court (port, jeton, absence de `sudo`) | Détails USB non nécessaires à la récupération QR |
| Heredoc `scans/LISEZMOI.txt` | Opérateur devant le dossier `scans/` | Rappel court | `binary_eye_all_qr.json`, format `LQR1`, refus des traductions | Procédure complète |
| `docs/*.md` | Opérateur avancé | Détail et historique | Procédures détaillées, contexte | Statut de source normative |

### Cibles de disques

La distinction est entérinée :

- `README.md` peut conserver la notation de disque physique pour l'opérateur
  humain, avec vérification obligatoire par `lsblk` et avertissements
  destructifs.
- Les compétences d'agents et les tests automatisés utilisent uniquement
  `$LOOP` ou `/dev/loopX`, avec `--allow-loopback`.
- Ne jamais recopier une commande de disque physique dans un `SKILL.md`.
- Le `LISEZMOI.txt` QR ne cible aucun disque : il ne doit pas introduire de
  commande USB ambiguë.

### Interface web

L'interface web locale est une surface supplémentaire depuis la version 1.0.
Les trois sources normatives doivent rester alignées sur :

- l'écoute strictement locale `127.0.0.1:5100`, jamais `0.0.0.0` ;
- le jeton de fragment `#jeton=…` échangé contre un cookie
  `HttpOnly`/`SameSite=Strict`, avec expiration des données après 60 min
  d'inactivité ;
- l'absence de `sudo` dans le serveur : `POST /api/usb/demonter` exécute
  uniquement `udisksctl unmount --no-user-interaction -b /dev/sdXN`, sans
  `-f`/`-l` ; les autres opérations USB ne produisent que des commandes à
  copier ;
- les plafonds de téléversement : CSV 338 000 octets, scans 16 Mio, ZIP
  256 Mio, index 64 Mio et métadonnées 1 Mio ;
- les contrôles `Host` et `Origin` des requêtes mutantes, l'en-tête
  `X-QR-Web` et l'absence de secrets dans les journaux.

Le heredoc principal ne doit conserver qu'un rappel court de l'interface web :
port, jeton, absence de `sudo` et démontage `udisksctl`. Les commandes USB
complètes restent dans `README.md` et `AGENTS.md`.

## Invariants stricts

| Domaine | Invariant | Sources normatives | Contrôle |
|---|---|---|---|
| Limite | 338 000 octets maximum | README, AGENTS, LISEZMOI | `rg '338 000\|338000'` |
| Segmentation | 676 morceaux maximum, blocs de 500 octets | README, AGENTS, LISEZMOI | `rg '676\|500 octets'` |
| Découpage | `split -a 2 -b 500`, glob `morceau_??` | Code, AGENTS | `rg 'split -a 2 -b 500\|morceau_\\?\\?'` |
| Refus | CSV > 338 000 octets refusé, jamais tronqué | Code, AGENTS | Test synthétique aux limites |
| En-tête QR | `LQR1 <suffixe> <n>/<total>\n` + octets bruts | Code, AGENTS, README, LISEZMOI | Lire le `printf` et décoder un QR |
| Suffixes | `aa` à `zz` | Code, AGENTS, README | Génération de contrôle |
| Export scans | JSON global Binary Eye uniquement, `scans/binary_eye_all_qr.json` | README, AGENTS, LISEZMOI, scans/LISEZMOI | `rg 'binary_eye_all_qr'` |
| Formats refusés | CSV aplati et TXT non utilisés, traductions automatiques refusées | README, AGENTS, LISEZMOI | `rg 'CSV\|TXT\|traduit'` |
| Statut succès | `IDENTIQUE` | README, AGENTS, LISEZMOI, code | Test de restauration |
| Statut succès NBSP | `IDENTIQUE APRÈS NORMALISATION NBSP` | README, AGENTS, LISEZMOI, code | Test avec NBSP |
| Statut échec | `DIFFÉRENT`, code de sortie 1 | README, AGENTS, LISEZMOI, code | Test avec corruption |
| Confidentialité | Mot de passe masqué par défaut | README, AGENTS, LISEZMOI, code | Extraction sans `--afficher` |
| Confidentialité | `--afficher` toujours explicite, jamais automatique | README, AGENTS, LISEZMOI, code | `rg -- '--afficher'` |
| LUKS2 | AES-XTS 512 bits, Argon2id 2048 MiB / 4 threads | README, AGENTS, docs, code | `rg 'aes-xts-plain64\|key-size 512\|ARGON2_MIB=2048\|ARGON2_THREADS=4'` |
| Détails LUKS2 | SHA-512, secteur 4096 dans le code ; secteur 4096 aussi dans README | Code, README, docs avancés | `rg 'hash sha512\|sector-size 4096'` |
| Secours USB | `URGENCE_QR` 256 MiB, exFAT | README, AGENTS, docs, code | `rg '256 MiB\|256 Mio'` |
| Parité | `par2` 15 % | README, AGENTS, docs, code | `rg 'par2 create -r15'` |
| En-tête | `luks_header_qr.bak.age`, chiffré par `age` | README, AGENTS, docs, code | `rg 'luksHeaderBackup\|age -p'` |
| Lecture seule | `cryptsetup open --readonly`, `ro,noatime,nodev,nosuid,noload` | README, AGENTS, docs, code | `rg 'readonly\|noload'` |
| Web — écoute | `127.0.0.1:5100` uniquement, jamais `0.0.0.0` | README, AGENTS, LISEZMOI | `rg '127\.0\.0\.1:5100'` et revue de `HOTE` |
| Web — session | Jeton de fragment, cookie `HttpOnly`/`SameSite=Strict`, 60 min | README, AGENTS, code | `rg 'TTL_SECONDES'` et revue de `serveur.py` |
| Web — privilèges | `udisksctl unmount --no-user-interaction -b`, aucun `sudo` exécuté | README, AGENTS, LISEZMOI, code | `rg 'no-user-interaction'` et revue de `usb.py` |
| Web — limites | CSV 338 000 octets, scans 16 Mio, ZIP 256 Mio | README, AGENTS, code | `rg 'LIMITE_' web/config.py` |

Le `LISEZMOI.txt` principal est un guide QR : les invariants LUKS2/USB sont
portés par `README.md`, `AGENTS.md` et les documents secondaires. Ne pas
gonfler le guide papier avec des détails USB qui n'aident pas à restaurer les
QR.

## Procédure de validation

**Règle d'ordre : toujours stabiliser le code en premier.**

### 1. Stabiliser le code

Avant toute modification documentaire :

```bash
python3 -m py_compile *.py
bash -n *.sh
```

Exécuter ensuite les tests pertinents avec des données synthétiques :

- `test-sauvegarde-qr` pour le pipeline QR et la restauration ;
- `test-coffre-loopback` pour les scripts USB, avec `$LOOP`.

Ne jamais utiliser un export réel, une phrase de passe réelle ou un disque
physique pour cette validation.

### 2. Vérifier les heredocs

Le fichier `creer_sauvegarde_qr.sh` contient deux heredocs distincts :

```bash
# Heredoc principal, interpolé par Bash
cat > "$OUT/LISEZMOI.txt" <<EOF

# Heredoc du dossier scans, littéral
cat > "$OUT/scans/LISEZMOI.txt" <<'EOF'
```

Contrôles obligatoires :

- le heredoc principal rend `$BASE`, `$TOTAL`, `$PAGES_COMPACT` et
  `$PAGES_GRAND` ;
- le heredoc `scans/LISEZMOI.txt` conserve littéralement
  `LQR1 aa 1/100` et n'interprète aucune variable ;
- aucun `$` destiné à l'impression n'est interprété par erreur dans le
  heredoc principal ;
- les deux blocs se terminent par un `EOF` seul en début de ligne ;
- le texte n'est pas édité dans un `LISEZMOI.txt` déjà généré : il serait
  écrasé à la prochaine génération.

### 3. Générer une sauvegarde de contrôle

Créer un CSV synthétique dans `/tmp/opencode` et générer une sauvegarde
complète :

```bash
BASE="/tmp/opencode/tripartite-$(date +%s)"
mkdir -p "$BASE"
printf 'Group,Title,Username,Password,URL,Notes\n"demo","Alpha","alpha@example.test","DEMO-ALPHA","https://example.test","note"\n' > "$BASE/export.csv"
SANS_PLANCHES=1 ./creer_sauvegarde_qr.sh "$BASE/export.csv" "$BASE/sauvegarde"
```

Si WeasyPrint est disponible, relancer sans `SANS_PLANCHES=1` pour valider
aussi les PDF. Lire ensuite le rendu réel :

```bash
cat "$BASE/sauvegarde/LISEZMOI.txt"
cat "$BASE/sauvegarde/scans/LISEZMOI.txt"
```

Vérifier que le titre contient `export`, que `$TOTAL` est remplacé par le
nombre de QR, que les pages sont calculées, et qu'aucun `$BASE` ou `$TOTAL`
littéral ne subsiste.

### 4. Exécuter les commandes copiées

Construire un export Binary Eye synthétique à partir des morceaux, puis
exécuter exactement les commandes du `README.md` et du `LISEZMOI.txt` :

```bash
python3 - "$BASE/sauvegarde" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
chunks = sorted((out / "morceaux").glob("morceau_??"))
items = []
for index, chunk in enumerate(chunks, 1):
    suffix = chunk.name.split("_", 1)[1]
    items.append({
        "content": f"LQR1 {suffix} {index}/{len(chunks)}\n"
        + chunk.read_bytes().decode("utf-8")
    })
(out / "scans" / "binary_eye_all_qr.json").write_text(
    json.dumps(items, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

cd "$BASE/sauvegarde"
python3 scripts/extraire_entree.py R001 --scans ./scans
python3 scripts/extraire_entree.py --nom Alpha --scans ./scans
python3 scripts/restaurer_sauvegarde.py --scans ./scans
```

Contrôles :

- l'extraction affiche `Mot de passe non affiché` et aucun mot de passe
  synthétique n'apparaît sans `--afficher` ;
- la restauration affiche `Résultat : IDENTIQUE` ;
- un test `--afficher` sur données synthétiques montre que l'option est
  strictement opt-in ;
- les commandes USB documentées sont vérifiées par `--help` et parsées, mais
  jamais exécutées sur un disque physique.

### 5. Comparer les trois sources

Pour chaque invariant modifié, rechercher la même valeur dans les trois
sources et citer le fichier et la ligne :

```bash
rg -n '338 000|338000|676|500 octets|LQR1|binary_eye_all_qr|IDENTIQUE|DIFFÉRENT|NBSP|--afficher' \
  README.md AGENTS.md creer_sauvegarde_qr.sh
```

Vérifier aussi les sources secondaires :

```bash
rg -n '256 MiB|256 Mio|2048|4 threads|AES-XTS|par2|15 %|luks_header' \
  README.md AGENTS.md docs/*.md
```

Les divergences des documents d'audit historiques sont signalées comme
`Info` si elles décrivent un état ancien. Elles ne doivent pas être copiées
dans les sources normatives.

### 6. Corriger et régénérer

- Corriger d'abord le code si le code est fautif, puis relancer les tests.
- Mettre à jour `README.md`, `AGENTS.md` et le heredoc principal dans le même
  changement.
- Mettre à jour `scans/LISEZMOI.txt` si le nom du JSON, le format `LQR1` ou le
  refus des traductions change.
- Mettre à jour les documents secondaires seulement s'ils contredisent la
  nouvelle vérité ; ne pas réécrire un audit historique comme s'il était
  actuel.
- Régénérer une sauvegarde synthétique et relire le `LISEZMOI.txt` rendu.

### 7. Produire le rapport

Modèle :

```text
Invariant | README | AGENTS | LISEZMOI | Code | Statut | Preuve | Action
```

Statuts : `PASS`, `FAIL`, `À VÉRIFIER`. Un `FAIL` sur une source normative
bloque la clôture. Un écart d'un document historique est `Info` s'il ne
trompe pas l'opérateur sur l'état actuel.

Le rapport final doit citer les fichiers modifiés, les tests exécutés et le
résultat du `LISEZMOI.txt` rendu. Aucun secret réel ne doit y apparaître.

### 8. Vérifier l'interface web

Si le changement touche `web/`, `lancer_interface.sh` ou le paragraphe web du
`LISEZMOI.txt`, exécuter la procédure de `AGENTS.md` section « Vérification
d'un changement », point 4, avec des données synthétiques. Contrôler au
minimum : écoute `127.0.0.1:5100`, 401 sans cookie, CSP sur `/`, plafonds de
téléversement et commande exacte
`udisksctl unmount --no-user-interaction -b`.

## Pièges et anti-patrons

- Modifier un `LISEZMOI.txt` généré au lieu du heredoc.
- Confondre le heredoc principal `<<EOF` et le heredoc littéral `<<'EOF'`.
- Attendre l'expansion de `$TOTAL` dans un heredoc protégé par des quotes.
- Oublier `DIFFÉRENT` : ce n'est pas un succès, et le code de sortie est 1.
- Documenter `--afficher` comme comportement par défaut.
- Recopier la notation de disque physique dans un skill d'agent : utiliser
  `$LOOP` ou `/dev/loopX`.
- Tester avec un export réel ou une phrase de passe réelle.
- Prendre `docs/Audit-technique-cryptographique-et-dintegrite-complet.md`
  pour l'état actuel du code.
- Changer uniquement `README.md` : le guide papier et `AGENTS.md` resteront
  faux.
- Changer le code pour faire passer un document sans test de régression.

## Vérification finale

```bash
python3 -m py_compile *.py
python3 -m compileall -q web
bash -n *.sh
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
```

Le skill est validé lorsque les trois sources normatives sont cohérentes,
que le `LISEZMOI.txt` rendu a été relu, que les commandes copiées ont été
exécutées sur des données synthétiques et qu'aucun secret réel n'a été
manipulé. Si le périmètre inclut l'interface web, les contrôles du point 8
doivent aussi être passés.
