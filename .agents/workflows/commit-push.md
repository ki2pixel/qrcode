---
description: Contrôles de syntaxe (Python, Bash), vérification de non-régression et de sécurité des secrets, commit et push de la branche courante
---

# Commit & Push (branche courante)

## Prérequis

- Des fichiers modifiés existent dans le dépôt.
- Le remote `origin` est configuré (`git remote -v`).
- **SÉCURITÉ CRITIQUE — AUCUN SECRET NI FICHIER SENSIBLE STAGÉ** :
  - Aucun export CSV de mots de passe réel (`*.csv`, `export.csv`, etc.). Seuls les CSV synthétiques créés temporairement pour des tests (dans `/tmp` ou un dossier de test non versionné) peuvent exister et ne doivent JAMAIS être committés.
  - Aucun dossier de sauvegarde généré (`sauvegarde_qr_*`, `sauvegarde_*`).
  - Aucune sauvegarde d'en-tête LUKS chiffrée ou en clair (`luks_header*`, `*.bak`, `*.bak.age`).
  - Aucune capsule chiffrée, archive ou fichier de parité (`*.tar.zst`, `*.age`, `*.par2`, `*.sha256`).
  - Aucun artefact de scan, extraction ou restauration (`scans/*.json`, `binary_eye_all_qr.json`, `entree_*.csv`, `restauration.csv`, `*.qrpayload`, `morceaux/`, `qrcodes/`, `pdf/`, `html/`, `csv/`, `json/`).
  - Aucun fichier temporaire, image loopback (`*.img`, `*.raw`) ou cache Python (`__pycache__/`).
- **Permissions POSIX respectées** :
  - Scripts exécutables en `700` (`rwx------`) : `*.sh`, `extraire_entree.py`, `restaurer_sauvegarde.py`, `generer_index_qr.py`, `generer_planches_qr.py`.
  - Fichiers de documentation et de configuration en `600` (`rw-------`).
- Si une option CLI, un argument ou une constante a été modifié(e), s'assurer de la cohérence tripartite entre le code (`*.sh`, `*.py`), `README.md`, `AGENTS.md` et le heredoc `LISEZMOI.txt` de `creer_sauvegarde_qr.sh`.

## Étapes

1. Vérifier l'état git :
   ```sh
   git status
   git diff --stat
   ```

2. Lancer les contrôles de syntaxe et de format :
   ```sh
   python3 -m py_compile *.py
   bash -n *.sh
   git diff --check
   ```

3. (Si du code de traitement CSV/QR a été modifié) Valider sur un CSV synthétique de test :
   - Créer un CSV synthétique dans un répertoire temporaire isolé (ex. `/tmp/test_qr_...`).
   - Tester le pipeline (`./creer_sauvegarde_qr.sh export_test.csv`) ou avec `SANS_PLANCHES=1` si WeasyPrint n'est pas requis.
   - Vérifier la détection et la restauration avec simulation d'un export JSON Binary Eye (`python3 scripts/restaurer_sauvegarde.py --scans ...`).
   - Supprimer impérativement le dossier temporaire après le test.

4. Stager explicitement les fichiers ciblés :
   ```sh
   git add <fichiers>
   git diff --cached --check
   ```
   *Éviter impérativement `git add -A` ou `git add .` par défaut afin de ne jamais inclure par inadvertance un export CSV réel, un fichier de scan ou une image loopback.*

5. Committer avec un message Conventional Commits dont le résumé est en français, fidèle au diff :
   ```sh
   git commit -m "<type>: <résumé court en français>"
   ```
   Types usuels : `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`.

6. Pousser la branche courante :
   ```sh
   git push -u origin "$(git branch --show-current)"
   ```

## Exécution étape par étape

```sh
BRANCH=$(git branch --show-current)

# 1. Vérification de l'état
git status
git diff --stat

# 2. Contrôles syntaxiques obligatoires
python3 -m py_compile *.py
bash -n *.sh
git diff --check

# 3. Stage ciblé (remplacer par les fichiers réellement modifiés)
git add <fichiers>
git diff --cached --check

# 4. Commit et push
git commit -m "<type>: <résumé court en français>"
git push -u origin "$BRANCH"
```

## Notes

- Pas de suite de tests CI automatisée sur ce dépôt : la rigueur des contrôles syntaxiques locaux et des tests synthétiques manuels est primordiale.
- Ne jamais désactiver ou contourner les contrôles avec `--no-verify`.
- Ne jamais committer de secrets réels (mots de passe, clés age, sauvegardes d'en-tête LUKS).
- En cas de modification d'un script Bash ou Python, vérifier que les messages et les documentations restent intégralement en français.
- En cas d'échec de syntaxe (`py_compile` ou `bash -n`) ou de fin de ligne / whitespace indésirable (`git diff --check`), corriger avant de committer.
