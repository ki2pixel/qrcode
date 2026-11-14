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
import codecs
import csv
import io
import json
import os
import re
import sys
from pathlib import Path


# Correspondance entre les champs internes de l'index et les noms de colonnes
# utilisés par les gestionnaires de mots de passe et les exports génériques.
ALIASES_CHAMPS = {
    "nom": ("name", "Title", "title", "nom"),
    "dossier": ("folder", "Group", "group", "dossier"),
    "uri": ("login_uri", "URL", "url", "uri"),
    "identifiant": ("login_username", "Username", "username", "identifiant"),
}

# Champs de l'index utilisés pour reconnaître une entrée dans les scans.
CHAMPS_INDEX = [
    ("nom", ALIASES_CHAMPS["nom"]),
    ("dossier", ALIASES_CHAMPS["dossier"]),
    ("uri", ALIASES_CHAMPS["uri"]),
    ("identifiant", ALIASES_CHAMPS["identifiant"]),
]

# Borne volontaire de la recherche multi-encodages. Elle évite l'explosion
# combinatoire historique de type 2^n tout en gardant les chemins les plus
# plausibles (taille attendue, UTF-8, candidat réparé).
MAX_ETATS = 64


def _cp1252_raw_handler(exc):
    """Replie les points de code C1 non définis sur leur octet Latin-1."""
    if isinstance(exc, UnicodeEncodeError):
        return (exc.object[exc.start : exc.end].encode("latin-1"), exc.end)
    raise exc


codecs.register_error("cp1252_raw", _cp1252_raw_handler)


def norm_nbsp(value: str) -> str:
    """Normalise l'espace insécable comme le fait Binary Eye."""
    return value.replace("\u00a0", " ")


def indice_champ(header: list[str], champ: str) -> int | None:
    """Retourne l'indice de la première colonne correspondant au champ."""
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


def _reparer_nbsp_apres_utf8(brut: bytes) -> bytes:
    """Restaure 0xA0 lorsqu'il a été normalisé en 0x20 par Binary Eye."""
    motif = rb"([\xc2-\xdf]|[\xe0-\xef][\x80-\xbf]|[\xf0-\xf4][\x80-\xbf]{2}) "
    return re.sub(motif, lambda m: m.group(1) + b"\xa0", brut)


def _suffixe_frontiere_utf8(prefixe: bytes) -> bytes:
    """Extrait un suffixe commençant sur une frontière de séquence UTF-8."""
    suffixe = prefixe[-4:]
    while suffixe and 0x80 <= suffixe[0] <= 0xBF:
        suffixe = suffixe[1:]
    return suffixe


def est_prefixe_utf8(data: bytes) -> bool:
    """Vrai si data est un début valide d'UTF-8 (fin incomplète acceptée)."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(data, final=False)
    except UnicodeDecodeError:
        return False
    return True


def est_utf8_complet(data: bytes) -> bool:
    """Vrai si data est une séquence UTF-8 complète et valide."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(data, final=True)
    except UnicodeDecodeError:
        return False
    return True


def ordonner_candidats(candidats: list[bytes], taille_attendue: int | None) -> list[bytes]:
    """Place d'abord les candidats dont la taille correspond au morceau."""
    uniques: list[bytes] = []
    for cand in candidats:
        if cand not in uniques:
            uniques.append(cand)
    if not taille_attendue:
        return uniques
    # Tri stable : à taille égale, l'ordre UTF-8/cp1252/latin-1 de génération
    # est conservé.
    return sorted(uniques, key=lambda c: 0 if len(c) == taille_attendue else 1)


def construire_candidats_complets(
    candidats_par_morceau: list[list[bytes]],
    tailles_attendues: list[int | None],
    max_etats: int = MAX_ETATS,
) -> tuple[list[bytes], bool]:
    """Construit au plus max_etats concaténations UTF-8 plausibles.

    La validité UTF-8 n'est vérifiée qu'à la frontière entre le préfixe et le
    morceau courant. Les états sont dédupliqués et limités pour éviter la
    croissance exponentielle.
    """
    etats: list[tuple[bytes, int, int, int]] = [(b"", 0, 0, 0)]
    tronque = False

    for i, candidats in enumerate(candidats_par_morceau):
        taille = tailles_attendues[i] if i < len(tailles_attendues) else None
        candidats = ordonner_candidats(candidats, taille)
        if not candidats:
            return [], tronque

        suivants: dict[bytes, tuple[int, int, int]] = {}
        for prefixe, conformes, ecart, rang in etats:
            for rang_cand, cand in enumerate(candidats):
                if not est_prefixe_utf8(
                    _suffixe_frontiere_utf8(prefixe) + cand
                ):
                    continue
                data = prefixe + cand
                conforme = 1 if taille is not None and len(cand) == taille else 0
                ecart_cand = abs(len(cand) - taille) if taille is not None else 0
                score = (
                    conformes + conforme,
                    ecart + ecart_cand,
                    rang + rang_cand,
                )
                ancien = suivants.get(data)
                if ancien is None or (
                    score[0],
                    -score[1],
                    -score[2],
                ) > (
                    ancien[0],
                    -ancien[1],
                    -ancien[2],
                ):
                    suivants[data] = score

        if not suivants:
            return [], tronque

        if len(suivants) > max_etats:
            tronque = True
            tries = sorted(
                suivants.items(),
                key=lambda item: (item[1][0], -item[1][1], -item[1][2]),
                reverse=True,
            )
            suivants = dict(tries[:max_etats])

        etats = [
            (data, score[0], score[1], score[2])
            for data, score in suivants.items()
        ]

    resultats = [data for data, _, _, _ in etats if est_utf8_complet(data)]
    return resultats, tronque


def charger_index(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def charger_meta(path: Path) -> dict:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


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

    L'ordre privilégie UTF-8, puis CP1252 tolérant et Latin-1. Un candidat
    complémentaire répare l'octet 0xA0 normalisé en 0x20 par Binary Eye.
    """
    candidats: list[bytes] = []

    def ajouter(brut: bytes) -> None:
        if brut not in candidats:
            candidats.append(brut)
        repare = _reparer_nbsp_apres_utf8(brut)
        if repare != brut and repare not in candidats:
            candidats.append(repare)

    for encodage, erreurs in (
        ("utf-8", "strict"),
        ("cp1252", "cp1252_raw"),
        ("latin-1", "strict"),
    ):
        try:
            brut = texte.encode(encodage, errors=erreurs)
        except UnicodeEncodeError:
            continue
        if retirer_separateur:
            if brut.endswith(b" \r\n"):
                brut = brut[:-3]
            elif brut.endswith(b" \n"):
                brut = brut[:-2]
            elif brut.endswith(b"\r\n"):
                brut = brut[:-2]
            elif brut.endswith(b"\n"):
                brut = brut[:-1]
        ajouter(brut)
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


def analyser_entete_lqr(ligne: str) -> tuple[str, int, int] | None:
    """Analyse strictement une ligne `LQR1 xx n/total`."""
    elements = ligne.split()
    if len(elements) < 3 or elements[0] != "LQR1":
        return None
    suffixe = elements[1]
    if len(suffixe) != 2 or not suffixe.isalpha():
        return None
    if not all("a" <= c <= "z" for c in suffixe):
        return None
    num, sep, total_txt = elements[2].partition("/")
    if not sep or not num.isdigit() or not total_txt.isdigit():
        return None
    n, total = int(num), int(total_txt)
    if total < 1 or n < 1 or n > total:
        return None
    if numero_vers_suffixe(n) != suffixe:
        return None
    return f"morceau_{suffixe}", n, total


def charger_export_json(
    path: Path, total_attendu: int | None = None
) -> dict[str, list[bytes]]:
    """Charge un export JSON natif de Binary Eye.

    Le fichier contient une liste d'objets avec un champ `content` qui commence
    par la ligne `LQR1 xx n/total`. On renvoie un dictionnaire
    `morceau_xx -> candidats d'octets`, comme pour les scans individuels.
    Les entrées malformées ou issues d'une autre sauvegarde sont écartées.
    """
    if path.suffix.lower() != ".json":
        raise SystemExit(
            f"Export non supporté : {path}\n"
            "Utilise l'export JSON global de Binary Eye. L'export CSV "
            "remplace les sauts de ligne par des espaces et ne permet pas "
            "une restauration fidèle."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Export JSON invalide : {path} ({exc})") from exc
    if not isinstance(data, list):
        raise SystemExit(f"Format d'export JSON inattendu : {path}")

    mapping: dict[str, list[bytes]] = {}
    ignores = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        content = content.lstrip("\ufeff")
        if not content.startswith("LQR1 "):
            continue
        header, sep, reste = content.partition("\n")
        if not sep:
            # Export CSV : les sauts de ligne ont été remplacés par des espaces.
            ignores += 1
            continue
        entete = analyser_entete_lqr(header)
        if entete is None:
            ignores += 1
            continue
        morceau, _n, total = entete
        if total_attendu is not None and total != total_attendu:
            ignores += 1
            continue
        mapping[morceau] = candidats_depuis_texte(reste, retirer_separateur=False)

    if ignores:
        print(
            f"Attention : {ignores} entrée(s) LQR1 ignorée(s) "
            "(format invalide ou autre sauvegarde).",
            file=sys.stderr,
        )
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
    ligne = data[:fin].decode("ascii", errors="replace").rstrip("\r")
    entete = analyser_entete_lqr(ligne)
    if entete is None:
        return None, data
    nom, _n, _total = entete
    return nom, data[fin + 1 :]


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
        recherche = norm_nbsp(args.nom).casefold()
        rows = [
            r for r in base if norm_nbsp(r["nom"]).casefold() == recherche
        ]
        # Si le nom exact n'a rien donné, on tente une recherche partielle.
        if not rows:
            rows = [
                r
                for r in base
                if recherche in norm_nbsp(r["nom"]).casefold()
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
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {r["morceau"].lstrip("\ufeff"): int(r["taille_octets"]) for r in csv.DictReader(f)}


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
    for cle, _alias in CHAMPS_INDEX:
        idx = indice_champ(header, cle)
        if idx is not None and idx < len(rows[0]):
            if norm_nbsp(rows[0][idx]) != norm_nbsp(cible.get(cle, "")):
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

    attendu = []
    for cle, _alias in CHAMPS_INDEX:
        idx = indice_champ(header, cle)
        if idx is not None:
            attendu.append((idx, norm_nbsp(cible.get(cle, ""))))
    if not attendu:
        return None

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
                if all(
                    norm_nbsp(row[pos]) == valeur for pos, valeur in attendu
                ):
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
    terminator = "\n" if meta.get("line_ending") == "lf" else "\r\n"
    quoting = csv.QUOTE_ALL if meta.get("quote_all") else csv.QUOTE_MINIMAL
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator=terminator, quoting=quoting)
        writer.writerow(header)
        writer.writerow(row)
    out_path.chmod(0o600)

    # Longueur de la ligne seule, hors en-tête.
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator=terminator, quoting=quoting).writerow(row)
    ligne = buf.getvalue().encode("utf-8")

    # Un enregistrement final ne possède un terminateur que si le fichier
    # source en avait un. Les anciens index ne stockent pas final_newline :
    # on conserve alors l'ancien comportement (pas de saut final).
    total = int(meta.get("size", 0))
    if total and int(cible["fin_octet_exclue"]) == total:
        final_newline = meta.get("final_newline")
        if final_newline is not True:
            suffixe = terminator.encode("utf-8")
            if ligne.endswith(suffixe):
                ligne = ligne[: -len(suffixe)]
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
    os.umask(0o077)
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
    if not isinstance(header, list) or not header:
        raise SystemExit(
            f"En-tête CSV introuvable dans {args.meta}. "
            "Garde index_meta.json avec l'index, ou fournis un index complet."
        )
    header[0] = header[0].lstrip("\ufeff")
    if not any(indice_champ(header, cle) is not None for cle, _ in CHAMPS_INDEX):
        raise SystemExit(
            "Aucune colonne d'identification reconnue dans l'en-tête CSV. "
            "Formats pris en charge : Bitwarden, KeePassXC ou colonnes "
            "génériques (nom, dossier, url, identifiant)."
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
            mapping_export = charger_export_json(
                export_path, int(meta.get("total_chunks", 0)) or None
            )
        else:
            auto = scan_dir / "binary_eye_all_qr.json"
            if auto.is_file():
                export_path = auto
                mapping_export = charger_export_json(
                    auto, int(meta.get("total_chunks", 0)) or None
                )

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
        taille = tailles.get(morceau, int(meta.get("chunk_size", 500)))
        candidats_par_morceau.append(ordonner_candidats(candidats, taille))
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

    tailles_attendues = [
        tailles.get(m, int(meta.get("chunk_size", 500))) for m in morceaux
    ]
    candidats_complets, tronque = construire_candidats_complets(
        candidats_par_morceau, tailles_attendues
    )
    if tronque:
        print(
            "Attention : la recherche d'encodages a été limitée "
            f"à {MAX_ETATS} états.",
            file=sys.stderr,
        )

    lignes: list[list[str]] | None = None
    methode = "recherche par nom"
    for data in candidats_complets:
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
        complement = (
            " La recherche bornée a peut-être écarté une combinaison rare ; "
            "essaie un export en octets bruts."
            if tronque
            else ""
        )
        raise SystemExit(
            "Entrée introuvable dans les scans. "
            "Vérifie que les morceaux indiqués sont bien présents et complets. "
            "Si le scan contient des accents, essaie un export en octets bruts."
            + complement
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
