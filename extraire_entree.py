#!/usr/bin/env python3
"""
Extrait une entrée d'une sauvegarde QR.

Exemples :
    python3 extraire_entree.py R123 --scans ./scans
    python3 extraire_entree.py --nom example.com --scans ./scans

Le script accepte :
  - l'export JSON global de Binary Eye (binary_eye_all_qr.json), détecté
    automatiquement dans scans/ ;
  - les morceaux bruts (morceau_ec, morceau_ed, ...) ;
  - les exports texte de Binary Eye (binary_eye_morceau_ec.txt, ...).
Pour ignorer l'export global et lire les fichiers individuels, ajoute
--individuels.

Il ne contient aucun mot de passe et n'en affiche pas par défaut.
Le résultat est écrit dans entree_R123.csv (ou --sortie).
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
import sys
from pathlib import Path


# Champs de l'index utilisés pour reconnaître une entrée dans les scans.
CHAMPS_INDEX = [
    ("name", "nom"),
    ("folder", "dossier"),
    ("login_uri", "uri"),
    ("login_username", "identifiant"),
]


def charger_index(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def charger_meta(path: Path) -> dict:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def suffixe_vers_numero(sfx: str) -> int:
    return (ord(sfx[0]) - ord("a")) * 26 + (ord(sfx[1]) - ord("a")) + 1


def numero_vers_suffixe(n: int) -> str:
    n -= 1
    return chr(ord("a") + n // 26) + chr(ord("a") + n % 26)


def trouver_fichier(
    scan_dir: Path, morceau: str, mapping: dict[str, Path] | None = None
) -> Path:
    if mapping and morceau in mapping:
        return mapping[morceau]

    candidats = [
        scan_dir / morceau,                       # brut
        scan_dir / f"{morceau}.txt",              # texte
        scan_dir / f"binary_eye_{morceau}.txt",   # Binary Eye
        scan_dir / f"scan_{morceau}.txt",
    ]
    for p in candidats:
        if p.is_file():
            return p

    # Repli : fichier dont le nom contient le morceau, hors images/PDF.
    matches = sorted(
        p
        for p in scan_dir.glob(f"*{morceau}*")
        if p.is_file() and p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf"}
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        for p in matches:
            if "binary_eye" in p.name:
                return p
        return matches[0]
    raise FileNotFoundError(
        f"Fichier de scan introuvable pour {morceau} dans {scan_dir}"
    )


def candidats_depuis_texte(texte: str, retirer_separateur: bool = True) -> list[bytes]:
    """Reconstruit les octets possibles à partir du texte d'un QR.

    Binary Eye peut avoir décodé le QR soit en UTF-8 (octets valides), soit en
    Latin-1/CP1252 (octets non valides, par exemple un accent coupé entre deux
    morceaux). On produit les deux candidats ; l'extraction choisit celui qui
    redonne une ligne cohérente avec l'index.

    Les exports texte ajoutent un séparateur en fin d'enregistrement ; les
    exports JSON ne le font pas. `retirer_separateur` permet de distinguer les
    deux cas.
    """
    candidats: list[bytes] = []
    for encodage in ("latin-1", "cp1252", "utf-8"):
        try:
            brut = texte.encode(encodage)
        except UnicodeEncodeError:
            continue
        if retirer_separateur:
            if brut.endswith(b" \n"):
                brut = brut[:-2]
            elif brut.endswith(b"\n"):
                brut = brut[:-1]
        if brut not in candidats:
            candidats.append(brut)
    return candidats


def candidats_export_texte(path: Path) -> list[bytes]:
    """Retourne les reconstructions possibles des octets d'un export texte.

    Binary Eye normalise aussi les CRLF en LF et ajoute un séparateur en fin
    de fichier.
    """
    data = path.read_bytes()
    try:
        texte = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = data.decode("latin-1")
    return candidats_depuis_texte(texte, retirer_separateur=True)


def charger_export_json(path: Path) -> dict[str, list[bytes]]:
    """Charge un export JSON natif de Binary Eye.

    Le fichier contient une liste d'objets avec un champ `content` qui commence
    par la ligne `LQR1 xx n/total`. On renvoie un dictionnaire
    `morceau_xx -> candidats d'octets`, comme pour les scans individuels.
    """
    if path.suffix.lower() != ".json":
        raise SystemExit(
            f"Export non supporté : {path}\n"
            "Utilise l'export JSON global de Binary Eye. L'export CSV "
            "remplace les sauts de ligne par des espaces et ne permet pas "
            "une restauration fidèle."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Export JSON invalide : {path} ({exc})") from exc
    if not isinstance(data, list):
        raise SystemExit(f"Format d'export JSON inattendu : {path}")

    mapping: dict[str, list[bytes]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.startswith("LQR1 "):
            continue
        header, sep, reste = content.partition("\n")
        if not sep:
            # Export CSV : les sauts de ligne ont été remplacés par des espaces.
            continue
        morceau = header.split()[1]
        if not morceau.startswith("morceau_"):
            morceau = f"morceau_{morceau}"
        if len(morceau) != len("morceau_") + 2:
            continue
        mapping[morceau] = candidats_depuis_texte(reste, retirer_separateur=False)
    return mapping


def semble_traduit(data: bytes) -> bool:
    """Détecte un export qui a été traduit automatiquement (Google Lens, etc.).

    Un QR contient du CSV brut. Une traduction remplace les en-têtes anglais
    (« folder », « login »…) par du français et ajoute des espaces : les octets
    ne correspondent plus au CSV d'origine.
    """
    marqueurs = (
        b"dossier, favori",
        b"dossier,favori",
        b"URI de connexion",
        b"mot de passe de connexion",
        b"nom d'utilisateur de connexion",
        b",connexion,",
        b", connexion,",
    )
    return any(m in data for m in marqueurs)


def retirer_entete_lqr(data: bytes) -> tuple[str | None, bytes]:
    """Retire une éventuelle ligne 'LQR1 aa n/total'."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if not data.startswith(b"LQR1 "):
        return None, data
    fin = data.find(b"\n")
    if fin == -1:
        return None, data
    entete = data[:fin].decode("ascii", errors="replace").split()
    if len(entete) >= 2:
        nom = entete[1]
        if not nom.startswith("morceau_"):
            nom = f"morceau_{nom}"
        if len(nom) == len("morceau_") + 2:
            return nom, data[fin + 1 :]
    return None, data


def lire_morceau(path: Path) -> tuple[list[bytes], str, str | None]:
    """Retourne (candidats d'octets utiles, mode, nom du morceau).

    mode = 'brut' ou 'texte'. Le nom du morceau provient de l'en-tête LQR1
    s'il est présent. Un export texte peut avoir plusieurs candidats
    d'encodage (UTF-8 ou Latin-1/CP1252) ; un morceau brut n'en a qu'un.
    """
    if path.suffix.lower() == ".txt":
        bruts = candidats_export_texte(path)
        mode = "texte"
    else:
        bruts = [path.read_bytes()]
        mode = "brut"
    nom = None
    contenus = []
    for brut in bruts:
        nom_candidat, contenu = retirer_entete_lqr(brut)
        if nom is None and nom_candidat:
            nom = nom_candidat
        contenus.append(contenu)
    return contenus, mode, nom


def indexer_scans(scan_dir: Path) -> dict[str, Path]:
    """Repère les scans par leur en-tête LQR1, même si le fichier est mal nommé."""
    mapping: dict[str, Path] = {}
    suffixes_ignores = {
        ".png", ".jpg", ".jpeg", ".pdf", ".csv", ".json", ".html", ".htm",
        ".py", ".sh", ".md",
    }
    for p in sorted(scan_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() in suffixes_ignores:
            continue
        try:
            if p.stat().st_size > 10_000_000:
                continue
            _, _, nom = lire_morceau(p)
        except Exception:
            continue
        if nom and nom not in mapping:
            mapping[nom] = p
    return mapping


def choisir_cible(index: list[dict], args) -> dict:
    base = index
    if args.id:
        base = [
            r for r in base if r["record_id"].upper() == args.id.upper()
        ]

    rows = base
    if args.nom:
        rows = [
            r for r in base if r["nom"].casefold() == args.nom.casefold()
        ]
        # Si le nom exact n'a rien donné, on tente une recherche partielle.
        if not rows:
            rows = [
                r
                for r in base
                if args.nom.casefold() in r["nom"].casefold()
            ]

    if not rows:
        raise SystemExit(
            "Aucune entrée trouvée. Essaie --nom avec une partie du nom, "
            "ou vérifie l'index."
        )

    if len(rows) > 1:
        print("Plusieurs entrées correspondent. Précise avec --id :", file=sys.stderr)
        print(
            f"{'ID':<6} {'Nom':<32} {'Dossier':<14} {'Identifiant':<28} Morceaux",
            file=sys.stderr,
        )
        for r in rows:
            print(
                f"{r['record_id']:<6} {r['nom'][:32]:<32} "
                f"{r['dossier'][:14]:<14} {r['identifiant'][:28]:<28} "
                f"{r['morceaux']}",
                file=sys.stderr,
            )
        raise SystemExit(2)

    return rows[0]


def charger_tailles_morceaux(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {r["morceau"]: int(r["taille_octets"]) for r in csv.DictReader(f)}


def extraire_par_offsets(
    data: bytes, cible: dict, meta: dict, header: list[str]
) -> list[str] | None:
    chunk_size = int(meta.get("chunk_size", 500))
    sfx = cible["morceau_debut"].split("_")[1]
    premier = suffixe_vers_numero(sfx)
    base = (premier - 1) * chunk_size
    debut = int(cible["debut_octet"])
    fin = int(cible["fin_octet_exclue"])
    extrait = data[debut - base : fin - base]
    try:
        rows = list(csv.reader(io.StringIO(extrait.decode("utf-8"))))
    except UnicodeDecodeError:
        return None
    if len(rows) != 1 or len(rows[0]) != len(header):
        return None

    # Vérifie que la ligne correspond bien aux métadonnées de l'index.
    idx = {name: i for i, name in enumerate(header)}
    for champ, cle in CHAMPS_INDEX:
        if champ in idx and rows[0][idx[champ]] != cible.get(cle, ""):
            return None
    return rows[0]


def extraire_par_recherche(
    data: bytes, cible: dict, header: list[str]
) -> list[list[str]] | None:
    try:
        texte = data.decode("utf-8")
    except UnicodeDecodeError:
        # Ce candidat d'encodage n'est pas le bon ; l'appelant essaiera le
        # suivant (UTF-8 ou Latin-1/CP1252).
        return None

    idx = {name: i for i, name in enumerate(header)}
    attendu = {}
    for champ, cle in CHAMPS_INDEX:
        if champ in idx:
            attendu[champ] = (idx[champ], cible.get(cle, ""))

    candidats: set[tuple[str, ...]] = set()

    # On essaie chaque début de ligne comme point de resynchronisation :
    # la zone scannée peut commencer au milieu d'un enregistrement.
    debuts = [0] + [i + 1 for i, ch in enumerate(texte) if ch == "\n"]
    for start in debuts:
        try:
            reader = csv.reader(io.StringIO(texte[start:]))
            for row in reader:
                if len(row) != len(header):
                    continue
                if all(row[pos] == valeur for pos, valeur in attendu.values()):
                    candidats.add(tuple(row))
        except csv.Error:
            continue

    return [list(row) for row in candidats]


def ecrire_sortie(
    out_path: Path,
    header: list[str],
    row: list[str],
    cible: dict,
    meta: dict,
) -> int:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerow(row)
    out_path.chmod(0o600)

    # Longueur de la ligne seule, hors en-tête.
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator="\r\n").writerow(row)
    ligne = buf.getvalue().encode("utf-8")

    # Le dernier enregistrement du CSV n'a pas de CRLF final.
    total = int(meta.get("size", 0))
    if total and int(cible["fin_octet_exclue"]) == total and ligne.endswith(b"\r\n"):
        ligne = ligne[:-2]
    return len(ligne)


def trouver_racine() -> Path:
    """Trouve la racine du dataset, qu'on lance le script depuis la racine
    ou depuis le sous-dossier scripts/."""
    candidats = []
    for base in (
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
    ):
        if base not in candidats:
            candidats.append(base)
    for base in candidats:
        if (base / "csv" / "index_enregistrements.csv").exists():
            return base
        if (base / "index_enregistrements.csv").exists():
            return base
    return Path.cwd()


def premier_existant(racine: Path, *chemins: str) -> Path:
    for rel in chemins:
        p = racine / rel
        if p.exists():
            return p
    return racine / chemins[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrait une entrée d'une sauvegarde QR à partir des scans."
    )
    parser.add_argument("record_id", nargs="?", help="identifiant R… (ex. R123)")
    parser.add_argument("--id", dest="id", help="identifiant R… (alternative)")
    parser.add_argument("--nom", help="nom exact ou partiel de l'entrée")
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
        "--index",
        default=None,
        help="index des enregistrements (détection automatique)",
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
        help="fichier CSV de sortie (défaut : entree_Rxxx.csv)",
    )
    parser.add_argument(
        "--afficher",
        action="store_true",
        help="affiche aussi la ligne extraite, mot de passe compris",
    )
    args = parser.parse_args()

    if args.id and args.record_id and args.id.upper() != args.record_id.upper():
        raise SystemExit("--id et l'argument positionnel sont différents.")
    args.id = args.id or args.record_id

    if not args.id and not args.nom:
        parser.error("Indique un identifiant (R123) ou --nom.")

    racine = trouver_racine()
    if args.scans is None:
        scans = racine / "scans"
        args.scans = str(scans if scans.is_dir() else racine)
    if args.index is None:
        args.index = str(
            premier_existant(
                racine,
                "csv/index_enregistrements.csv",
                "index_enregistrements.csv",
            )
        )
    if args.morceaux is None:
        args.morceaux = str(
            premier_existant(
                racine,
                "csv/index_morceaux.csv",
                "index_morceaux.csv",
            )
        )
    if args.meta is None:
        args.meta = str(
            premier_existant(
                racine,
                "json/index_meta.json",
                "index_meta.json",
            )
        )

    index_path = Path(args.index)
    if not index_path.exists():
        raise SystemExit(f"Index introuvable : {index_path}")
    index = charger_index(index_path)
    meta = charger_meta(Path(args.meta))
    header = meta.get("header")
    if not header:
        raise SystemExit(
            f"En-tête CSV introuvable dans {args.meta}. "
            "Garde index_meta.json avec l'index, ou fournis un index complet."
        )

    cible = choisir_cible(index, args)
    morceaux = cible["morceaux"].split()
    scan_dir = Path(args.scans)
    if not scan_dir.is_dir():
        raise SystemExit(f"Dossier de scans introuvable : {scan_dir}")

    export_path: Path | None = None
    mapping_export: dict[str, list[bytes]] | None = None
    if not args.individuels:
        if args.export:
            export_path = Path(args.export)
            if not export_path.is_file():
                raise SystemExit(f"Export introuvable : {export_path}")
            mapping_export = charger_export_json(export_path)
        else:
            auto = scan_dir / "binary_eye_all_qr.json"
            if auto.is_file():
                export_path = auto
                mapping_export = charger_export_json(auto)

    tailles = charger_tailles_morceaux(Path(args.morceaux))
    mapping = indexer_scans(scan_dir) if mapping_export is None else {}
    candidats_par_morceau: list[list[bytes]] = []
    modes: list[str] = []
    fichiers: list[Path] = []
    traduits: list[Path] = []
    for morceau in morceaux:
        if mapping_export is not None:
            candidats = mapping_export.get(morceau)
            if not candidats:
                raise SystemExit(
                    f"Le morceau {morceau} est absent de l'export {export_path}."
                )
            mode = "texte"
            nom_entete = morceau
            source = export_path
        else:
            source = trouver_fichier(scan_dir, morceau, mapping)
            candidats, mode, nom_entete = lire_morceau(source)
            if nom_entete and nom_entete != morceau:
                raise SystemExit(
                    f"Le fichier {source} contient l'en-tête {nom_entete}, "
                    f"mais le morceau attendu est {morceau}."
                )
        if any(semble_traduit(c) for c in candidats):
            traduits.append(source)
        candidats_par_morceau.append(candidats)
        modes.append(mode)
        if mapping_export is None:
            fichiers.append(source)

    if mapping_export is not None:
        fichiers = [export_path]

    if traduits:
        liste = ", ".join(str(p) for p in traduits)
        raise SystemExit(
            "Ces scans semblent avoir été traduits en français : "
            f"{liste}\n"
            "Le QR contient du CSV brut ; une traduction automatique casse "
            "les en-têtes et les valeurs.\n"
            "Réexporte les scans avec Binary Eye, sans traduction, puis relance."
        )

    total_attendu = sum(
        tailles.get(m, int(meta.get("chunk_size", 500))) for m in morceaux
    )

    lignes: list[list[str]] | None = None
    methode = "recherche par nom"
    for combinaison in itertools.product(*candidats_par_morceau):
        data = b"".join(combinaison)
        if len(data) == total_attendu and "texte" not in modes:
            ligne = extraire_par_offsets(data, cible, meta, header)
            if ligne is not None:
                lignes = [ligne]
                methode = "offsets"
                break
        candidats = extraire_par_recherche(data, cible, header)
        if candidats:
            lignes = candidats
            methode = "recherche par nom"
            break

    if lignes is None:
        raise SystemExit(
            "Entrée introuvable dans les scans. "
            "Vérifie que les morceaux indiqués sont bien présents et complets. "
            "Si le scan contient des accents, essaie un export en octets bruts."
        )

    if len(lignes) > 1:
        print(
            f"{len(lignes)} lignes correspondent aux métadonnées de "
            f"{cible['record_id']}. Elles seront écrites séparément.",
            file=sys.stderr,
        )

    if args.sortie:
        sorties = [Path(args.sortie)]
        if len(lignes) > 1:
            base = sorties[0]
            sorties = [
                base.with_name(f"{base.stem}_{i + 1}{base.suffix}")
                for i in range(len(lignes))
            ]
    else:
        base = Path(f"entree_{cible['record_id']}.csv")
        sorties = (
            [base]
            if len(lignes) == 1
            else [
                base.with_name(f"{base.stem}_{i + 1}{base.suffix}")
                for i in range(len(lignes))
            ]
        )

    longueurs = []
    for path, row in zip(sorties, lignes):
        longueurs.append(ecrire_sortie(path, header, row, cible, meta))

    print(f"Entrée        : {cible['record_id']} — {cible['nom']}")
    print(f"Morceaux lus  : {', '.join(morceaux)}")
    print(f"Fichiers      : {', '.join(str(p) for p in fichiers)}")
    print(f"Méthode       : {methode}")
    print(
        f"Ligne         : {longueurs[0]} octets "
        f"(attendu {cible['longueur_octets']})"
    )
    for path in sorties:
        print(f"Écrit         : {path}")
    print("Mot de passe non affiché. Utilise --afficher pour l'afficher.")
    if args.afficher:
        print()
        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(header)
        for row in lignes:
            writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
