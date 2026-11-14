# AGENTS.md

Petit outil autonome (Bash + Python) qui transforme un export CSV de mots de passe en QR codes imprimés, puis extrait une entrée ou restaure le CSV. Les données sont réelles et sensibles : utiliser uniquement des CSV synthétiques pour les tests, ne jamais afficher un mot de passe sans nécessité.

Pas de manifeste, lockfile, CI, linter ni suite de tests. Les scripts et messages sont en français ; conserver ce choix. Flux utilisateur détaillé : `LISEZMOI.md`.

## Commandes

- Génération complète :
  `./creer_sauvegarde_qr.sh export.csv [dossier_sortie]`
  Dépendances : `split`, `qrencode`, Python 3.10+, paquet Python `weasyprint` (PDF). `SANS_PLANCHES=1` saute les planches ; sans WeasyPrint, les PDF ne sont pas produits (le HTML l'est).
- Extraction ciblée, depuis la racine de la sauvegarde :
  `python3 scripts/extraire_entree.py R123 --scans ./scans`
  `python3 scripts/extraire_entree.py --nom example.com --scans ./scans`
- Restauration complète :
  `python3 scripts/restaurer_sauvegarde.py --scans ./scans`
- Contrôle syntaxique :
  `python3 -m py_compile *.py && bash -n creer_sauvegarde_qr.sh`

## Flux et fichiers

- `creer_sauvegarde_qr.sh` : `split -b 500` → `morceaux/morceau_aa…`, puis un QR par morceau avec l'en-tête `LQR1 <suffixe> <n>/<total>\n` + octets bruts. QR en `-s 16 -d 600` (format validé ; ne pas réduire).
- Il appelle ensuite `generer_index_qr.py --chunk-size 500 --qr-header --organise` puis `generer_planches_qr.py` (compact 4×5/38 mm, grand 3×4/54 mm, test 8 QR).
- Si tu appelles `generer_index_qr.py` seul, passe `--qr-header --organise` pour reproduire l'arborescence de `creer_sauvegarde_qr.sh`.
- `generer_index_qr.py` calcule les offsets d'octets et écrit `csv/index_enregistrements.csv`, `csv/index_morceaux.csv`, `json/index_meta.json`, HTML/PDF. Il vérifie que chaque enregistrement se reconstruit exactement et sort en code 2 sinon.
- `generer_planches_qr.py` ne lit que les PNG, les étiquettes et `index_meta.json` ; il écrit toujours le HTML, mais le PDF exige WeasyPrint.
- `extraire_entree.py` et `restaurer_sauvegarde.py` doivent rester dans le même dossier : le second importe le premier.
- `restaurer_sauvegarde.py` s'appuie sur `index_morceaux.csv` (ordre/tailles) et `index_meta.json` (en-tête, `sha256`, `sha256_sans_nbsp`, `record_count`). Il essaie CRLF/LF, avec ou sans saut de ligne final, et sort en code 1 si le résultat est `DIFFÉRENT`.

## Pièges vérifiés

- Export Binary Eye : **JSON global uniquement**, `scans/binary_eye_all_qr.json`. Le CSV global aplatit les sauts de ligne des champs ; le TXT perd certains espaces de bord.
- Binary Eye normalise les espaces insécables U+00A0 en espaces. `IDENTIQUE APRÈS NORMALISATION NBSP` est un succès ; `DIFFÉRENT` ne l'est pas. Le SHA sans NBSP est dans `index_meta.json`.
- Le JSON peut contenir du Latin-1/CP1252 (mojibake) : les scripts essaient UTF-8, Latin-1 et CP1252. Ne pas réécrire les scans à la main.
- Les scans traduits automatiquement (Google Lens, etc.) sont refusés : réexporter sans traduction.
- `extraire_entree.py` n'affiche pas le mot de passe sans `--afficher` ; ne pas ajouter de log de secrets. Sortie par défaut : `entree_Rxxx.csv`.
- `--individuels` ignore le JSON global ; `--export` impose un JSON précis. Ce sont des secours, pas le flux nominal.
- Changer `--chunk-size` invalide les scans/index existants ; changer la taille des QR impose de réimprimer.
- Le pipeline suppose ≤676 morceaux (suffixes `aa`…`zz`, glob `morceau_??`) ; au-delà, adapter `split -a` et les globs.
- L'index ne contient pas de mots de passe, mais noms/URL/identifiants restent sensibles. Permissions attendues : scripts 700, fichiers 600.
- `LISEZMOI.md` est la doc utilisateur ; le `LISEZMOI.txt` de chaque sauvegarde est généré par un heredoc dans `creer_sauvegarde_qr.sh`. Mettre les deux à jour si le flux change.

## Vérification d'un changement

Pas de tests automatisés. Créer un CSV synthétique dans `/tmp/opencode`, lancer `creer_sauvegarde_qr.sh`, fabriquer un faux export JSON (`[{"content": "LQR1 aa 1/N\n" + contenu_brut}, …]`), puis vérifier :

1. `restaurer_sauvegarde.py` affiche `Résultat : IDENTIQUE` et le SHA-256 correspond ;
2. une extraction `--nom` retrouve la bonne ligne ;
3. tester si possible CRLF et LF, avec et sans saut de ligne final.

Ne jamais lancer la génération ou la restauration sur un export réel sans accord explicite.
