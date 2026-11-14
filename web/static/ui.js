// Utilitaires partagés : DOM, appels API, confirmations, téléchargements.
// Aucune donnée secrète n'est journalisée dans la console.

const gestionnaires = { sessionExpiree: null };

export const $ = (selecteur, racine = document) => racine.querySelector(selecteur);
export const $$ = (selecteur, racine = document) => [...racine.querySelectorAll(selecteur)];

export function surSessionExpiree(fonction) {
  gestionnaires.sessionExpiree = fonction;
}

export function icone(nom, classe = "icone") {
  return `<svg class="${classe}" aria-hidden="true"><use href="#icone-${nom}"></use></svg>`;
}

export function echapper(valeur) {
  return String(valeur ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function octets(nombre) {
  const valeur = Number(nombre);
  if (!Number.isFinite(valeur) || valeur < 0) return "—";
  if (valeur < 1024) return `${valeur} o`;
  if (valeur < 1024 * 1024) return `${(valeur / 1024).toFixed(1).replace(".0", "")} Kio`;
  if (valeur < 1024 * 1024 * 1024) {
    return `${(valeur / (1024 * 1024)).toFixed(1).replace(".0", "")} Mio`;
  }
  return `${(valeur / (1024 * 1024 * 1024)).toFixed(2).replace(".00", "")} Gio`;
}

export function vider(element) {
  while (element && element.firstChild) element.removeChild(element.firstChild);
}

export function afficher(element, visible = true) {
  if (element) element.hidden = !visible;
}

export function toast(message, type = "info", duree = 6000) {
  const zone = $("#zone-toasts");
  if (!zone) return;
  const element = document.createElement("div");
  element.className = `toast ${type}`;
  element.setAttribute("role", "status");
  element.textContent = message;
  zone.append(element);
  window.setTimeout(() => element.remove(), duree);
}

function messageErreur(donnees, statut) {
  if (donnees && typeof donnees.erreur === "string" && donnees.erreur.trim()) {
    return donnees.erreur;
  }
  return `Erreur HTTP ${statut}.`;
}

async function traiterReponse(reponse) {
  let donnees = null;
  const type = reponse.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    try {
      donnees = await reponse.json();
    } catch {
      donnees = null;
    }
  }
  if (reponse.status === 401) {
    gestionnaires.sessionExpiree?.();
    throw new Error(messageErreur(donnees, 401));
  }
  if (!reponse.ok) throw new Error(messageErreur(donnees, reponse.status));
  return donnees;
}

export async function api(chemin, options = {}) {
  const entetes = new Headers(options.headers || {});
  entetes.set("X-QR-Web", "1");
  let corps = options.body;
  if (options.json !== undefined) {
    entetes.set("Content-Type", "application/json");
    corps = JSON.stringify(options.json);
  }
  let reponse;
  try {
    reponse = await fetch(chemin, {
      method: options.method || "GET",
      headers: entetes,
      body: corps,
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (erreur) {
    if (erreur.name === "AbortError") throw erreur;
    throw new Error(
      "Connexion au serveur local interrompue. Vérifiez que ./lancer_interface.sh est toujours actif."
    );
  }
  return traiterReponse(reponse);
}

export async function envoyer(chemin, corps, entetes = {}, methode = "POST") {
  const entetesFinaux = new Headers(entetes);
  entetesFinaux.set("X-QR-Web", "1");
  let reponse;
  try {
    reponse = await fetch(chemin, {
      method: methode,
      headers: entetesFinaux,
      body: corps,
      credentials: "same-origin",
    });
  } catch {
    throw new Error(
      "Connexion au serveur local interrompue. Vérifiez que ./lancer_interface.sh est toujours actif."
    );
  }
  return traiterReponse(reponse);
}

export function confirmer({
  titre,
  message,
  libelle = "Confirmer",
  danger = true,
}) {
  const dialogue = $("#dialogue-confirmation");
  if (!dialogue || typeof dialogue.showModal !== "function") {
    return Promise.resolve(window.confirm(`${titre}\n\n${message}`));
  }
  $("#dialogue-titre").textContent = titre;
  $("#dialogue-message").textContent = message;
  const bouton = $("#dialogue-confirmer");
  bouton.textContent = libelle;
  bouton.className = danger ? "bouton bouton-danger" : "bouton bouton-principal";
  dialogue.returnValue = "annuler";
  return new Promise((resoudre) => {
    const surFermeture = () => {
      dialogue.removeEventListener("close", surFermeture);
      resoudre(dialogue.returnValue === "confirmer");
    };
    dialogue.addEventListener("close", surFermeture);
    dialogue.showModal();
  });
}

export async function telecharger(url, nom, { silencieux = false } = {}) {
  if (!silencieux) toast(`Préparation de « ${nom} »…`, "info", 3000);
  let reponse;
  try {
    reponse = await fetch(url, {
      headers: { "X-QR-Web": "1" },
      credentials: "same-origin",
    });
  } catch {
    throw new Error("Téléchargement impossible : connexion au serveur interrompue.");
  }
  if (reponse.status === 401) {
    gestionnaires.sessionExpiree?.();
    throw new Error("Session expirée.");
  }
  if (!reponse.ok) {
    let donnees = null;
    try {
      donnees = await reponse.json();
    } catch {
      donnees = null;
    }
    throw new Error(messageErreur(donnees, reponse.status));
  }
  const blob = await reponse.blob();
  const lien = document.createElement("a");
  const urlObjet = URL.createObjectURL(blob);
  lien.href = urlObjet;
  lien.download = nom;
  lien.rel = "noopener";
  document.body.append(lien);
  lien.click();
  lien.remove();
  window.setTimeout(() => URL.revokeObjectURL(urlObjet), 30000);
  if (!silencieux) toast(`Téléchargement lancé : ${nom}`, "succes", 4000);
}

export async function copier(texte, message = "Commande copiée dans le presse-papiers.") {
  try {
    await navigator.clipboard.writeText(texte);
    toast(message, "succes", 4000);
  } catch {
    toast(
      "Copie automatique impossible. Sélectionnez le texte puis Ctrl+C.",
      "attention",
      7000
    );
  }
}

export function afficherMessage(element, texte, type = "erreur") {
  if (!element) return;
  element.className = `message ${type}`;
  element.textContent = texte;
  element.hidden = false;
}

export function masquerMessage(element) {
  if (!element) return;
  element.hidden = true;
  element.textContent = "";
}

export function debounce(fonction, delai = 300) {
  let minuteur = null;
  return (...arguments_) => {
    window.clearTimeout(minuteur);
    minuteur = window.setTimeout(() => fonction(...arguments_), delai);
  };
}

export async function chargerEtatGlobal() {
  return api("/api/etat");
}
