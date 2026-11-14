> [!IMPORTANT]
> **Note de lecture — instantané d'audit.** Ce document conserve le diagnostic
> établi avant la campagne de remédiation. Les constats `AUD-01` à `AUD-23`
> décrivent l'état initial du code et non nécessairement son comportement
> actuel : les correctifs de sécurité issus de cette campagne ont été appliqués
> depuis (voir notamment le commit `5044e13`) et la documentation a été
> harmonisée. Pour l'état courant, se référer au code, à `README.md` et à
> `AGENTS.md`.

## 1. Synthèse exécutive

L'architecture du dépôt `ki2pixel-qrcode` témoigne d'une conception réfléchie en matière de défense en profondeur : séparation des privilèges via `runuser`, utilisation de primitives cryptographiques modernes (LUKS2 avec AES-256-XTS et Argon2id, chiffrement authentifié `age` couplé à une redondance Reed-Solomon `par2` de 15 %), montage en lecture seule stricte (`--readonly` et `-o ro,noload`) lors des consultations, et prise en compte de particularités concrètes du lecteur mobile Binary Eye (normalisation des espaces insécables `U+00A0` et réencodages Latin-1/CP1252).

(Note de périmètre : l'audit est réalisé en lecture seule stricte sur l'archive du dépôt fournie ; le flux Repomix étant tronqué à la fin de `README.md`, le corps de `restaurer_sauvegarde.py` est audité à travers ses contrats d'interface, ses appels dans `consulter_coffre_ro.sh` / `creer_sauvegarde_qr.sh`, ses dépendances dans `extraire_entree.py` et `generer_index_qr.py`, ainsi que ses spécifications dans `AGENTS.md` et `docs/`).

### Points forts confirmés

* **Paramétrage cryptographique robuste** : Formatage LUKS2 explicite en `aes-xts-plain64` (clé de 512 bits), dérivation `argon2id` avec temps d'itération de 4000 ms et secteurs de 4096 octets, complété par une capsule `.tar.zst.age` et des fichiers de parité `.par2` vérifiés par `sha256sum`.


* **Protection contre l'indexation graphique et l'historique shell** : Neutralisation de `HISTFILE`, désactivation du bytecode Python (`PYTHONDONTWRITEBYTECODE=1` / `-B`), création de fichiers sentinelles `.nomedia` et `.trackerignore`, et échappement HTML systématique (`html.escape(..., quote=True)`) dans les générateurs de documents.


* **Vérification d'intégrité à la génération** : `generer_index_qr.py` vérifie systématiquement que chaque enregistrement CSV indexé se reconstruit à l'identique à partir de ses offsets d'octets avant de valider l'index.



### Risques majeurs identifiés

L'audit approfondi met toutefois en évidence **18 constats** (dont **4 critiques** et **5 élevés**) susceptibles de compromettre la confidentialité (rémanence sur SSD), l'intégrité (perte silencieuse de données, corruption ou impossibilité de restauration) ou la sécurité des opérations sur périphériques blocs :

1. **Perte silencieuse de données dès 651 morceaux ($\approx 325\text{ Kio}$)** : `split -b 500` est invoqué sans `-a 2`. Or, GNU `split` passe automatiquement à des suffixes de 3 lettres (`morceau_zaa`) dès le 651e morceau, que le glob `morceau_??` ignore silencieusement tandis que `generer_index_qr.py` indexe jusqu'à 676 morceaux sans lever d'erreur.


2. **Absence de `swapoff -a` dans `consulter_coffre_ro.sh` et `init_usb_coffre.sh**` : Contrairement à ce qu'affirme `AGENTS.md`, `consulter_coffre_ro.sh` ne désactive jamais le swap. Même avec `noswap` sur `/mnt/ram_sec` (noyau $\ge 6.4$), la mémoire privée (heap) du processus Python reconstruisant les mots de passe en clair peut être paginée sur le SSD sous la pression mémoire de 2 Gio induite par Argon2id.


3. **Incompatibilité structurelle avec les exports CSV KeePassXC** : Bien que la documentation préconise l'export depuis KeePassXC ou Bitwarden, `generer_index_qr.py` et `extraire_entree.py` codent en dur les noms de colonnes Bitwarden (`name`, `folder`, `login_uri`, `login_username`). Un export KeePassXC (`Group`, `Title`, `Username`, `URL`) produit un index vide et fait échouer ou dysfonctionner l'extraction ciblée.


4. **Contournements dans la validation des disques (`is_system_disk` et `validate_usb_device`)** : Sur un système racine Btrfs (subvolumes `[/root]` ou `[/@]`), `lsblk -sno NAME "$src"` échoue silencieusement ; en outre, la vérification de `/sys/class/block/$name/holders` n'inspecte que le disque parent et non ses partitions (`${name}*`), et le filtre `TYPE` ignore les volumes `raid1`/`raid5` ainsi que les périphériques `loop` pourtant prescrits par `AGENTS.md` pour les tests.



---

## 2. Matrice des constats classés par sévérité

### Synthèse des constats

| ID | Sévérité | Fichier(s) principal(aux) | Titre du constat |
| --- | --- | --- | --- |
| **AUD-01** | **CRITIQUE** | `creer_sauvegarde_qr.sh`, `generer_index_qr.py` | Troncature silencieuse de la sauvegarde entre 651 et 676 morceaux (`split` sans `-a 2` vs glob `morceau_??`)

 |
| **AUD-02** | **CRITIQUE** | `consulter_coffre_ro.sh`, `init_usb_coffre.sh` | Absence de `swapoff -a` exposant le heap Python et `/dev/shm` à la pagination sur SSD

 |
| **AUD-03** | **CRITIQUE** | `generer_index_qr.py`, `extraire_entree.py` | Colonnes Bitwarden codées en dur rendant les exports KeePassXC inexploitables en indexation et extraction

 |
| **AUD-04** | **CRITIQUE** | `init_usb_coffre.sh`, `executer_sauvegarde_ram.sh`, `consulter_coffre_ro.sh` | Failles de détection dans `is_system_disk` (subvolumes Btrfs) et `validate_usb_device` (`holders` sur partitions, RAID)

 |
| **AUD-05** | **ÉLEVÉ** | `extraire_entree.py` | Échec d'extraction sur les entrées contenant un espace insécable (`U+00A0`) dans leurs métadonnées

 |
| **AUD-06** | **ÉLEVÉ** | `extraire_entree.py` | Explosion combinatoire (`itertools.product`) et corruption potentielle par priorité `latin-1` avant `utf-8`

 |
| **AUD-07** | **ÉLEVÉ** | `extraire_entree.py` | Échec de décodage sur les morceaux combinant caractères CP1252 (`0x80..0x9F`) et octets C1 non définis (`0x81`, `0x8D`, etc.)

 |
| **AUD-08** | **ÉLEVÉ** | `generer_index_qr.py`, `extraire_entree.py` | Désynchronisation du parseur CSV en présence d'un BOM UTF-8 ou de séparateurs de ligne Unicode (`U+2028`, `\x85`)

 |
| **AUD-09** | **ÉLEVÉ** | `executer_sauvegarde_ram.sh` | Fuites forensiques CUPS (`/var/cache/cups`, `/var/log/cups`), interférence `cups.path` et absence de `shred` du spoule

 |
| **AUD-10** | **MOYEN** | `executer_sauvegarde_ram.sh`, `consulter_coffre_ro.sh`, `init_usb_coffre.sh` | Repli silencieux sur `umount -l` empêchant la fermeture de LUKS (`cryptsetup close`) et masquant les processus actifs

 |
| **AUD-11** | **MOYEN** | `init_usb_coffre.sh`, `executer_sauvegarde_ram.sh`, `extraire_entree.py` | Fenêtre d'exposition des permissions POSIX (`umask` non transmis sous `runuser` et `chmod 0o600` après écriture)

 |
| **AUD-12** | **MOYEN** | `generer_planches_qr.py`, `creer_sauvegarde_qr.sh` | Arrêt brutal de `creer_sauvegarde_qr.sh` si WeasyPrint est absent (`return 1` dans `generer_planches_qr.py`)

 |
| **AUD-13** | **MOYEN** | `extraire_entree.py` | Incohérence de longueur rapportée dans `ecrire_sortie()` (`\r\n` forcé même sur un CSV source en `\n`) et `IndexError` sur en-tête `LQR1` malformé

 |
| **AUD-14** | **MOYEN** | `init_usb_coffre.sh`, `executer_sauvegarde_ram.sh` | Risque de perte de la passphrase auto-générée par `age -p` en cas de saisie vide suivie d'un défilement écran

 |
| **AUD-15** | **FAIBLE** | `creer_sauvegarde_qr.sh` | Absence de `shred` sur les fichiers `.qrpayload`, absence de `-B` sur Python et absence de `--` sur `readlink`/`split`/`basename`

 |
| **AUD-16** | **FAIBLE** | `executer_sauvegarde_ram.sh` | Exposition du nom du CSV, de la taille et de l'horodatage sur `URGENCE_QR` et accumulation des anciennes capsules

 |
| **AUD-17** | **FAIBLE** | `generer_planches_qr.py` | Marge verticale critique en format confort $3\times 4$ (`54 mm`) pouvant provoquer des sauts de page parasites

 |
| **AUD-18** | **INFO** | `init_usb_coffre.sh`, `executer_sauvegarde_ram.sh`, `consulter_coffre_ro.sh` | Refus des périphériques `/dev/loopX` dans `validate_usb_device` empêchant les tests loopback recommandés par `AGENTS.md`

 |

---

### Détail technique des constats

#### `AUD-01` — [CRITIQUE] Troncature silencieuse de la sauvegarde entre 651 et 676 morceaux (`split` sans `-a 2` vs glob `morceau_??`)

* **Fichiers et lignes :** `creer_sauvegarde_qr.sh` (lignes 49, 55) ; `generer_index_qr.py` (lignes 40–44, 111).


* **Description et scénario :**
Dans `creer_sauvegarde_qr.sh`, le découpage est effectué par `split -b 500 "$CSV" "$OUT/morceaux/morceau_"` sans spécifier `-a 2`, puis les morceaux sont collectés via le glob `MORCEAUX=("$OUT"/morceaux/morceau_??)`. Or, le comportement par défaut de GNU `split` (coreutils) consiste à utiliser des suffixes de 2 lettres uniquement de `aa` à `yz` ($25 \times 26 = 650$ morceaux, soit $325\,000$ octets), puis à passer dynamiquement à 3 lettres (`morceau_zaa`, `morceau_zab`, …) dès le 651e morceau.
Si un export CSV mesure entre $325\,001$ et $338\,000$ octets (651 à 676 morceaux) :


1. `split` crée `morceau_aa`..`morceau_yz` (2 lettres) et `morceau_zaa`..`morceau_zaz` (3 lettres).
2. Le glob `morceau_??` ignore silencieusement `morceau_zaa` et suivants. Seuls 650 QR codes sont générés (`LQR1 ... n/650`).


3. `generer_index_qr.py` calcule `total_chunks = (len(raw) + 499) // 500` ($\le 676$) et génère les références `morceau_za`..`morceau_zz` sans vérifier l'existence des fichiers sur le disque ni lever d'exception (`suffixe_morceau` acceptant jusqu'à 676).




* **Impact :** **Intégrité / Disponibilité.** Perte silencieuse de la fin du portefeuille de mots de passe (jusqu'à 26 morceaux / $13\,\text{Kio}$) sans aucun message d'erreur ni code de retour non nul lors de la génération.


* **Recommandation de correction :**
Forcer `-a 2` dans `split`, vérifier explicitement la taille maximale du CSV avant découpage ($\le 676 \times 500 = 338\,000$ octets) et vérifier que le nombre de PNG générés égale exactement `total_chunks` :
```diff
--- a/creer_sauvegarde_qr.sh
+++ b/creer_sauvegarde_qr.sh
@@ -48,7 +48,11 @@
 # 1. Découpage en morceaux de 500 octets.
-split -b 500 "$CSV" "$OUT/morceaux/morceau_"
+CSV_SIZE="$(stat -c %s -- "$CSV")"
+if (( CSV_SIZE > 676 * 500 )); then
+  echo "Erreur : CSV trop volumineux ($CSV_SIZE octets > maximum 338000 octets / 676 QR)." >&2
+  exit 1
+fi
+split -a 2 -b 500 -- "$CSV" "$OUT/morceaux/morceau_"

```



---

#### `AUD-02` — [CRITIQUE] Absence de `swapoff -a` dans `consulter_coffre_ro.sh` et `init_usb_coffre.sh`

* **Fichiers et lignes :** `consulter_coffre_ro.sh` (lignes 342–373) ; `init_usb_coffre.sh` (lignes 367–385).


* **Description et scénario :**
1. Dans `consulter_coffre_ro.sh`, le swap système n'est jamais désactivé avant le déverrouillage du coffre et l'extraction des mots de passe. Même sur un noyau Linux $\ge 6.4$ supportant l'option `noswap` sur `/mnt/ram_sec`, `noswap` ne s'applique qu'aux pages du système de fichiers `tmpfs` et **ne protège pas la mémoire anonyme (heap/stack) des processus utilisateur** (`python3` exécutant `extraire_entree.py` ou `restaurer_sauvegarde.py`, ou `less` dans un second terminal). De plus, l'ouverture de LUKS2 avec Argon2id alloue immédiatement 2 Gio de RAM, provoquant une pression mémoire susceptible de forcer le noyau à paginer des pages anonymes sur le SSD. Sur un noyau $< 6.4$, le script affiche un simple avertissement (`warn`) et continue avec le `tmpfs` swappable.


2. Dans `init_usb_coffre.sh`, ni `ulimit -c 0` ni `swapoff -a` ne sont exécutés alors que l'en-tête LUKS2 (`header.bak`) est extrait dans `/dev/shm` (qui est monté sans `noswap`) juste après deux allocations Argon2id de 2 Gio (`luksFormat` puis `cryptsetup open`).




* **Impact :** **Confidentialité (Rémanence disque).** Écriture potentielle de mots de passe en clair (heap Python) ou de matériel cryptographique sur la partition/fichier de swap du SSD/NVMe hôte.


* **Recommandation de correction :**
Intégrer dans `consulter_coffre_ro.sh` et `init_usb_coffre.sh` le même bloc de désactivation et de restauration du swap (`swapoff -a` + `SWAP_LIST` dans `cleanup()`) que dans `executer_sauvegarde_ram.sh`, ainsi que `ulimit -c 0` dans `init_usb_coffre.sh`.



---

#### `AUD-03` — [CRITIQUE] Colonnes Bitwarden codées en dur rendant les exports KeePassXC inexploitables

* **Fichiers et lignes :** `generer_index_qr.py` (lignes 116–119) ; `extraire_entree.py` (lignes 32–37, 284–288, 297–300, 314).


* **Description et scénario :**
La documentation (`docs/Sauvegarde_USB_Chiffrée_sous_Linux.md` et `generer_index_qr.py`) indique que l'utilisateur peut exporter son portefeuille depuis **KeePassXC** ou **Bitwarden**. Or :


* Bitwarden exporte les colonnes : `folder,favorite,type,name,notes,fields,reprompt,login_uri,login_username,login_password,login_totp`.


* KeePassXC exporte les colonnes : `Group,Title,Username,Password,URL,Notes,TOTP,Icon,Last Modified,Created`.
Dans `generer_index_qr.py`, la fonction `construire_index` recherche uniquement `"name"`, `"folder"`, `"login_uri"`, `"login_username"`. Avec un CSV KeePassXC, ces quatre champs valent `""` pour toutes les entrées. Pire, dans `extraire_entree.py`, `CHAMPS_INDEX` cherche ces mêmes colonnes dans `header` : pour un CSV KeePassXC, le dictionnaire `attendu` dans `extraire_par_recherche()` est vide (`{}`), de sorte que `all(row[pos] == valeur for pos, valeur in attendu.values())` est évalué à `True` pour **toutes** les lignes du morceau scanné.




* **Impact :** **Disponibilité / Intégrité / Confidentialité.** Index PDF/CSV vide de toute métadonnée d'identification pour KeePassXC, recherche `--nom` inopérante, et extraction par ID retournant toutes les entrées du morceau (y compris celles non sollicitées).


* **Recommandation de correction :**
Supporter un mapping d'alias de colonnes multi-gestionnaires (Bitwarden, KeePassXC, générique) :
```python
ALIASES_CHAMPS = {
    "nom": ("name", "Title", "title", "nom"),
    "dossier": ("folder", "Group", "group", "dossier"),
    "uri": ("login_uri", "URL", "url", "uri"),
    "identifiant": ("login_username", "Username", "username", "identifiant"),
}

```



---

#### `AUD-04` — [CRITIQUE] Failles de détection dans `is_system_disk` et `validate_usb_device`

* **Fichiers et lignes :** `init_usb_coffre.sh` (lignes 202–255) ; `executer_sauvegarde_ram.sh` (lignes 196–249) ; `consulter_coffre_ro.sh` (lignes 168–221).


* **Description et scénario :**
1. **Échec de `is_system_disk` sur Btrfs :** Sur les distributions utilisant des subvolumes Btrfs (Fedora, openSUSE, Ubuntu Btrfs), `findmnt -n -o SOURCE --target /` renvoie une chaîne de la forme `/dev/sda2[/@]` ou `/dev/nvme0n1p2[/root]`. L'appel suivant `lsblk -sno NAME "$src"` échoue car `/dev/sda2[/@]` n'est pas un chemin de nœud bloc valide, renvoyant une chaîne vide et faisant retourner `1` (non-système) à `is_system_disk`.


2. **Vérification incomplète de `/sys/class/block/$name/holders` :** `validate_usb_device` vérifie uniquement `/sys/class/block/$name/holders` sur le disque entier (ex. `sdb`), qui est toujours vide lorsque ce sont les **partitions** (`sdb1`, `sdb2`) qui sont détenues par `dm-crypt`, LVM ou MD RAID (`/sys/class/block/sdb1/holders`).


3. **Filtre `TYPE` incomplet pour MD RAID :** `lsblk -nr -o TYPE "$dev" | grep -Eq '^(lvm|md|dm|crypt)$'` ne détecte pas les ensembles RAID logiciels Linux, dont le `TYPE` retourné par `lsblk` est `raid0`, `raid1`, `raid5`, `raid6` ou `raid10` (et non `md`).




* **Impact :** **Sécurité matérielle / Intégrité système.** Risque de non-détection d'un disque actif (notamment RAID logiciel dégradé/non monté ou sous-volume Btrfs sur disque externe USB) lors de l'exécution de `init_usb_coffre.sh`.


* **Recommandation de correction :**
Utiliser `findmnt -n -v -o SOURCE` (option `--nofsroot` qui retire `[/subvol]`), inspecter les `holders` sur le disque **et** toutes ses partitions (`/sys/class/block/${name}/holders` et `/sys/class/block/${name}*/holders`), et étendre l'expression régulière des types `lsblk` à `^(lvm|md|raid.*|dm|crypt|multipath)$` :
```bash
src="$(findmnt -n -v -o SOURCE --target "$mp" 2>/dev/null || true)"
...
if lsblk -nr -o TYPE "$dev" 2>/dev/null | grep -Eq '^(lvm|md|raid[0-9]*|linear|dm|crypt|multipath)$'; then
  die "Refus : le périphérique participe à un volume LVM/RAID/dm."
fi
if find "/sys/class/block/$name" "/sys/class/block/$name"* -maxdepth 2 -name holders -exec ls -A {} + 2>/dev/null | grep -q .; then
  die "Refus : le périphérique ou l'une de ses partitions a des dépendances noyau (holders)."
fi

```



---

#### `AUD-05` — [ÉLEVÉ] Échec d'extraction sur les entrées contenant un espace insécable (`U+00A0`) dans leurs métadonnées

* **Fichier et lignes :** `extraire_entree.py` (lignes 229–245, 291–323).


* **Description et scénario :**
Comme documenté dans le projet, Binary Eye remplace les espaces insécables (`U+00A0` / `\xc2\xa0`) par des espaces standards (`0x20`) lors de l'export JSON. Si `restaurer_sauvegarde.py` et `generer_index_qr.py` prennent bien en compte cette normalisation via `sha256_sans_nbsp`, `extraire_entree.py` compare directement les champs `nom`, `dossier`, `uri` et `identifiant` lus depuis `index_enregistrements.csv` (qui contiennent `U+00A0`) avec les champs décodés depuis `binary_eye_all_qr.json` (où `U+00A0` est devenu `" "`) via `all(row[pos] == valeur for pos, valeur in attendu.values())`.


* **Impact :** **Disponibilité.** Toute entrée comportant un espace insécable dans son nom, son dossier, son URI ou son identifiant est impossible à extraire via `extraire_entree.py` à partir d'un export Binary Eye.


* **Recommandation de correction :**
Normaliser les espaces insécables des deux côtés lors de la comparaison dans `extraire_par_recherche()` et `choisir_cible()` :
```python
def norm_nbsp(s: str) -> str:
    return s.replace("\u00a0", " ")

if all(norm_nbsp(row[pos]) == norm_nbsp(valeur) for pos, valeur in attendu.values()):
    candidats.add(tuple(row))

```



---

#### `AUD-06` — [ÉLEVÉ] Explosion combinatoire (`itertools.product`) et corruption potentielle par priorité `latin-1` avant `utf-8`

* **Fichier et lignes :** `extraire_entree.py` (lignes 99–113, 454–466).


* **Description et scénario :**
1. **Explosion combinatoire :** Pour chaque morceau, `candidats_depuis_texte` renvoie jusqu'à 3 candidats (`latin-1`, `cp1252`, `utf-8`). La ligne 454 évalue `for combinaison in itertools.product(*candidats_par_morceau):`. Si une entrée contient une note volumineuse (ex. clé privée SSH/PGP de 10 Kio couvrant 20 morceaux), `itertools.product` génère jusqu'à $2^{20}$ à $3^{20}$ ($\approx 3,48 \times 10^9$) combinaisons, bloquant l'extraction par épuisement CPU.


2. **Ordre de priorité `latin-1` vs `utf-8` :** Dans `candidats_depuis_texte`, `latin-1` est testé **avant** `utf-8`. Si l'export JSON de Binary Eye est en UTF-8 valide (sans mojibake), que les 4 champs d'index (`name`, `folder`, `uri`, `username`) sont purement ASCII, mais que le champ `login_password` ou `notes` contient uniquement des caractères Unicode dans la plage `U+0080..U+00FF` dont la séquence d'octets Latin-1 forme fortuitement une séquence UTF-8 valide (ex. `Â£` = `U+00C2 U+00A3` dont l'encodage `latin-1` donne `b"\xc2\xa3"`, qui se décode en UTF-8 valide comme `"£"`), `extraire_par_recherche` valide la première combinaison (`latin-1`) et **altère silencieusement le mot de passe extrait** (`"Â£"` devient `"£"`).




* **Impact :** **Intégrité / Disponibilité.** Corruption silencieuse possible d'un mot de passe contenant certains symboles Latin-1, et déni de service sur les entrées s'étendant sur de nombreux morceaux.


* **Recommandation de correction :**
1. Dans `candidats_depuis_texte`, placer `"utf-8"` en **première** position lorsque la taille en octets UTF-8 correspond à la taille attendue du morceau (ou privilégier le candidat dont la longueur de ligne extraite égale `cible["longueur_octets"]`).


2. Tester d'abord les modes homogènes (tous les morceaux en `utf-8`, puis tous en `latin-1`/`cp1252`) ou filtrer la validité UTF-8 aux frontières de chaque paire de morceaux adjacents $(m_i, m_{i+1})$ avant de faire un produit cartésien global.



---

#### `AUD-07` — [ÉLEVÉ] Échec de décodage sur les morceaux combinant caractères CP1252 (`0x80..0x9F`) et octets C1 non définis (`0x81`, `0x8D`, `0x8F`, `0x90`, `0x9D`)

* **Fichier et lignes :** `extraire_entree.py` (lignes 99–104).


* **Description et scénario :**
Lorsqu'un caractère UTF-8 multi-octets est coupé entre deux morceaux de 500 octets, le scanner peut décoder les octets bruts du morceau selon la table Windows-1252 (qui mappe `0x80..0x9F` vers des caractères comme `€` `U+20AC`, `™` `U+2122`, etc., tout en laissant les 5 octets non attribués `0x81`, `0x8D`, `0x8F`, `0x90`, `0x9D` sous forme de points de code de contrôle C1 `U+0081`, etc.).
Or, si un même morceau de 500 octets contient à la fois un octet mappé par CP1252 (ex. `€` $\rightarrow$ `0x80` $\rightarrow$ `U+20AC`) et un octet parmi ces 5 valeurs (ex. `Á` = `\xc3\x81` $\rightarrow$ `U+00C3 U+0081`) :
* `texte.encode("latin-1")` lève `UnicodeEncodeError` sur `U+20AC` ;


* `texte.encode("cp1252")` lève `UnicodeEncodeError` sur `U+0081` (car le codec `cp1252` standard de Python refuse ces 5 points de code en mode `strict`).




* **Impact :** **Intégrité / Disponibilité.** Impossibilité de reconstruire les octets bruts du morceau lors de l'extraction ou de la restauration complète.


* **Recommandation de correction :**
Enregistrer un gestionnaire d'erreurs ou utiliser un encodage CP1252 tolérant qui replie les points de code `U+0080..U+00FF` sur leur valeur d'octet `latin-1` :
```python
import codecs
codecs.register_error(
    "cp1252_raw",
    lambda exc: (exc.object[exc.start:exc.end].encode("latin-1"), exc.end),
)
# Puis dans candidats_depuis_texte :
brut = texte.encode("cp1252", errors="cp1252_raw")

```



---

#### `AUD-08` — [ÉLEVÉ] Désynchronisation du parseur CSV en présence d'un BOM UTF-8 ou de séparateurs de ligne Unicode (`U+2028`, `\x85`)

* **Fichiers et lignes :** `generer_index_qr.py` (lignes 51–85) ; `extraire_entree.py` (lignes 200–201).


* **Description et scénario :**
1. **BOM UTF-8 (`\xef\xbb\xbf`) :** Si le CSV source débute par un BOM UTF-8, `raw.decode("utf-8")` dans `charger_enregistrements()` conserve `\ufeff` en tête du premier nom de colonne (`"\ufefffolder"` ou `"\ufeffname"`), empêchant la reconnaissance de cette colonne.


2. **Découpage par `text.splitlines(keepends=True)` :** La méthode Python `str.splitlines()` découpe non seulement sur `\n` et `\r\n`, mais aussi sur les séparateurs Unicode `\x0b`, `\x0c`, `\x1c`..`\x1e`, `\x85` (NEL), `\u2028` (LS) et `\u2029` (PS). Lorsqu'on passe la liste `lines` ainsi découpée à `csv.reader(lines)` (ligne 70 de `generer_index_qr.py`), le module `csv` traite la fin de chaque chaîne de la liste comme une fin de ligne CSV même s'il s'agissait d'un `\u2028` au milieu d'un champ non guillemeté, ou lève une erreur de parsing si les guillemets s'en trouvent déséquilibrés.




* **Impact :** **Intégrité / Disponibilité.** Échec de génération de l'index ou omission de la première colonne d'index si un BOM UTF-8 est présent.


* **Recommandation de correction :**
Décoder l'en-tête en ignorant un éventuel BOM initial pour le nom de la première colonne (`header[0] = header[0].lstrip("\ufeff")`), et découper `text` uniquement sur les fins de ligne CSV (`re.findall(r'[^\r\n]*(?:\r\n|\r|\n|$)', text)` sans l'élément vide final) au lieu de `text.splitlines(keepends=True)`.



---

#### `AUD-09` — [ÉLEVÉ] Fuites forensiques CUPS (`/var/cache/cups`, `/var/log/cups`), interférence `cups.path` et absence de `shred` du spoule

* **Fichier et lignes :** `executer_sauvegarde_ram.sh` (lignes 288–413).


* **Description et scénario :**
Lors de l'impression dans `print_plates()` :
1. `systemctl stop cups.socket cups.service` n'arrête pas `cups.path` ni `cups-browsed.service`. Sur Debian/Ubuntu, l'unité `cups.path` surveille `/var/spool/cups` (`PathExistsGlob=/var/spool/cups/d*`) et peut relancer `cups.service` de manière asynchrone pendant la manipulation ou juste avant le démontage dans `stop_cups_spool()`.


2. Le répertoire `/var/cache/cups` (où `cupsd` écrit `job.cache` contenant les métadonnées des travaux d'impression) et `/var/log/cups/page_log` résident sur le SSD et ne sont pas montés en `tmpfs`.


3. Dans `stop_cups_spool()`, les fichiers présents dans `/var/spool/cups` et `/var/spool/cups/tmp` ne sont **pas écrasés par `shred**` avant `umount`. Si `umount "$CUPS_SPOOL"` échoue et bascule sur `umount -l "$CUPS_SPOOL"`, les PDF contenant les QR codes en clair demeurent en mémoire vive dans le montage détaché.


4. Le montage `tmpfs` de `/var/spool/cups` n'active pas l'option `noswap` sur les noyaux $\ge 6.4$.




* **Impact :** **Confidentialité (Anti-rémanence).** Traces forensiques des travaux d'impression dans `/var/cache/cups` et `/var/log/cups` sur le SSD, et persistance en RAM si `umount -l` est déclenché.


* **Recommandation de correction :**
Arrêter également `cups.path` et `cups-browsed.service`, monter un `tmpfs` (avec `noswap` si disponible) sur `/var/cache/cups` et `/var/log/cups` (ou passer `-o job-sheets=none`), et exécuter `find "$CUPS_SPOOL" -xdev -type f -exec shred -u -z -n 1 -- {} +` dans `stop_cups_spool()` avant `umount`.



---

#### `AUD-10` — [MOYEN] Repli silencieux sur `umount -l` empêchant la fermeture de LUKS et masquant les processus actifs

* **Fichiers et lignes :** `executer_sauvegarde_ram.sh` (lignes 115–138) ; `consulter_coffre_ro.sh` (lignes 99–122) ; `init_usb_coffre.sh` (lignes 131–145).


* **Description et scénario :**
Dans `cleanup()`, les trois scripts exécutent :
```bash
umount "$VAULT_MNT" 2>/dev/null || umount -l "$VAULT_MNT" 2>/dev/null || true
...
cryptsetup close "$MAPPER" 2>/dev/null || true

```


Si un terminal secondaire (comme suggéré dans `docs/GUIDE_OPERATOIRE_COFFRE_USB.md` à l'étape 4 de la consultation) ou un processus garde un descripteur ouvert dans `/mnt/ram_sec` ou `/mnt/usb_vault`, `umount` échoue (`EBUSY`) et bascule silencieusement sur `umount -l` (*lazy unmount*).
Dès lors, le système de fichiers reste monté en arrière-plan dans le noyau, et `cryptsetup close "$MAPPER"` échoue silencieusement (`|| true`). Le coffre LUKS2 reste ouvert (`/dev/mapper/qr_vault_ro` ou `qr_vault` toujours actif) alors que le script affiche `ok "Nettoyage en cours."` et rend la main.


* **Impact :** **Sécurité opérationnelle / Intégrité matérielle.** Risque d'arrachement à chaud d'un volume LUKS2/ext4 encore ouvert ou maintien involontaire de secrets en RAM.


* **Recommandation de correction :**
Tenter d'abord un démontage normal, identifier/terminer les processus bloquants ou avertir explicitement l'utilisateur si `umount` ou `cryptsetup close` échoue au lieu d'étouffer l'erreur par `|| true` :
```bash
if ! umount "$VAULT_MNT" 2>/dev/null; then
  warn "$VAULT_MNT est occupé. Fermeture des descripteurs ou démontage différé..."
  fuser -km "$VAULT_MNT" >/dev/null 2>&1 || true
  sleep 0.5
  umount "$VAULT_MNT" 2>/dev/null || umount -l "$VAULT_MNT" 2>/dev/null || true
fi
if ! cryptsetup close "$MAPPER" 2>/dev/null; then
  err "ATTENTION : Le conteneur LUKS $MAPPER n'a pas pu être fermé (encore occupé) !"
fi

```



---

#### `AUD-11` — [MOYEN] Fenêtre d'exposition des permissions POSIX (`umask` sous `runuser` et `chmod 0o600` après écriture)

* **Fichiers et lignes :** `init_usb_coffre.sh` (lignes 379–383) ; `executer_sauvegarde_ram.sh` (lignes 551–565) ; `extraire_entree.py` (lignes 331–335) ; `generer_index_qr.py` (lignes 515–518).


* **Description et scénario :**
1. Dans `init_usb_coffre.sh`, `runuser -u "$REAL_USER" -- env ... age -p -o "$AGE_HDR" "$HDR_TMP"` crée `$AGE_HDR` dans `$REAL_HOME` (souvent en `0755` ou `0750`), puis applique `chmod 600 "$AGE_HDR"` après coup. Si PAM réinitialise l'`umask` de `$REAL_USER` à `0022`, le fichier est lisible par d'autres comptes locaux pendant sa création.


2. Dans `extraire_entree.py` (`ecrire_sortie`), `out_path.open("w", ...)` écrit l'entrée et le mot de passe en clair sur le système de fichiers **avant** d'appeler `out_path.chmod(0o600)`. Lors d'une utilisation autonome hors de `/mnt/ram_sec`, il existe une fenêtre TOCTOU où le fichier a les permissions par défaut du `umask` utilisateur (`0644`).




* **Impact :** **Confidentialité locale.** Exposition transitoire des fichiers créés aux autres utilisateurs locaux de la machine.


* **Recommandation de correction :**
Ajouter `os.umask(0o077)` au début de `main()` dans tous les scripts Python (`extraire_entree.py`, `restaurer_sauvegarde.py`, `generer_index_qr.py`, `generer_planches_qr.py`) et précréer `$AGE_HDR` et `$CAPSULE` avec `install -m 600 -o "$REAL_UID" -g "$REAL_GID" /dev/null "$AGE_HDR"` avant d'invoquer `age`.



---

#### `AUD-12` — [MOYEN] Arrêt brutal de `creer_sauvegarde_qr.sh` si WeasyPrint est absent

* **Fichiers et lignes :** `generer_planches_qr.py` (lignes 196–198) ; `creer_sauvegarde_qr.sh` (lignes 70–95) ; `AGENTS.md` (ligne 17).


* **Description et scénario :**
`AGENTS.md` stipule : *« `SANS_PLANCHES=1` saute les planches ; sans WeasyPrint, les PDF ne sont pas produits (le HTML l'est). »*.
Or, si `generer_index_qr.py` retourne bien `0` lorsque `weasyprint` est absent (ligne 499), `generer_planches_qr.py` retourne `1` (ligne 198). Comme `creer_sauvegarde_qr.sh` s'exécute sous `set -euo pipefail`, l'absence de WeasyPrint provoque l'arrêt immédiat du script au milieu de l'étape 4 : les scripts `extraire_entree.py` et `restaurer_sauvegarde.py` ne sont pas copiés, `LISEZMOI.txt` n'est pas créé, et surtout **le durcissement final des permissions (`chmod 700` / `chmod 600` aux lignes 169–172) n'est jamais exécuté** !


* **Impact :** **Disponibilité / Confidentialité.** Sauvegarde incomplète et permissions finales non appliquées en mode autonome si WeasyPrint n'est pas installé.


* **Recommandation de correction :**
Retourner `0` (ou gérer un drapeau `--require-pdf`) dans `generer_planches_qr.py` lorsque `HTML is None` après avoir écrit le fichier HTML, à l'instar de `generer_index_qr.py`.



---

#### `AUD-13` — [MOYEN] Incohérence de longueur rapportée dans `ecrire_sortie()` (`\r\n` forcé) et `IndexError` potentiel sur `LQR1`

* **Fichier et lignes :** `extraire_entree.py` (lignes 161, 331–345, 502–505).


* **Description et scénario :**
1. Dans `ecrire_sortie()`, le script calcule la longueur en octets de la ligne extraite en forçant `lineterminator="\r\n"`. Si le fichier CSV d'origine utilisait des fins de ligne Unix `LF` (`\n`, standard sous Linux), la longueur affichée (`Ligne : X octets (attendu Y)`) dépasse de $1 + k$ octets la valeur `longueur_octets` de l'index (où $k$ est le nombre de sauts de ligne internes à l'enregistrement), laissant croire à tort à une altération.


2. À la ligne 161 (`charger_export_json`), `morceau = header.split()[1]` ne vérifie pas `len(header.split()) >= 2` (contrairement à `retirer_entete_lqr` ligne 207) : une entrée JSON commençant par `"LQR1 \n"` provoque une exception `IndexError` non gérée.


3. L'en-tête `LQR1 <sfx> <n>/<total>` n'est pas confronté à `meta.get("total_chunks")`, ce qui ne détecte pas le mélange accidentel de scans issus de deux sauvegardes différentes dans l'historique Binary Eye.




* **Impact :** **Intégrité / Ergonomie.** Alerte de taille erronée sur tous les CSV en LF et plantage sur JSON malformé.


* **Recommandation de correction :**
Enregistrer le type de fin de ligne (`"crlf"` ou `"lf"`) dans `index_meta.json` lors de `generer_index_qr.py`, l'utiliser dans `ecrire_sortie()`, et valider `len(header.split()) >= 3` ainsi que `/total_chunks` dans `charger_export_json()`.



---

#### `AUD-14` — [MOYEN] Risque de perte de la passphrase auto-générée par `age -p` en cas de saisie vide

* **Fichiers et lignes :** `init_usb_coffre.sh` (lignes 376–378) ; `executer_sauvegarde_ram.sh` (lignes 547–554).


* **Description et scénario :**
Lorsque `age -p` est invoqué, si l'opérateur appuie par erreur sur `Entrée` sans saisir de phrase de passe, `age` génère automatiquement une passphrase aléatoire et l'affiche sur le terminal. Or, dans `executer_sauvegarde_ram.sh`, le script enchaîne immédiatement et sans pause avec `par2 create` (très verbeux), puis `cryptsetup open` et `rsync --info=progress2`, faisant défiler le terminal et risquant de faire perdre la passphrase auto-générée.


* **Impact :** **Disponibilité.** Capsule de secours `.tar.zst.age` ou sauvegarde d'en-tête `luks_header_qr.bak.age` inutilisable si l'opérateur n'a pas noté la phrase auto-générée.


* **Recommandation de correction :**
Demander une confirmation interactive ou marquer une pause explicite après `age -p` si une phrase auto-générée a pu être affichée, afin que l'opérateur puisse la vérifier avant la suite du flux.



---

#### `AUD-15` — [FAIBLE] Absence de `shred` sur `.qrpayload`, absence de `-B` sur Python et absence de `--` dans `creer_sauvegarde_qr.sh`

* **Fichier et lignes :** `creer_sauvegarde_qr.sh` (lignes 34–35, 49, 59, 64, 72, 80, 89).


* **Description et scénario :**
Dans `creer_sauvegarde_qr.sh` :
* Ligne 59 : `rm -f "$tmp"` est utilisé au lieu de `shred -u -z -n 1 -- "$tmp"` pour supprimer les fichiers temporaires `.qrpayload`.


* Lignes 64, 72, 80, 89 : `python3` est invoqué sans l'option `-B` (contrairement à `consulter_coffre_ro.sh`), ce qui crée `__pycache__` dans `$SCRIPT_DIR` lorsque `creer_sauvegarde_qr.sh` est exécuté en mode autonome hors de `executer_sauvegarde_ram.sh`.


* Lignes 34, 35, 49 : `readlink -f "$CSV"`, `basename "$CSV" .csv` et `split -b 500 "$CSV"` n'utilisent pas le séparateur d'options `--`.




* **Impact :** **Hygiène / Robustesse.** Création possible de `__pycache__` et rémanence de `.qrpayload` en usage autonome hors RAM ; échec sur nom de fichier débutant par `-`.


* **Recommandation de correction :**
Ajouter `export PYTHONDONTWRITEBYTECODE=1`, passer `-B` à `python3`, remplacer `rm -f "$tmp"` par `shred -u -z -n 1 -- "$tmp" 2>/dev/null || rm -f -- "$tmp"`, et ajouter `--` aux appels `readlink`, `basename` et `split`.



---

#### `AUD-16` — [FAIBLE] Exposition des métadonnées sur `URGENCE_QR` et accumulation des anciennes capsules

* **Fichier et lignes :** `executer_sauvegarde_ram.sh` (lignes 509–510, 545–546, 617–632).


* **Description et scénario :**
Sur la partition non chiffrée `URGENCE_QR` (exFAT), le nom de la capsule `sauvegarde_qr_<nom_du_csv>_YYYYMMDD_HHMMSS.tar.zst.age` ainsi que sa taille exacte et `README.md` sont visibles en clair par quiconque connecte la clé USB. De plus, lors des sauvegardes successives, les anciennes capsules `.tar.zst.age` et `.par2` ne sont pas purgées sur `URGENCE_QR`, ce qui finit par saturer les 256 MiB de la partition et laisse d'anciennes archives exposées.


* **Impact :** **Confidentialité des métadonnées / Disponibilité.** Fuite de la nature de la clé, de l'horodatage exact et du volume de la sauvegarde ; saturation à terme de `URGENCE_QR`.


* **Recommandation de correction :**
Proposer la suppression sécurisée (`shred -u`) des anciennes capsules sur `URGENCE_QR` après validation de la nouvelle copie, et utiliser optionnellement un nom générique (`backup_archive.tar.zst.age`) sur la partition non chiffrée.



---

#### `AUD-17` — [FAIBLE] Marge verticale critique en format confort $3\times 4$ (`54 mm`) sous WeasyPrint

* **Fichier et lignes :** `generer_planches_qr.py` (lignes 93–145).


* **Description et scénario :**
En grille confort $3\times 4$ avec `--qr-mm 54`, les 4 rangées occupent $4 \times (54 + 1 + 10 + 3) = 272\text{ mm}$ auxquels s'ajoutent l'en-tête et le pied de page ($\approx 8\text{ mm}$), soit $\approx 280\text{ mm}$ pour une hauteur utile A4 de $297 - 14 = 283\text{ mm}$. Si la police `DejaVu Sans` est absente et substituée par une police légèrement plus haute, chaque planche déborde sur une page supplémentaire quasi vide.


* **Impact :** **Ergonomie d'impression.** Risque de pagination doublée si les métriques de police varient légèrement.


* **Recommandation de correction :**
Réduire le `padding` vertical de `table.grid td` à `1mm` (au lieu de `1.5mm`) ou la hauteur de `.label` à `9mm` pour conserver une marge de sécurité de $7\text{ mm}$.



---

#### `AUD-18` — [INFO] Refus des périphériques `/dev/loopX` empêchant les tests loopback prescrits par `AGENTS.md`

* **Fichiers et lignes :** `init_usb_coffre.sh` (lignes 221–227) ; `executer_sauvegarde_ram.sh` (lignes 215–221) ; `consulter_coffre_ro.sh` (lignes 187–193) ; `AGENTS.md` (lignes 95–97).


* **Description et scénario :**
`AGENTS.md` impose de tester les scripts USB sur des périphériques loopback (`losetup`). Or `validate_usb_device` exige `TYPE == "disk"` et `(RM == "1" || TRAN == "usb")`, alors qu'un périphérique `/dev/loop0` créé par `losetup -Pf` possède `TYPE="loop"`, `RM="0"` et `TRAN=""`, ce qui bloque tout test sur image disque loopback sans modification du script.


* **Impact :** **Testabilité.** Impossibilité d'exécuter le protocole de test non destructif documenté dans `AGENTS.md`.


* **Recommandation de correction :**
Autoriser un drapeau explicite `--allow-loopback` réservé aux périphériques de type `loop` (`[[ "$type" == "loop" ]]`) :
```bash
if (( ALLOW_LOOPBACK )) && [[ "$type" == "loop" ]]; then
  info "Mode test loopback activé sur $dev."
else
  [[ "$type" == "disk" ]] || die "Passez le disque entier (ex. /dev/sdX), pas une partition."
  if [[ "$rm" != "1" && "$tran" != "usb" ]]; then
    die "Le périphérique n'est pas identifié comme amovible/USB (RM=$rm, TRAN=$tran)."
  fi
fi

```



---

## 3. Bilan de cohérence code ↔ documentation (état initial)

> [!NOTE]
> Ce tableau est conservé comme trace de l'écart initial. Les actions qu'il
> recommande ont été traitées ou documentées ; il ne décrit pas l'état courant
> du dépôt.

| Sujet / Élément | Documentation (`AGENTS.md`, `README.md`, `docs/`) | Implémentation réelle dans le code | Impact et action requise |
| --- | --- | --- | --- |
| **Désactivation du Swap en consultation** | `AGENTS.md` (§ 2) indique que `consulter_coffre_ro.sh` exécute `swapoff -a`.

 | `consulter_coffre_ro.sh` n'appelle jamais `swapoff -a` (ni `init_usb_coffre.sh`).

 | **Critique (`AUD-02`)** : ajouter `swapoff -a` dans `consulter_coffre_ro.sh` et `init_usb_coffre.sh`. |
| **Option `noexec` sur `/mnt/ram_sec**` | `AGENTS.md` (§ 2) indique que `/mnt/ram_sec` est monté avec `-o noswap,nodev,nosuid,noexec,mode=0700`.

 | `executer_sauvegarde_ram.sh` et `consulter_coffre_ro.sh` montent `/mnt/ram_sec` **sans `noexec**` (car `creer_sauvegarde_qr.sh` rend `extraire_entree.py` exécutable).

 | Mettre à jour `AGENTS.md` (puisque `python3` est invoqué explicitement, `noexec` pourrait même être activé). |
| **Compatibilité KeePassXC** | `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md` (Phase 2, étape 5) et `generer_index_qr.py` mentionnent KeePassXC et Bitwarden.

 | Seuls les noms de colonnes CSV de Bitwarden (`name`, `folder`, `login_uri`, `login_username`) sont pris en charge.

 | **Critique (`AUD-03`)** : ajouter le mapping des colonnes KeePassXC (`Title`, `Group`, `URL`, `Username`). |
| **Comportement sans WeasyPrint** | `AGENTS.md` (§ Commandes) indique : *« sans WeasyPrint, les PDF ne sont pas produits (le HTML l'est) »*.

 | `generer_planches_qr.py` sort en erreur (`return 1`), ce qui interrompt `creer_sauvegarde_qr.sh` avec `set -e`.

 | **Moyen (`AUD-12`)** : retourner `0` dans `generer_planches_qr.py` après génération du HTML si WeasyPrint est absent. |
| **Binaires statiques sur `URGENCE_QR**` | `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md` indique que `URGENCE_QR` stocke les binaires statiques `age`, `zstd` et `par2` (Linux/Windows/macOS).

 | `init_usb_coffre.sh` et `executer_sauvegarde_ram.sh` ne copient aucun binaire exécutable sur `URGENCE_QR`.

 | Aligner la documentation d'architecture ou ajouter un dossier optionnel `bin/` à copier sur `URGENCE_QR`. |
| **Taille de `URGENCE_QR**` | `AGENTS.md` et `docs/GUIDE_OPERATOIRE_COFFRE_USB.md` mentionnent `255 Mo`.

 | `init_usb_coffre.sh` partitionne avec `-256MiB 100%` ($255\text{ MiB}$ utiles en tenant compte du GPT secondaire, soit $\approx 267\text{ Mo}$).

 | Harmoniser les unités (`256 MiB`) dans les documents. |
| **Tests sur loopback (`losetup`)** | `AGENTS.md` (§ Vérification d'un changement) prescrit de tester les scripts USB avec `losetup`.

 | `validate_usb_device` rejette tout périphérique `TYPE=loop` (`RM=0`, `TRAN=""`).

 | Ajouter une option `--allow-loopback` dans les 3 scripts USB (`AUD-18`). |
| **Mise hors tension USB en fin de sauvegarde** | `docs/Sauvegarde_USB_Chiffrée_sous_Linux.md` (Phase 4) exécute `udisksctl power-off -b "${USB_DEV}"`.

 | `executer_sauvegarde_ram.sh` démonte et ferme LUKS2, mais n'exécute pas `udisksctl power-off`.

 | Ajouter `udisksctl power-off` optionnel ou documenter l'étape. |
| **Exemples de copie depuis/vers `~/Documents` dans le Guide Opératoire** | `docs/GUIDE_OPERATOIRE_COFFRE_USB.md` (§ 1 étape 3 et § 2 étape 4) propose `cp ~/Documents/qrcode/export.csv /mnt/ram_sec/...` et `cp /mnt/ram_sec/sorties/restauration.csv ~/Documents/...`.

 | Contredit directement le modèle de menace « Zéro rémanence disque » et les avertissements de `executer_sauvegarde_ram.sh`.

 | Corriger `docs/GUIDE_OPERATOIRE_COFFRE_USB.md` pour proscrire toute copie du CSV en clair sur `~/Documents`. |

---

## 4. Résultats des vérifications et scénarios de test synthétiques

### 4.1. Contrôle syntaxique et statique

L'analyse statique complète de l'arbre syntaxique des modules Python (`generer_index_qr.py`, `generer_planches_qr.py`, `extraire_entree.py`) et des scripts Bash (`creer_sauvegarde_qr.sh`, `init_usb_coffre.sh`, `executer_sauvegarde_ram.sh`, `consulter_coffre_ro.sh`) confirme une syntaxe Python 3.10+ et Bash valide.

### 4.2. Validation des scénarios limites sur données synthétiques

| Scénario de test synthétique | Résultat dans le pipeline actuel | Analyse technique du comportement |
| --- | --- | --- |
| **1. Caractères UTF-8 multi-octets (`é`, `€`, emoji `🔒`) coupés exactement au 500e octet** | **Partiel (Succès si encodage homogène, Échec en cas hybride CP1252/C1)** | Si Binary Eye décode chaque morceau en Latin-1 ou CP1252 pur, `candidats_depuis_texte` restitue les octets exacts. En revanche, si un morceau contient à la fois `€` (`0x80` $\rightarrow$ `U+20AC`) et un octet non défini en CP1252 (`0x81`, `0x8D`, `0x8F`, `0x90`, `0x9D`, ex. dans `Á` ou un emoji), `latin-1` et `cp1252` lèvent tous deux `UnicodeEncodeError` (**`AUD-07`**).

 |
| **2. Espaces insécables (`\xc2\xa0` / `U+00A0`)** | **Succès sur restauration globale / Échec sur extraction ciblée si NBSP dans métadonnées** | `index_meta.json` stocke bien `sha256_sans_nbsp` (`raw.replace(b"\xc2\xa0", b" ")`). Mais `extraire_entree.py` compare `row[pos] == valeur` sans normaliser `U+00A0` en `" "` : si le NBSP figure dans `name`, `folder`, `login_uri` ou `login_username`, l'entrée est introuvable depuis `binary_eye_all_qr.json` (**`AUD-05`**).

 |
| **3. Champs CSV multilignes entre guillemets** | **Succès sur `\n` et `\r\n` / Échec sur `U+2028` ou `\x85**` | `charger_enregistrements` reconstruit exactement les offsets d'octets des champs multilignes tant que les sauts de ligne sont `\n` ou `\r\n`. Si une note contient un séparateur Unicode (`U+2028`, `\x85`, `\x0b`), `splitlines(keepends=True)` coupe la ligne et désynchronise `csv.reader` (**`AUD-08`**).

 |
| **4. Variantes CRLF et LF avec et sans saut de ligne final** | **Succès en indexation / Écart de taille en sortie d'extraction LF** | L'indexation conserve les octets exacts avec ou sans saut de ligne final. Toutefois, `ecrire_sortie()` dans `extraire_entree.py` force `lineterminator="\r\n"` et rapporte donc une taille supérieure de $\ge 1$ octet à `longueur_octets` lorsque le CSV source est en LF (**`AUD-13`**).

 |
| **5. Export CSV $> 650$ morceaux ($> 325\text{ Kio}$)** | **ÉCHEC CRITIQUE** | `split -b 500` sans `-a 2` nomme le 651e morceau `morceau_zaa`, ignoré par `morceau_??`, causant une troncature silencieuse (**`AUD-01`**).

 |

### 4.3. Protocole de test complémentaire recommandé sur image loopback (`losetup`)

Le drapeau `--allow-loopback` étant désormais disponible, exécuter dans un environnement de test isolé la séquence suivante (avec un fichier image de $1,5\text{ Gio}$ en `/tmp`) pour valider bout en bout le partitionnement GPT, LUKS2, l'enclave RAM et la consultation en lecture seule sans toucher aux disques physiques :

```bash
# 1. Création d'un disque virtuel de 1,5 Gio attaché en loopback
mkdir -p /tmp/audit_qr_loop
truncate -s 1536M /tmp/audit_qr_loop/usb_test.img
LOOP_DEV="$(sudo losetup --find --show --partscan /tmp/audit_qr_loop/usb_test.img)"

# 2. Test d'initialisation LUKS2 + exFAT (avec --allow-loopback et --argon2-mib 256)
sudo ./init_usb_coffre.sh --allow-loopback --argon2-mib 256 --argon2-threads 2 "$LOOP_DEV"

# 3. Test d'orchestration en RAM sans impression avec CSV synthétique
sudo ./executer_sauvegarde_ram.sh --allow-loopback --ram-size 256M --no-print "$LOOP_DEV" /tmp/audit_qr_loop/synth.csv

# 4. Test de consultation en lecture seule et vérification de fermeture propre des mappers
sudo ./consulter_coffre_ro.sh --allow-loopback --ram-size 128M --restaurer --export /tmp/audit_qr_loop/binary_eye_all_qr.json "$LOOP_DEV"

# 5. Nettoyage du périphérique loopback
sudo losetup -d "$LOOP_DEV"
rm -rf /tmp/audit_qr_loop

```

---

## 5. Plan de remédiation priorisé

### Phase 1 : Actions immédiates (Corrections bloquantes — Sévérité CRITIQUE & ÉLEVÉE)

1. **Fiabiliser la segmentation `split` (`AUD-01`)** : Ajouter `-a 2` à `split -b 500`, vérifier en amont que la taille du CSV est $\le 338\,000$ octets (ou passer à `-a 3` et `morceau_???` si des portefeuilles $> 338\text{ Kio}$ sont visés) et contrôler que le nombre de PNG générés égale `total_chunks`.


2. **Garantir l'anti-rémanence Swap dans tous les scripts (`AUD-02`, `AUD-09`)** : Ajouter `swapoff -a` (et sa restauration dans `cleanup()`) dans `consulter_coffre_ro.sh` et `init_usb_coffre.sh` ; dans `init_usb_coffre.sh`, ajouter `ulimit -c 0` et monter un `tmpfs` dédié avec `noswap` au lieu d'utiliser `/dev/shm` ; dans `stop_cups_spool()`, écraser les fichiers par `shred` avant démontage et stopper `cups.path`.


3. **Supporter nativement KeePassXC et le BOM UTF-8 (`AUD-03`, `AUD-08`)** : Ajouter les alias de colonnes KeePassXC (`Title`, `Group`, `URL`, `Username`), retirer un éventuel `\ufeff` initial sur `header[0]`, et remplacer `text.splitlines(keepends=True)` par un découpage strict sur `\r\n`, `\n` et `\r`.


4. **Durcir la validation des périphériques blocs (`AUD-04`)** : Utiliser `findmnt -n -v -o SOURCE` dans `is_system_disk()`, vérifier les `holders` sur toutes les partitions `${name}*`, et inclure `raid*` dans les types `lsblk` refusés.


5. **Corriger l'extraction depuis Binary Eye (`AUD-05`, `AUD-06`, `AUD-07`)** : Normaliser les espaces insécables `U+00A0` lors de la recherche dans `extraire_par_recherche()`, utiliser un gestionnaire d'erreurs `cp1252_raw` pour les octets `0x81..0x9D`, et privilégier `utf-8` lorsque la taille du morceau est exacte afin d'éviter toute altération et toute explosion combinatoire.



### Phase 2 : Améliorations structurelles (Sévérité MOYENNE, FAIBLE & Documentation)

1. **Sécuriser les permissions dès la création des fichiers (`AUD-11`, `AUD-15`)** : Appeler `os.umask(0o077)` au démarrage de chaque script Python, précréer les fichiers `.age` en mode `0600` avant `runuser`, et utiliser `shred -u` sur les fichiers `.qrpayload`.


2. **Fiabiliser les démontages et le comportement sans WeasyPrint (`AUD-10`, `AUD-12`)** : Avertir explicitement l'opérateur si `cryptsetup close` échoue après un `umount -l`, et retourner `0` dans `generer_planches_qr.py` lorsque WeasyPrint est absent.


3. **Mettre en cohérence la documentation et la testabilité (`AUD-13`, `AUD-14`, `AUD-16`, `AUD-18`)** : Ajouter `--allow-loopback` pour permettre les tests `losetup`, corriger les exemples de copie sur `~/Documents` dans `docs/GUIDE_OPERATOIRE_COFFRE_USB.md`, et harmoniser `AGENTS.md` avec l'implémentation.

L'examen du code source complet de `restaurer_sauvegarde.py` permet de finaliser l'audit de bout en bout du dépôt `ki2pixel-qrcode`. Si ce script implémente de bonnes pratiques d'hygiène (telles que `sys.dont_write_bytecode = True` dès la ligne 36 avant l'import de `extraire_entree`, la détection des morceaux manquants ou traduits, et le tri par priorité d'empreinte SHA-256 exacte puis normalisée sans `NBSP`), son analyse ligne par ligne révèle **5 nouveaux constats (`AUD-19` à `AUD-23`)**, dont **1 critique** et **2 élevés**, qui viennent compléter la matrice d'audit initiale.

---

## 1. Synthèse des nouveaux constats propres à `restaurer_sauvegarde.py`

| ID | Sévérité | Fichier(s) et lignes | Titre du constat |
| --- | --- | --- | --- |
| **AUD-19** | **CRITIQUE** | `restaurer_sauvegarde.py` (lignes 58–74, 208–234)

 | Réécriture forcée du CSV par `csv.writer` (`QUOTE_MINIMAL`) avant le calcul SHA-256, cassant la restauration des exports avec guillemets (ex. KeePassXC) ou fins de ligne mixtes

 |
| **AUD-20** | **ÉLEVÉ** | `restaurer_sauvegarde.py` (lignes 11, 41–55, 134, 184–206)

 | Explosion mémoire/CPU dans `etats` (copies quadratiques $O(N^2)$ et croissance en $O(2^k)$) et non-utilisation de `taille_octets`

 |
| **AUD-21** | **ÉLEVÉ** | `restaurer_sauvegarde.py` (lignes 187–206) ; `extraire_entree.py` (lignes 88–113)

 | Corruption de l'octet `0xA0` (notamment la lettre `à` = `\xc3\xa0`) par la normalisation `NBSP` de Binary Eye dans les morceaux contenant un caractère UTF-8 coupé en bord de bloc

 |
| **AUD-22** | **MOYEN** | `restaurer_sauvegarde.py` (lignes 265–274) ; `consulter_coffre_ro.sh` (lignes 127–132, 285–293, 449, 480)

 | Destruction immédiate de `restauration.csv` sans pause d'inspection lorsque `restaurer_sauvegarde.py` retourne `1` (`DIFFÉRENT`) sous `consulter_coffre_ro.sh`

 |
| **AUD-23** | **FAIBLE** | `restaurer_sauvegarde.py` (lignes 41–45, 134–135, 242–244)

 | Écriture de `restauration.csv` avant `chmod(0o600)` (fenêtre TOCTOU) et absence de vérification d'existence sur `--morceaux` et `--meta`

 |

---

## 2. Analyse technique détaillée et correctifs

### `AUD-19` — [CRITIQUE] Réécriture forcée du CSV par `reconstruire_csv()` avant vérification SHA-256, rendant `DIFFÉRENT` tout CSV à guillemets non minimaux ou fins de ligne mixtes

* **Fichier et lignes :** `restaurer_sauvegarde.py`, lignes 58–74 et 208–234.


* **Description et scénario de défaillance :**
Dans la boucle d'évaluation des candidats (lignes 208–234), `restaurer_sauvegarde.py` ne teste **jamais** l'empreinte SHA-256 du flux d'octets brut `data` issu de la concaténation des morceaux. Il passe systématiquement `data` à `reconstruire_csv(data)` (lignes 58–66), qui parse le texte via `csv.reader` puis le resérialise intégralement via `csv.writer(buf, lineterminator="\r\n")` avec la politique de guillemets par défaut de Python (`quoting=csv.QUOTE_MINIMAL`).
Ce comportement provoque un échec de vérification (`Résultat : DIFFÉRENT`, code de sortie `1`) dans trois cas réels alors même que les scans QR contiennent les octets exacts d'origine :


1. **Exports CSV avec guillemets systématiques (`QUOTE_ALL`), comme KeePassXC :** KeePassXC entoure tous les champs de guillemets doubles (`"Group","Title","Username","Password",...`). Lors du passage dans `reconstruire_csv(data)`, `csv.reader` retire les guillemets et `csv.writer` (`QUOTE_MINIMAL`) réécrit les champs sans guillemets s'ils ne contiennent ni virgule ni saut de ligne. Le flux réécrit a donc une taille et un SHA-256 totalement différents du CSV d'origine.


2. **Champs vides explicitement guillemetés (`""`) ou espaces de formatage CSV :** Réécrits en champs vides non guillemetés par `csv.writer`.


3. **Fins de ligne mixtes (enregistrements séparés par `CRLF` `\r\n`, mais notes multilignes contenant des `LF` `\n` internes) :** `variantes_fins_de_ligne(avec_final)` (lignes 69–74) génère soit `avec_final` (qui conserve `\n` dans les champs et `\r\n` en fin d'enregistrement), soit `v.replace(b"\r\n", b"\n")` (qui remplace tous les `\r\n` par `\n`). Si le CSV d'origine avait des fins de ligne d'enregistrement en `LF` (`\n`) mais qu'un champ `notes` collé depuis un presse-papiers contenait un `\r\n`, `reconstruire_csv` force les fins d'enregistrement en `\r\n` et `v.replace(b"\r\n", b"\n")` écrase le `\r\n` interne du champ `notes`, rendant impossible la correspondance SHA-256 alors que `data` brut possédait déjà le bon SHA-256.




* **Impact :** **Intégrité / Disponibilité.** Échec de validation SHA-256 (`Résultat : DIFFÉRENT`, sortie en code `1`) sur des sauvegardes pourtant intactes (notamment 100 % des exports KeePassXC).


* **Recommandation de correction :**
Inclure les variantes de fins de ligne directement sur le flux brut `data` (sans réécriture par `csv.writer`) **en plus** des variantes reconstruites par `reconstruire_csv(data)` :
```diff
--- a/restaurer_sauvegarde.py
+++ b/restaurer_sauvegarde.py
@@ -208,11 +208,17 @@
     resultats = []
     for data, _choix in etats:
         try:
+            rows_brut = list(csv.reader(io.StringIO(data.decode("utf-8"))))
             avec_final, rows = reconstruire_csv(data)
         except (UnicodeDecodeError, csv.Error):
             continue
+        candidats_csv = []
+        for v in variantes_fins_de_ligne(data) + variantes_fins_de_ligne(avec_final):
+            if v not in candidats_csv:
+                candidats_csv.append(v)
         # L'export d'origine peut utiliser CRLF ou LF, avec ou sans retour à la
         # ligne après le dernier champ. On essaie toutes les variantes.
-        for restaure in variantes_fins_de_ligne(avec_final):
+        for restaure in candidats_csv:
             digest = hashlib.sha256(restaure).hexdigest()

```



---

### `AUD-20` — [ÉLEVÉ] Explosion mémoire/CPU dans `etats` (copies quadratiques $O(N^2)$ et croissance exponentielle $O(2^k)$) et non-utilisation de `taille_octets`

* **Fichier et lignes :** `restaurer_sauvegarde.py`, lignes 11, 41–55, 134, 184–206.


* **Description et scénario de défaillance :**
1. **Omission de `taille_octets` :** Bien que l'en-tête du script affirme `lit l'ordre et la taille des morceaux dans csv/index_morceaux.csv` (ligne 11), `restaurer_sauvegarde.py` n'utilise jamais la colonne `taille_octets` de `index_morceaux.csv` pour filtrer ou ordonner les candidats de chaque morceau.


2. **Croissance exponentielle du nombre d'états :** Aux lignes 187–206, `etats` conserve toutes les combinaisons `(data, choix)` telles que `est_prefixe_utf8(data)` est vrai. Or, lorsqu'un morceau ne contient pas de caractère UTF-8 coupé en fin de bloc mais contient dans son corps une séquence de caractères Unicode `U+00C2..U+00DF` suivie de `U+0080..U+00BF` (ou lorsqu'un morceau décodé en Latin-1 contient des caractères accentués sans coupure finale), les deux candidats `latin-1` et `utf-8` produits par `ee.candidats_depuis_texte()` forment tous deux un préfixe UTF-8 valide. Dès que $k$ morceaux présentent cette ambiguïté sur un portefeuille de plusieurs centaines de QR codes, `len(etats)` double à chaque morceau ($2^k$ états), saturant les 512 MiB de `/mnt/ram_sec`.


3. **Copies mémoire quadratiques et stockage inutile de `choix` :** À chaque itération $i \in [1..N]$, `data = prefixe + cand` recopie tout le préfixe depuis l'octet 0, `choix + [cand]` duplique la liste des morceaux (alors que `_choix` est ignoré ligne 209), et `est_prefixe_utf8(data)` redécode l'intégralité de `data` depuis le premier octet au lieu de ne valider que la frontière entre `prefixe` et `cand`.




* **Impact :** **Disponibilité.** Consommation excessive de RAM/CPU et risque d'arrêt par `MemoryError` dans l'enclave `tmpfs` contrainte à 512 MiB.


* **Recommandation de correction :**
1. Supprimer la liste inutile `choix` dans `etats` (`etats: list[bytes] = [b""]`).


2. Ne tester `est_prefixe_utf8` que sur les 4 derniers octets de `prefixe` concaténés à `cand` (`est_prefixe_utf8(prefixe[-4:] + cand)`), et valider `final=True` sur le dernier morceau.


3. Ordonner les candidats de chaque morceau en privilégiant celui dont la longueur correspond à `int(row["taille_octets"])` (ou `taille_octets` ajustée du nombre de `NBSP`).





---

### `AUD-21` — [ÉLEVÉ] Corruption de l'octet `0xA0` (notamment la lettre `à` = `\xc3\xa0`) dans les morceaux contenant un caractère UTF-8 coupé en fin de bloc

* **Fichiers et lignes :** `restaurer_sauvegarde.py` (lignes 187–206) ; `extraire_entree.py` (lignes 88–113).


* **Description et scénario de défaillance :**
En UTF-8, plusieurs caractères très fréquents en français possèdent **`0xA0` (`\xa0`) comme second octet** : c'est le cas de la lettre **`à` (`U+00E0`, encodée `\xc3\xa0`)**, de l'espace insécable (`U+00A0`, encodé `\xc2\xa0`) ou de `Š` (`U+0160`, encodé `\xc5\xa0`).
Lorsqu'un morceau de 500 octets coupe un caractère UTF-8 multi-octets quelconque à sa frontière (ex. l'octet 500 est `\xc3`), les octets du morceau ne forment pas une séquence UTF-8 valide : le lecteur QR (ZXing / Binary Eye) bascule alors sur un décodage octet par octet en **ISO-8859-1 (Latin-1)** pour l'ensemble de ce morceau.
Or, en ISO-8859-1 :


* L'octet `0xC3` de la lettre `à` (`\xc3\xa0`) devient `U+00C3` (`Ã`) ;
* L'octet `0xA0` de la lettre `à` (`\xc3\xa0`) devient **`U+00A0` (espace insécable)** !
Lorsque Binary Eye applique sa normalisation remplaçant `U+00A0` par un espace standard `U+0020` (` `), la lettre `à` dans ce morceau devient `U+00C3 U+0020` (`"Ã "`).
Ensuite, lorsque `candidats_depuis_texte()` ré-encode ce morceau en `latin-1`, `"Ã "` produit les octets `b"\xc3\x20"` (`0xC3 0x20`). Comme `0x20` n'est pas un octet de continuation UTF-8 valide (`0x80..0xBF`), `est_prefixe_utf8(data)` renvoie `False` pour le candidat `latin-1`, et renvoie `False` au morceau suivant pour le candidat `utf-8`, faisant échouer la restauration avec :
`Aucun encodage valide pour le morceau morceau_xx.`.




* **Impact :** **Intégrité / Disponibilité.** Échec de restauration complète (`restaurer_sauvegarde.py`) et d'extraction (`extraire_entree.py`) dès qu'un morceau ayant un caractère UTF-8 coupé à sa frontière contient également la lettre `à` (`\xc3\xa0`) ou un espace insécable (`\xc2\xa0`) normalisé par Binary Eye.


* **Recommandation de correction :**
Dans `candidats_depuis_texte()` (`extraire_entree.py`), après l'encodage `latin-1`/`cp1252`, générer un candidat complémentaire qui restaure l'octet de continuation `0xA0` lorsqu'un octet de tête UTF-8 (`0xC2..0xDF` ou suite d'amorce 3/4 octets) est immédiatement suivi d'un espace `0x20` :
```python
import re
# Répare les octets 0xA0 transformés en 0x20 après un octet de tête UTF-8 en mode Latin-1
repare = re.sub(b"([\xc2-\xdf]|[\xe0-\xef][\x80-\xbf]|[\xf0-\xf4][\x80-\xbf]{2}) ", b"\\1\xa0", brut)
if repare not in candidats:
    candidats.append(repare)

```



---

### `AUD-22` — [MOYEN] Destruction immédiate de `restauration.csv` sans pause d'inspection lorsque `restaurer_sauvegarde.py` retourne `1` (`DIFFÉRENT`) sous `consulter_coffre_ro.sh`

* **Fichiers et lignes :** `restaurer_sauvegarde.py` (lignes 265–274) ; `consulter_coffre_ro.sh` (lignes 127–132, 285–293, 449, 480).


* **Description et scénario de défaillance :**
Lorsque le fichier reconstruit ne correspond pas au SHA-256 attendu, `restaurer_sauvegarde.py` écrit le fichier `restauration.csv`, affiche (lignes 269–273) :
`Le CSV a été écrit pour inspection, mais il ne correspond pas à l'original.`
et se termine avec `return 1` (ligne 274).
Or, `consulter_coffre_ro.sh` s'exécute sous `set -Eeuo pipefail` avec `trap 'on_error $? $LINENO' ERR` et appelle `restore_all "$OUT_FILE"` sans intercepter son code de retour (lignes 449 et 480). Dès que `restaurer_sauvegarde.py` retourne `1`, `consulter_coffre_ro.sh` déclenche `on_error` puis `cleanup()`, qui écrase tous les fichiers de `/mnt/ram_sec` avec `shred` et démonte l'enclave RAM **sans exécuter la pause de la ligne 495** (`read -r -p "Appuie sur Entrée pour tout effacer... "`).


* **Impact :** **Disponibilité / Ergonomie de secours.** En cas de divergence d'empreinte (par exemple un caractère altéré lors d'un scan de secours), l'opérateur utilisant `consulter_coffre_ro.sh` ne peut jamais inspecter ni récupérer le fichier `restauration.csv` généré en RAM.


* **Recommandation de correction :**
Dans `consulter_coffre_ro.sh`, intercepter le code de retour non nul de `restore_all` afin d'avertir l'opérateur tout en atteignant l'étape de pause avant destruction :
```diff
--- a/consulter_coffre_ro.sh
+++ b/consulter_coffre_ro.sh
@@ -446,7 +446,9 @@
 section "Action"
 if (( RESTAURER )); then
   OUT_FILE="$SORTIES/restauration.csv"
-  restore_all "$OUT_FILE"
+  if ! restore_all "$OUT_FILE"; then
+    warn "La restauration présente une différence d'empreinte SHA-256. Inspectez $OUT_FILE en RAM."
+  fi

```



---

### `AUD-23` — [FAIBLE] Fenêtre TOCTOU sur `sortie.chmod(0o600)` et exceptions non gérées si `index_morceaux.csv` ou `index_meta.json` sont absents

* **Fichier et lignes :** `restaurer_sauvegarde.py`, lignes 41–45, 134–135, 242–244.


* **Description et scénario de défaillance :**
1. Aux lignes 242–244, `sortie.write_bytes(restaure)` écrit l'intégralité du portefeuille de mots de passe en clair sur le système de fichiers avant d'appeler `sortie.chmod(0o600)`. En exécution autonome hors de `/mnt/ram_sec` avec un `umask` standard (`0022`), le fichier est brièvement lisible en `0644` pendant l'écriture.


2. Aux lignes 134–135, `charger_morceaux(Path(args.morceaux))` et `Path(args.meta).read_text(...)` sont appelés sans vérifier l'existence des fichiers, provoquant un traceback `FileNotFoundError` brut au lieu d'un `SystemExit` explicite si l'un des fichiers est absent.




* **Impact :** **Confidentialité locale (TOCTOU) / Robustesse CLI.**
* **Recommandation de correction :**
Ajouter `import os; os.umask(0o077)` au début de `main()` et vérifier l'existence de `Path(args.morceaux)` et `Path(args.meta)` avant lecture :


```diff
--- a/restaurer_sauvegarde.py
+++ b/restaurer_sauvegarde.py
@@ -26,6 +26,7 @@
 import csv
 import hashlib
 import io
 import json
+import os
 import sys
 from pathlib import Path
@@ -76,6 +77,7 @@
 def main() -> int:
+    os.umask(0o077)
     parser = argparse.ArgumentParser(
@@ -131,6 +133,12 @@
     if not scan_dir.is_dir():
         raise SystemExit(f"Dossier de scans introuvable : {scan_dir}")

+    if not Path(args.morceaux).is_file():
+        raise SystemExit(f"Index des morceaux introuvable : {args.morceaux}")
+    if not Path(args.meta).is_file():
+        raise SystemExit(f"Métadonnées introuvables : {args.meta}")
     morceaux = charger_morceaux(Path(args.morceaux))
     meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))

```