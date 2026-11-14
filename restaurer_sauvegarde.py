#!/usr/bin/env python3
"""
Restaure le CSV complet à partir des scans et vérifie son SHA-256.

Exemple, depuis la racine d'une sauvegarde :

    python3 scripts/restaurer_sauvegarde.py --scans ./scans

Le script :
- utilise scans/binary_eye_all_qr.json s'il est présent, ou --export ;
- sinon, lit les fichiers individuels (ou --individuels) ;
- lit l'ordre et la taille des morceaux dans csv/index_morceaux.csv ;
- lit la taille, le SHA-256 et le nombre d'enregistrements dans
  json/index_meta.json ;
- reconnaît les scans par leur en-tête LQR1, quel que soit leur nom ;
- essaie les encodages UTF-8 et Latin-1/CP1252 de Binary Eye ;
- reconstruit le CSV, essaie les fins de ligne CRLF et LF, puis compare le
  SHA-256 exact et le SHA-256 sans NBSP (normalisation connue de Binary Eye).

Il ne faut pas modifier les scans entre-temps : le SHA-256 est calculé sur
l'export d'origine, octet pour octet.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

# Le script est livré dans scripts/, à côté de extraire_entree.py.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

sys.dont_write_bytecode = True
import extraire_entree as ee  # noqa: E402


def charger_morceaux(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: int(r["numero"]))
    return rows


def est_prefixe_utf8(data: bytes) -> bool:
    """Vrai si data est un début valide d'UTF-8 (fin incomplète acceptée)."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(data, final=False)
    except UnicodeDecodeError:
        return False
    return True


def reconstruire_csv(data: bytes) -> tuple[bytes, list[list[str]]]:
    """Reconstruit le CSV avec des fins de ligne CRLF."""
    texte = data.decode("utf-8")
    rows = list(csv.reader(io.StringIO(texte)))
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerows(rows)
    resultat = buf.getvalue().encode("utf-8")
    return resultat, rows


def variantes_fins_de_ligne(data: bytes) -> list[bytes]:
    """Renvoie les variantes CRLF/LF, avec ou sans fin de ligne finale."""
    variantes = [data]
    if data.endswith(b"\r\n"):
        variantes.append(data[:-2])
    return variantes + [v.replace(b"\r\n", b"\n") for v in variantes]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restaure le CSV complet depuis les scans et vérifie le SHA-256."
    )
    parser.add_argument(
        "--scans",
        default=None,
        help="dossier des scans (défaut : ./scans si présent, sinon .)",
    )
    parser.add_argument(
        "--export",
        default=None,
        help="export JSON global de Binary Eye (détection automatique)",
    )
    parser.add_argument(
        "--individuels",
        action="store_true",
        help="ignorer l'export global et lire les fichiers individuels",
    )
    parser.add_argument(
        "--morceaux",
        default=None,
        help="index des morceaux (détection automatique)",
    )
    parser.add_argument(
        "--meta",
        default=None,
        help="métadonnées de la sauvegarde (détection automatique)",
    )
    parser.add_argument(
        "--sortie",
        default="restauration.csv",
        help="CSV restauré (défaut : restauration.csv)",
    )
    args = parser.parse_args()

    racine = ee.trouver_racine()
    if args.scans is None:
        scans = racine / "scans"
        args.scans = str(scans if scans.is_dir() else racine)
    if args.morceaux is None:
        args.morceaux = str(
            ee.premier_existant(
                racine,
                "csv/index_morceaux.csv",
                "index_morceaux.csv",
            )
        )
    if args.meta is None:
        args.meta = str(
            ee.premier_existant(
                racine,
                "json/index_meta.json",
                "index_meta.json",
            )
        )

    scan_dir = Path(args.scans)
    if not scan_dir.is_dir():
        raise SystemExit(f"Dossier de scans introuvable : {scan_dir}")

    morceaux = charger_morceaux(Path(args.morceaux))
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    sha_attendu = meta.get("sha256")
    sha_sans_nbsp_attendu = meta.get("sha256_sans_nbsp")
    taille_attendue = int(meta.get("size", 0))
    taille_sans_nbsp = int(meta.get("size_sans_nbsp", taille_attendue))
    nb_attendu = int(meta.get("record_count", 0))

    export_path: Path | None = None
    mapping_export: dict[str, list[bytes]] | None = None
    if not args.individuels:
        if args.export:
            export_path = Path(args.export)
            if not export_path.is_file():
                raise SystemExit(f"Export introuvable : {export_path}")
            mapping_export = ee.charger_export_json(export_path)
        else:
            auto = scan_dir / "binary_eye_all_qr.json"
            if auto.is_file():
                export_path = auto
                mapping_export = ee.charger_export_json(auto)

    mapping = ee.indexer_scans(scan_dir) if mapping_export is None else {}
    candidats_par_morceau: list[list[bytes]] = []
    manquants: list[str] = []
    traduits: list[str] = []

    for row in morceaux:
        nom = row["morceau"]
        if mapping_export is not None:
            candidats = mapping_export.get(nom)
            if not candidats:
                manquants.append(nom)
                continue
            source = export_path
        else:
            try:
                source = ee.trouver_fichier(scan_dir, nom, mapping)
            except (FileNotFoundError, SystemExit):
                manquants.append(nom)
                continue
            candidats, _mode, nom_entete = ee.lire_morceau(source)
            if nom_entete and nom_entete != nom:
                raise SystemExit(
                    f"Le fichier {source} contient l'en-tête {nom_entete}, "
                    f"mais le morceau attendu est {nom}."
                )
        if any(ee.semble_traduit(c) for c in candidats):
            traduits.append(str(source))
        candidats_par_morceau.append(candidats)

    if manquants:
        apercu = ", ".join(manquants[:12])
        if len(manquants) > 12:
            apercu += f", … ({len(manquants)} au total)"
        raise SystemExit(f"{len(manquants)} morceau(x) manquant(s) : {apercu}")
    if traduits:
        raise SystemExit(
            "Ces scans semblent avoir été traduits en français : "
            + ", ".join(traduits)
            + "\nRéexporte-les avec Binary Eye, sans traduction."
        )

    # On garde toutes les combinaisons d'encodage qui restent un préfixe
    # UTF-8 valide. En pratique il y en a très peu : la plupart des morceaux
    # sont ASCII, et les deux encodages ne diffèrent que sur les accents.
    etats: list[tuple[bytes, list[bytes]]] = [(b"", [])]
    for i, candidats in enumerate(candidats_par_morceau):
        nouveaux: list[tuple[bytes, list[bytes]]] = []
        for prefixe, choix in etats:
            for cand in candidats:
                data = prefixe + cand
                if est_prefixe_utf8(data):
                    nouveaux.append((data, choix + [cand]))
        vus: set[bytes] = set()
        etats = []
        for data, choix in nouveaux:
            if data not in vus:
                vus.add(data)
                etats.append((data, choix))
        if not etats:
            raise SystemExit(
                f"Aucun encodage valide pour le morceau "
                f"{morceaux[i]['morceau']}."
            )

    resultats = []
    for data, _choix in etats:
        try:
            avec_final, rows = reconstruire_csv(data)
        except (UnicodeDecodeError, csv.Error):
            continue
        # L'export d'origine peut utiliser CRLF ou LF, avec ou sans retour à la
        # ligne après le dernier champ. On essaie toutes les variantes.
        for restaure in variantes_fins_de_ligne(avec_final):
            digest = hashlib.sha256(restaure).hexdigest()
            digest_sans_nbsp = hashlib.sha256(
                restaure.replace(b"\xc2\xa0", b" ")
            ).hexdigest()
            exact = digest == sha_attendu
            normalise = bool(sha_sans_nbsp_attendu) and (
                digest_sans_nbsp == sha_sans_nbsp_attendu
            )
            resultats.append(
                (
                    exact,
                    normalise,
                    digest,
                    digest_sans_nbsp,
                    len(restaure),
                    rows,
                    restaure,
                )
            )

    if not resultats:
        raise SystemExit("Impossible de reconstruire un CSV valide depuis les scans.")

    # Priorité au SHA-256 exact, puis à la normalisation NBSP connue de
    # Binary Eye, puis au bon nombre de lignes.
    resultats.sort(
        key=lambda r: (r[0], r[1], len(r[5]) == nb_attendu + 1),
        reverse=True,
    )
    exact, normalise, digest, digest_sans_nbsp, taille, rows, restaure = resultats[0]

    sortie = Path(args.sortie)
    sortie.write_bytes(restaure)
    sortie.chmod(0o600)

    if export_path is not None:
        print(f"Source           : {export_path}")
    print(f"Morceaux lus     : {len(morceaux)}/{len(morceaux)}")
    print(f"Taille restaurée : {taille:,} octets (attendu {taille_attendue:,})")
    print(f"Enregistrements  : {len(rows) - 1} (+ en-tête, attendu {nb_attendu})")
    if exact:
        print(f"SHA-256          : {digest}")
        print(f"SHA-256 attendu  : {sha_attendu}")
        print("Résultat         : IDENTIQUE")
    elif normalise:
        nb_nbsp = max(0, taille_attendue - taille)
        print(f"SHA-256 restauré : {digest}")
        print(f"SHA-256 attendu  : {sha_attendu} (exact)")
        print(f"SHA-256 sans NBSP: {digest_sans_nbsp}")
        print(f"attendu sans NBSP: {sha_sans_nbsp_attendu}")
        print(f"Taille sans NBSP : {taille:,} octets (attendu {taille_sans_nbsp:,})")
        print("Résultat         : IDENTIQUE APRÈS NORMALISATION NBSP")
        print(
            f"Détail           : {nb_nbsp} espace(s) insécable(s) (U+00A0) "
            "normalisé(s) en espace(s) par Binary Eye."
        )
    else:
        print(f"SHA-256          : {digest}")
        print(f"SHA-256 attendu  : {sha_attendu}")
        print("Résultat         : DIFFÉRENT")
        print(f"Écrit            : {sortie}")
        print(
            "\nLe CSV a été écrit pour inspection, mais il ne correspond pas "
            "à l'original. Vérifie les scans manquants ou incomplets.",
            file=sys.stderr,
        )
        return 1
    print(f"Écrit            : {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
