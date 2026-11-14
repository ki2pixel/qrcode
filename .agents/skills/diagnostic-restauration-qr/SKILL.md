---
name: diagnostic-restauration-qr
description: "Use when une restauration affiche DIFFÉRENT, une extraction renvoie « Entrée introuvable », des morceaux LQR1 manquent ou sont ignorés, un export Binary Eye est invalide, ou des caractères NBSP/mojibake perturbent la récupération."
---

# Diagnostic de restauration QR

## Vue d'ensemble

Diagnostiquer un échec de restauration ou d'extraction sans modifier les
scans, sans réécrire le JSON et sans afficher de mot de passe. Le diagnostic
doit d'abord distinguer un morceau manquant, un doublon, un mauvais export,
un problème d'encodage ou une simple normalisation NBSP.

## Quand l'utiliser

- `restaurer_sauvegarde.py` affiche `Résultat : DIFFÉRENT`.
- `extraire_entree.py` affiche `Entrée introuvable` ou plusieurs résultats.
- Le message `X entrée(s) LQR1 ignorée(s)` apparaît.
- L'export Binary Eye est invalide ou ne contient pas de saut de ligne.
- Des caractères `Ã©`, `â€™`, `�` ou des NBSP perturbent la récupération.
- Le nombre de morceaux lus est inférieur au total attendu.

Ce skill ne teste pas la génération : pour reproduire un bogue de pipeline,
utiliser `test-sauvegarde-qr`. Pour les scripts USB, utiliser
`test-coffre-loopback`.

## Règles absolues

1. **Ne jamais éditer, réencoder ou « réparer » un scan original.**
2. **Ne jamais supprimer la source** avant `IDENTIQUE` ou
   `IDENTIQUE APRÈS NORMALISATION NBSP`.
3. **Ne jamais utiliser `--afficher`** pendant le diagnostic.
4. Pour un incident réel, travailler dans l'enclave RAM de
   `consulter_coffre_ro.sh` ou dans un `tmpfs` dédié. Ne jamais copier les
   scans sur le disque, dans un ticket ou dans un chat.
5. Pour les tests, utiliser uniquement des données synthétiques dans
   `/tmp/opencode`.
6. Ne pas utiliser les exports CSV ou TXT globaux de Binary Eye : ils
   aplatissent les sauts de ligne.
7. Ne pas utiliser de traduction automatique ni d'OCR tiers.

## Référence rapide

| Symptôme | Cause probable | Action |
|---|---|---|
| `Entrée introuvable` | Morceau manquant, scan tronqué, nom mal reconnu | Inventaire ; essayer `--id` ; extraction ciblée ; rescanner |
| `Résultat : DIFFÉRENT` | Chunk manquant/incomplet, doublon, encodage, fin de ligne | Comparer taille, nombre d'enregistrements, SHA sans NBSP |
| `Export JSON invalide` | JSON malformé, mauvais fichier | Utiliser `binary_eye_all_qr.json` |
| `Format d'export JSON inattendu` | Liste absente ou structure incorrecte | Réexporter depuis Binary Eye |
| `X entrée(s) LQR1 ignorée(s)` | Autre sauvegarde, total incohérent, CSV aplati | Vérifier `LQR1 ... n/total` et `total_chunks` |
| `Aucun encodage UTF-8 valide` | Scan corrompu, traduction, binaire | Réexporter sans traduction |
| `Mojibake` (`Ã©`, `â€™`, `�`) | Traduction automatique ou mauvais encodage | Rescanner avec Binary Eye, sans traduction |
| `IDENTIQUE APRÈS NORMALISATION NBSP` | Normalisation U+00A0 par Binary Eye | Succès, ne pas corriger |
| `Morceaux lus n/total` | Chunks manquants | Inventaire, rescan des pages concernées |
| `Taille restaurée` différente | Octets manquants, NBSP, fin de ligne | Comparer avec `size` et `size_sans_nbsp` |
| `Montage strictement lecture seule impossible` | Journal ext4 non vide | Démonter proprement ou réparer une fois en écriture, puis relancer |
| `Mémoire insuffisante pour ouvrir le coffre` | Argon2id supérieur à la RAM disponible | Libérer de la RAM ou changer de machine ; ne pas affaiblir le coffre |

## Procédure

### 1. Se placer à la racine de la sauvegarde

```bash
cd /chemin/vers/sauvegarde_qr_...
ls -l csv/index_morceaux.csv json/index_meta.json scans/
```

### 2. Inventorier sans afficher la charge utile

Le script ci-dessous ne lit que les en-têtes `LQR1`, les compteurs et les
tailles. Il n'affiche jamais le contenu des scans.

```bash
python3 - <<'PY'
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

root = Path.cwd()
try:
    meta = json.loads((root / "json/index_meta.json").read_text(encoding="utf-8-sig"))
    expected = int(meta["total_chunks"])
    rows = list(csv.DictReader((root / "csv/index_morceaux.csv").open(encoding="utf-8-sig")))
    expected_sfx = {r["morceau"].removeprefix("morceau_") for r in rows}
except Exception as exc:
    print(f"ERREUR index/métadonnées : {exc}")
    raise SystemExit(2)

export = root / "scans/binary_eye_all_qr.json"
if not export.is_file():
    print(f"ERREUR export absent : {export}")
    raise SystemExit(2)

try:
    items = json.loads(export.read_text(encoding="utf-8-sig"))
except Exception as exc:
    print(f"ERREUR JSON invalide : {exc}")
    raise SystemExit(2)
if not isinstance(items, list):
    print("ERREUR format inattendu : la racine JSON n'est pas une liste")
    raise SystemExit(2)

seen = Counter()
invalid = []
for index, item in enumerate(items):
    content = item.get("content") if isinstance(item, dict) else None
    if not isinstance(content, str) or not content.startswith("LQR1 "):
        invalid.append((index, "sans en-tête LQR1"))
        continue
    if "\n" not in content:
        invalid.append((index, "charge utile aplatie (export CSV ?)"))
        continue
    header, _sep, _payload = content.partition("\n")
    match = re.fullmatch(r"LQR1 ([a-z]{2}) (\d+)/(\d+)", header)
    if not match:
        invalid.append((index, "en-tête LQR1 invalide"))
        continue
    suffix, number, total = match.group(1), int(match.group(2)), int(match.group(3))
    if total != expected:
        invalid.append((index, f"total {total} != {expected}"))
        continue
    if suffix not in expected_sfx:
        invalid.append((index, f"morceau inconnu {suffix}"))
        continue
    seen[suffix] += 1

print(f"attendu      : {expected}")
print(f"présents     : {len(seen)}")
print(f"manquants    : {sorted(expected_sfx - set(seen))}")
print(f"doublons     : {[s for s, n in sorted(seen.items()) if n > 1]}")
print(f"invalides    : {len(invalid)}")
for index, reason in invalid:
    print(f"  - entrée {index}: {reason}")
PY
```

### 3. Lire les statuts de restauration

Si `/mnt/ram_sec/sorties` n'existe pas, utiliser l'enclave de
`consulter_coffre_ro.sh` ou monter un `tmpfs` dédié. Pour un incident réel,
ne jamais rediriger la sortie vers `/tmp` ou un autre stockage persistant.

```bash
python3 scripts/restaurer_sauvegarde.py --scans ./scans \
  --sortie /mnt/ram_sec/sorties/restauration.csv
```

Interprétation :
- `IDENTIQUE` : le CSV est restauré octet pour octet.
- `IDENTIQUE APRÈS NORMALISATION NBSP` : succès ; seuls des U+00A0 ont été
  normalisés par Binary Eye.
- `DIFFÉRENT` : ne pas supprimer l'original ; utiliser l'inventaire et
  rescanner les morceaux manquants.

### 4. Utiliser les replis prévus

```bash
# Export JSON précis
python3 scripts/extraire_entree.py --export /chemin/binary_eye_all_qr.json \
  --id R123

# Ignorer le JSON global et lire les scans individuels
python3 scripts/extraire_entree.py --individuels --nom "Banque" --scans ./scans

# Extraction ciblée avant une restauration complète
python3 scripts/extraire_entree.py R123 --scans ./scans \
  --sortie /mnt/ram_sec/sorties/entree_R123.csv

# Nom ambigu : préciser l'identifiant
python3 scripts/extraire_entree.py --id R123 --scans ./scans
```

Un enregistrement peut être extrait même si la restauration complète échoue,
tant que tous les morceaux qu'il chevauche sont présents. Ne pas conclure à
une perte totale avant d'avoir tenté l'extraction ciblée.

### 5. Décider et consigner

- `manquants=[]`, `doublons=[]`, `invalides=0` : le problème est probablement
  l'encodage, la fin de ligne ou le nom recherché.
- `manquants` non vide : rescanner les pages correspondantes ; ne pas
  fabriquer de morceau.
- `doublons` avec contenus différents : rescanner les pages concernées ; ne
  pas choisir à la main.
- `invalides > 0` : vérifier le total, le type d'export et l'absence de
  traduction.
- Mojibake : rescanner ; ne jamais corriger les caractères à la main.

## Pièges et anti-patrons

- Éditer `binary_eye_all_qr.json` ou réencoder un fichier de scan.
- Utiliser un export CSV/TXT de Binary Eye : les sauts de ligne sont perdus.
- Utiliser Google Lens, un OCR ou une traduction automatique.
- Supprimer le CSV original avant un statut de succès.
- Afficher `--afficher` ou journaliser la ligne extraite.
- Copier des scans réels dans `/tmp`, dans un ticket ou dans une réponse.
- Considérer `DIFFÉRENT` comme un succès partiel.
- Oublier que `IDENTIQUE APRÈS NORMALISATION NBSP` est un succès.
- Conclure à une perte totale sans tenter `--individuels`, `--export` ou
  l'extraction ciblée.
- Forcer un montage en écriture pour « réparer » un journal ext4.

## Vérification

```bash
python3 -m py_compile *.py
bash -n *.sh
```

Le diagnostic est validé lorsque l'inventaire identifie correctement
`manquants`, `doublons` et `invalides`, que la restauration affiche le statut
attendu, que l'extraction ciblée fonctionne et qu'aucun scan original n'a été
modifié.
