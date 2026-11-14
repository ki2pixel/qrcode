// Amorçage de l'interface : jeton d'URL, onglets, hygiène et purge globale.

import {
  $,
  $$,
  afficher,
  api,
  confirmer,
  icone,
  surSessionExpiree,
  toast,
} from "./ui.js";
import {
  initialiserGeneration,
  purgerGeneration,
  reinitialiserGeneration,
  reprendreGeneration,
} from "./modules/generation.js";
import {
  initialiserConsultation,
  masquerSecretsConsultation,
  purgerSession,
  rafraichirSources,
  reinitialiserConsultation,
} from "./modules/consultation.js";
import {
  initialiserUsb,
  rafraichirPeripheriques,
  reinitialiserUsb,
} from "./modules/usb.js";

let jetonMemoire = "";
let sessionOuverte = false;
let interfaceInitialisee = false;

function afficherEcranSession(message, proposerReessai = true) {
  sessionOuverte = false;
  afficher($("#application"), false);
  afficher($("#ecran-session"), true);
  $("#message-session").textContent = message;
  const bouton = $("#bouton-reessayer");
  bouton.hidden = !proposerReessai || !jetonMemoire;
}

async function echangerJeton(jeton) {
  let reponse;
  try {
    reponse = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-QR-Web": "1" },
      body: JSON.stringify({ jeton }),
      credentials: "same-origin",
    });
  } catch {
    throw new Error(
      "Connexion au serveur local impossible. Vérifiez que ./lancer_interface.sh est actif."
    );
  }
  if (!reponse.ok) throw new Error("Jeton refusé. Relancez ./lancer_interface.sh.");
}

function rendreBandeau(etat) {
  const bandeau = $("#bandeau-hygiene");
  bandeau.innerHTML = "";
  const blocs = [];
  if (etat.swap_disque_actif) {
    blocs.push({
      type: "attention",
      texte:
        "Un swap disque est actif : des pages mémoire peuvent être écrites sur le disque. Pour une confidentialité maximale, relancez avec --strict-ram ou utilisez le coffre USB.",
    });
  }
  if (!etat.weasyprint) {
    blocs.push({
      type: "info",
      texte:
        "WeasyPrint n'est pas disponible : les PDF ne seront pas générés. Les QR individuels et l'index HTML restent produits.",
    });
  }
  if (!etat.qrencode || !etat.split) {
    blocs.push({
      type: "danger",
      texte: `Commande manquante : ${[
        !etat.qrencode ? "qrencode" : "",
        !etat.split ? "split" : "",
      ]
        .filter(Boolean)
        .join(", ")}. La génération échouera tant qu'elle n'est pas installée.`,
    });
  }
  if (!blocs.length) {
    bandeau.hidden = true;
    return;
  }
  for (const bloc of blocs) {
    const element = document.createElement("div");
    element.className = `bandeau ${bloc.type}`;
    element.textContent = bloc.texte;
    bandeau.append(element);
  }
  bandeau.hidden = false;
}

async function ouvrirApplication() {
  const etat = await api("/api/etat");
  sessionOuverte = true;
  afficher($("#ecran-session"), false);
  afficher($("#application"), true);
  rendreBandeau(etat);
  if (!interfaceInitialisee) {
    initialiserGeneration();
    initialiserConsultation();
    initialiserUsb();
    interfaceInitialisee = true;
  }
  await reprendreGeneration(etat.generations || []);
}

async function demarrer() {
  const parametres = new URLSearchParams(window.location.hash.slice(1));
  const jeton = parametres.get("jeton") || "";
  if (jeton) {
    jetonMemoire = jeton;
    history.replaceState(null, "", `${location.pathname}${location.search}`);
  }

  if (!jetonMemoire) {
    try {
      await ouvrirApplication();
      return;
    } catch (erreur) {
      afficherEcranSession(
        "Lien d'accès incomplet. Ouvrez exactement l'URL affichée dans le terminal par ./lancer_interface.sh, avec le fragment #jeton=….",
        false
      );
      return;
    }
  }

  try {
    $("#message-session").textContent = "Vérification du jeton local…";
    await echangerJeton(jetonMemoire);
    await ouvrirApplication();
  } catch (erreur) {
    afficherEcranSession(
      `${erreur.message} Si le serveur a été relancé, le jeton a changé : utilisez la nouvelle URL affichée dans le terminal.`
    );
  }
}

function initialiserOnglets() {
  const modules = {
    generation: $("#module-generation"),
    consultation: $("#module-consultation"),
    usb: $("#module-usb"),
  };
  $$(".onglet").forEach((onglet) => {
    onglet.addEventListener("click", () => {
      const cible = onglet.dataset.module;
      $$(".onglet").forEach((element) => {
        const actif = element === onglet;
        element.classList.toggle("actif", actif);
        element.setAttribute("aria-selected", actif ? "true" : "false");
        element.setAttribute("tabindex", actif ? "0" : "-1");
      });
      Object.entries(modules).forEach(([nom, module]) => {
        afficher(module, nom === cible);
      });
      if (cible === "consultation") rafraichirSources();
      if (cible === "usb") rafraichirPeripheriques();
    });
  });
  const barre = $(".onglets");
  barre?.addEventListener("keydown", (evenement) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(evenement.key)) return;
    const onglets = $$(".onglet");
    const index = onglets.indexOf(document.activeElement);
    if (index < 0) return;
    evenement.preventDefault();
    let cible = index;
    if (evenement.key === "ArrowLeft") cible = (index - 1 + onglets.length) % onglets.length;
    if (evenement.key === "ArrowRight") cible = (index + 1) % onglets.length;
    if (evenement.key === "Home") cible = 0;
    if (evenement.key === "End") cible = onglets.length - 1;
    onglets[cible].focus();
    onglets[cible].click();
  });
}

async function purgeGlobale() {
  const confirme = await confirmer({
    titre: "Purger toute la session ?",
    message:
      "Les générations, index copiés, scans, extractions et fichiers restaurés en mémoire vive seront détruits immédiatement. Les téléchargements déjà effectués sur le disque ne sont pas concernés.",
    libelle: "Purger maintenant",
  });
  if (!confirme) return;
  try {
    const resultat = await api("/api/purge", { method: "POST" });
    reinitialiserGeneration(false);
    reinitialiserConsultation();
    reinitialiserUsb();
    toast(
      `Session purgée : ${resultat.generations || 0} génération(s), ${resultat.consultations || 0} consultation(s).`,
      "succes",
      6000
    );
    rafraichirSources();
  } catch (erreur) {
    toast(erreur.message, "erreur", 8000);
  }
}

function initialiserGlobal() {
  initialiserOnglets();
  $("#bouton-purge-global")?.addEventListener("click", purgeGlobale);
  $("#bouton-reessayer")?.addEventListener("click", async () => {
    if (!jetonMemoire) return;
    try {
      $("#message-session").textContent = "Nouvelle tentative…";
      await echangerJeton(jetonMemoire);
      await ouvrirApplication();
    } catch (erreur) {
      afficherEcranSession(erreur.message);
    }
  });
  surSessionExpiree(() => {
    masquerSecretsConsultation();
    if (!sessionOuverte) return;
    afficherEcranSession(
      "La session locale a expiré ou le cookie a été effacé. Vous pouvez réessayer avec le jeton de ce lancement, ou relancer ./lancer_interface.sh."
    );
  });
}

initialiserGlobal();
demarrer();
