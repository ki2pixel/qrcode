// Module « Créer mes QR codes » : préflight CSV et suivi du pipeline.

import {
  $,
  $$,
  afficher,
  afficherMessage,
  api,
  confirmer,
  echapper,
  envoyer,
  icone,
  masquerMessage,
  octets,
  toast,
  telecharger,
} from "../ui.js";

const etat = {
  fichier: null,
  apercu: null,
  jobId: null,
  intervalle: null,
  termine: false,
};

const etapes = ["import", "apercu", "progression", "resultat"];

function marquerEtape(active) {
  const index = etapes.indexOf(active);
  $$("#etapes-generation li").forEach((element, position) => {
    element.classList.toggle("actif", position === index);
    element.classList.toggle("fait", position < index);
  });
}

function afficherEtape(active) {
  etapes.forEach((nom) => {
    afficher($(`#gen-etape-${nom}`), nom === active);
  });
  marquerEtape(active);
}

function arreterSuivi() {
  if (etat.intervalle !== null) {
    window.clearInterval(etat.intervalle);
    etat.intervalle = null;
  }
}

function reinitialiser(supprimer = true) {
  arreterSuivi();
  const ancien = etat.jobId;
  etat.fichier = null;
  etat.apercu = null;
  etat.jobId = null;
  etat.termine = false;
  const entree = $("#fichier-csv");
  if (entree) entree.value = "";
  afficher($("#gen-fichier-choisi"), false);
  afficher($("#gen-analyse-en-cours"), false);
  masquerMessage($("#gen-erreur"));
  masquerMessage($("#gen-echec"));
  afficher($("#bouton-retour-apercu"), false);
  $("#gen-journal").textContent = "";
  $("#gen-fichiers").innerHTML = "";
  $("#gen-resultat-stats").innerHTML = "";
  $("#gen-resultat-avertissements").innerHTML = "";
  $("#gen-resume").textContent = "";
  afficherEtape("import");
  if (ancien && supprimer !== false) {
    api(`/api/generation/${encodeURIComponent(ancien)}`, { method: "DELETE" }).catch(() => {});
  }
}

async function purgerGeneration() {
  const confirme = await confirmer({
    titre: "Effacer la génération ?",
    message:
      "Les QR, PDF, index et l'archive encore présents en mémoire vive seront détruits immédiatement.",
    libelle: "Tout effacer",
  });
  if (!confirme) return;
  const identifiant = etat.jobId;
  arreterSuivi();
  if (identifiant) {
    try {
      await api(`/api/generation/${encodeURIComponent(identifiant)}`, {
        method: "DELETE",
      });
    } catch {
      // La génération a peut-être déjà été purgée : continuer le nettoyage local.
    }
  }
  etat.fichier = null;
  etat.apercu = null;
  etat.jobId = null;
  etat.termine = false;
  $("#fichier-csv").value = "";
  afficher($("#gen-fichier-choisi"), false);
  afficher($("#gen-analyse-en-cours"), false);
  masquerMessage($("#gen-erreur"));
  masquerMessage($("#gen-echec"));
  afficher($("#bouton-retour-apercu"), false);
  $("#gen-journal").textContent = "";
  afficherEtape("import");
  toast("Génération purgée de la mémoire vive.", "succes");
}

function descriptionFinLigne(code) {
  const libelles = { crlf: "CRLF (Windows)", lf: "LF (Unix)", cr: "CR (ancien Mac)" };
  return libelles[code] || "standard";
}

function rendreStatistiques(apercu) {
  const grille = $("#gen-stats");
  const elements = [
    ["Format détecté", apercu.format],
    ["Entrées", new Intl.NumberFormat("fr-FR").format(apercu.enregistrements)],
    [`QR code${apercu.morceaux > 1 ? "s" : ""}`, apercu.morceaux],
    ["Pages compactes", apercu.pages_compact],
    ["Pages confort", apercu.pages_confort],
    ["Taille", octets(apercu.taille)],
    ["Fins de ligne", descriptionFinLigne(apercu.fin_ligne)],
    ["Saut final", apercu.saut_final ? "préservé" : "absent (préservé)"],
  ];
  grille.innerHTML = elements
    .map(
      ([libelle, valeur]) =>
        `<div class="stat"><span class="stat-valeur">${echapper(valeur)}</span><span class="stat-libelle">${echapper(libelle)}</span></div>`
    )
    .join("");
  $("#gen-badge-format").textContent = apercu.format;
  $("#gen-badge-format").className = "badge badge-vert";
}

function rendreAvertissements(liste) {
  const zone = $("#gen-avertissements");
  zone.innerHTML = "";
  (liste || []).forEach((texte) => {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent = texte;
    zone.append(bloc);
  });
  if (apercuSansPlanches()) {
    const bloc = document.createElement("div");
    bloc.className = "message info";
    bloc.textContent =
      "Le mode « sans planches » ne produit pas de PDF ; les QR individuels et l'index HTML restent disponibles.";
    zone.append(bloc);
  }
}

function apercuSansPlanches() {
  const choix = $('input[name="mise-en-page"]:checked');
  return choix?.value === "aucune";
}

async function analyserFichier(fichier) {
  masquerMessage($("#gen-erreur"));
  masquerMessage($("#gen-echec"));
  etat.fichier = null;
  etat.apercu = null;
  afficher($("#gen-analyse-en-cours"), true);
  afficher($("#gen-etape-apercu"), false);
  afficher($("#gen-etape-import"), true);
  afficher($("#gen-fichier-choisi"), false);
  $$("#etapes-generation li").forEach((element, index) => {
    element.classList.toggle("actif", index === 0);
    element.classList.remove("fait");
  });

  if (fichier.size > 338000) {
    afficher($("#gen-analyse-en-cours"), false);
    afficherMessage(
      $("#gen-erreur"),
      `Le fichier fait ${octets(fichier.size)} alors que la limite stricte est de 338 000 octets (676 QR de 500 octets).`
    );
    return;
  }
  if (fichier.size === 0) {
    afficher($("#gen-analyse-en-cours"), false);
    afficherMessage($("#gen-erreur"), "Le fichier CSV est vide.");
    return;
  }

  try {
    const donnees = await fichier.arrayBuffer();
    const apercu = await envoyer("/api/generation/apercu", donnees, {
      "Content-Type": "text/csv",
      "X-QR-Fichier": encodeURIComponent(fichier.name),
    });
    etat.fichier = fichier;
    etat.apercu = apercu;
    afficher($("#gen-analyse-en-cours"), false);
    afficher($("#gen-fichier-choisi"), true);
    $("#gen-nom-fichier").textContent = fichier.name;
    $("#gen-taille-fichier").textContent = `${octets(fichier.size)} · ${apercu.enregistrements} entrée(s)`;
    rendreStatistiques(apercu);
    rendreAvertissements(apercu.avertissements);
    afficherEtape("apercu");
  } catch (erreur) {
    afficher($("#gen-analyse-en-cours"), false);
    afficher($("#gen-fichier-choisi"), etat.fichier !== null);
    afficherMessage($("#gen-erreur"), erreur.message);
  }
}

function choisirFichier(fichier) {
  if (!fichier) return;
  analyserFichier(fichier);
}

function mettreAJourProgression(instantane) {
  const progression = Math.max(0, Math.min(100, Number(instantane.progression) || 0));
  $("#gen-progression").value = progression;
  $("#gen-progression").textContent = `${progression} %`;
  $("#gen-pourcentage").textContent = `${progression} %`;
  $("#gen-etape").textContent = instantane.etape || "Traitement";
  const journal = $("#gen-journal");
  const messages = instantane.messages || [];
  const collé = journal.scrollTop + journal.clientHeight >= journal.scrollHeight - 30;
  journal.textContent = messages.join("\n");
  if (collé) journal.scrollTop = journal.scrollHeight;
}

function afficherEchec(message) {
  const zone = $("#gen-echec");
  if (zone) {
    zone.textContent = message;
    zone.hidden = false;
  }
  afficher($("#bouton-retour-apercu"), true);
  $("#gen-progression-titre").textContent = "La génération a échoué";
  $("#bouton-annuler-generation").disabled = true;
}

function rendreFichiers(resultat, jobId) {
  const zone = $("#gen-fichiers");
  zone.innerHTML = "";
  for (const fichier of resultat.fichiers || []) {
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "fichier-telechargement";
    bouton.dataset.cle = fichier.cle;
    bouton.dataset.nom = fichier.nom;
    bouton.innerHTML = `${icone(fichier.type === "zip" ? "archive" : fichier.type === "pdf" ? "imprimante" : "fichier")}
      <div><strong>${echapper(fichier.libelle)}</strong><span>${echapper(fichier.nom)} · ${octets(fichier.taille)}</span></div>`;
    bouton.addEventListener("click", async () => {
      bouton.disabled = true;
      try {
        await telecharger(
          `/api/generation/${encodeURIComponent(jobId)}/fichier/${encodeURIComponent(fichier.cle)}`,
          fichier.nom
        );
      } catch (erreur) {
        toast(erreur.message, "erreur", 8000);
      } finally {
        bouton.disabled = false;
      }
    });
    zone.append(bouton);
  }
}

function afficherResultat(instantane) {
  const resultat = instantane.resultat || {};
  $("#gen-resume").textContent =
    `La sauvegarde « ${resultat.nom_dossier || ""} » a été reconstruite et vérifiée. ` +
    "Le SHA-256 correspond au CSV d'origine et le nombre de QR est exact.";
  const stats = [
    ["Enregistrements", resultat.enregistrements],
    ["QR codes", resultat.morceaux],
    ["Taille du CSV", octets(resultat.taille_csv)],
    ["Mise en page", resultat.mise_en_page === "aucune" ? "sans planches" : resultat.mise_en_page],
  ];
  $("#gen-resultat-stats").innerHTML = stats
    .map(
      ([libelle, valeur]) =>
        `<div class="stat succes"><span class="stat-valeur">${echapper(valeur)}</span><span class="stat-libelle">${echapper(libelle)}</span></div>`
    )
    .join("");
  rendreFichiers(resultat, instantane.id);
  const zoneErreur = $("#gen-resultat-avertissements");
  zoneErreur.innerHTML = "";
  if (resultat.archive_erreur) {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent = resultat.archive_erreur;
    zoneErreur.append(bloc);
  }
  if ((resultat.fichiers || []).some((fichier) => fichier.type === "zip")) {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent =
      "L'archive ZIP n'est pas chiffrée : elle contient les QR, les index et les scripts en clair. Conservez-la dans un coffre ou supprimez-la après impression.";
    zoneErreur.append(bloc);
  }
  if (!resultat.weasyprint) {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent =
      "WeasyPrint n'était pas disponible : les PDF n'ont pas été produits. Les QR et le HTML restent exploitables.";
    zoneErreur.append(bloc);
  }
  afficherEtape("resultat");
}

function suivre(identifiant) {
  arreterSuivi();
  etat.intervalle = window.setInterval(async () => {
    if (!etat.jobId) return;
    try {
      const instantane = await api(
        `/api/generation/${encodeURIComponent(identifiant)}`
      );
      mettreAJourProgression(instantane);
      if (instantane.etat === "succes") {
        arreterSuivi();
        etat.termine = true;
        afficherResultat(instantane);
        toast("Génération terminée et vérifiée.", "succes", 5000);
      } else if (instantane.etat === "erreur") {
        arreterSuivi();
        etat.termine = true;
        afficherEchec(instantane.erreur || "Erreur inconnue.");
        toast("La génération a échoué.", "erreur", 8000);
      } else if (instantane.etat === "annule") {
        arreterSuivi();
        etat.jobId = null;
        if (etat.fichier) {
          afficherEtape("apercu");
        } else {
          etat.apercu = null;
          afficherEtape("import");
        }
        toast("Génération annulée.", "attention", 5000);
      }
    } catch (erreur) {
      arreterSuivi();
      afficherEchec(erreur.message);
    }
  }, 900);
}

async function lancerGeneration() {
  if (!etat.fichier || !etat.apercu) return;
  const choix = $('input[name="mise-en-page"]:checked');
  const miseEnPage = choix?.value || "compact";
  const bouton = $("#bouton-generer");
  bouton.disabled = true;
  try {
    const donnees = await etat.fichier.arrayBuffer();
    const instantane = await envoyer(
      "/api/generation",
      donnees,
      {
        "Content-Type": "text/csv",
        "X-QR-Fichier": encodeURIComponent(etat.fichier.name),
        "X-QR-Mise-En-Page": miseEnPage,
      },
      "POST"
    );
    etat.jobId = instantane.id;
    etat.termine = false;
    afficherEtape("progression");
    $("#gen-progression-titre").textContent = "Génération en cours…";
    $("#gen-progression").value = 0;
    $("#gen-pourcentage").textContent = "0 %";
    $("#gen-journal").textContent = "";
    $("#bouton-annuler-generation").disabled = false;
    masquerMessage($("#gen-echec"));
    afficher($("#bouton-retour-apercu"), false);
    mettreAJourProgression(instantane);
    suivre(instantane.id);
  } catch (erreur) {
    toast(erreur.message, "erreur", 9000);
  } finally {
    bouton.disabled = false;
  }
}

async function annulerGeneration() {
  if (!etat.jobId) return;
  const bouton = $("#bouton-annuler-generation");
  bouton.disabled = true;
  try {
    await api(`/api/generation/${encodeURIComponent(etat.jobId)}/annuler`, {
      method: "POST",
    });
    toast("Annulation demandée…", "attention", 4000);
  } catch (erreur) {
    toast(erreur.message, "erreur", 6000);
    bouton.disabled = false;
  }
}

function configurerDepot(zone, entree, surFichier) {
  if (!zone || !entree) return;
  zone.addEventListener("click", () => entree.click());
  zone.addEventListener("keydown", (evenement) => {
    if (evenement.key === "Enter" || evenement.key === " ") {
      evenement.preventDefault();
      entree.click();
    }
  });
  entree.addEventListener("change", () => {
    if (entree.files && entree.files[0]) surFichier(entree.files[0]);
    entree.value = "";
  });
  ["dragenter", "dragover"].forEach((nom) => {
    zone.addEventListener(nom, (evenement) => {
      evenement.preventDefault();
      zone.classList.add("survol");
    });
  });
  ["dragleave", "drop"].forEach((nom) => {
    zone.addEventListener(nom, (evenement) => {
      evenement.preventDefault();
      zone.classList.remove("survol");
    });
  });
  zone.addEventListener("drop", (evenement) => {
    const fichier = evenement.dataTransfer?.files?.[0];
    if (fichier) surFichier(fichier);
  });
}

export function initialiserGeneration() {
  configurerDepot($("#zone-depot"), $("#fichier-csv"), choisirFichier);
  $("#bouton-remplacer-fichier")?.addEventListener("click", () => $("#fichier-csv").click());
  $("#bouton-changer-fichier")?.addEventListener("click", () => {
    afficherEtape("import");
    $("#fichier-csv").click();
  });
  $("#bouton-generer")?.addEventListener("click", lancerGeneration);
  $("#bouton-annuler-generation")?.addEventListener("click", annulerGeneration);
  $("#bouton-nouvelle-generation")?.addEventListener("click", reinitialiser);
  $("#bouton-purger-generation")?.addEventListener("click", purgerGeneration);
  $("#bouton-retour-apercu")?.addEventListener("click", () => {
    if (etat.apercu) afficherEtape("apercu");
    else afficherEtape("import");
  });
  $$('input[name="mise-en-page"]').forEach((entree) => {
    entree.addEventListener("change", () => {
      if (etat.apercu) rendreAvertissements(etat.apercu.avertissements);
    });
  });
}

export async function reprendreGeneration(jobs) {
  const actifs = (jobs || []).filter((job) =>
    ["attente", "en_cours"].includes(job.etat)
  );
  const succes = (jobs || []).filter((job) => job.etat === "succes");
  const choisi = actifs[0] || succes[0];
  if (!choisi) return;
  try {
    const instantane = await api(
      `/api/generation/${encodeURIComponent(choisi.id)}`
    );
    etat.jobId = choisi.id;
    etat.fichier = null;
    etat.apercu = null;
    afficher($("#gen-etape-import"), false);
    afficher($("#gen-etape-apercu"), false);
    afficher($("#gen-etape-progression"), false);
    if (instantane.etat === "succes") {
      etat.termine = true;
      afficherEtape("resultat");
      afficherResultat(instantane);
      toast("Génération précédente retrouvée en mémoire vive.", "info", 5000);
    } else if (["attente", "en_cours"].includes(instantane.etat)) {
      etat.termine = false;
      afficherEtape("progression");
      $("#gen-progression-titre").textContent = "Génération en cours…";
      $("#bouton-annuler-generation").disabled = false;
      afficher($("#bouton-retour-apercu"), false);
      mettreAJourProgression(instantane);
      suivre(choisi.id);
    }
  } catch {
    // La génération a pu expirer entre /api/etat et la lecture : ne pas bloquer.
  }
}

export { reinitialiser as reinitialiserGeneration, purgerGeneration };
