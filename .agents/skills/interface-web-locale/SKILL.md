---
name: interface-web-locale
description: "Use when il faut modifier, faire évoluer ou auditer l'interface web locale (HTML, CSS, JavaScript vanilla ES6, accessibilité, CSP stricte, modules generation/consultation/usb, sécurité côté client ou intégration avec l'API Flask)."
---

# Interface web locale

## Vue d'ensemble

L'interface web locale est un **assistant graphique optionnel**. Elle ne
remplace jamais les scripts CLI : `creer_sauvegarde_qr.sh`,
`extraire_entree.py`, `restaurer_sauvegarde.py` et les scripts USB restent
autonomes et constituent la source de vérité. Le frontend se contente de
préparer les mêmes opérations, de les rendre lisibles et de générer les
commandes terminal.

**Principe directeur :** le navigateur est une couche de présentation non
privilégiée. Le serveur Flask valide les entrées ; pour le coffre USB, il relit
l'état réel du système (`lsblk`) et n'exécute que le démontage non privilégié.
Le navigateur ne reçoit jamais de phrase de passe LUKS2 ou age, ne lance jamais
`sudo` et ne construit jamais lui-même une commande privilégiée.

L'interface écoute uniquement sur `127.0.0.1:5100`. Une fois le `.venv` Flask
préparé par `lancer_interface.sh`, elle n'ouvre aucune connexion sortante. Le
frontend n'utilise ni CDN, ni npm, ni bundler. Les données de travail restent
dans un répertoire de travail privé sur tmpfs (`0700`, `umask 077`, core dumps
désactivés). Les téléchargements (PDF, ZIP, CSV extrait ou restauré) sortent
volontairement de la RAM et contiennent des données en clair.

Lancement : `./lancer_interface.sh [--strict-ram] [--no-browser]`.
`--strict-ram` refuse le démarrage si un swap disque est actif ;
`--no-browser` est utilisé pour les tests et l'automatisation.

Le navigateur peut paginer ou conserver des données dans son profil :
l'interface ne remplace pas le flux coffre USB anti-rémanence pour les secrets
critiques.

**Confidentialité :** les données réelles sont hautement sensibles. Pour toute
modification ou tout test, utiliser exclusivement des CSV, scans et phrases de
passe synthétiques sous `/tmp/opencode`. Ne jamais afficher, journaliser ou
copier un secret réel.

## Quand l'utiliser

- Modifier `web/templates/index.html`, `web/templates/erreur.html`,
  `web/static/style.css`, `web/static/app.js`, `web/static/ui.js` ou un module
  `web/static/modules/*.js`.
- Ajouter ou modifier une interaction avec l'API Flask locale : session,
  génération, consultation, révélation de secrets, restauration, USB.
- Auditer la CSP, l'accessibilité, l'hygiène des secrets côté navigateur, le
  jeton de session ou les téléchargements.
- Faire évoluer l'assistant USB guidé sans lui donner de privilèges.

Ne pas utiliser ce skill pour :

- le pipeline QR lui-même : utiliser `test-sauvegarde-qr` ;
- les scripts USB, LUKS2 et l'enclave RAM : utiliser `test-coffre-loopback` ;
- l'alignement README/AGENTS/`LISEZMOI.txt` : utiliser
  `sync-docs-tripartite` en complément ;
- une modification purement backend sans impact sur le contrat d'API ou le
  frontend : vérifier d'abord le service concerné et les tests existants.

## Invariants non négociables

| Sujet | Invariant | Contrôle |
|---|---|---|
| Écoute | `127.0.0.1:5100` uniquement, jamais `0.0.0.0`, proxy ou tunnel | `ss -ltnp`, revue de `lancer_interface.sh` |
| Session | Jeton dans le fragment `#jeton=…`, échangé contre un cookie `HttpOnly`/`SameSite=Strict`, fragment retiré de l'URL | Revue de `app.js` et `web/serveur.py` |
| API | `X-QR-Web: 1` sur **tous** les appels `/api`, cookie `same-origin` | `rg 'X-QR-Web' web/static` |
| Origine | `Host` contrôlé sur toutes les requêtes, `Origin` sur les requêtes mutantes ; le frontend reste en URLs relatives | `web/securite.py` |
| CSP | Aucun `unsafe-inline`, aucun `unsafe-eval`, aucun script/style inline | En-tête CSP et revue du HTML |
| Dépendances | Aucun npm/yarn/pnpm, aucun `node_modules`, aucun bundler, aucun CDN, aucune police distante | `rg -i 'cdn|unpkg|jsdelivr|googleapis|npm' web` |
| Limites | CSV 338 000 octets, scans 16 Mio, ZIP 256 Mio, index 64 Mio, métadonnées 1 Mio ; protections zip-slip/zip-bomb ; le serveur reste l'autorité | `web/config.py` et tests de refus |
| Tmpfs | Répertoire de travail privé sous `$XDG_RUNTIME_DIR/qrcode_web_5100` ou `/dev/shm/qrcode_web_5100_<uid>`, `0700`, `umask 077`, core dumps désactivés | `web/espace_ram.py`, `lancer_interface.sh`, `web/serveur.py` |
| Secrets | Masqués par défaut, révélation explicite, re-masquage automatique ; limites de purge et exception d'URI documentées dans les points d'audit | Revue de `consultation.js` |
| USB | Aucun `sudo`, aucune phrase de passe, démontage uniquement via `udisksctl unmount --no-user-interaction` | `web/services/usb.py`, tests avec faux `lsblk` |
| Langue | Interface, messages, commentaires et nommage en français | Revue |
| Permissions | Scripts `700`, documents et sources `600` | `stat -c '%a %n'` |

## Cartographie frontend

```text
web/templates/index.html
  ├── web/static/style.css
  └── web/static/app.js          (point d'entrée, session, onglets, purge)
        ├── web/static/ui.js      (DOM, API, toasts, dialogues, téléchargements)
        ├── web/static/modules/generation.js
        ├── web/static/modules/consultation.js
        └── web/static/modules/usb.js
```

| Fichier | Responsabilité | Points de vigilance |
|---|---|---|
| `web/templates/index.html` | Squelette sémantique, sprites SVG inline, écran de session, onglets Génération/Consultation/Coffre USB, dialogues, zone de toasts | `lang="fr"`, `color-scheme: light`, lien d'évitement, `type="module"`, aucune balise `<script>` ou `<style>` inline |
| `web/static/app.js` | Amorçage, jeton du fragment, échange `POST /api/session`, `GET /api/etat`, routage des onglets, écran de session, purge globale, reprise d'une génération | Ne jamais persister le jeton ; retirer le fragment immédiatement ; n'initialiser les modules qu'une fois |
| `web/static/ui.js` | `$`/`$$`, `icone`, `echapper`, `octets`, `toast`, `api`, `envoyer`, `confirmer`, `telecharger`, `copier`, `debounce` | Tout appel `/api` doit passer par ces helpers ; `echapper` ne remplace pas une validation serveur |
| `web/static/modules/generation.js` | Dépôt du CSV, préflight client et serveur, suivi asynchrone, annulation, résultat et téléchargements | Limite 338 000 octets, `arrayBuffer` uniquement, interrogation périodique arrêtée et purgée |
| `web/static/modules/consultation.js` | Sources session/dossier/ZIP, scans Binary Eye, recherche, extraction masquée, révélation, restauration | Ne jamais précharger les secrets ; minuteur de re-masquage annulé à la purge |
| `web/static/modules/usb.js` | Assistant matériel en deux étapes, cartes de périphériques, démontage assisté, confirmation d'initialisation, commandes terminal | Aucun `sudo` exécuté ; commandes de secours uniquement issues du serveur |
| `web/static/style.css` | Charte sobre, variables CSS, responsive 980/640 px, focus visible, mouvement réduit | Aucun framework, aucune police distante, contraste conservé, mode clair forcé |

`web/templates/erreur.html` est une page autonome pour les erreurs non-API.
Elle possède son propre sprite SVG minimal ; si une icône y est ajoutée, ajouter
aussi le symbole correspondant dans `index.html` lorsque l'icône est partagée.

## Contrat d'API utilisé par le frontend

Tous les chemins ci-dessous exigent le cookie de session et l'en-tête
`X-QR-Web: 1`, sauf l'échange initial `POST /api/session` qui exige l'en-tête
mais pas encore le cookie. Les réponses d'erreur API sont de la forme
`{"erreur": "...", "code": "..."}`.

### Session et global

| Méthode | Chemin | Usage |
|---|---|---|
| `POST` | `/api/session` | Échange `{jeton}` contre le cookie `qr_web_session` |
| `GET` | `/api/etat` | Version, port, `strict_ram`, WeasyPrint, `qrencode`, `split`, swap, espace RAM, limites, TTL, générations et consultations en cours |
| `POST` | `/api/purge` | Purge globale des générations et consultations |

### Génération

| Méthode | Chemin | Usage |
|---|---|---|
| `POST` | `/api/generation/apercu` | Corps CSV brut, en-têtes `Content-Type: text/csv` et `X-QR-Fichier` |
| `POST` | `/api/generation` | Démarre le pipeline ; en-tête `X-QR-Mise-En-Page` : `compact`, `confort` ou `aucune` ; réponse `202` |
| `GET` | `/api/generation/<job_id>` | Instantané de progression |
| `POST` | `/api/generation/<job_id>/annuler` | Demande d'annulation |
| `DELETE` | `/api/generation/<job_id>` | Destruction de la génération |
| `GET` | `/api/generation/<job_id>/fichier/<cle>` | Téléchargement d'un fichier produit |

### Consultation

| Méthode | Chemin | Usage |
|---|---|---|
| `GET` | `/api/consultation/sauvegardes` | Sessions et dossiers détectés |
| `POST` | `/api/consultation/source` | `{type: "job", job_id}` ou `{type: "dossier", chemin}` |
| `POST` | `/api/consultation/archive` | Corps ZIP brut, uniquement les trois index |
| `GET` | `/api/consultation/<session_id>` | État de la session |
| `POST` | `/api/consultation/<session_id>/scans` | Corps JSON brut de `binary_eye_all_qr.json` |
| `POST` | `/api/consultation/<session_id>/recherche` | `{q}` ; 50 résultats maximum |
| `POST` | `/api/consultation/<session_id>/extraire` | `{record_id}` ; renvoie les champs visibles et les libellés masqués. L'URI est renvoyée en clair et peut contenir des identifiants intégrés |
| `POST` | `/api/consultation/<session_id>/reveler` | `{extraction_id, ligne}` ; seule voie d'obtention des valeurs masquées |
| `POST` | `/api/consultation/<session_id>/restaurer` | Restauration complète et verdict |
| `GET` | `/api/consultation/<session_id>/fichier/extraction` | Téléchargement de l'extraction |
| `GET` | `/api/consultation/<session_id>/fichier/restauration` | Téléchargement du CSV restauré |
| `DELETE` | `/api/consultation/<session_id>` | Destruction de la consultation |

### Coffre USB

| Méthode | Chemin | Usage |
|---|---|---|
| `GET` | `/api/usb/peripheriques` | Lecture seule de `lsblk`, dépendances, garde-fous et catégories |
| `POST` | `/api/usb/demonter` | `{partition}` ; exécute uniquement `udisksctl unmount --no-user-interaction -b` |
| `POST` | `/api/usb/commandes` | `{operation, peripherique, ...}` ; revalide l'état et renvoie les commandes à copier |

## Règles de développement

### 1. Zéro dépendance JavaScript

Le frontend doit fonctionner hors ligne, dans un navigateur moderne récent,
sans étape de build :

- pas de `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
  ni `node_modules` ;
- pas de Webpack, Vite, Rollup, esbuild, Parcel ou équivalent ;
- pas de jQuery, React, Vue, Alpine, Bootstrap, Tailwind ou autre bibliothèque ;
- pas de script, style, police, image ou icône chargés depuis un CDN ou un
  domaine tiers ;
- pas de `@import` CSS distant, ni de `url(http…)` ;
- imports ES6 natifs et relatifs, avec l'extension `.js` :

```js
import { $, api, echapper } from "../ui.js";
```

Les seules ressources externes au frontend sont les polices système déjà
présentes et les outils du système (navigateur, `lsblk`, `udisksctl`). Le
`.venv` Flask est une dépendance **serveur** installée par
`lancer_interface.sh` ; elle ne doit jamais être exposée au navigateur, ni
remplacée par un CDN. Ne pas ajouter de dépendance frontend pour « faciliter »
un test : le chargement réel via `./lancer_interface.sh` fait foi.

### 2. CSP et intégrité DOM

La CSP appliquée par `web/securite.py` est :

```text
default-src 'self'; base-uri 'none'; object-src 'none';
frame-ancestors 'none'; form-action 'self'; script-src 'self';
style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'
```

Conséquences directes :

- **Interdit** : `onclick`, `onchange`, `onsubmit` et tout autre attribut
  d'écouteur inline ; `<script>` inline ; `<style>` inline ; attribut `style="…"` ;
  `eval`, `new Function`, `setTimeout("code")`, `javascript:…`.
- **Obligatoire** : `addEventListener`, `textContent`, création d'éléments DOM
  et, pour le balisage statique uniquement, `innerHTML` avec des valeurs
  échappées.
- Les icônes passent par le sprite SVG local et le helper `icone("nom")`.
  Ne jamais injecter un nom d'icône provenant du serveur ou de l'utilisateur.
- Le HTML Jinja2 est auto-échappé. Ne jamais utiliser `|safe` pour une valeur
  issue d'un CSV, d'un scan, d'un nom de fichier ou d'une réponse d'API.

Motif recommandé :

```js
// Bon : contenu non fiable, création DOM.
const ligne = document.createElement("p");
ligne.textContent = donnees.message;
zone.append(ligne);

// Toléré : balisage statique + échappement explicite.
zone.innerHTML = `<span>${echapper(donnees.nom)}</span>`;

// Interdit : injection directe d'une valeur non fiable.
zone.innerHTML = `<span>${donnees.nom}</span>`;
```

`echapper()` échappe `&`, `<`, `>`, `"` et `'`. Il ne dispense pas de valider
une URL, un chemin ou un identifiant côté serveur. Pour un lien, préférer
`textContent` et une URL construite par le frontend à partir d'un identifiant
validé, jamais une URL arbitraire renvoyée par un scan.

### 3. Hygiène des secrets côté client

- Les champs classés sensibles (mot de passe, TOTP, notes, champs
  personnalisés) sont masqués par défaut par `••••••••` et leurs valeurs ne sont
  **jamais** incluses dans la réponse d'extraction initiale. Seul
  `POST /reveler` les renvoie, après un clic explicite sur l'œil. L'URI est une
  exception documentée ci-dessous.
- La révélation globale (`#cons-bouton-reveler`) doit rester une action
  explicite. Ne jamais révéler au chargement, au survol, au focus ou dans un
  `title`.
- Le minuteur de re-masquage utilise `document.body.dataset.ttl` (UX), mais la
  sécurité réelle est le TTL serveur de 60 minutes. Ne pas considérer le minuteur
  client comme une protection.
- Lors du masquage, supprimer la valeur du DOM (`delete valeur.dataset.valeur`)
  et remettre le libellé du bouton à « Afficher le secret ».
- À la purge, réinitialiser les structures JavaScript des modules qui
  détiennent des données de session : génération et consultation dans
  l'implémentation actuelle, USB après correction du point d'audit. Annuler les
  intervalles et minuteurs, vider les zones DOM et les messages. Le bouton
  « Purger la session » doit purger les fichiers de travail du répertoire
  privé sur tmpfs côté serveur et l'état côté client ; le répertoire privé est
  supprimé à l'arrêt, mais le tmpfs sous-jacent (`/dev/shm` ou
  `XDG_RUNTIME_DIR`) n'est pas démonté par l'application.
- **Interdit** : `localStorage`, `sessionStorage`, IndexedDB, cookies écrits
  par le JS, `window.name`, journalisation console, journalisation d'un corps
  de requête, URL contenant un secret, attribut `data-*` persistant.
- **Interdit** de copier un mot de passe dans le presse-papiers. `copier()`
  est réservé aux commandes terminal et aux valeurs non secrètes.
- Les téléchargements CSV extraits/restaurés sont en clair : le rappel visuel
  doit rester visible. Ne pas lancer automatiquement un téléchargement de
  secrets. La purge ne supprime pas les fichiers déjà téléchargés (PDF, ZIP,
  CSV) : le dialogue de confirmation doit le rappeler.
- Exception actuelle : `uri` est renvoyée en clair par `/extraire` et peut
  contenir des identifiants intégrés. Voir les points d'audit ci-dessous.
- Pour ajouter un champ, vérifier côté serveur `CHAMPS_SURS` et
  `LIBELLES_MASQUES` dans `web/services/consultation.py`. Le frontend ne doit
  pas décider seul qu'un champ est sûr.

#### Points d'audit connus

Plusieurs écarts sont à corriger lors d'une évolution :

- `uri` figure dans `CHAMPS_SURS` et `extraire()` renvoie sa valeur brute. Une
  URL de la forme `https://user:password@host` expose donc ces identifiants
  avant tout `/reveler`. Masquer ou rédiger l'URI côté serveur (`rediger_uri`)
  avant de la classer comme sûre.
- `messageErreur()` dans `ui.js` ne lit que `donnees.erreur` et ignore
  `donnees.reference`, pourtant renvoyée sur une erreur 500.
- `purgerGeneration()` ne vide pas `#gen-fichiers`, `#gen-resultat-stats`,
  `#gen-resultat-avertissements` ni `#gen-resume` ; seul
  `reinitialiserGeneration()` les vide.
- `extraire()` et `restaurer()` ne vérifient pas
  `scans_info["manquants_total"]` ; l'interface empêche seulement de poursuivre,
  un appel direct reste accepté.
- Un `/dev/loopX` monté reste dans `autres` (`ecarte`) et n'a pas de bouton de
  démontage, car `a_demonter` exige `not est_loop`.
- `purgeGlobale()` ne réinitialise pas le cache USB (`etat.donnees`,
  `etat.selection`, `etat.commandes`) ni les commandes affichées.
- `surSessionExpiree()` ne re-masque pas immédiatement les secrets révélés
  avant d'afficher l'écran de verrouillage ; conserver `jetonMemoire` pour la
  possibilité de réessayer.

### 4. Jeton, session et réseau

- Le jeton est lu depuis `window.location.hash`, puis retiré immédiatement par
  `history.replaceState`, avant même l'échange. Il reste dans la variable
  mémoire `jetonMemoire` pour permettre « Réessayer » après une expiration de
  cookie. Le jeton change à chaque lancement : relancer le serveur invalide les
  liens et cookies précédents.
- Le jeton ne doit jamais être écrit dans un fichier, un log, un stockage
  navigateur, un `data-*`, un `title` ou une URL de requête. Le cookie est
  `HttpOnly` : le JS ne doit pas tenter de le lire ni de le réécrire.
- `POST /api/session` est le seul appel qui utilise un `fetch` manuel dans
  `app.js` ; il doit conserver `Content-Type: application/json`,
  `X-QR-Web: 1`, `credentials: "same-origin"` et le corps `{jeton}`.
- Tous les autres appels passent par `api()`, `envoyer()` ou `telecharger()`.
  Ne jamais utiliser `fetch` brut pour `/api` : l'en-tête `X-QR-Web` manquant
  produit un `403 entete_manquant`.
- Les URL sont relatives (`/api/...`) et le déploiement reste sur l'origine
  locale `http://127.0.0.1:5100`. Aucun WebSocket, `EventSource`, service
  worker, balise de pistage ou requête sortante.
- Le serveur fixe `Cache-Control: no-store`, `Referrer-Policy: no-referrer`
  et une CSP stricte. Son journal HTTP ne contient ni chaîne de requête, ni
  en-tête, ni corps. Ne pas ajouter de cache applicatif de secrets ni de
  journal du corps de requête.

### 5. Accessibilité et ergonomie

- Conserver le lien d'évitement `.lien-evitement` en premier élément
  focusable, vers `#contenu`.
- Les onglets utilisent `role="tablist"`, `role="tab"`, `role="tabpanel"`,
  `aria-selected`, `aria-controls` et `aria-labelledby`. Le clavier doit gérer
  `ArrowLeft`, `ArrowRight`, `Home` et `End`, puis activer l'onglet.
- Les zones de dépôt sont des `div` avec `role="button"`, `tabindex="0"` et
  gestion de `Enter`/`Espace` ; l'input fichier reste `hidden`.
- Les toasts utilisent `role="status"` et `aria-live="polite"`. Les erreurs
  persistantes doivent être affichées dans un message intégré, pas uniquement
  dans un toast. Si un message d'erreur est ajouté dynamiquement, lui donner
  `role="alert"` ou l'insérer dans une zone `aria-live`.
- Les volets pliables utilisent de préférence `<details>/<summary>`. Pour un
  volet personnalisé, maintenir `aria-expanded` et `aria-controls`.
- Le dialogue de confirmation utilise `<dialog>` et `showModal()`. Le repli
  `window.confirm` n'est acceptable que si `showModal` est indisponible.
- `<progress>` doit conserver `max="100"`, une valeur mise à jour et un texte
  de progression lisible. Ne pas noyer un lecteur d'écran avec chaque message
  de journal : le journal technique reste dans un `<details>`.
- Ne jamais supprimer les styles `:focus-visible`. Conserver le contraste de la
  palette existante et vérifier tout nouveau couple texte/fond.
- Respecter `prefers-reduced-motion` et les points de rupture 980 px et
  640 px. Les commandes terminal utilisent une police monospace, un retour à la
  ligne et un défilement horizontal maîtrisé, sans casser la page.

### 6. Langue et permissions

- Tous les textes visibles, messages d'erreur, commentaires et libellés
  d'accessibilité sont en français. Les nouveaux noms métier sont en français ;
  les identifiants techniques imposés par la plateforme ou l'API (`fetch`,
  `innerHTML`, `job_id`, `X-QR-Web`) restent inchangés.
- Les documents et sources sont en `600` ; les scripts en `700`. Après création
  d'un fichier :

```bash
chmod 700 .agents/skills/interface-web-locale
chmod 600 .agents/skills/interface-web-locale/SKILL.md
```

## Workflow par module

### `app.js` — amorçage et session

1. Lire `window.location.hash`, extraire `jeton`, puis
   `history.replaceState` pour retirer le fragment.
2. Si le jeton est présent : `POST /api/session`, puis `GET /api/etat`.
3. Si aucun jeton n'est présent mais qu'un cookie valide subsiste (rechargement
   de page), tenter `GET /api/etat` ; sinon afficher l'écran de session avec le
   message « Lien d'accès incomplet ».
4. Afficher l'application, initialiser les trois modules une seule fois via
   `interfaceInitialisee`, puis reprendre une génération active ou réussie
   depuis `etat.generations`.
5. `rendreBandeau(etat)` affiche les avertissements de swap disque, WeasyPrint
   et qrencode/split sans bloquer l'interface.
6. `surSessionExpiree()` affiche l'écran de verrouillage et propose
   « Réessayer » uniquement si `jetonMemoire` est non vide.
7. La purge globale appelle `POST /api/purge`, `reinitialiserGeneration(false)`,
   `reinitialiserConsultation()` et rafraîchit les sources. Ne pas oublier de
   vider les messages, résultats et fichiers affichés.

Toute nouvelle initialisation de module doit être ajoutée dans
`initialiserGlobal()`/`ouvrirApplication()` et non exécutée au chargement du
module, pour éviter les accès DOM avant l'affichage de `#application`.

### `ui.js` — boîte à outils partagée

- `$` et `$$` : sélecteurs locaux, jamais de sélecteur construit avec une
  valeur non échappée.
- `api(chemin, options)` : ajoute `X-QR-Web`, gère `json`, `credentials:
  "same-origin"`, mappe `401` vers `surSessionExpiree` et transforme les erreurs
  réseau en message local. Retourne `null` pour une réponse vide.
- `envoyer(chemin, corps, entetes, methode)` : pour les corps bruts (CSV, ZIP,
  JSON de scans), ajoute aussi `X-QR-Web`. L'appelant fournit le bon
  `Content-Type`.
- `telecharger(url, nom)` : `fetch` avec `X-QR-Web`, `credentials:
  "same-origin"`, gestion explicite du `401`, conversion en blob, lien
  temporaire, `URL.revokeObjectURL` après 30 s. À utiliser pour tous les
  téléchargements.
- `confirmer({titre, message, libelle, danger})` : dialogue natif, repli
  `window.confirm`.
- `toast(message, type, duree)` : messages éphémères, `role="status"`.
- `echapper`, `icone`, `octets`, `vider`, `afficher`, `afficherMessage`,
  `masquerMessage`, `copier`, `debounce` : conserver leurs signatures et leur
  comportement, les modules en dépendent.

### `generation.js` — pipeline QR

1. **Import** : clic, clavier ou glisser-déposer. Vérifier côté client
   `fichier.size <= 338000` et `fichier.size > 0` pour un retour immédiat ;
   le serveur et le pipeline refont le contrôle.
2. **Préflight** : lire le fichier avec `arrayBuffer()` (jamais d'écriture
   disque), envoyer `POST /api/generation/apercu` avec
   `Content-Type: text/csv` et `X-QR-Fichier: encodeURIComponent(nom)`, puis
   afficher format, entrées, QR, pages, taille, fin de ligne et saut final.
3. **Choix de mise en page** : `compact`, `confort` ou `aucune`. Envoyer
   `X-QR-Mise-En-Page` lors du démarrage.
4. **Démarrage** : `POST /api/generation` avec le même corps brut. La réponse
   `202` fournit `id`, `etat`, `progression`, `etape`, `messages`.
5. **Suivi** : interroger `GET /api/generation/<id>` toutes les 900 ms.
   Mettre à jour `<progress>`, le pourcentage, l'étape et le journal. Arrêter
   l'intervalle sur `succes`, `erreur` ou `annule`.
6. **Annulation** : `POST /api/generation/<id>/annuler`, puis attendre l'état
   `annule`. Ne pas supprimer le job avant la fin de l'annulation.
7. **Reprise** : après rechargement, `reprendreGeneration()` choisit le premier
   job actif, sinon le premier succès, et restaure l'étape correspondante.
8. **Résultat** : afficher `nom_dossier`, enregistrements, morceaux, taille et
   mise en page. Les fichiers sont téléchargés via
   `/api/generation/<id>/fichier/<cle>`. Signaler que le ZIP n'est pas chiffré
   et que WeasyPrint peut être absent.
9. **Nettoyage** : `reinitialiserGeneration()` arrête l'intervalle et vide les
   champs, les statistiques, les messages et les listes de fichiers.
   `purgerGeneration()` arrête aussi l'intervalle et supprime le job serveur,
   mais ne vide pas encore `#gen-fichiers`, `#gen-resultat-stats`,
   `#gen-resultat-avertissements` ni `#gen-resume` : point d'audit à corriger
   pour éviter de laisser des métadonnées dans le DOM.

Ne jamais afficher un nom de fichier ou un libellé serveur sans `echapper()`
lorsqu'il est interpolé dans du HTML. Ne jamais journaliser le contenu du CSV.

### `consultation.js` — extraction et restauration

1. **Sources** : `GET /api/consultation/sauvegardes` affiche les sessions et
   les dossiers détectés (8 maximum). Ouvrir une source avec
   `POST /api/consultation/source` (`job` ou `dossier`) ou une archive avec
   `POST /api/consultation/archive` (corps ZIP brut, `X-QR-Fichier`).
   L'archive ne fournit que les trois index ; les scripts exécutés restent ceux
   du dépôt. Les index extraits sont plafonnés à 64 Mio et `index_meta.json` à
   1 Mio, avec protections zip-slip et zip-bomb.
2. **Scans** : seul l'export JSON global de Binary Eye (normalement
   `scans/binary_eye_all_qr.json`) est accepté ; les exports CSV/TXT globaux et
   les scans traduits automatiquement sont refusés. Envoyer le JSON brut avec
   `Content-Type: application/json` et `X-QR-Fichier`, limite 16 Mio. Afficher
   morceaux trouvés/attendus, entrées, doublons, invalides, morceaux d'une
   autre sauvegarde et exemples manquants. Si des morceaux manquent, l'interface
   masque la poursuite ; le serveur `extraire()` ne vérifie cependant pas
   `scans_info["manquants_total"]`, donc un appel direct reste accepté :
   point d'audit côté serveur.
3. **Recherche** : `debounce` de 280 ms, `POST .../recherche` avec `{q}`.
   Utiliser un compteur de séquence pour ignorer les réponses obsolètes. La
   recherche porte sur le nom (`name`/`Title`) et l'identifiant `R…` ; elle ne
   doit pas être présentée comme une recherche dans les mots de passe.
4. **Extraction** : `POST .../extraire` avec `{record_id}`. La réponse contient
   `extraction_id`, `lignes[].visibles` (nom, dossier, URI, identifiant) et
   `lignes[].masques` (clé et libellé uniquement). Les mots de passe, TOTP,
   notes et champs personnalisés ne sont pas renvoyés, mais l'URI est une
   exception : `uri` est classée `CHAMPS_SURS` et sa valeur brute peut contenir
   des identifiants intégrés (`https://user:password@host`). Ne pas la présenter
   comme un champ sûr avant correction côté serveur.
5. **Révélation** : un clic sur l'œil appelle `POST .../reveler` avec
   `{extraction_id, ligne}` pour la ligne concernée. Le bouton global révèle
   toutes les lignes une par une, puis planifie le re-masquage. Un second clic
   masque et supprime la valeur du DOM.
6. **Téléchargement** : `/fichier/extraction` (CSV ou ZIP multi-lignes) et
   `/fichier/restauration`. Toujours prévenir que le fichier est en clair.
7. **Restauration** : `POST .../restaurer` renvoie `statut` :
   `identique`, `nbsp` ou `different`, avec SHA-256, tailles, enregistrements
   et parfois les SHA sans NBSP. `nbsp` est un succès ; `different` ne doit
   jamais conduire à supprimer l'original.
8. **Purge** : `DELETE /api/consultation/<id>`, réinitialisation locale,
   rechargement des sources. Annuler le minuteur de masquage et vider
   `etat.extraction`.

Ne jamais appeler `/reveler` au chargement, lors de la recherche ou pour
préparer un téléchargement. Ne pas conserver les valeurs révélées dans un état
global hors du DOM temporaire.

### `usb.js` — assistant matériel en deux étapes

**Séparation stricte :** le navigateur et Flask ne disposent d'aucun privilège
root. Le frontend ne reçoit ni phrase de passe LUKS2, ni phrase age, ni droit
d'exécution. `POST /api/usb/demonter` est la seule action système exécutée par
le serveur ; elle utilise `udisksctl unmount --no-user-interaction -b` avec les
droits de l'utilisateur courant. Toutes les autres opérations sont des
commandes texte générées par le serveur, à copier dans un terminal.

#### Étape 1 — détection et sélection

`GET /api/usb/peripheriques` renvoie `candidats`, `a_demonter`, `tests`,
`autres` (20 maximum), `dependances`, `swap_disque_actif`, `swaps`,
`header_age_existe`, `montages_actifs` et `mappeurs_actifs`. Le serveur lit
`lsblk` en lecture seule et applique les garde-fous :

- disque entier, taille ≥ 1 Gio, non protégé en écriture ;
- transport USB ou indicateur amovible ;
- ni système en cours, ni swap, ni holder noyau, ni LVM/RAID/dm/crypt ;
- pour un disque physique, une partition montée n'est pas un candidat prêt :
  elle bascule dans `a_demonter` ;
- un `/dev/loopX` monté n'est pas proposé au démontage : il reste dans `autres`
  (`ecarte`), car `a_demonter` exige `not est_loop`. C'est un point d'audit du
  parcours de test loopback.

| État serveur | Affichage | Action |
|---|---|---|
| `candidat` | badge vert « Prête / Sûre » | « Choisir ce support » |
| `a_demonter` | badge ambre « Partition montée (accès verrouillé) » | « Démonter la partition », puis rafraîchir |
| `test` | badge vert « test loopback » | sélection avec mode test explicite |
| `ecarte` | badge rouge « écarté » + raisons | aucune sélection |

Ce tableau décrit les disques physiques ; un loopback monté reste écarté et
n'ouvre pas le démontage assisté.

Les disques système et les supports dangereux restent dans le bloc
« Périphériques écartés » ; ne jamais les rendre sélectionnables. Un support
`a_demonter` reste un support sûr : il est seulement verrouillé par un montage.

Les avertissements d'hygiène (`swap_disque_actif`, `montages_actifs`,
`mappeurs_actifs`, `header_age_existe`) et les dépendances absentes sont
affichés sans action automatique. Le frontend ne désactive pas le swap, ne
ferme pas un mapper LUKS et ne déplace pas la sauvegarde d'en-tête.

**Démontage assisté :**

1. Un bouton par partition montée d'un support `a_demonter` appelle
   `POST /api/usb/demonter` avec `{partition}`.
2. Le serveur revalide la partition contre l'état `lsblk` courant, jamais
   contre la seule valeur envoyée par le navigateur. Une cible qui n'appartient
   pas à un disque amovible sûr est refusée en `403` ; le frontend affiche
   alors uniquement le message d'erreur et **ne propose aucune commande** pour
   cette cible.
3. Si le serveur répond `ok: true`, vider le cache `etat.donnees`, recharger
   la détection, puis sélectionner automatiquement le support libéré.
4. Si le serveur répond `partition_non_montee`, recharger la détection.
5. Si le serveur répond avec `ok: false` et des commandes (partition occupée,
   `udisksctl` absent, délai, échec), afficher l'encadré « Démontage
   automatique impossible » avec la ou les commandes **exactes renvoyées par
   le serveur**, un bouton « Copier » et un bouton « Rafraîchir la détection ».
   Ne jamais reconstruire la commande à partir de la saisie navigateur.

Codes de retour utiles :

| Code | Signification | Réaction frontend |
|---|---|---|
| `demonte` | Démontage réussi | Toast, rechargement, sélection automatique |
| `partition_non_montee` | Déjà démontée | Rechargement |
| `udisksctl_absent` | Outil absent | Encadré avec la commande de secours du serveur |
| `demonter_echoue` / `demonter_delai` / `demonter_impossible` | Échec ou délai | Encadré avec commande principale et alternative |
| `partition_non_autorisee` (`403`) | Cible non sûre | Message inline, aucune commande |

La commande de secours affichée est fournie par le serveur et mise entre
guillemets avec `shlex`. Pour une partition occupée, le serveur renvoie la
commande `udisksctl unmount -b <partition>` et l'alternative
`sudo umount <partition>` ; si `udisksctl` est absent, seule l'alternative
`sudo umount <partition>` est proposée. Ces valeurs fictives ne doivent jamais
être remplacées par une cible physique recopiée à la main : le frontend affiche
le texte exact de la réponse serveur, et les tests utilisent un faux `lsblk`
ou une image loopback.

#### Étape 2 — opération et commandes

`choisirAppareil()` affiche un récapitulatif reconstruit à partir des données
serveur :

- **Cible** : chemin, modèle, taille ;
- **État** : badge vert « Partitions démontées » ou badge ambre « Montage
  détecté » ;
- **Vérification** : `lsblk -o NAME,MODEL,SERIAL <cible>`.

Règles :

- Aucune case à cocher « vérifié » ou « démonté » pour `sauvegarde`,
  `consulter` ou `restaurer`. Le serveur revalide l'absence de montage à chaque
  génération et renvoie `409 partition_montee` si une partition a été remontée.
- Seule l'opération `init` (destructive) exige une confirmation explicite. Le
  champ accepte le nom court (`sde`), le chemin complet (`/dev/sde`) ou le
  numéro de série. Le bouton « Insérer » pré-remplit avec le nom, le numéro de
  série ou le chemin fourni par le serveur, et la commande de vérification est
  mise à jour avec le chemin réel.
- Options `init` : mémoire Argon2id 256–8192 MiB (défaut du script 2048,
  réduit selon la RAM disponible) et 1–32 threads (défaut 4). Le serveur borne
  les valeurs ; le script reste seul à les valider à l'exécution.
- `sauvegarde` : `sans_csv` est coché par défaut (export direct en RAM) et
  masque `csv_path` ; `no_print` et `garder_source` sont facultatifs. Taille
  RAM par défaut `2G`, minimum `256M`.
- `consulter`/`restaurer` : taille RAM par défaut `512M`, minimum `128M`.
  `consulter` propose le menu, l'extraction par `id`, par `nom` ou la
  restauration ; `restaurer` force la restauration complète.
- `init` est refusé en `409 header_age_existant` si
  `~/luks_header_qr.bak.age` existe déjà. L'interface signale ce garde-fou mais
  ne déplace jamais le fichier.
- Le mode test loopback est réservé aux périphériques `/dev/loopX`. La case
  n'est visible que pour un type `loop` ; le backend exige `mode_test: true`
  pour un loop et le refuse pour un disque physique.
- Les tailles RAM (`2G`, `512M`, etc.) sont validées côté serveur et converties
  en MiB pour la comparaison au minimum. Le frontend ne doit pas comparer
  naïvement une chaîne comme `2G` à un minimum en MiB.
- Les chemins `csv_path` et `export_path` sont des chemins du système lus par
  les scripts CLI ; le navigateur ne téléverse pas ces fichiers. Avertir que
  l'export direct en RAM est préférable et qu'un fichier hors
  `/mnt/ram_sec/` ou `/run/user/` peut laisser des traces.
- `--afficher` n'est proposé que pour `consulter` avec `id` ou `nom`. Il
  révèle le mot de passe dans le terminal et doit rester accompagné d'un
  avertissement sur le scrollback.

`construireRequete()` envoie `operation`, `peripherique`, `mode_test` et les
options ; `POST /api/usb/commandes` revalide la cible et l'absence de montage
à partir de l'état `lsblk` courant, jamais du cache frontend, puis renvoie :

- `controle.partitions_demontees` et `controle.source` ;
- trois commandes : `set +o history`, vérification `lsblk`, commande
  `sudo` de l'opération ;
- `checklist` et `avertissements`.

Afficher chaque commande dans un `<pre class="commande-texte">` avec
`textContent`, jamais avec `innerHTML`. Le bouton « Copier la commande » copie
le texte renvoyé par le serveur ; pour la commande d'opération, le presse-papiers
reçoit actuellement `set +o history` en première ligne. Ne jamais exécuter la
commande depuis le navigateur, ne jamais ajouter de bouton « Lancer », et ne
jamais demander de mot de passe administrateur.

## Gestion des erreurs et des sessions

| Situation | Code | Comportement attendu |
|---|---|---|
| Cookie absent ou expiré | `401` | `surSessionExpiree` affiche l'écran de verrouillage ; bouton « Réessayer » si le jeton est encore en mémoire |
| En-tête `X-QR-Web` absent | `403 entete_manquant` | Corriger l'appel, ne pas boucler |
| `Host` ou `Origin` refusé | `403` | Message ; rouvrir l'URL locale exacte, ne pas contourner |
| Partition USB refusée | `403 partition_non_autorisee` | Message intégré ; aucune commande de secours |
| Partition remontée ou en-tête existant | `409` | Recharger l'état USB / relire le garde-fou, ne pas réessayer à l'aveugle |
| Fichier trop volumineux | `413` | Afficher la limite concernée ; ne pas réessayer avec le même fichier |
| Validation métier | `400` | Afficher le message serveur dans la zone de message intégré |
| Erreur interne | `500` | Le message invite à consulter le terminal avec la référence, mais `messageErreur()` ne lit pas `donnees.reference` — point d'audit |
| Réseau local interrompu | — | Message « Vérifiez que ./lancer_interface.sh est toujours actif » |
| Jeton refusé à l'échange | `403` | Écran de session : le serveur a probablement été relancé |

Règles :

- `api()` et `telecharger()` doivent gérer explicitement le `401` ; un nouveau
  chemin de téléchargement ne doit pas oublier `surSessionExpiree`.
- Un `403` n'est pas un `409` : ne pas proposer de commande de secours USB et
  ne pas recharger en boucle.
- Un `409 partition_montee` doit déclencher un rechargement de
  `/api/usb/peripheriques` avant de proposer une nouvelle sélection.
- Les messages d'erreur backend sont déjà en français et ne contiennent pas de
  secret ; les afficher via `textContent`. Ne jamais exposer une réponse brute
  ou un objet d'exception dans le DOM.

## Procédure de validation

### 1. Contrôles statiques obligatoires

```bash
python3 -m py_compile *.py
python3 -m compileall -q web
bash -n *.sh
```

### 2. Contrôle de syntaxe JavaScript et CSS

Si Node.js est disponible localement, il peut servir de parseur sans être une
dépendance du projet. Cette vérification est facultative : ne pas créer de
`package.json`, de `node_modules` ni de script de build pour autant.

```bash
if command -v node >/dev/null 2>&1; then
  for fichier in web/static/app.js web/static/ui.js web/static/modules/*.js; do
    node --input-type=module --check < "$fichier" || exit 1
  done
fi
```

Pour la CSS, vérifier l'équilibre des accolades et des commentaires, puis
valider le rendu réel dans le navigateur (le parseur du navigateur fait foi) :

```bash
python3 - <<'PY'
from pathlib import Path

css = Path("web/static/style.css").read_text(encoding="utf-8")
assert css.count("{") == css.count("}"), "accolades CSS déséquilibrées"
assert css.count("/*") == css.count("*/"), "commentaires CSS non fermés"
print("CSS : structure équilibrée")
PY
```

### 3. Chargement réel via le lanceur

```bash
# Terminal 1 : lancer le serveur, qui reste au premier plan.
./lancer_interface.sh --no-browser

# Terminal 2, après l'affichage de l'URL :
ss -ltnp | grep 5100
```

Contrôles :

- l'URL affichée contient `http://127.0.0.1:5100/#jeton=…` ; ne pas la
  recopier dans un fichier ou un historique partagé ;
- une seule écoute sur `127.0.0.1:5100` ;
- la page se charge sans erreur dans la console du navigateur, avec la CSP et
  `Cache-Control: no-store` ;
- avec l'en-tête `X-QR-Web` mais sans cookie, `GET /api/etat` renvoie `401` ;
  sans l'en-tête, il renvoie `403` ;
- le fragment disparaît de la barre d'adresse dès l'amorçage, avant l'échange
  du jeton ;
- un rechargement de page avec le cookie encore valide fonctionne ; après
  expiration, l'écran de session propose « Réessayer » tant que le jeton est
  en mémoire.

Contrôle HTTP minimal sans secret :

```bash
curl -sS -D - http://127.0.0.1:5100/ -o /dev/null \
  | grep -Ei 'content-security-policy|cache-control'
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H 'X-QR-Web: 1' http://127.0.0.1:5100/api/etat
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5100/api/etat
```

Attendu : CSP stricte, `no-store`, `401` avec l'en-tête `X-QR-Web` mais sans
cookie, et `403` sans l'en-tête. Pour les appels authentifiés, utiliser
l'interface et son jeton, sans journaliser l'URL complète.

### 4. Tests fonctionnels avec données synthétiques

Créer un CSV synthétique dans `/tmp/opencode` avec `umask 077` (Bitwarden ou
KeePassXC), puis :

1. générer une sauvegarde depuis l'onglet Créer et vérifier que la génération
   se termine avec le sceau de succès et le message indiquant que le SHA-256
   correspond au CSV d'origine ;
2. fabriquer un faux export Binary Eye à partir des morceaux avec l'en-tête
   `LQR1 <suffixe> <n>/<total>\n` ;
3. importer le JSON, rechercher par nom et par `R…`, vérifier que les champs
   masqués le sont ; vérifier aussi qu'une URI synthétique avec `user:password@`
   est visible avant révélation (exception d'URI à corriger) ;
4. révéler un secret explicitement, vérifier le re-masquage automatique après
   le TTL (ou avec une valeur `data-ttl` réduite pour le test uniquement) ;
5. restaurer tout le CSV et vérifier `IDENTIQUE` ainsi que le SHA-256 ;
6. simuler la normalisation NBSP et vérifier
   `IDENTIQUE APRÈS NORMALISATION NBSP` ;
7. tester les refus : CSV > 338 000 octets, scans > 16 Mio, ZIP > 256 Mio ;
8. vérifier « Purger la session » : les fichiers de travail du répertoire privé
   sur tmpfs et l'état JS sont purgés ;
9. après « Tout effacer » sur une génération, vérifier que les panneaux de
   résultat ne contiennent plus de métadonnées (point d'audit actuel de
   `purgerGeneration()`).

Ne jamais utiliser un export réel, même pour un test rapide. Ne jamais
afficher un mot de passe synthétique hors du test ponctuel de révélation.

### 5. Tests USB sans disque physique

Utiliser un faux `lsblk` placé en tête de `PATH` et, pour les scripts, une
image loopback avec `--allow-loopback`. Jamais de clé ou de disque physique.

Vérifier :

- une clé montée apparaît en ambre « Partition montée (accès verrouillé) » et
  reste hors des périphériques écartés ;
- un loopback monté reste écarté et n'ouvre pas le démontage assisté : point
  d'audit à couvrir si le parcours de test doit inclure ce cas ;
- « Démonter la partition » appelle
  `udisksctl unmount --no-user-interaction -b <partition>`, sans `sudo`, sans
  `-f` et sans `-l` ;
- après démontage, la carte passe en vert et l'étape 2 s'ouvre ;
- une partition du disque système est refusée en `403` sans appel à
  `udisksctl` ;
- un échec « busy » affiche la commande exacte, « Copier » et « Rafraîchir » ;
- `udisksctl` absent ne propose que la commande de secours du serveur ;
- l'étape 2 affiche « Cible » et « Partitions démontées », sans case à cocher
  pour les opérations non destructives ;
- `init` exige une confirmation, accepte nom court, chemin complet ou numéro
  de série, refuse une valeur erronée et renvoie `409 partition_montee` si une
  partition est remontée entre-temps ;
- le mode test loopback est requis pour `/dev/loopX` et refusé pour un disque
  physique ;
- aucune commande USB privilégiée n'est exécutée par le serveur en dehors du
  démontage non privilégié `udisksctl`.

### 6. Contrôles de sécurité et de finition

```bash
rg -n 'onclick|onchange|onsubmit|javascript:|eval\(|new Function|unsafe-inline' web || true
rg -n 'X-QR-Web' web/static
rg -n 'cdn|unpkg|jsdelivr|googleapis|npm|node_modules' web || true
rg -n 'innerHTML|fetch\(' web/static
git diff --check
! grep -n '[[:blank:]]$' .agents/skills/interface-web-locale/SKILL.md
stat -c '%a %n' .agents/skills/interface-web-locale/SKILL.md
```

Attendu : aucune occurrence interdite, `X-QR-Web` présent dans `ui.js` et
`app.js`, aucune dépendance distante, chaque `innerHTML` statique ou échappé,
chaque `fetch` couvert par `X-QR-Web` (ou l'échange de session), aucun espace
superflu, permissions `600`. `git diff --check` ne voit pas un fichier non
suivi : le `grep` ci-dessus contrôle explicitement les espaces de fin de ligne
du nouveau skill.

## Pièges et anti-patrons

- Ajouter `onclick` ou un `<script>` inline : bloqué par la CSP et contraire à
  l'architecture.
- Injecter une réponse d'API dans `innerHTML` sans `echapper()` : XSS DOM.
- Utiliser `innerHTML` avec un nom d'icône ou une classe provenant du serveur.
- Mettre le jeton ou un secret dans `localStorage`, un cookie JS, un log, un
  `title`, un attribut `data-*` ou une URL.
- Oublier `X-QR-Web` sur un `fetch` direct : `403 entete_manquant`.
- Utiliser `fetch` brut pour un téléchargement et oublier le `401`.
- Révéler les secrets au chargement ou pendant la recherche.
- Oublier d'annuler le minuteur de re-masquage ou l'intervalle d'interrogation
  périodique après une purge.
- Afficher un toast pour une erreur qui exige une action : préférer un message
  intégré persistant.
- Ajouter une case à cocher « partition démontée » pour `sauvegarde`,
  `consulter` ou `restaurer` : le serveur revalide déjà.
- Reconstruire une commande `sudo` côté navigateur à partir de la saisie.
- Proposer une commande de secours après un `403` de démontage.
- Exécuter `sudo` ou demander une phrase de passe dans le navigateur.
- Tester le mode loopback sur un disque physique ou sans `--allow-loopback`.
- Considérer `2G` comme une valeur déjà en MiB.
- Changer un `id` HTML sans mettre à jour tous les sélecteurs JS.
- Ajouter un module sans l'enregistrer dans `app.js` et sans
  `aria-controls`/`aria-labelledby`.
- Utiliser une police, un script ou un style distant « juste pour tester ».
- Télécharger automatiquement un CSV extrait ou restauré sans avertissement.
- Croire que `prefers-reduced-motion`, `color-scheme` ou le minuteur client sont
  des mesures de sécurité.
- Modifier `README.md` pour y décrire des détails réservés aux agents : la
  documentation utilisateur reste centrée sur les commandes et les limites.

## Alignement documentaire

- `README.md` section 6 reste la documentation utilisateur. La mettre à jour
  uniquement si une commande, un comportement visible, une limite ou une
  procédure de sécurité change. Ne pas y ajouter de détails d'implémentation
  frontend. La création de ce skill n'ajoute aucune commande ni comportement
  utilisateur : `README.md` et le heredoc `LISEZMOI.txt` restent inchangés,
  seul `AGENTS.md` reçoit le pointeur de découverte.
- `AGENTS.md` section 3 porte les invariants web et référence ce skill. Toute
  modification du périmètre (nouveau module, nouvelle limite, nouveau
  garde-fou) doit y être répercutée.
- Le heredoc `LISEZMOI.txt` de `creer_sauvegarde_qr.sh` ne contient qu'un
  rappel web court (port, jeton, absence de `sudo`, démontage `udisksctl`).
  Ne pas y ajouter la cartographie frontend.
- Pour un changement de commande, de drapeau, de limite ou de procédure,
  appliquer `sync-docs-tripartite` après avoir stabilisé le code et exécuté les
  tests.
- Ce skill décrit le frontend ; il ne remplace pas `test-sauvegarde-qr` pour le
  pipeline QR ni `test-coffre-loopback` pour LUKS2, l'enclave RAM et les scripts
  USB.

## Vérification finale

Le changement est terminé seulement si :

- [ ] aucun npm, bundler, CDN ni ressource distante n'a été introduit ;
- [ ] aucun écouteur inline, `eval`, `new Function` ou `innerHTML` non
  échappé n'a été ajouté ;
- [ ] tous les appels `/api` portent `X-QR-Web: 1` et utilisent les helpers ;
- [ ] le jeton n'est jamais persisté et le fragment est retiré ;
- [ ] les secrets restent masqués par défaut (hors exception d'URI documentée) ;
  la purge globale vide génération et consultation ; le cache USB et les
  panneaux de `purgerGeneration()` restent des points d'audit ;
- [ ] les erreurs `401`/`403`/`409`/`413` ont le comportement attendu ;
- [ ] l'assistant USB ne demande ni `sudo` ni phrase de passe et ne propose
  que les commandes générées par le serveur ;
- [ ] l'accessibilité clavier, les focus, les `aria-*` et le responsive sont
  préservés ;
- [ ] les textes et commentaires sont en français ;
- [ ] `python3 -m py_compile *.py && python3 -m compileall -q web &&
  bash -n *.sh` réussit ;
- [ ] `git diff --check` ne signale rien ;
- [ ] le chargement réel via `./lancer_interface.sh --no-browser` ne produit
  aucune erreur console ;
- [ ] le fichier est en `600` et le dossier en `700`.
