---
name: test-sauvegarde-qr
description: "Use when il faut valider la chaîne de sauvegarde QR, reproduire un échec de génération ou de restauration, ou vérifier une modification du découpage, des index, du JSON Binary Eye, de la normalisation NBSP ou du SHA-256, exclusivement avec des CSV synthétiques."
---

# Test de la sauvegarde QR

## Vue d'ensemble

Valider la chaîne QR hors USB avec des CSV synthétiques : découpage,
indexation, génération, simulation d'un export Binary Eye, restauration
exacte, normalisation NBSP et extraction ciblée. Le résultat est correct
uniquement si le CSV restauré est identique octet pour octet, ou identique
après normalisation NBSP, avec un SHA-256 concordant.

**Ne jamais utiliser un export réel de mots de passe.** Ne pas afficher de
secret, même synthétique, hors du test ponctuel de `--afficher`.

## Quand l'utiliser

- Après une modification de `creer_sauvegarde_qr.sh`,
  `generer_index_qr.py`, `generer_planches_qr.py`, `extraire_entree.py` ou
  `restaurer_sauvegarde.py`.
- Pour reproduire un échec de restauration, d'extraction ou de découpage.
- Pour vérifier les fins de ligne, les exports `QUOTE_ALL`, les champs
  multi-lignes, les NBSP ou la limite de 338 000 octets.
- Ne pas utiliser ce skill pour LUKS2, l'enclave RAM ou les partitions USB :
  utiliser `test-coffre-loopback`.

## Règles

- Données synthétiques uniquement, sous `/tmp/opencode`, avec `umask 077`.
- Ne pas éditer à la main les scans, index ou `index_meta.json`.
- Ne pas utiliser les exports CSV ou TXT globaux de Binary Eye.
- Comparer avec `cmp` ou le SHA-256, jamais avec un `diff` textuel.
- `--afficher` est réservé au test synthétique de non-fuite ; ne jamais le
  journaliser.
- Traiter `IDENTIQUE APRÈS NORMALISATION NBSP` comme un succès.

## Référence rapide

| Élément | Attendu |
|---|---|
| Découpage | `split -a 2 -b 500`, suffixes `aa` à `zz`, 676 morceaux max |
| En-tête QR | `LQR1 xx n/total\n` suivi des octets bruts du morceau |
| Métadonnées | `json/index_meta.json` : `sha256`, `sha256_sans_nbsp`, `total_chunks`, `record_count`, `line_ending`, `final_newline`, `quote_all` |
| Restauration exacte | `Résultat : IDENTIQUE` + `cmp` |
| Normalisation NBSP | `Résultat : IDENTIQUE APRÈS NORMALISATION NBSP` |
| Échec | `Résultat : DIFFÉRENT` : ne pas supprimer l'original |
| Permissions | scripts `700`, `LISEZMOI.txt` et index `600` |

## Procédure

### 1. Préflight

```bash
command -v split qrencode python3
python3 -c 'import weasyprint' 2>/dev/null && echo "PDF disponible" || echo "PDF facultatif"
umask 077
ROOT=/tmp/opencode/qr-tests-$(date +%s)
install -d -m 700 "$ROOT"
```

### 2. Générer les fixtures synthétiques

Le jeu couvre Bitwarden et KeePassXC, LF/CRLF, avec et sans saut de ligne
final, un champ multi-lignes et un cas NBSP.

```bash
python3 - "$ROOT" <<'PY'
import csv
import sys
from pathlib import Path

root = Path(sys.argv[1])
bw_header = ["folder", "favorite", "type", "name", "notes", "fields",
             "reprompt", "login_uri", "login_username", "login_password",
             "login_totp"]
kp_header = ["Group", "Title", "Username", "Password", "URL", "Notes"]
bw_rows = [
    ["Banque", "0", "login", "Banque exemple", "note simple", "", "0",
     "https://banque.example", "alice@example.com", "DEMO-BANQUE-001", ""],
    ["Web", "0", "login", "Portail exemple", "autre note", "", "0",
     "https://portail.example", "bob@example.com", "DEMO-WEB-002", ""],
]
kp_rows = [
    ["Banque", "Banque exemple", "alice@example.com", "DEMO-BANQUE-001",
     "https://banque.example", "note simple"],
    ["Web", "Portail exemple", "bob@example.com", "DEMO-WEB-002",
     "https://portail.example", "autre note"],
]

def write(path, header, rows, nl, final):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator=nl, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(rows)
    if not final:
        data = path.read_bytes()
        path.write_bytes(data[:-len(nl)])

for nl, tag in (("\n", "lf"), ("\r\n", "crlf")):
    for final, suffix in ((True, "final"), (False, "sans_final")):
        write(root / f"bitwarden_{tag}_{suffix}.csv", bw_header, bw_rows, nl, final)
        write(root / f"keepass_{tag}_{suffix}.csv", kp_header, kp_rows, nl, final)

with (root / "keepass_lf_edge.csv").open("w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow(kp_header)
    writer.writerow(["Divers", "Multi-ligne", "carol@example.com",
                     "DEMO-EDGE-003", "https://edge.example",
                     "ligne 1\nligne 2"])

with (root / "keepass_lf_nbsp.csv").open("w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow(kp_header)
    writer.writerow(["Web", "Portail NBSP", "bob@example.com",
                     "DEMO-NBSP-004", "https://portail.example",
                     "café\u00a0test"])
PY
```

### 3. Générer les sauvegardes

```bash
for csv in "$ROOT"/*.csv; do
  out="$ROOT/out_$(basename "$csv" .csv)"
  SANS_PLANCHES=1 ./creer_sauvegarde_qr.sh "$csv" "$out"
done
```

### 3 bis. Vérifier les planches PDF/HTML

Relancer une seule fixture sans `SANS_PLANCHES` si WeasyPrint est disponible.

```bash
OUT_PDF="$ROOT/out_pdf"
./creer_sauvegarde_qr.sh "$ROOT/bitwarden_lf_final.csv" "$OUT_PDF"
test -s "$OUT_PDF/pdf/planches_qr.pdf"
test -s "$OUT_PDF/pdf/planches_qr_grand.pdf"
test -s "$OUT_PDF/pdf/test_grand_8qr.pdf"
test -s "$OUT_PDF/html/planches_qr.html"
```

Si WeasyPrint est absent, vérifier au minimum les HTML et ignorer les PDF.

### 4. Vérifier les index et métadonnées

```bash
python3 - "$ROOT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for out in sorted(root.glob("out_*")):
    meta = json.loads((out / "json/index_meta.json").read_text(encoding="utf-8"))
    source = root / (out.name.removeprefix("out_") + ".csv")
    raw = source.read_bytes()
    assert meta["sha256"] == hashlib.sha256(raw).hexdigest()
    assert meta["size"] == len(raw)
    assert meta["total_chunks"] == (len(raw) + 499) // 500
print("index et métadonnées OK")
PY
```

### 5. Simuler l'export Binary Eye

```bash
for out in "$ROOT"/out_*; do
  python3 - "$out" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
meta = json.loads((root / "json/index_meta.json").read_text(encoding="utf-8"))
items = []
for n, part in enumerate(sorted((root / "morceaux").glob("morceau_??")), 1):
    suffix = part.name.split("_", 1)[1]
    payload = part.read_bytes().decode("utf-8")
    if "nbsp" in root.name:
        payload = payload.replace("\u00a0", " ")
    items.append({
        "content": f"LQR1 {suffix} {n}/{meta['total_chunks']}\n{payload}",
    })
(root / "scans/binary_eye_all_qr.json").write_text(
    json.dumps(items, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY
done
```

### 6. Restaurer et vérifier

```bash
for out in "$ROOT"/out_*; do
  log="$(cd "$out" && python3 scripts/restaurer_sauvegarde.py \
      --scans ./scans --sortie "$out/restauration.csv" 2>&1)"
  printf '%s\n' "$log"
  if [[ "$out" == *nbsp* ]]; then
    printf '%s\n' "$log" | grep -q 'IDENTIQUE APRÈS NORMALISATION NBSP'
  else
    printf '%s\n' "$log" | grep -q 'Résultat.*IDENTIQUE'
    source="$ROOT/$(basename "$out" | sed 's/^out_//').csv"
    cmp -s "$source" "$out/restauration.csv"
  fi
done
```

### 7. Extraction ciblée et non-fuite

```bash
OUT="$ROOT/out_bitwarden_lf_final"
msg="$(cd "$OUT" && python3 scripts/extraire_entree.py R001 \
  --scans ./scans --sortie "$OUT/entree_R001.csv" 2>&1)"
printf '%s\n' "$msg"
printf '%s' "$msg" | grep -q 'DEMO-BANQUE-001' && { echo "FUITE"; exit 1; }

msg_affiche="$(cd "$OUT" && python3 scripts/extraire_entree.py R001 \
  --scans ./scans --afficher 2>&1)"
printf '%s' "$msg_affiche" | grep -q 'DEMO-BANQUE-001'

(cd "$OUT" && python3 scripts/extraire_entree.py --nom "Banque exemple" \
  --scans ./scans --sortie "$OUT/entree_nom.csv")
grep -q 'DEMO-BANQUE-001' "$OUT/entree_nom.csv"
```

### 8. Tester les refus

```bash
: > "$ROOT/vide.csv"
if SANS_PLANCHES=1 ./creer_sauvegarde_qr.sh "$ROOT/vide.csv" "$ROOT/out_vide"; then
  echo "ÉCHEC : CSV vide accepté"
  exit 1
fi

python3 - "$ROOT/trop_gros.csv" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(b"A" * 338001)
PY
if SANS_PLANCHES=1 ./creer_sauvegarde_qr.sh "$ROOT/trop_gros.csv" "$ROOT/out_gros"; then
  echo "ÉCHEC : CSV trop gros accepté"
  exit 1
fi
```

### 9. Vérifier les permissions

```bash
stat -c '%a %n' \
  "$OUT/scripts/extraire_entree.py" \
  "$OUT/scripts/restaurer_sauvegarde.py" \
  "$OUT/LISEZMOI.txt" \
  "$OUT/json/index_meta.json"
```

Attendu : `700`, `700`, `600`, `600`.

### 10. Nettoyer

```bash
find "$ROOT" -type f -exec shred -u -z -n 1 -- {} +
rm -rf "$ROOT"
```

## Pièges et anti-patrons

- Utiliser un export réel ou un fichier hors de `/tmp/opencode`.
- Ne tester qu'un seul couple LF/final : la matrice CRLF/LF × final/sans final
  est obligatoire.
- Réécrire le CSV avant le calcul du SHA : perte de la restitution
  octet pour octet, notamment pour `QUOTE_ALL`.
- Éditer le faux JSON ou les scans à la main.
- Confondre `DIFFÉRENT` avec un succès partiel.
- Traiter la normalisation NBSP comme une corruption.
- Utiliser `--afficher` dans un log, un historique ou une sortie partagée.
- Utiliser `SANS_PLANCHES=1` puis exiger les PDF.
- Placer le dossier de sortie à l'intérieur de la sauvegarde testée.

## Vérification finale

```bash
python3 -m py_compile *.py
bash -n *.sh
```

Le skill est validé lorsque toutes les fixtures restaurent avec le statut
attendu, que les SHA-256 concordent, que l'extraction `R001` et `--nom`
fonctionne, qu'aucun secret n'apparaît sans `--afficher` et que les
permissions sont conformes.
