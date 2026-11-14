#!/usr/bin/env bash
#
# Crée une sauvegarde QR complète et organisée à partir d'un export CSV.
#
# Usage :
#   ./creer_sauvegarde_qr.sh export.csv [dossier_sortie]
#
# Arborescence produite :
#   csv/        index_enregistrements.csv, index_morceaux.csv, etiquettes_qr.csv/.txt
#   json/       index_meta.json
#   morceaux/   morceaux texte du CSV
#   qrcodes/    QR PNG individuels
#   pdf/        planches_qr.pdf, planches_qr_grand.pdf, test_grand_8qr.pdf, index_qr.pdf
#   html/       versions HTML des index
#   scripts/    extraire_entree.py, restaurer_sauvegarde.py
#   scans/      dossier vide pour déposer les scans
#   LISEZMOI.txt

set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage : $0 export.csv [dossier_sortie]" >&2
  exit 1
fi

CSV="$1"
if [[ ! -f "$CSV" ]]; then
  echo "Fichier CSV introuvable : $CSV" >&2
  exit 1
fi
CSV="$(readlink -f -- "$CSV")"
BASE="$(basename -- "$CSV" .csv)"
OUT="${2:-sauvegarde_qr_${BASE}_$(date +%Y%m%d_%H%M%S)}"

for cmd in split qrencode python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Commande requise absente : $cmd" >&2
    exit 1
  fi
done

CSV_SIZE="$(stat -c %s -- "$CSV")"
if (( CSV_SIZE == 0 )); then
  echo "Erreur : le CSV est vide." >&2
  exit 1
fi
if (( CSV_SIZE > 676 * 500 )); then
  echo "Erreur : CSV trop volumineux ($CSV_SIZE octets > maximum 338000 octets / 676 QR)." >&2
  exit 1
fi
EXPECTED_CHUNKS=$(( (CSV_SIZE + 499) / 500 ))

mkdir -p "$OUT"/{csv,json,morceaux,qrcodes,pdf,html,scripts,scans}
OUT="$(cd "$OUT" && pwd)"

echo "Création de la sauvegarde QR"
echo "  source : $CSV"
echo "  sortie : $OUT"
echo

# 1. Découpage en morceaux de 500 octets. -a 2 garantit les suffixes aa à zz
#    et évite le passage silencieux de GNU split à trois lettres.
split -a 2 -b 500 -- "$CSV" "$OUT/morceaux/morceau_"

# 2. Génération des QR (uniquement les morceaux texte, pas les .png).
#    Chaque QR commence par une ligne d'identification :
#        LQR1 aa 1/100
#    Elle permet de reconnaître le morceau même si le scanner renomme le fichier.
shopt -s nullglob
MORCEAUX=("$OUT"/morceaux/morceau_??)
shopt -u nullglob
TOTAL=${#MORCEAUX[@]}
if (( TOTAL != EXPECTED_CHUNKS )); then
  echo "Erreur : $TOTAL morceaux générés, $EXPECTED_CHUNKS attendus." >&2
  exit 1
fi
n=1
for f in "${MORCEAUX[@]}"; do
  name="$(basename -- "$f")"
  sfx="${name#morceau_}"
  tmp="$OUT/qrcodes/$name.qrpayload"
  printf 'LQR1 %s %d/%d\n' "$sfx" "$n" "$TOTAL" > "$tmp"
  cat "$f" >> "$tmp"
  qrencode -s 16 -d 600 -o "$OUT/qrcodes/$name.png" < "$tmp"
  shred -u -z -n 1 -- "$tmp" 2>/dev/null || rm -f -- "$tmp"
  n=$((n + 1))
done

shopt -s nullglob
QR_PNG=("$OUT"/qrcodes/morceau_??.png)
shopt -u nullglob
if (( ${#QR_PNG[@]} != TOTAL )); then
  echo "Erreur : ${#QR_PNG[@]} PNG générés, $TOTAL attendus." >&2
  exit 1
fi

# 3. Index de récupération.
python3 -B "$SCRIPT_DIR/generer_index_qr.py" "$CSV" \
  --chunk-size 500 \
  --qr-header \
  --organise \
  --out-dir "$OUT"

# 4. Planches A4 prêtes à imprimer.
if [[ "${SANS_PLANCHES:-0}" != "1" ]]; then
  # Format compact : 20 QR par page.
  python3 -B "$SCRIPT_DIR/generer_planches_qr.py" \
    --qr-dir "$OUT/qrcodes" \
    --labels "$OUT/csv/etiquettes_qr.csv" \
    --meta "$OUT/json/index_meta.json" \
    --out "$OUT/pdf/planches_qr.pdf" \
    --html "$OUT/html/planches_qr.html"

  # Format confort : 12 QR par page, modules plus grands.
  python3 -B "$SCRIPT_DIR/generer_planches_qr.py" \
    --qr-dir "$OUT/qrcodes" \
    --labels "$OUT/csv/etiquettes_qr.csv" \
    --meta "$OUT/json/index_meta.json" \
    --out "$OUT/pdf/planches_qr_grand.pdf" \
    --html "$OUT/html/planches_qr_grand.html" \
    --cols 3 --rows 4 --qr-mm 54

  # Une page de test avec les 8 premiers QR en grand.
  python3 -B "$SCRIPT_DIR/generer_planches_qr.py" \
    --qr-dir "$OUT/qrcodes" \
    --labels "$OUT/csv/etiquettes_qr.csv" \
    --meta "$OUT/json/index_meta.json" \
    --out "$OUT/pdf/test_grand_8qr.pdf" \
    --html "$OUT/html/test_grand_8qr.html" \
    --cols 3 --rows 4 --qr-mm 54 --limit 8

  if [[ ! -f "$OUT/pdf/planches_qr.pdf" || ! -f "$OUT/pdf/planches_qr_grand.pdf" ]]; then
    echo "WeasyPrint absent : les PDF de planches ne sont pas générés, les HTML le sont." >&2
  fi
fi

# 5. Scripts de récupération autonomes.
cp "$SCRIPT_DIR/extraire_entree.py" "$OUT/scripts/extraire_entree.py"
cp "$SCRIPT_DIR/restaurer_sauvegarde.py" "$OUT/scripts/restaurer_sauvegarde.py"

cat > "$OUT/scans/LISEZMOI.txt" <<'EOF'
Dépose ici l'export JSON global de Binary Eye.

Nom attendu : binary_eye_all_qr.json
Les scripts le détectent automatiquement et retrouvent chaque morceau grâce à
la ligne « LQR1 aa 1/100 ».

C'est le seul format utilisé pour la sauvegarde. Les exports CSV et TXT de
Binary Eye ne sont pas conservés. Les scans traduits automatiquement sont
refusés.
EOF

PAGES_COMPACT=$(( (TOTAL + 19) / 20 ))
PAGES_GRAND=$(( (TOTAL + 11) / 12 ))

cat > "$OUT/LISEZMOI.txt" <<EOF
Sauvegarde QR — $BASE
============================================================

FORMAT SOURCE
-------------
Export CSV Bitwarden, KeePassXC ou colonnes génériques.
Limite : 338 000 octets, soit 676 morceaux de 500 octets maximum.

ARBORESCENCE
------------
csv/        index_enregistrements.csv, index_morceaux.csv, etiquettes_qr.csv/.txt
json/       index_meta.json
morceaux/   morceaux texte du CSV (500 octets)
qrcodes/    QR PNG individuels (16 px/module, 600 dpi)
pdf/        planches_qr.pdf, planches_qr_grand.pdf, test_grand_8qr.pdf, index_qr.pdf
html/       versions HTML des index
scripts/    extraire_entree.py, restaurer_sauvegarde.py
scans/      dépose ici les scans ou l'export JSON global

IMPRESSION
----------
Deux formats de planches sont fournis :

  pdf/planches_qr.pdf        compact : 4×5 QR par page, $PAGES_COMPACT pages, QR 38 mm
  pdf/planches_qr_grand.pdf  confort : 3×4 QR par page, $PAGES_GRAND pages, QR 54 mm
  pdf/test_grand_8qr.pdf     test    : 8 premiers QR en 54 mm, 1 page

Si les PDF sont absents (WeasyPrint non installé), les versions HTML sont
disponibles dans html/ et restent imprimables depuis un navigateur.

1. Imprimer d'abord pdf/test_grand_8qr.pdf à 100 % (sans « ajuster à la page »),
   en 600 dpi si possible, et scanner les 8 QR avec Binary Eye.
2. Si le test est bon, imprimer le format choisi, puis pdf/index_qr.pdf.
3. Ne pas utiliser la traduction automatique du lecteur : le script refuse les
   scans traduits, car le QR contient du CSV brut et une traduction le rend
   illisible.
4. Papier mat 80–100 g et imprimante laser de préférence ; éviter le papier
   brillant (reflets) et vérifier que l'impression est à l'échelle 100 %.

RÉCUPÉRATION
------------
Depuis la racine de ce dossier :

    python3 scripts/extraire_entree.py R123 --scans ./scans
    python3 scripts/extraire_entree.py --nom example.com --scans ./scans

--nom cherche dans le nom de l'entrée (name/Title), pas dans l'URL.

Le script utilise scans/binary_eye_all_qr.json.
Les QR commencent par « LQR1 xx n/total » : le script retire cette ligne et
retrouve chaque morceau.

Options de secours : --export FICHIER impose un autre export JSON ;
--sortie FICHIER choisit le CSV de sortie ; --individuels lit les fichiers
individuels (morceaux bruts ou exports texte) au lieu de l'export global.
Options avancées : --index, --morceaux et --meta forcent les chemins des
index.

Il n'affiche pas le mot de passe par défaut ; ajoute --afficher si tu veux le
voir dans le terminal.

RESTAURATION COMPLÈTE
---------------------
Après avoir scanné les $TOTAL QR et exporté l'historique Binary Eye en JSON
dans scans/binary_eye_all_qr.json :

    python3 scripts/restaurer_sauvegarde.py --scans ./scans

Le script reconstitue le CSV complet, vérifie le SHA-256 et écrit
restauration.csv. Il doit afficher « Résultat : IDENTIQUE » avant de supprimer
le CSV d'origine.

Options de secours : --export FICHIER, --individuels, --sortie FICHIER,
--morceaux FICHIER et --meta FICHIER.

Binary Eye normalise les espaces insécables (U+00A0) en espaces simples dans
ses exports. Le script affiche alors « IDENTIQUE APRÈS NORMALISATION NBSP » :
c'est normal, seuls ces caractères de présentation changent, pas les mots de
passe.

Tout autre résultat, notamment « DIFFÉRENT », est un échec : ne supprime pas
le CSV d'origine et corrige les scans avant de recommencer.

FORMAT D'EXPORT BINARY EYE
--------------------------
JSON global uniquement : binary_eye_all_qr.json.
Les exports CSV et TXT de Binary Eye ne sont pas utilisés.

INTERFACE WEB LOCALE (OPTIONNELLE)
----------------------------------
Depuis le dossier racine du dépôt qrcode, une interface guidée peut ouvrir ce
dossier de sauvegarde sans écrire sur le disque :

    ./lancer_interface.sh

Elle écoute uniquement sur 127.0.0.1:5100 et affiche une URL avec un jeton
changeant à chaque lancement. Elle permet de générer une sauvegarde, d'importer
les scans Binary Eye, de rechercher une entrée, de télécharger une extraction
ou de restaurer le CSV. Les secrets restent masqués jusqu'à un clic explicite.
L'interface n'exécute jamais sudo et ne remplace pas le flux coffre USB pour
les secrets critiques. Si le bureau monte automatiquement une clé, l'assistant
USB peut démonter sa partition avec udisksctl, sans privilèges ; sinon il
affiche la commande exacte à copier dans un terminal. Les opérations de
sauvegarde, consultation et restauration ne demandent aucune confirmation
matérielle. L'initialisation destructive exige le nom, le chemin complet ou
le numéro de série du disque, avec un bouton d'insertion assistée.

SÉCURITÉ
--------
Les QR codes contiennent le CSV en clair, mots de passe compris.
Un QR code n'est pas un chiffrement.
Conserve les planches et l'index dans un coffre.
Ne supprime le CSV et les fichiers numériques qu'après un test de restauration.
EOF

# Tous les fichiers contiennent des secrets ou des métadonnées.
find "$OUT" -type d -exec chmod 700 {} +
find "$OUT" -type d -exec chmod g-s {} +
find "$OUT" -type f -exec chmod 600 {} +
chmod 700 "$OUT/scripts/extraire_entree.py" "$OUT/scripts/restaurer_sauvegarde.py"

echo
echo "Sauvegarde créée : $OUT"
echo "  QR          : $(find "$OUT/qrcodes" -maxdepth 1 -name 'morceau_??.png' | wc -l)"
if [[ "${SANS_PLANCHES:-0}" == "1" ]]; then
  echo "  Planches    : non générées (SANS_PLANCHES=1)"
elif [[ -f "$OUT/pdf/planches_qr.pdf" ]]; then
  echo "  Planches    : $OUT/pdf/planches_qr.pdf (compact)"
  echo "                $OUT/pdf/planches_qr_grand.pdf (confort)"
  echo "  Test        : $OUT/pdf/test_grand_8qr.pdf"
else
  echo "  Planches    : PDF non générés (WeasyPrint absent), HTML disponible"
fi
if [[ -f "$OUT/pdf/index_qr.pdf" ]]; then
  echo "  Index       : $OUT/pdf/index_qr.pdf"
else
  echo "  Index       : PDF non généré (WeasyPrint absent), HTML disponible"
fi
echo "  Récupération: cd $OUT && python3 scripts/extraire_entree.py R123 --scans ./scans"
echo "  Restauration: cd $OUT && python3 scripts/restaurer_sauvegarde.py --scans ./scans"
echo
echo "Pense à tester une impression et une restauration avant de supprimer le CSV."
