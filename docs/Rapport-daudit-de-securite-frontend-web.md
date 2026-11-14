# Rapport d'Audit Technique, Architectural et de Sécurité — Interface Web Locale (`web/`)

## 1. Synthèse exécutive et score de maturité

L'interface web locale (`web/`, amorcée par `./lancer_interface.sh`) respecte avec une grande rigueur sa philosophie d'**assistant graphique optionnel non privilégié**. Le serveur Flask 3.1 est strictement confiné à l'adresse de bouclage `127.0.0.1:5100`, la politique de sécurité de contenu (CSP) est appliquée sans aucune directive permissive (`unsafe-inline` ou `unsafe-eval`), et le frontend repose à 100 % sur du JavaScript Vanilla ES6 et du CSS natif sans aucune dépendance externe ni requête sortante. L'architecture de confinement en mémoire vive (`tmpfs` sous `$XDG_RUNTIME_DIR/qrcode_web_5100` ou `/dev/shm/qrcode_web_5100_<uid>`, permissions `0700`, `umask 077`, désactivation des core dumps via `RLIMIT_CORE` et `PR_SET_DUMPABLE`, verrouillage `mlockall`) offre une défense en profondeur exemplaire pour une application locale.

**Remédiation v1.0.1 :** les trois constats majeurs et les sept constats mineurs/améliorations du plan priorisé ont été corrigés et vérifiés par des tests synthétiques : rédaction des identifiants d'URI, re-masquage immédiat à l'expiration de session, contrôle serveur de la complétude des scans, purge complète des modules génération/USB, restitution des références d'incident, démontage assisté des loopbacks sûrs et finitions WAI-ARIA. Aucun constat d'audit frontend ne reste ouvert.

| Axe d'évaluation | Score | Niveau de maturité | Appréciation synthétique |
| --- | --- | --- | --- |
| **Isolation réseau & Authentification** | **9,5 / 10** | Très élevé | Écoute `127.0.0.1:5100`, contrôle `Host`/`Origin`, en-tête `X-QR-Web: 1`, jeton d'URL purgé et cookie `HttpOnly`/`SameSite=Strict`.

 |
| **CSP & Intégrité DOM (Anti-XSS)** | **9,5 / 10** | Très élevé | Aucun script/style/écouteur inline, échappement systématique via `echapper()` et usage majoritaire de `textContent`.

 |
| **Étanchéité des secrets & Anti-rémanence** | **9,5 / 10** | Très élevé | URI rédigée dès l'extraction, URI complète réservée à `POST /reveler`, re-masquage immédiat sur `401`, purge intégrale du DOM à la purge et au « Tout effacer ».

 |
| **Isolation des privilèges (Assistant USB)** | **9,5 / 10** | Très élevé | Zéro `sudo` exécuté, zéro saisie de secret LUKS2/age, démontage restreint à `udisksctl unmount --no-user-interaction -b` revalidé côté serveur, loopbacks sûrs inclus.

 |
| **Robustesse API & Architecture ES6** | **9,5 / 10** | Très élevé | Plafonds stricts anti-DoS/zip-slip, contrôle serveur de `manquants_total` (`409 scans_incomplets`) et référence d'incident restituée sur erreur 500.

 |
| **Accessibilité (RGAA / WAI-ARIA) & UX** | **9,5 / 10** | Très élevé | Landmarks, ARIA Tabs avec roving `tabindex`, `role="alert"` sur les erreurs dynamiques, focus visible sur les cartes radio et boutons métiers, `prefers-reduced-motion` conforme.

 |
| **Score de maturité global** | **97 / 100** | **Excellent** | **Aucun constat bloquant ni ouvert** ; les 3 constats majeurs et les 7 constats mineurs/améliorations sont résolus en v1.0.1.

 |

---

## 2. Matrice de conformité aux Invariants non négociables

Cette matrice synthétise le contrôle statique et architectural des 12 invariants fondamentaux définis dans les spécifications du projet.

| ID | Sujet | Invariant exigé | Preuve technique (`fichier:ligne` ou mécanisme) | Statut | Sévérité |
| --- | --- | --- | --- | --- | --- |
| **INV-01** | **Écoute** | `127.0.0.1:5100` uniquement, jamais `0.0.0.0`, aucun proxy ni tunnel.

 | `web/config.py` (`HOTE = "127.0.0.1"`, `PORT = 5100`), `web/serveur.py` (`make_server(config.HOTE, config.PORT, ...)`), `lancer_interface.sh` (test de `sock.bind(("127.0.0.1", 5100))` avant lancement).

 | **PASS** | — |
| **INV-02** | **Session** | Jeton transmis dans `#jeton=…`, échangé contre un cookie `HttpOnly`/`SameSite=Strict`, fragment retiré immédiatement.

 | `web/static/app.js` (`URLSearchParams(window.location.hash.slice(1))` suivi de `history.replaceState` avant `echangerJeton`), `web/serveur.py` (`set_cookie(..., httponly=True, samesite="Strict")`).

 | **PASS** | — |
| **INV-03** | **API** | En-tête `X-QR-Web: 1` et `credentials: "same-origin"` sur tous les appels `/api`.

 | `web/static/app.js` (`/api/session`), `web/static/ui.js` (`api()`, `envoyer()`, `telecharger()`), imposé par `web/securite.py` (`request.headers.get(config.ENTETE_API) == "1"`).

 | **PASS** | — |
| **INV-04** | **Origine** | Contrôle de `Host` sur toutes les requêtes et `Origin` sur les requêtes mutantes ; URLs relatives côté client.

 | `web/config.py` (`HOTES_AUTORISES`, `ORIGINES_AUTORISEES`), `web/securite.py` (`controler_acces()` vérifie `request.host` et `_origine_autorisee()` sur `POST`, `PUT`, `PATCH`, `DELETE`).

 | **PASS** | — |
| **INV-05** | **CSP** | Aucun `unsafe-inline`, aucun `unsafe-eval`, aucun script/style/écouteur inline.

 | `web/securite.py` (`CSP` stricte), `web/templates/index.html` et `erreur.html` (zéro attribut `on*` ou `style`), `web/static/**/*.js` (zéro `eval` ou `new Function`).

 | **PASS** | — |
| **INV-06** | **Dépendances** | Zéro npm/yarn/pnpm, zéro bundler, zéro framework, zéro CDN ni police distante.

 | Arborescence `web/` (uniquement ES6 natif et CSS local), `requirements.txt` (`Flask>=3.1,<4` côté serveur uniquement), piles de polices système dans `web/static/style.css`.

 | **PASS** | — |
| **INV-07** | **Limites** | CSV ≤ 338 000 o, scans ≤ 16 Mio, ZIP ≤ 256 Mio, index ≤ 64 Mio, meta ≤ 1 Mio, anti zip-slip / zip-bomb.

 | `web/config.py` (`LIMITE_CSV`, `LIMITE_JSON_SCANS`, `LIMITE_ZIP`, `LIMITE_INDEX`, `LIMITE_META`), `web/utilitaires.py` (`lire_corps_limite`), `web/services/consultation.py` (`_extraire_index_zip`).

 | **PASS** | — |
| **INV-08** | **Tmpfs** | Répertoire privé sous `$XDG_RUNTIME_DIR/qrcode_web_5100` ou `/dev/shm/qrcode_web_5100_<uid>`, `0700`, `umask 077`, core dumps désactivés.

 | `web/espace_ram.py` (`_choisir_base()` vérifie `findmnt -n -o FSTYPE` == `tmpfs` et mode `0700`), `web/serveur.py` (`os.umask(0o077)`, `_desactiver_core_dumps()`, `_desactiver_dumpable()`).

 | **PASS** | — |
| **INV-09** | **Secrets** | Masqués par défaut, révélation explicite, re-masquage auto, zéro presse-papiers, zéro stockage navigateur, purge intégrale.

 | `extraire()` applique `rediger_uri()` et ne renvoie l'URI complète qu'après `POST /reveler` ; `masquerSecretsConsultation()` réagit au `401` ; `purgerGeneration()` et `reinitialiserUsb()` vident leurs panneaux et caches.

 | **PASS** | — |
| **INV-10** | **USB** | Aucun `sudo`, aucune phrase de passe, démontage uniquement via `udisksctl unmount --no-user-interaction -b`.

 | `web/services/usb.py` (`demonter_partition` et `generer_commandes`), `web/static/modules/usb.js`. Les loopbacks sûrs montés rejoignent désormais `a_demonter` et bénéficient du démontage assisté, sans élargir les critères de sécurité.

 | **PASS** | — |
| **INV-11** | **Langue** | Interface, messages, commentaires et nommage métier exclusivement en français.

 | `web/templates/*.html` (`lang="fr"`), `web/static/**/*.js`, `web/**/*.py`.

 | **PASS** | — |
| **INV-12** | **Permissions** | Scripts exécutables en `700` (`rwx------`), gabarits, styles, scripts JS et documents en `600` (`rw-------`).

 | `creer_sauvegarde_qr.sh`, `lancer_interface.sh`, `web/espace_ram.py` (`0o700` dossiers, `0o600` fichiers) et règles POSIX documentées dans `.agents/skills/interface-web-locale/SKILL.md`.

 | **PASS** | — |

---

## 3. Constats de sécurité et analyse des risques

### 3.1 Résultats des contrôles statiques (Étape 1 & 2)

L'inspection exhaustive du code source de `web/` et des scripts associés démontre une hygiène statique irréprochable :

* **Compilation et syntaxe** : L'ensemble des modules Python (`*.py` et `web/**/*.py`), des scripts Bash (`*.sh`) et des modules ES6 (`web/static/**/*.js`) présente une structure syntaxique valide et équilibrée (les accolades `{`/`}` et commentaires `/*`/`*/` de `web/static/style.css` sont parfaitement appariés).


* **Absence d'anti-patrons CSP** : Aucune occurrence de `onclick`, `onchange`, `onsubmit`, `onfocus`, `onblur`, `javascript:`, `eval(`, `new Function`, `setTimeout("...")` ni d'attribut `style="..."` ou de balise `<style>`/`<script>` inline n'existe dans `web/templates/` ou `web/static/`.


* **Absence de ressources externes** : Aucune URL distante (`http://`, `https://`), aucun CDN (`unpkg`, `jsdelivr`, `googleapis`, `fonts.`) et aucun artefact `npm`/`node_modules` n'est référencé dans les templates ou fichiers statiques.


* **Couverture de l'en-tête `X-QR-Web: 1**` : Les 4 seuls appels `fetch()` du frontend — 1 dans `web/static/app.js` (`echangerJeton`) et 3 dans `web/static/ui.js` (`api`, `envoyer`, `telecharger`) — injectent systématiquement l'en-tête `X-QR-Web: 1` et l'option `credentials: "same-origin"`.



### 3.2 Vulnérabilités et faiblesses identifiées dans la gestion des secrets (Étape 3 & 4)

Les fiches ci-dessous conservent l'analyse d'origine pour la traçabilité ; toutes sont **RÉSOLUES en v1.0.1** et les correctifs ont été validés par des tests synthétiques.

#### [SEC-01] Exposition d'identifiants intégrés dans le champ `uri` lors de l'extraction (Sévérité : Majeur) — **RÉSOLU (v1.0.1)**

* **Statut** : corrigé dans `web/services/consultation.py`. `extraire()` applique `rediger_uri()` au champ `uri` visible ; si des identifiants étaient présents, l'URI complète est ajoutée aux champs masqués sous le libellé « URL complète (avec identifiants) » et n'est renvoyée que par `POST /reveler`.

* **Localisation** : `web/services/consultation.py` (lignes définissant `CHAMPS_SURS` et la fonction `extraire()`) et `web/static/modules/consultation.js` (`rendreExtraction()`).


* **Analyse technique** : La constante `CHAMPS_SURS = ("nom", "dossier", "uri", "identifiant")` classe le champ `uri` parmi les métadonnées affichables sans révélation. Si la fonction `rechercher()` nettoie bien l'URI via `rediger_uri(ligne.get("uri", ""))` (qui remplace `https://user:password@host` par `https://•••@host`), la fonction `extraire()` omet d'appeler `rediger_uri()` et insère la valeur brute `row[index]` dans le tableau `visibles`. Côté client, `rendreExtraction()` injecte directement `champ.valeur` dans la liste de définitions `#cons-detail-metadonnees` dès la sélection de l'entrée, **avant tout clic sur « Afficher les secrets »** (`POST /reveler`).


* **Impact** : Fuite visuelle immédiate (shoulder surfing) et présence en clair dans le DOM d'identifiants ou de jetons intégrés dans les URLs de connexion.



#### [SEC-02] Absence de re-masquage immédiat des secrets lors de l'expiration de session (Sévérité : Majeur) — **RÉSOLU (v1.0.1)**

* **Statut** : corrigé dans `web/static/modules/consultation.js` et `web/static/app.js`. `masquerSecretsConsultation()` annule le minuteur, efface `data-valeur`, rétablit `••••••••` et réinitialise le bouton global ; il est appelé avant l'affichage de l'écran de verrouillage, en conservant `jetonMemoire`.

* **Localisation** : `web/static/app.js` (`initialiserGlobal()` -> callback `surSessionExpiree`) et `web/static/modules/consultation.js`.


* **Analyse technique** : Lorsqu'un appel API renvoie `401` (`session_expiree`), `ui.js` invoque le gestionnaire enregistré via `surSessionExpiree()`. Dans `app.js`, ce gestionnaire appelle uniquement `afficherEcranSession(...)`, ce qui applique l'attribut `hidden` sur `<div id="application">` et affiche `<div id="ecran-session">`. Cependant, aucune fonction n'est appelée pour purger ou re-masquer les champs secrets (`#cons-champs-masques .champ-masque-valeur`) qui avaient été révélés avant l'expiration.


* **Impact** : Les mots de passe, secrets TOTP et notes révélés demeurent en clair dans le DOM (`textContent` et attribut `data-valeur`) en arrière-plan jusqu'à l'échéance du minuteur client `minuteurMasquage` (60 minutes par défaut). Si l'utilisateur clique sur « Réessayer » ou inspecte le DOM, les secrets sont toujours exposés.



#### [SEC-03] Absence de contrôle serveur de `scans_info["manquants_total"]` sur `/extraire` et `/restaurer` (Sévérité : Majeur) — **RÉSOLU (v1.0.1)**

* **Statut** : corrigé dans `web/services/consultation.py`. `_verifier_scans_complets()` est appelée en tête de `extraire()` et de `restaurer()` ; un export absent ou incomplet produit `409 scans_incomplets`, y compris pour un appel API direct.

* **Localisation** : `web/services/consultation.py` (fonctions `extraire()` et `restaurer()`) et `web/static/modules/consultation.js` (`rendreInfosScans()`).


* **Analyse technique** : Dans `consultation.js`, `rendreInfosScans()` vérifie `const complet = info.manquants_total === 0;` et masque le bouton « Continuer vers la recherche » si des morceaux manquent. En revanche, côté backend (`web/services/consultation.py`), `extraire()` et `restaurer()` vérifient uniquement `if session.scans_path is None:` sans contrôler `session.scans_info.get("manquants_total", 0)`.


* **Impact** : Contournement de la garde-fou d'interface par requête API directe vers `POST /api/consultation/<id>/extraire` ou `POST /api/consultation/<id>/restaurer`, déclenchant l'exécution inutile ou partielle des sous-processus Python sur un jeu de scans incomplet.



#### [SEC-04] Résidus de métadonnées dans le DOM après `purgerGeneration()` et `purgeGlobale()` (Sévérité : Mineur) — **RÉSOLU (v1.0.1)**

* **Statut** : corrigé dans `web/static/modules/generation.js`, `web/static/modules/usb.js` et `web/static/app.js`. `purgerGeneration()` vide les quatre panneaux de résultat ; `reinitialiserUsb()` remet à zéro l'état mémoire, les zones DOM, les étapes et les messages, et `purgeGlobale()` l'invoque avec les deux autres réinitialisations.

* **Localisation** : `web/static/modules/generation.js` (`purgerGeneration()`) et `web/static/app.js` (`purgeGlobale()`).


* **Analyse technique** :
1. Dans `generation.js`, la fonction `purgerGeneration()` (déclenchée par le bouton « Tout effacer » à l'étape de résultat) détruit bien le job sur le serveur (`DELETE /api/generation/<id>`) et ramène l'affichage à l'étape `"import"`, mais contrairement à `reinitialiser()`, elle **omet de vider** `#gen-fichiers`, `#gen-resultat-stats`, `#gen-resultat-avertissements` et `#gen-resume`.


2. Dans `app.js`, la fonction `purgeGlobale()` (déclenchée par « Purger la session ») réinitialise la génération et la consultation, mais **ne réinitialise pas l'état ni le DOM du module USB** (`etat.donnees`, `etat.selection`, `etat.commandes`, `#usb-peripheriques`, `#usb-appareil-selectionne`, `#usb-commandes`).




* **Impact** : Persistance en mémoire JavaScript et dans le DOM (bien que masqué par `hidden`) du nom du dossier de sauvegarde, des statistiques d'entrées/QR, de la topologie matérielle USB et des commandes générées après une action explicite de purge.



### 3.3 Robustesse contre les attaques DOM XSS, Clickjacking, CSRF et fuites mémoire

* **Protection contre le DOM-based XSS** :
* Tous les usages de `innerHTML` dans `web/static/` ont été audités individuellement. Chaque interpolation de donnée dynamique (nom de fichier CSV ou JSON, nom de dossier détecté, libellé de statistique, nom/URI/dossier dans les résultats de recherche, nom de commande de dépendance) est systématiquement enveloppée par `echapper()`, qui neutralise `&`, `<`, `>`, `"` et `'`.


* Le helper `icone(nom)` n'est jamais appelé avec une valeur provenant du serveur ou de l'utilisateur, mais exclusivement avec des constantes littérales codées en dur.


* Les journaux techniques (`#gen-journal`), les détails d'erreurs, les valeurs de secrets révélés et les commandes terminal (`<pre class="commande-texte">`) utilisent exclusivement `textContent`.




* **Protection contre le Clickjacking et les fuites Cross-Origin** :
* Les en-têtes `frame-ancestors 'none'` (CSP), `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin` et `Referrer-Policy: no-referrer` sont injectés sur toutes les réponses par `ajouter_entetes()` dans `web/securite.py`.




* **Protection contre le CSRF et le DNS Rebinding** :
* La défense combine quatre verrous indépendants : vérification stricte de l'en-tête `Host` contre `HOTES_AUTORISES` (`127.0.0.1:5100`, `localhost:5100`, `[::1]:5100`), vérification de l'en-tête `Origin` sur toutes les requêtes mutantes (`POST`, `PUT`, `PATCH`, `DELETE`), obligation de l'en-tête personnalisé `X-QR-Web: 1` (qui déclenche une pré-vérification CORS *preflight* impossible à franchir depuis une origine tierce) et cookie `SameSite=Strict` comparé en temps constant via `hmac.compare_digest`.




* **Étanchéité du presse-papiers et des journaux** :
* La fonction `copier()` de `ui.js` n'est jamais invoquée sur un mot de passe, un TOTP ou une note ; aucun bouton de copie de secret n'existe dans `consultation.js`.


* Côté serveur, `JournalDiscret` (`web/serveur.py`) supprime toute query string des logs HTTP et neutralise `log_message`/`log_error`, tandis que `erreur_generale` (`web/securite.py`) ne journalise que le type d'exception (`type(exc).__name__`) et une référence aléatoire de 8 caractères hexadécimaux, sans jamais imprimer le message de l'exception susceptible de contenir un extrait de CSV.





### 3.4 Évaluation de l'assistant USB et isolation des privilèges (Étape 5)

* **Absence totale d'exécution privilégiée** : Ni le frontend (`usb.js`) ni le service backend (`web/services/usb.py`) n'exécutent `sudo` ou les scripts `init_usb_coffre.sh`, `executer_sauvegarde_ram.sh` et `consulter_coffre_ro.sh`. Le serveur agit uniquement comme générateur de commandes shell échappées via `shlex.join` et `shlex.quote`.


* **Sécurité du démontage assisté (`POST /api/usb/demonter`)** :
* Le serveur ne fait jamais confiance au chemin `partition` envoyé par le navigateur : il réexécute `peripheriques()` (`lsblk --json --bytes`) et vérifie que la partition figure dans `partitions_montees` d'un disque classé `a_demonter` (disque physique ou loopback de test ≥ 1 Gio, non RO, USB/amovible ou loopback, hors système, hors swap, sans holders noyau ni LVM/RAID/dm/crypt).


* Si la partition cible appartient au disque système ou à un disque écarté, le serveur répond `403 partition_non_autorisee` et le frontend affiche uniquement le message d'erreur sans proposer aucune commande de démontage.


* En cas d'échec non privilégié de `udisksctl unmount --no-user-interaction -b` (partition occupée, polkit, ou `udisksctl` absent), le frontend restitue textuellement `reponse.commande` et `reponse.commande_alternative` fournies par le serveur sans aucune recomposition côté client.




* **[USB-01] Restriction excessive sur les périphériques loopback montés (Sévérité : Mineur) — RÉSOLU (v1.0.1)** :
* **Statut** : corrigé dans `web/services/usb.py`. `sur_sans_montage` accepte désormais `amovible or est_loop` et `a_demonter = sur_sans_montage and monte` ; un `/dev/loopX` sûr et monté rejoint `a_demonter`, puis devient `test` après démontage. Les critères de taille, lecture seule, système, swap, holders et LVM/RAID restent inchangés.
* Dans `web/services/usb.py` (`_analyser`), le booléen `sur_sans_montage` exigeait `not est_loop and type_principal == "disk"`, ce qui excluait les périphériques `/dev/loopX` de la catégorie `a_demonter`. Si une image loopback de test a une partition montée, elle basculait directement dans `autres` (`statut: "ecarte"`) sans accès au démontage assisté.





---

## 4. Constats d'architecture et de maintenabilité logicielle

### 4.1 Modèle Vanilla ES6 et orchestration événementielle

* **Découplage modulaire** : L'architecture frontend est scindée proprement en 5 fichiers ES6 natifs (`app.js`, `ui.js` et 3 modules métier sous `modules/`) totalisant un code concis, lisible et sans surcharge cognitive.


* **Amorçage contrôlé** : L'utilisation du drapeau `interfaceInitialisee` dans `app.js` garantit que les écouteurs d'événements des trois modules (`initialiserGeneration()`, `initialiserConsultation()`, `initialiserUsb()`) ne sont attachés qu'une seule fois après validation effective de la session, même si l'utilisateur réessaie d'ouvrir la session après une expiration.


* **Gestion de la concurrence côté client** :
* Dans `consultation.js`, la recherche débouncée (280 ms) utilise un compteur monotone `etat.sequence` (`const sequence = ++etat.sequence; ... if (sequence !== etat.sequence) return;`) qui élimine toute condition de course (*race condition*) en cas de réponses réseau désordonnées.


* Dans `generation.js`, l'interrogation périodique (`setInterval` à 900 ms) est systématiquement nettoyée par `arreterSuivi()` avant toute nouvelle souscription ou lors des transitions d'état finales (`succes`, `erreur`, `annule`).





### 4.2 Traitement des erreurs et contrat d'API

* **[ARCH-01] Perte de la référence de diagnostic `donnees.reference` sur erreur HTTP 500 (Sévérité : Mineur) — RÉSOLU (v1.0.1)** :
* **Statut** : corrigé dans `web/static/ui.js`. `messageErreur()` concatène `(Référence : …)` lorsque `donnees.reference` est une chaîne non vide, sans journaliser ni exposer d'autre donnée serveur.
* **Localisation** : `web/static/ui.js` (fonction `messageErreur(donnees, statut)`).


* **Analyse** : Lorsqu'une exception non gérée survient côté serveur, `erreur_generale()` dans `web/securite.py` renvoie `{"erreur": "Erreur interne. Consultez le terminal du serveur avec cette référence.", "code": "erreur_interne", "reference": "a1b2c3d4"}`. Or, `messageErreur()` dans `ui.js` se limite à :


```javascript
function messageErreur(donnees, statut) {
  if (donnees && typeof donnees.erreur === "string" && donnees.erreur.trim()) {
    return donnees.erreur;
  }
  return `Erreur HTTP ${statut}.`;
}

```


Le champ `donnees.reference` est ignoré, rendant le message affiché à l'utilisateur incomplet et contradictoire.




* **[ARCH-02] Écrasement de la structure interne de `#gen-erreur` par `afficherMessage()` (Sévérité : Mineur) — RÉSOLU (v1.0.1)** :
* **Statut** : corrigé dans `web/templates/index.html`. `#gen-erreur` est désormais un conteneur vide, aligné sur les autres blocs `.message.erreur` et compatible avec `element.textContent`.
* **Localisation** : `web/templates/index.html` et `web/static/ui.js` (`afficherMessage`).


* **Analyse** : Dans `index.html`, le bloc `#gen-erreur` est structuré avec un titre et un paragraphe dédié : `<div id="gen-erreur" class="message erreur" hidden><strong>Impossible d'analyser ce fichier.</strong><p id="gen-erreur-message"></p></div>`. Cependant, `generation.js` appelle `afficherMessage($("#gen-erreur"), erreur.message)`, qui exécute `element.textContent = texte;`, détruisant définitivement le `<strong>` et le `<p id="gen-erreur-message">` enfants.





---

## 5. Constats d'accessibilité (RGAA / WAI-ARIA) et d'expérience utilisateur (UX)

### 5.1 Conformité des composants WAI-ARIA et navigation clavier (Étape 6)

* **Lien d'évitement et structure sémantique** : Le lien `.lien-evitement` (« Aller au contenu ») est le premier élément focusable du DOM, pointe vers `<main id="contenu">` et devient visible au focus clavier (`:focus-visible { top: 1rem; }`).


* **Système d'onglets (ARIA Tabs)** : Le composant `<nav class="onglets" role="tablist">` associe correctement chaque `<button role="tab" aria-selected="..." aria-controls="...">` à sa `<section role="tabpanel" aria-labelledby="...">`. La navigation clavier gère `ArrowLeft`, `ArrowRight`, `Home` et `End` de manière circulaire.


* *[A11Y-03] Amélioration WAI-ARIA Tabs (RÉSOLU v1.0.1)* : Les onglets inactifs (`aria-selected="false"`) portent désormais `tabindex="-1"` et l'onglet actif `tabindex="0"`, avec mise à jour dynamique dans `initialiserOnglets()` ; le libellé du champ est conservé via `bouton.dataset.libelle` pour restaurer `aria-label="Afficher <libellé>"` au re-masquage.




* **Zones de dépôt et boîte de dialogue `<dialog>**` : Les zones `#zone-depot` et `#zone-depot-scans` disposent de `tabindex="0"`, `role="button"`, `aria-describedby` et déclenchent l'ouverture du sélecteur de fichiers sur `Enter` et `Espace`. Le composant `<dialog id="dialogue-confirmation">` utilise l'API native `showModal()` qui piège le focus et gère la touche `Escape` nativement, avec repli sur `window.confirm`.



### 5.2 Signalement des erreurs et ergonomie visuelle

* **[A11Y-01] Absence d'indicateur `:focus-visible` sur les cartes de choix radio `.choix` et certains boutons métiers (Sévérité : Mineur) — RÉSOLU (v1.0.1)** :
* **Statut** : corrigé dans `web/static/style.css`. La règle d'outline couvre `.choix:has(input:focus-visible)`, `.dossier-detecte`, `.resultat-recherche`, `.champ-masque-bouton` et `.fichier-telechargement`.
* **Localisation** : `web/static/style.css`.


* **Analyse** : Dans `style.css`, les boutons radio des cartes `.choix` (`#gen-layouts` et `#usb-operations`) sont masqués visuellement par `.choix input { position: absolute; opacity: 0; pointer-events: none; }`. Si l'état coché est stylé via `.choix:has(input:checked)`, aucune règle `.choix:has(input:focus-visible)` n'est définie. De même, la règle d'outline `:focus-visible` cible `.bouton:focus-visible, .onglet:focus-visible, .zone-depot:focus-visible`, oubliant les boutons `.dossier-detecte`, `.resultat-recherche`, `.champ-masque-bouton` et `.fichier-telechargement` (qui s'appuient alors uniquement sur l'outline natif du navigateur).




* **[A11Y-02] Absence d'attribut `role="alert"` sur les blocs de messages d'erreur dynamiques (Sévérité : Mineur) — RÉSOLU (v1.0.1)** :
* **Statut** : corrigé dans `web/static/ui.js`. `afficherMessage()` applique `role="alert"` pour une erreur et `role="status"` sinon ; `masquerMessage()` retire l'attribut et vide le texte.
* **Localisation** : `web/templates/index.html` et `web/static/ui.js` (`afficherMessage()`).


* **Analyse** : Les conteneurs d'erreur intégrés (`#gen-erreur`, `#gen-echec`, `#cons-erreur-source`, `#cons-erreur-scans`, `#cons-erreur-extraction`, `#cons-erreur-globale`, `#usb-erreur`, `#usb-erreur-operation`) ne possèdent pas `role="alert"` ni `aria-live="assertive"`. Lorsqu'une erreur de validation (ex. chemin de dossier vide, confirmation d'initialisation USB manquante, fichier > 338 000 octets) est affichée uniquement via `afficherMessage()` sans `toast()`, elle n'est pas annoncée par les technologies d'assistance.




* **Contrastes, typographie et mouvement réduit** :
* Les couples de couleurs principaux dans `style.css` offrent un excellent ratio de contraste WCAG AA/AAA : texte principal `#1d2a24` sur fond `#fffaf0` (> 13:1), texte secondaire `#4f5f56` sur `#fffaf0` (~6,3:1), boutons principaux `#fff9ed` sur `#123f32` (> 11:1), et alertes d'erreur `#631c1c` sur `#f7e2df` (> 7:1).


* La media query `@media (prefers-reduced-motion: reduce)` désactive intégralement les animations (`apparition`, `toast`, `sceau`, `tourner`) et les transitions.





---

## 6. Évaluation fonctionnelle des parcours et scénarios synthétiques (Étape 7)

L'analyse de bout en bout de la chaîne d'exécution entre le frontend (`web/static/`) et le backend (`web/serveur.py` et `web/services/`) valide le comportement exact des scénarios de référence :

1. **Contrôle des en-têtes et des gardes d'accès HTTP (`/`, `/api/etat`)** :
* Une requête `GET /` retourne le gabarit `index.html` accompagné des en-têtes `Content-Security-Policy` stricts et `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` injectés par `ajouter_entetes()`.


* Une requête `GET /api/etat` avec l'en-tête `X-QR-Web: 1` mais sans cookie `qr_web_session` est interceptée par `controler_acces()` dans `web/securite.py` et rejetée en **`401`** (`{"code": "session_expiree", ...}`).


* Une requête `GET /api/etat` sans l'en-tête `X-QR-Web: 1` est immédiatement rejetée en **`403`** (`{"code": "entete_manquant", ...}`) avant même la lecture du cookie.




2. **Parcours Génération (CSV synthétique Bitwarden / KeePassXC)** :
* **Préflight et refus aux bornes** : Un fichier vide (`0` octet) ou dépassant `338 000` octets est bloqué immédiatement côté client dans `analyserFichier()` (`generation.js`) sans appel réseau, et revalidé côté serveur par `lire_corps_limite(config.LIMITE_CSV)` (renvoyant `413` au-delà du plafond) et `analyser_donnees()`.


* **Exécution et suivi** : `POST /api/generation` crée un `EspaceRam("gen")`, lance `creer_sauvegarde_qr.sh` dans un groupe de processus isolé avec `PYTHON_SYSTEME` et répond `202`. Le suivi à 900 ms met à jour `<progress id="gen-progression">`, vérifie la concordance du `sha256`, de `total_chunks` et de `record_count` dans `_verifier_resultat()`, puis affiche le sceau de succès.




3. **Parcours Consultation (Scans Binary Eye synthétiques, NBSP, Révélation)** :
* **Validation des scans** : `uploader_scans()` refuse les fichiers > 16 Mio (`413`), les structures non-listes, les exports sans saut de ligne après l'en-tête `LQR1` (exports CSV aplatis) et les scans traduits détectés par `ee.semble_traduit()` (`400 scans_traduits`).


* **Recherche et extraction** : La recherche débouncée filtre sur `record_id` (`R\d+`) ou `nom` (insensible à la casse et aux espaces insécables via `normaliser_nbsp`). L'extraction masque `login_password`, `login_totp`, `notes` et `fields` ; le champ `uri` est rédigé (`https://•••@hôte`) et l'URI complète avec identifiants n'est proposée que parmi les champs masqués, via `POST /reveler`.


* **Révélation et restauration** : Le clic sur l'icône d'œil interroge `POST /reveler`, affiche le secret et arme le minuteur `data-ttl`. La restauration complète distingue les trois verdicts `identique`, `nbsp` (`IDENTIQUE APRÈS NORMALISATION NBSP`) et `different` (avec alerte rouge de préservation du CSV source).




4. **Parcours Coffre USB (Simulation `lsblk` et `udisksctl`)** :
* **Transition Ambre → Vert** : Un disque USB sûr (ou un loopback de test sûr) ayant une partition montée est classé dans `a_demonter` (badge ambre « Partition montée (accès verrouillé) »). L'action « Démonter la partition » appelle `udisksctl unmount --no-user-interaction -b`, vide `etat.donnees`, recharge `chargerPeripheriques(true)` et sélectionne automatiquement le support devenu `candidat` (ou `test` pour un loopback), ouvrant l'étape 2.


* **Refus et conflits** : Une partition système renvoie `403 partition_non_autorisee` sans commande de secours ; si une partition est remontée avant `POST /api/usb/commandes`, le serveur renvoie `409 partition_montee`, ce qui déclenche automatiquement le rafraîchissement de la détection dans `genererCommandes()` (`if (/partition.*mont[ée]e/i.test(erreur.message))`).





---

## 7. Plan de remédiation priorisé

Aucune vulnérabilité de sévérité **Bloquante** (ex. exécution de code à distance, écoute réseau exposée, exécution `sudo` non autorisée, fuite de secret dans les journaux) n'a été relevée. Les recommandations ci-dessous sont ordonnées par niveau de criticité décroissant (**Majeur**, **Mineur**, **Amélioration**) et ont toutes été appliquées dans la version **v1.0.1** ; les tests synthétiques de validation sont décrits au § 6 et dans `.agents/skills/interface-web-locale/SKILL.md`.

### Priorité 1 — Sévérité Majeure

#### 1. [SEC-01] Rédiger les identifiants intégrés dans le champ `uri` lors de l'extraction — **RÉSOLU (v1.0.1)**

* **Fichier cible** : `web/services/consultation.py` (fonction `extraire()`).


* **Solution technique** : Appliquer la fonction existante `rediger_uri()` sur la valeur visible du champ `uri` dans `extraire()` (exactement comme dans `rechercher()`), et, si l'URI originale contient des identifiants (`rediger_uri(val) != val`), ajouter l'URI complète non rédigée dans la liste des champs `masques` afin qu'elle ne soit accessible qu'après un appel explicite à `POST /reveler` :


```python
# Dans web/services/consultation.py -> extraire()
valeur_brute = row[index] if index < len(row) else ""
valeur_visible = (
    rediger_uri(valeur_brute)
    if libelle == LIBELLES_SURS["uri"]
    else valeur_brute
)
visibles.append(
    {
        "cle": entete[index],
        "libelle": libelle,
        "valeur": valeur_visible,
    }
)

```



#### 2. [SEC-02] Masquer immédiatement les secrets révélés lors de l'expiration de session — **RÉSOLU (v1.0.1)**

* **Fichiers cibles** : `web/static/modules/consultation.js` et `web/static/app.js`.


* **Solution technique** : Exporter une fonction `masquerSecretsConsultation()` depuis `consultation.js` qui annule `minuteurMasquage`, parcourt `tousLesBlocs()` pour exécuter `afficherBloc(element, false)` (supprimant `dataset.valeur` et rétablissant `••••••••`) et réinitialise `#cons-bouton-reveler`, puis l'appeler dès l'entrée dans le callback `surSessionExpiree()` de `app.js` tout en conservant `jetonMemoire` :


```javascript
// Dans web/static/modules/consultation.js
export function masquerSecretsConsultation() {
  annulerMasquage();
  tousLesBlocs().forEach((element) => afficherBloc(element, false));
  const bouton = $("#cons-bouton-reveler");
  if (bouton) {
    bouton.innerHTML = `${icone("oeil")} Afficher les secrets`;
    bouton.dataset.affiche = "0";
  }
}

```



#### 3. [SEC-03] Contrôler `scans_info["manquants_total"]` côté serveur dans `extraire()` et `restaurer()` — **RÉSOLU (v1.0.1)**

* **Fichier cible** : `web/services/consultation.py` (fonctions `extraire()` et `restaurer()`).


* **Solution technique** : Ajouter une vérification stricte de complétude des scans au début de `restaurer()` et de `extraire()` :


```python
if not session.scans_info or session.scans_info.get("manquants_total", 0) > 0:
    raise ErreurUtilisateur(
        "Des morceaux QR manquent dans l'export de scans. Complétez les scans avant de continuer.",
        409,
        "scans_incomplets",
    )

```



---

### Priorité 2 — Sévérité Mineure

#### 4. [SEC-04a] Compléter le nettoyage DOM dans `purgerGeneration()` — **RÉSOLU (v1.0.1)**

* **Fichier cible** : `web/static/modules/generation.js` (fonction `purgerGeneration()`).


* **Solution technique** : Aligner `purgerGeneration()` sur `reinitialiser()` en vidant explicitement les quatre conteneurs de résultats (`#gen-fichiers`, `#gen-resultat-stats`, `#gen-resultat-avertissements`, `#gen-resume`) ou en appelant directement `reinitialiser(false)` après la suppression serveur :


```javascript
$("#gen-fichiers").innerHTML = "";
$("#gen-resultat-stats").innerHTML = "";
$("#gen-resultat-avertissements").innerHTML = "";
$("#gen-resume").textContent = "";

```



#### 5. [SEC-04b] Réinitialiser le cache et l'affichage du module USB lors de `purgeGlobale()` — **RÉSOLU (v1.0.1)**

* **Fichiers cibles** : `web/static/modules/usb.js` et `web/static/app.js`.


* **Solution technique** : Créer et exporter une fonction `reinitialiserUsb()` dans `usb.js` qui remet `etat.donnees = null`, `etat.selection = null`, `etat.commandes = null`, vide `#usb-peripheriques`, `#usb-dependances`, `#usb-appareil-selectionne`, `#usb-commandes`, `#usb-checkliste`, `#usb-avertissements`, masque `#usb-etape-operation` et `#usb-etape-commandes`, et l'appeler dans `purgeGlobale()` (`app.js`).



#### 6. [ARCH-01] Restituer `donnees.reference` dans `messageErreur()` sur erreur 500 — **RÉSOLU (v1.0.1)**

* **Fichier cible** : `web/static/ui.js` (fonction `messageErreur()`).


* **Solution technique** : Concaténer la référence d'incident lorsqu'elle est présente dans la réponse JSON d'erreur :


```javascript
function messageErreur(donnees, statut) {
  if (donnees && typeof donnees.erreur === "string" && donnees.erreur.trim()) {
    if (typeof donnees.reference === "string" && donnees.reference.trim()) {
      return `${donnees.erreur} (Référence : ${donnees.reference.trim()})`;
    }
    return donnees.erreur;
  }
  return `Erreur HTTP ${statut}.`;
}

```



#### 7. [USB-01] Permettre le démontage assisté ou documenter explicitement le cas d'un `/dev/loopX` monté — **RÉSOLU (v1.0.1)**

* **Fichier cible** : `web/services/usb.py` (fonctions `_analyser()` et `demonter_partition()`).


* **Solution technique** : Si le parcours de test loopback doit couvrir le démontage assisté dans l'interface, autoriser un périphérique `est_loop` réunissant tous les autres critères de sécurité (`taille >= 1 Gio`, `not ro`, `not systeme`, `not swap`, `not holders`, `not danger`) à entrer dans `a_demonter` lorsqu'il est monté (`monte=True`).



#### 8. [A11Y-01 & A11Y-02] Ajouter `:focus-visible` sur `.choix` et `role="alert"` sur les erreurs dynamiques — **RÉSOLU (v1.0.1)**

* **Fichiers cibles** : `web/static/style.css` et `web/static/ui.js`.


* **Solution technique** :
* Dans `web/static/style.css`, ajouter `.choix:has(input:focus-visible)`, `.dossier-detecte:focus-visible`, `.resultat-recherche:focus-visible`, `.champ-masque-bouton:focus-visible` et `.fichier-telechargement:focus-visible` à la règle d'outline `3px solid rgba(28, 90, 71, 0.35)`.


* Dans `web/static/ui.js` (`afficherMessage`), ajouter `element.setAttribute("role", type === "erreur" ? "alert" : "status");` lors de l'affichage d'un message.





---

### Priorité 3 — Améliorations d'ergonomie et de finition

* **[ARCH-02] Préservation ou simplification de `#gen-erreur**` — **RÉSOLU (v1.0.1)** : Dans `web/templates/index.html`, simplifier `<div id="gen-erreur" class="message erreur" hidden></div>` (comme tous les autres blocs `.message.erreur` du gabarit) afin d'éviter la divergence avec `afficherMessage()` qui utilise `element.textContent`.


* **[A11Y-03] Roving `tabindex` sur la barre d'onglets et cohérence du `aria-label` de masquage — **RÉSOLU (v1.0.1)** :
* Dans `web/templates/index.html` et `web/static/app.js` (`initialiserOnglets`), appliquer `tabindex="0"` sur l'onglet actif et `tabindex="-1"` sur les onglets inactifs.


* Dans `web/static/modules/consultation.js` (`rendreExtraction` et `afficherBloc`), stocker le libellé du champ dans `bouton.dataset.libelle = champ.libelle` pour restaurer `aria-label="Afficher ${bouton.dataset.libelle}"` lors du re-masquage au lieu du libellé générique `"Afficher le secret"`.