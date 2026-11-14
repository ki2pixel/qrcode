#!/usr/bin/env python3
"""
Génère un PDF de planches A4 avec les QR codes et leurs étiquettes.

Exemple :
    python3 generer_planches_qr.py \
        --qr-dir sauvegarde_qr \
        --labels sauvegarde_qr/etiquettes_qr.csv \
        --meta sauvegarde_qr/index_meta.json \
        --out sauvegarde_qr/planches_qr.pdf
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
from pathlib import Path

try:
    from weasyprint import HTML
except ImportError:  # pragma: no cover
    HTML = None


def e(value) -> str:
    return html.escape(str(value), quote=True)


def charger_etiquettes(path: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            labels[row["morceau"]] = (
                row.get("libelle_court") or row.get("libelle") or row["morceau"]
            )
    return labels


def tri_morceau(path: Path):
    sfx = path.stem.split("_", 1)[-1]
    return (len(sfx), sfx)


def construire_html(
    qr_files: list[Path],
    labels: dict[str, str],
    meta: dict,
    cols: int,
    rows: int,
    qr_mm: int,
    html_dir: Path,
) -> tuple[str, int]:
    per_page = cols * rows
    pages = [qr_files[i : i + per_page] for i in range(0, len(qr_files), per_page)]
    source = meta.get("source", "—")

    pages_html = []
    for page_no, page_items in enumerate(pages, 1):
        first = page_items[0].stem.replace("morceau_", "")
        last = page_items[-1].stem.replace("morceau_", "")
        trs = []
        for r in range(rows):
            tds = []
            for c in range(cols):
                idx = r * cols + c
                if idx < len(page_items):
                    qr = page_items[idx]
                    label = labels.get(qr.stem, qr.stem)
                    try:
                        src = Path(os.path.relpath(qr.resolve(), html_dir)).as_posix()
                    except ValueError:
                        src = qr.resolve().as_uri()
                    tds.append(
                        "<td>"
                        f'<img src="{e(src)}" alt="{e(qr.stem)}">'
                        f'<div class="label">{e(label)}</div>'
                        "</td>"
                    )
                else:
                    tds.append("<td></td>")
            trs.append("<tr>" + "".join(tds) + "</tr>")

        pages_html.append(
            '<section class="page">'
            f'<div class="header">Sauvegarde QR — planche {page_no}/{len(pages)} '
            f"— morceaux {e(first)} à {e(last)}</div>"
            f'<table class="grid">{"".join(trs)}</table>'
            f'<div class="footer">Source : {e(source)} · index de recherche : '
            f"index_qr.pdf · {page_no}/{len(pages)}</div>"
            "</section>"
        )

    html_text = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Planches QR — {e(source)}</title>
<style>
  @page {{
    size: A4;
    margin: 6mm 8mm 8mm 8mm;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "DejaVu Sans", sans-serif;
    font-size: 8pt;
    color: #111;
  }}
  .page {{
    break-after: page;
  }}
  .page:last-child {{
    break-after: auto;
  }}
  .header {{
    font-size: 8pt;
    font-weight: 700;
    margin: 0 0 2mm 0;
  }}
  table.grid {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }}
  table.grid td {{
    width: {100 / cols:.4f}%;
    text-align: center;
    vertical-align: top;
    padding: 1mm;
  }}
  img {{
    width: {qr_mm}mm;
    height: {qr_mm}mm;
    display: block;
    margin: 0 auto;
  }}
  .label {{
    font-size: 6pt;
    line-height: 1.12;
    margin-top: 1mm;
    height: 10mm;
    overflow: hidden;
  }}
  .footer {{
    font-size: 6.5pt;
    color: #666;
    margin-top: 1mm;
    text-align: center;
  }}
</style>
</head>
<body>
{''.join(pages_html)}
</body>
</html>
"""
    return html_text, len(pages)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Génère les planches A4 de QR codes avec étiquettes."
    )
    parser.add_argument("--qr-dir", default=".", help="dossier des morceau_*.png")
    parser.add_argument(
        "--labels",
        default="etiquettes_qr.csv",
        help="CSV des étiquettes (défaut : etiquettes_qr.csv)",
    )
    parser.add_argument(
        "--meta",
        default="index_meta.json",
        help="métadonnées de la sauvegarde (défaut : index_meta.json)",
    )
    parser.add_argument(
        "--out",
        default="planches_qr.pdf",
        help="PDF de sortie (défaut : planches_qr.pdf)",
    )
    parser.add_argument(
        "--html",
        default="planches_qr.html",
        help="HTML intermédiaire (défaut : planches_qr.html)",
    )
    parser.add_argument("--cols", type=int, default=4, help="colonnes par page")
    parser.add_argument("--rows", type=int, default=5, help="lignes par page")
    parser.add_argument("--qr-mm", type=int, default=38, help="taille du QR en mm")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="ne générer que les N premiers QR (0 = tous)",
    )
    args = parser.parse_args()

    qr_dir = Path(args.qr_dir)
    qr_files = sorted(qr_dir.glob("morceau_*.png"), key=tri_morceau)
    if not qr_files:
        raise SystemExit(f"Aucun QR morceau_*.png dans {qr_dir}")
    if args.limit > 0:
        qr_files = qr_files[: args.limit]

    labels_path = Path(args.labels)
    if not labels_path.exists():
        raise SystemExit(f"Fichier d'étiquettes introuvable : {labels_path}")
    labels = charger_etiquettes(labels_path)

    meta_path = Path(args.meta)
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    html_path = Path(args.html)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_dir = html_path.resolve().parent
    html_text, page_count = construire_html(
        qr_files, labels, meta, args.cols, args.rows, args.qr_mm, html_dir
    )
    html_path.write_text(html_text, encoding="utf-8")
    html_path.chmod(0o600)

    if HTML is None:
        print(
            "WeasyPrint absent : PDF non généré, HTML conservé.",
            file=sys.stderr,
        )
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_text, base_url=str(html_dir)).write_pdf(out_path)
    out_path.chmod(0o600)

    print(f"QR codes    : {len(qr_files)}")
    print(f"Planches    : {page_count} pages A4 ({args.cols}×{args.rows})")
    print(f"PDF         : {out_path} ({out_path.stat().st_size:,} octets)")
    print(f"HTML        : {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())