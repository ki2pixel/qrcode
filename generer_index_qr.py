#!/usr/bin/env python3
"""
Génère un index de récupération pour un CSV découpé en morceaux de taille fixe
puis encodé en QR codes.

Exemple, pour générer uniquement l'index :
    python3 generer_index_qr.py export.csv

Pour créer la sauvegarde complète (découpage, QR, planches, index) :
    ./creer_sauvegarde_qr.sh export.csv

Sorties dans le dossier courant :
    index_enregistrements.csv
    index_morceaux.csv
    etiquettes_qr.csv
    etiquettes_qr.txt
    index_qr.html
    index_qr.pdf

L'index ne contient que des métadonnées (nom, dossier, URL, identifiant) :
aucun mot de passe, aucune note, aucun champ TOTP.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from weasyprint import HTML
except ImportError:  # pragma: no cover
    HTML = None


ALIASES_CHAMPS = {
    "nom": ("name", "Title", "title", "nom"),
    "dossier": ("folder", "Group", "group", "dossier"),
    "uri": ("login_uri", "URL", "url", "uri"),
    "identifiant": ("login_username", "Username", "username", "identifiant"),
}


def decouper_lignes_csv(texte: str) -> list[str]:
    """Découpe uniquement sur CRLF, LF ou CR, jamais sur U+2028/U+0085."""
    lignes: list[str] = []
    debut = 0
    i = 0
    while i < len(texte):
        if texte[i] == "\r":
            if i + 1 < len(texte) and texte[i + 1] == "\n":
                i += 2
            else:
                i += 1
            lignes.append(texte[debut:i])
            debut = i
        elif texte[i] == "\n":
            i += 1
            lignes.append(texte[debut:i])
            debut = i
        else:
            i += 1
    if debut < len(texte):
        lignes.append(texte[debut:])
    return lignes


def suffixe_morceau(n: int) -> str:
    """1 -> aa, 26 -> az, 27 -> ba, ... (même nommage que split)."""
    if n < 1 or n > 26 * 26:
        raise ValueError(f"numéro de morceau hors limites : {n}")
    n -= 1
    return chr(ord("a") + n // 26) + chr(ord("a") + n % 26)


def nom_morceau(n: int) -> str:
    return f"morceau_{suffixe_morceau(n)}"


def charger_enregistrements(csv_path: Path):
    raw = csv_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Le fichier n'est pas de l'UTF-8 valide : {exc}") from exc

    lines = decouper_lignes_csv(text)
    if "".join(lines).encode("utf-8") != raw:
        raise SystemExit(
            "Le découpage en lignes ne préserve pas les octets du fichier. "
            "Vérifie les fins de ligne."
        )

    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line.encode("utf-8"))
    offsets.append(len(raw))

    # Le BOM reste dans les offsets d'octets mais doit être retiré avant le
    # parseur CSV, sinon la première colonne n'est pas reconnue.
    lignes_csv = list(lines)
    if text.startswith("\ufeff") and lignes_csv:
        lignes_csv[0] = lignes_csv[0][1:]
    reader = csv.reader(lignes_csv)
    rows: list[tuple[int, int, list[str]]] = []
    prev = 0
    for row in reader:
        consumed = reader.line_num
        rows.append((offsets[prev], offsets[consumed], row))
        prev = consumed

    if prev != len(lines):
        raise SystemExit("Toutes les lignes n'ont pas été consommées par le parseur CSV.")
    if not rows:
        raise SystemExit("Le fichier CSV est vide.")

    header = rows[0][2]
    header[0] = header[0].lstrip("\ufeff")
    records = []
    for i, (start, end, row) in enumerate(rows[1:], 1):
        records.append({"id": f"R{i:03d}", "start": start, "end": end, "row": row})
    return raw, header, records


def indice_champ(header: list[str], champ: str) -> int | None:
    """Trouve une colonne par alias, sans tenir compte de la casse."""
    alias = ALIASES_CHAMPS.get(champ, ())
    normalises = [(v.lstrip("\ufeff").strip(), i) for i, v in enumerate(header)]
    for nom in alias:
        for valeur, i in normalises:
            if valeur == nom:
                return i
    alias_cf = {nom.casefold() for nom in alias}
    for valeur, i in normalises:
        if valeur.casefold() in alias_cf:
            return i
    return None


def champ(row: list[str], header: list[str], name: str) -> str:
    idx = indice_champ(header, name)
    if idx is None:
        return ""
    return row[idx] if idx < len(row) else ""


def detecter_fin_de_ligne(texte: str) -> str:
    """Retourne crlf ou lf selon le premier terminateur rencontré."""
    for i, char in enumerate(texte):
        if char == "\n":
            return "crlf" if i > 0 and texte[i - 1] == "\r" else "lf"
        if char == "\r":
            return "crlf" if i + 1 < len(texte) and texte[i + 1] == "\n" else "lf"
    return "lf"


def tronquer(value: str, max_len: int = 60) -> str:
    value = " ".join(value.split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def dossier_court(value: str) -> str:
    """Abrège les dossiers courants pour l'index imprimé."""
    if not value:
        return "—"
    if "KeePassXC" in value:
        return "KeePassXC"
    if value.startswith("Racine/Mots de passe"):
        return "Mdp"
    return tronquer(value, 18)


def construire_index(raw: bytes, header: list[str], records: list[dict], chunk_size: int):
    total_chunks = (len(raw) + chunk_size - 1) // chunk_size
    if total_chunks < 1:
        raise SystemExit("Le fichier CSV est vide.")
    if total_chunks > 26 * 26:
        raise SystemExit(
            f"CSV trop volumineux : {total_chunks} morceaux pour un maximum "
            "de 676 (suffixes aa à zz)."
        )

    for rec in records:
        start, end = rec["start"], rec["end"]
        rec["name"] = champ(rec["row"], header, "nom")
        rec["folder"] = champ(rec["row"], header, "dossier")
        rec["uri"] = champ(rec["row"], header, "uri")
        rec["username"] = champ(rec["row"], header, "identifiant")
        rec["first"] = start // chunk_size + 1
        rec["last"] = (end - 1) // chunk_size + 1
        rec["first_nom"] = nom_morceau(rec["first"])
        rec["last_nom"] = nom_morceau(rec["last"])
        rec["chunks"] = list(range(rec["first"], rec["last"] + 1))
        rec["chunks_noms"] = [nom_morceau(n) for n in rec["chunks"]]
        rec["chunks_court"] = (
            suffixe_morceau(rec["first"])
            if rec["first"] == rec["last"]
            else f"{suffixe_morceau(rec['first'])}–{suffixe_morceau(rec['last'])}"
        )

    chunks = []
    for n in range(1, total_chunks + 1):
        debut = (n - 1) * chunk_size
        fin_exclue = min(n * chunk_size, len(raw))
        starts = [r for r in records if r["first"] == n]
        overlaps = [r for r in records if r["first"] <= n <= r["last"]]

        if starts:
            premier = starts[0]["name"]
            dernier = starts[-1]["name"]
            plage = f'"{tronquer(premier, 40)}" → "{tronquer(dernier, 40)}"'
        elif overlaps:
            premier = overlaps[0]["name"]
            dernier = ""
            plage = f'suite de "{tronquer(premier, 40)}"'
        else:
            premier = dernier = ""
            plage = "—"

        if starts:
            compte = f"{len(starts)} entrée(s)"
            suites = len(overlaps) - len(starts)
            if suites:
                compte += f" (+{suites} suite(s))"
        else:
            compte = f"{len(overlaps)} entrée(s) à cheval"

        chunks.append(
            {
                "n": n,
                "nom": nom_morceau(n),
                "debut": debut,
                "fin": fin_exclue,
                "starts": starts,
                "overlaps": overlaps,
                "premier": premier,
                "dernier": dernier,
                "plage": plage,
                "compte": compte,
                "libelle": f"{nom_morceau(n)} · {n}/{total_chunks} · {compte} · {plage}",
                "libelle_court": f"{nom_morceau(n)} · {n}/{total_chunks} · {plage}",
            }
        )

    return total_chunks, chunks


def ecrire_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def e(value) -> str:
    return html.escape(str(value), quote=True)


def generer_html(
    csv_path: Path,
    raw: bytes,
    header: list[str],
    records: list[dict],
    chunks: list[dict],
    total_chunks: int,
    chunk_size: int,
    qr_header: bool = False,
    organise: bool = False,
) -> str:
    sha = hashlib.sha256(raw).hexdigest()
    date = datetime.now().strftime("%d/%m/%Y à %H:%M")
    header_txt = ",".join(header)
    format_qr = (
        "LQR1 — chaque QR commence par « LQR1 aa 1/100 » (suffixe du morceau)"
        if qr_header
        else "brut — le QR contient directement le morceau"
    )
    p_index_csv = (
        "csv/index_enregistrements.csv" if organise else "index_enregistrements.csv"
    )
    p_script = "scripts/extraire_entree.py" if organise else "extraire_entree.py"

    record_rows = []
    for rec in records:
        record_rows.append(
            "<tr>"
            f"<td class=\"id\">{e(rec['id'])}</td>"
            f"<td class=\"nom\">{e(tronquer(rec['name'], 48) or '—')}</td>"
            f"<td>{e(dossier_court(rec['folder']))}</td>"
            f"<td>{e(rec['username'] or '—')}</td>"
            f"<td class=\"morceaux\">{e(rec['chunks_court'])}</td>"
            f"<td class=\"octets\">{rec['start']}–{rec['end']}</td>"
            "</tr>"
        )

    chunk_rows = []
    for c in chunks:
        if c["starts"]:
            premier = tronquer(c["premier"], 32)
            dernier = tronquer(c["dernier"], 32)
        elif c["overlaps"]:
            premier = f"suite de « {tronquer(c['premier'], 28)} »"
            dernier = "—"
        else:
            premier = dernier = "—"
        chunk_rows.append(
            "<tr>"
            f"<td class=\"mono\">{e(c['nom'])}</td>"
            f"<td class=\"num\">{c['n']}</td>"
            f"<td class=\"mono\">{c['debut']}–{c['fin']}</td>"
            f"<td class=\"num\">{len(c['starts'])}</td>"
            f"<td class=\"num\">{len(c['overlaps'])}</td>"
            f"<td>{e(premier or '—')}</td>"
            f"<td>{e(dernier or '—')}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Index de sauvegarde QR — {e(csv_path.name)}</title>
<style>
  @page {{
    size: A4;
    margin: 13mm 12mm 15mm 12mm;
    @bottom-center {{
      content: "Index QR — page " counter(page) " / " counter(pages);
      font-family: "DejaVu Sans", sans-serif;
      font-size: 7pt;
      color: #666;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "DejaVu Sans", sans-serif;
    font-size: 9pt;
    line-height: 1.35;
    color: #111;
    margin: 0;
  }}
  h1 {{ font-size: 21pt; margin: 0 0 2mm 0; line-height: 1.15; }}
  h2 {{ font-size: 13pt; margin: 6mm 0 2mm 0; border-bottom: 0.3mm solid #999; padding-bottom: 1mm; }}
  h3 {{ font-size: 10pt; margin: 4mm 0 1.5mm 0; }}
  p {{ margin: 1.5mm 0; }}
  code, .mono {{ font-family: "DejaVu Sans Mono", monospace; font-size: 8pt; }}
  .subtitle {{ font-size: 10pt; color: #444; margin-bottom: 6mm; }}
  .couverture {{ break-after: page; }}
  .avertissement {{
    border: 0.4mm solid #a33;
    background: #fdf3f2;
    padding: 3mm 4mm;
    margin: 4mm 0 6mm 0;
    font-size: 8.5pt;
  }}
  .avertissement strong {{ color: #8b1a1a; }}
  .meta {{ width: 100%; border-collapse: collapse; margin: 3mm 0 2mm 0; font-size: 8.5pt; }}
  .meta td {{ padding: 1.2mm 2mm; border-bottom: 0.2mm solid #ddd; vertical-align: top; }}
  .meta td:first-child {{ width: 42mm; color: #555; }}
  .hash {{ word-break: break-all; font-size: 7.5pt; }}
  .section {{ break-before: page; }}
  .note {{ font-size: 8pt; color: #444; margin: 2mm 0 3mm 0; }}
  table.index {{
    width: 100%;
    border-collapse: collapse;
    font-size: 6.8pt;
    line-height: 1.12;
  }}
  table.index thead {{ display: table-header-group; }}
  table.index th {{
    background: #e9e9e9;
    border: 0.2mm solid #999;
    padding: 0.7mm 1mm;
    text-align: left;
    font-size: 6.8pt;
  }}
  table.index td {{
    border: 0.2mm solid #bbb;
    padding: 0.32mm 1mm;
    vertical-align: top;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  table.index tbody tr:nth-child(even) {{ background: #f7f7f7; }}
  table.index tr {{ break-inside: avoid; }}
  td.num {{ text-align: right; white-space: nowrap; }}
  td.id, td.morceaux, td.octets {{ white-space: nowrap; }}
  td.nom {{ font-weight: 600; }}
  .legende {{ font-size: 7.5pt; color: #444; margin-top: 2mm; }}
  .petit {{ font-size: 7.5pt; color: #444; }}
  ol, ul {{ margin: 1.5mm 0 1.5mm 5mm; padding: 0; }}
  li {{ margin: 0.8mm 0; }}
  .exemple {{
    background: #f4f4f4;
    border-left: 1mm solid #999;
    padding: 2mm 3mm;
    margin: 2mm 0;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 7.5pt;
    white-space: pre-wrap;
  }}
</style>
</head>
<body>

<section class="couverture">
  <h1>Index de sauvegarde QR</h1>
  <div class="subtitle">
    Récupération ciblée d’un portefeuille de mots de passe<br>
    Source : <span class="mono">{e(csv_path.name)}</span> — index généré le {e(date)}
  </div>

  <div class="avertissement">
    <strong>Confidentialité.</strong> Les QR codes contiennent le CSV en clair,
    mots de passe compris. Un QR code n’est pas un chiffrement.<br>
    <strong>Cet index ne contient aucun mot de passe</strong>, mais il contient des
    noms de services, dossiers, URL et identifiants. Conservez l’index et les QR
    dans un coffre, et ne les laissez pas traîner.<br>
    <strong>Ne supprimez le CSV et les PNG qu’après un test de restauration complet.</strong>
  </div>

  <table class="meta">
    <tr><td>Fichier source</td><td class="mono">{e(csv_path.name)}</td></tr>
    <tr><td>Taille</td><td>{len(raw):,} octets</td></tr>
    <tr><td>Enregistrements</td><td>{len(records)}</td></tr>
    <tr><td>Morceaux / QR</td><td>{total_chunks} morceaux de {chunk_size} octets (le dernier peut être plus court)</td></tr>
    <tr><td>Format QR</td><td>{e(format_qr)}</td></tr>
    <tr><td>SHA-256 du CSV</td><td class="hash mono">{e(sha)}</td></tr>
    <tr><td>En-tête CSV</td><td class="mono">{e(header_txt)}</td></tr>
  </table>

  <h2>Mode d’emploi</h2>
  <ol>
    <li>Repérez le compte dans <strong>l’index par nom</strong>. Notez son numéro
        <span class="mono">R…</span>, ses morceaux et ses offsets.</li>
    <li>Scannez les QR des morceaux indiqués, dans l’ordre, avec un décodeur qui
        préserve les octets. N’utilisez pas une application qui ajoute un retour
        à la ligne après chaque scan. Si le QR commence par une ligne
        <span class="mono">LQR1 aa 1/100</span>, ignorez-la : c’est un
        identifiant de morceau. <span class="mono">{e(p_script)}</span> le
        retire automatiquement.</li>
    <li>Concaténez les contenus sans séparateur :
        <span class="mono">data = b"".join(contenus)</span>.</li>
    <li>L’enregistrement se trouve dans
        <span class="mono">data[debut - base : fin - base]</span>, avec
        <span class="mono">base = (premier_numero - 1) × {chunk_size}</span>.
        Les offsets du CSV sont exprimés dans le fichier complet, avec
        <span class="mono">fin</span> exclusive.</li>
    <li>Préfixez l’en-tête CSV et parsez avec un outil CSV. Certains champs
        contiennent des retours à la ligne : <span class="mono">grep</span> et
        <span class="mono">awk</span> ne sont pas fiables.</li>
  </ol>

  <div class="exemple">base = (premier_numero - 1) * {chunk_size}
extrait = data[debut - base : fin - base]

# avec l'en-tête imprimé ci-dessus :
# csv = header + "\n" + extrait.decode("utf-8")
# puis lecture avec csv.reader / csv.DictReader</div>

  <h3>Vérification</h3>
  <p class="petit">
    Après réassemblage complet des {total_chunks} morceaux, le SHA-256 doit être
    identique à celui de la page de garde. Si un scanner en mode texte a normalisé
    les fins de ligne, parsez puis réécrivez le CSV avec les mêmes fins de ligne
    que l’original (CRLF ou LF) avant de comparer (voir le piège Binary Eye
    ci-dessous). Pour une récupération partielle,
    vérifiez au minimum que l’enregistrement extrait a le bon nombre de colonnes
    et que le nom correspond.
  </p>

  <h3>Trois pièges connus de cet export</h3>
  <ul class="petit">
    <li><strong>UTF-8 coupé :</strong> un caractère accentué peut être à cheval
        entre deux morceaux. Scannez les octets bruts ; un scanner qui convertit
        chaque morceau en texte peut remplacer ce caractère.</li>
    <li><strong>Retours à la ligne dans les champs :</strong> un enregistrement
        peut occuper plusieurs lignes physiques. Utilisez un parseur CSV, pas une
        extraction ligne par ligne.</li>
    <li><strong>Scanners en mode texte (ex. Binary Eye) :</strong> l’export peut
        convertir les CRLF en LF et ajouter <span class="mono">" \\n"</span> à la fin
        de chaque scan. Retirez ce suffixe avant de concaténer. Les offsets en octets
        ne s’appliquent alors plus directement : parsez le CSV et recherchez l’entrée
        par son nom, ou utilisez un export en octets bruts. Si le texte contient des
        caractères non-ASCII, il peut s’agir d’octets réinterprétés en Latin-1 puis
        réencodés en UTF-8 : pour retrouver les octets bruts, utilisez
        <span class="mono">texte.encode("latin-1")</span> (repli
        <span class="mono">cp1252</span>).</li>
  </ul>
</section>

<section class="section">
  <h2>Index par morceau ({total_chunks} morceaux)</h2>
  <p class="note">
    Chaque morceau correspond à un QR code. « Entrées » = nombre d’enregistrements
    qui <em>commencent</em> dans ce morceau. « Chevauche » inclut les enregistrements
    commencés dans un morceau précédent. Les noms sont les bornes alphabétiques.
  </p>
  <table class="index">
    <colgroup>
      <col style="width:14%"><col style="width:6%"><col style="width:14%">
      <col style="width:8%"><col style="width:9%"><col style="width:24.5%"><col style="width:24.5%">
    </colgroup>
    <thead>
      <tr>
        <th>Morceau</th><th>N°</th><th>Octets [début, fin[</th>
        <th>Entrées</th><th>Chevauche</th><th>Premier nom</th><th>Dernier nom</th>
      </tr>
    </thead>
    <tbody>
      {''.join(chunk_rows)}
    </tbody>
  </table>
  <p class="legende">
    Le nom du morceau correspond au fichier <span class="mono">morceau_XX.png</span>.
    Les suffixes sont ceux de <span class="mono">split</span> : aa, ab, …, az, ba, …
  </p>
</section>

<section class="section">
  <h2>Index par nom ({len(records)} enregistrements)</h2>
  <p class="note">
    Trié par nom, comme le CSV. « Morceaux » donne le suffixe du ou des QR à scanner.
    « Octets » est l’intervalle <span class="mono">[début, fin[</span> dans le fichier
    complet : par exemple <span class="mono">0–124</span> correspond aux octets 0 à 123.
  </p>
  <table class="index">
    <colgroup>
      <col style="width:6%"><col style="width:30%"><col style="width:11%">
      <col style="width:19%"><col style="width:14%"><col style="width:20%">
    </colgroup>
    <thead>
      <tr>
        <th>#</th><th>Nom</th><th>Dossier</th><th>Identifiant</th>
        <th>Morceaux</th><th>Octets [début, fin[</th>
      </tr>
    </thead>
    <tbody>
      {''.join(record_rows)}
    </tbody>
  </table>
  <p class="legende">
    Les valeurs longues sont tronquées à l’affichage ; les valeurs complètes
    (URL, dossier, identifiant) sont dans
    <span class="mono">{e(p_index_csv)}</span>.
    <span class="mono">Mdp</span> = dossier « Racine/Mots de passe ».
    Les doublons exacts sont distingués par le numéro <span class="mono">R…</span> ;
    au besoin, scannez les deux entrées.
  </p>
</section>

</body>
</html>
"""


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Génère un index de récupération pour un CSV découpé en morceaux QR."
    )
    parser.add_argument(
        "csv",
        nargs="?",
        default="export.csv",
        help="chemin du CSV d'origine (défaut : export.csv)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="taille des morceaux utilisée avec split -b (défaut : 500)",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="dossier de sortie (défaut : dossier courant)",
    )
    parser.add_argument(
        "--qr-header",
        action="store_true",
        help="indique que les QR commencent par une ligne LQR1 aa 1/100",
    )
    parser.add_argument(
        "--organise",
        action="store_true",
        help="indique que les fichiers seront rangés dans csv/, json/, pdf/, etc.",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"Fichier introuvable : {csv_path}")
    if args.chunk_size <= 0:
        raise SystemExit("--chunk-size doit être positif.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.organise:
        csv_dir = out_dir / "csv"
        json_dir = out_dir / "json"
        pdf_dir = out_dir / "pdf"
        html_dir = out_dir / "html"
        for d in (csv_dir, json_dir, pdf_dir, html_dir):
            d.mkdir(parents=True, exist_ok=True)
    else:
        csv_dir = json_dir = pdf_dir = html_dir = out_dir

    raw, header, records = charger_enregistrements(csv_path)
    if not any(
        indice_champ(header, champ) is not None for champ in ALIASES_CHAMPS
    ):
        raise SystemExit(
            "Aucune colonne d'identification reconnue. Formats pris en charge : "
            "Bitwarden, KeePassXC ou colonnes génériques."
        )
    total_chunks, chunks = construire_index(raw, header, records, args.chunk_size)

    # 1) Index machine-readable par enregistrement.
    record_rows = []
    for rec in records:
        record_rows.append(
            {
                "record_id": rec["id"],
                "nom": rec["name"],
                "dossier": rec["folder"],
                "uri": rec["uri"],
                "identifiant": rec["username"],
                "debut_octet": rec["start"],
                "fin_octet_exclue": rec["end"],
                "longueur_octets": rec["end"] - rec["start"],
                "morceau_debut": rec["first_nom"],
                "morceau_fin": rec["last_nom"],
                "morceaux": " ".join(rec["chunks_noms"]),
            }
        )
    ecrire_csv(
        csv_dir / "index_enregistrements.csv",
        [
            "record_id",
            "nom",
            "dossier",
            "uri",
            "identifiant",
            "debut_octet",
            "fin_octet_exclue",
            "longueur_octets",
            "morceau_debut",
            "morceau_fin",
            "morceaux",
        ],
        record_rows,
    )

    # 2) Index par morceau.
    chunk_rows = []
    for c in chunks:
        chunk_rows.append(
            {
                "morceau": c["nom"],
                "numero": c["n"],
                "total": total_chunks,
                "debut_octet": c["debut"],
                "fin_octet_exclue": c["fin"],
                "taille_octets": c["fin"] - c["debut"],
                "nb_entrees_debut": len(c["starts"]),
                "nb_entrees_chevauchantes": len(c["overlaps"]),
                "premier_nom": c["premier"],
                "dernier_nom": c["dernier"],
                "ids_debut": " ".join(r["id"] for r in c["starts"]),
                "ids_chevauchants": " ".join(r["id"] for r in c["overlaps"]),
                "libelle": c["libelle"],
            }
        )
    ecrire_csv(
        csv_dir / "index_morceaux.csv",
        [
            "morceau",
            "numero",
            "total",
            "debut_octet",
            "fin_octet_exclue",
            "taille_octets",
            "nb_entrees_debut",
            "nb_entrees_chevauchantes",
            "premier_nom",
            "dernier_nom",
            "ids_debut",
            "ids_chevauchants",
            "libelle",
        ],
        chunk_rows,
    )

    # 3) Étiquettes à imprimer sous les QR.
    etiquettes = [
        {
            "morceau": c["nom"],
            "numero": c["n"],
            "total": total_chunks,
            "libelle": c["libelle"],
            "libelle_court": c["libelle_court"],
        }
        for c in chunks
    ]
    ecrire_csv(
        csv_dir / "etiquettes_qr.csv",
        ["morceau", "numero", "total", "libelle", "libelle_court"],
        etiquettes,
    )
    with (csv_dir / "etiquettes_qr.txt").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(c["libelle_court"] + "\n")

    # 4) Métadonnées utiles au script d'extraction.
    meta = {
        "source": csv_path.name,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        # Binary Eye normalise les espaces insécables en espaces simples dans
        # ses exports JSON/CSV/TXT. Cette empreinte permet de vérifier une
        # restauration malgré cette normalisation.
        "sha256_sans_nbsp": hashlib.sha256(
            raw.replace(b"\xc2\xa0", b" ")
        ).hexdigest(),
        "size_sans_nbsp": len(raw.replace(b"\xc2\xa0", b" ")),
        "chunk_size": args.chunk_size,
        "total_chunks": total_chunks,
        "record_count": len(records),
        "header": header,
        "line_ending": detecter_fin_de_ligne(
            raw.decode("utf-8", errors="replace")
        ),
        "final_newline": raw.endswith((b"\r\n", b"\n", b"\r")),
        # Permet de restituer une ligne au format QUOTE_ALL (KeePassXC) lors
        # d'une extraction ciblée, sans réécrire le CSV complet.
        "quote_all": (
            raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        ).startswith(b'"'),
        "qr_header": "LQR1" if args.qr_header else None,
        "layout": "organise" if args.organise else "plat",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tool": "generer_index_qr.py",
    }
    (json_dir / "index_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 5) Index imprimable.
    html_text = generer_html(
        csv_path,
        raw,
        header,
        records,
        chunks,
        total_chunks,
        args.chunk_size,
        qr_header=args.qr_header,
        organise=args.organise,
    )
    (html_dir / "index_qr.html").write_text(html_text, encoding="utf-8")

    pdf_path = pdf_dir / "index_qr.pdf"
    if HTML is not None:
        HTML(string=html_text, base_url=str(html_dir.resolve())).write_pdf(pdf_path)
    else:
        print("WeasyPrint absent : index_qr.pdf non généré.", file=sys.stderr)

    # 6) Vérification : chaque enregistrement doit se reconstruire exactement.
    mismatches = 0
    for rec in records:
        extrait = raw[rec["start"] : rec["end"]]
        parsed = list(csv.reader([extrait.decode("utf-8")]))
        if len(parsed) != 1 or parsed[0] != rec["row"]:
            mismatches += 1
    if mismatches:
        print(
            f"ATTENTION : {mismatches} enregistrement(s) ne se reconstruisent pas exactement.",
            file=sys.stderr,
        )
        return 2

    print(f"CSV        : {csv_path} ({len(raw):,} octets)")
    print(f"Enregistrements : {len(records)}")
    print(f"Morceaux   : {total_chunks} × {args.chunk_size} octets")
    print(f"SHA-256    : {hashlib.sha256(raw).hexdigest()}")
    print(
        f"Vérification : {len(records)}/{len(records)} enregistrements "
        "reconstruits exactement."
    )
    print()
    outputs = (
        csv_dir / "index_enregistrements.csv",
        csv_dir / "index_morceaux.csv",
        csv_dir / "etiquettes_qr.csv",
        csv_dir / "etiquettes_qr.txt",
        json_dir / "index_meta.json",
        html_dir / "index_qr.html",
        pdf_dir / "index_qr.pdf",
    )
    for path in outputs:
        if path.exists():
            path.chmod(0o600)
            print(f"  {path} ({path.stat().st_size:,} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
