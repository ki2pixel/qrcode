// Module « Consulter » : sources, scans Binary Eye, extraction et restauration.

import {
  $,
  afficher,
  afficherMessage,
  api,
  confirmer,
  debounce,
  echapper,
  envoyer,
  icone,
  masquerMessage,
  octets,
  telecharger,
  toast,
} from "../ui.js";

const etat = {
  session: null,
  sources: null,
  scans: null,
  extraction: null,
  requete: "",
  sequence: 0,
  chargementSources: false,
};

let minuteurMasquage = null;

const etapes = ["source", "scans", "recherche", "resultat"];

function marquerEtape(active) {
  const index = etapes.indexOf(active);
  $("#etapes-consultation li") &&
    [...$("#etapes-consultation").children].forEach((element, position) => {
      element.classList.toggle("actif", position === index);
      element.classList.toggle("fait", position < index);
    });
}

function afficherEtape(active) {
  ["source", "scans", "recherche"].forEach((nom) => {
    afficher($(`#cons-etape-${nom}`), nom === active);
  });
  if (active === "source") {
    afficher($("#cons-etape-recherche"), false);
    afficher($("#cons-etape-scans"), false);
  }
  marquerEtape(active);
}

function raccourcir(texte, longueur = 20) {
  const valeur = String(texte || "");
  if (valeur.length <= longueur * 2) return valeur;
  return `${valeur.slice(0, longueur)}…${valeur.slice(-longueur)}`;
}

function resumeMeta(meta) {
  return [
    ["Source", meta.source || "—"],
    ["Entrées", meta.record_count ?? "—"],
    ["Morceaux", meta.total_chunks ?? "—"],
    ["Taille", octets(meta.size)],
    ["SHA-256", raccourcir(meta.sha256, 12)],
    ["Segmentation", `${meta.chunk_size || 500} octets`],
  ];
}

function rendreResumeSource() {
  const zone = $("#cons-source-resume");
  if (!etat.session) {
    zone.innerHTML = "";
    return;
  }
  const meta = etat.session.meta || {};
  zone.innerHTML = "";
  const titre = document.createElement("strong");
  titre.textContent = etat.session.source_nom || "Sauvegarde QR";
  zone.append(titre);
  for (const [libelle, valeur] of resumeMeta(meta)) {
    const element = document.createElement("span");
    element.textContent = `${libelle} : ${valeur}`;
    zone.append(element);
  }
}

function activerSession(session) {
  etat.session = session;
  etat.scans = session.scans || null;
  etat.extraction = null;
  $("#cons-recherche").value = "";
  etat.requete = "";
  $("#cons-resultats").innerHTML = "";
  afficher($("#cons-detail"), false);
  masquerMessage($("#cons-erreur-extraction"));
  masquerMessage($("#cons-erreur-globale"));
  afficher($("#cons-restauration-resultat"), false);
  rendreResumeSource();
  afficherEtape("scans");
  if (etat.session.id) {
    afficher($("#cons-etape-scans"), true);
    afficher($("#cons-etape-source"), false);
    afficher($("#cons-etape-recherche"), false);
    document.getElementById("module-consultation")?.scrollIntoView({ block: "start" });
  }
}

async function chargerSources() {
  if (etat.chargementSources) return;
  etat.chargementSources = true;
  try {
    const sources = await api("/api/consultation/sauvegardes");
    etat.sources = sources;
    rendreSourcesSession(sources.sessions || []);
    rendreDossiers(sources.dossiers || []);
  } catch (erreur) {
    afficherMessage($("#cons-erreur-source"), erreur.message);
  } finally {
    etat.chargementSources = false;
  }
}

function rendreSourcesSession(sessions) {
  const zone = $("#cons-sources-session");
  zone.innerHTML = "";
  if (!sessions.length) {
    const vide = document.createElement("p");
    vide.className = "aide";
    vide.textContent =
      "Aucune sauvegarde générée dans cette session. Utilisez un dossier local ou une archive ZIP.";
    zone.append(vide);
    return;
  }
  for (const session of sessions) {
    const bloc = document.createElement("div");
    bloc.className = "source-session";
    const texte = document.createElement("div");
    const titre = document.createElement("strong");
    titre.textContent = session.nom;
    const detail = document.createElement("span");
    detail.className = "petit";
    detail.textContent = `${session.morceaux ?? "?"} QR · généré pendant cette session`;
    texte.append(titre, detail);
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "bouton bouton-principal bouton-petit";
    bouton.textContent = "Ouvrir";
    bouton.addEventListener("click", () => ouvrirSource({ type: "job", job_id: session.id }));
    bloc.append(texte, bouton);
    zone.append(bloc);
  }
}

function rendreDossiers(dossiers) {
  const zone = $("#cons-dossiers-detectes");
  zone.innerHTML = "";
  if (!dossiers.length) {
    const vide = document.createElement("p");
    vide.className = "aide";
    vide.textContent = "Aucun dossier de sauvegarde détecté automatiquement.";
    zone.append(vide);
    return;
  }
  dossiers.slice(0, 8).forEach((dossier) => {
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "dossier-detecte";
    bouton.innerHTML = `${icone("dossier")}<span>${echapper(dossier.nom)}</span>`;
    bouton.title = dossier.chemin;
    bouton.addEventListener("click", () => {
      $("#cons-chemin").value = dossier.chemin;
      ouvrirSource({ type: "dossier", chemin: dossier.chemin });
    });
    zone.append(bouton);
  });
}

async function ouvrirSource(charge) {
  masquerMessage($("#cons-erreur-source"));
  try {
    const session = await api("/api/consultation/source", { method: "POST", json: charge });
    etat.session = session;
    etat.scans = session.scans || null;
    etat.extraction = null;
    activerSession(session);
    toast("Sauvegarde ouverte en RAM.", "succes", 4000);
  } catch (erreur) {
    afficherMessage($("#cons-erreur-source"), erreur.message);
  }
}

async function ouvrirDossier() {
  const chemin = $("#cons-chemin").value.trim();
  if (!chemin) {
    afficherMessage($("#cons-erreur-source"), "Indiquez le chemin d'un dossier de sauvegarde.");
    return;
  }
  await ouvrirSource({ type: "dossier", chemin });
}

async function ouvrirArchive() {
  const entree = $("#cons-fichier-zip");
  const fichier = entree.files?.[0];
  if (!fichier) {
    afficherMessage($("#cons-erreur-source"), "Choisissez d'abord une archive ZIP.");
    return;
  }
  masquerMessage($("#cons-erreur-source"));
  const bouton = $("#cons-bouton-zip");
  bouton.disabled = true;
  bouton.textContent = "Import en cours…";
  try {
    const donnees = await fichier.arrayBuffer();
    const session = await envoyer(
      "/api/consultation/archive",
      donnees,
      { "Content-Type": "application/zip", "X-QR-Fichier": encodeURIComponent(fichier.name) },
      "POST"
    );
    etat.session = session;
    etat.scans = session.scans || null;
    etat.extraction = null;
    activerSession(session);
    toast("Archive importée : seuls les index ont été extraits.", "succes", 5000);
  } catch (erreur) {
    afficherMessage($("#cons-erreur-source"), erreur.message);
  } finally {
    entree.value = "";
    bouton.disabled = false;
    bouton.textContent = "Importer l'archive";
  }
}

function rendreInfosScans(info) {
  const zone = $("#cons-scans-info");
  zone.innerHTML = "";
  if (!info) return;
  const complet = info.manquants_total === 0;
  const bloc = document.createElement("div");
  bloc.className = `message ${complet ? "succes" : "attention"}`;
  const lignes = [
    `${info.morceaux_trouves}/${info.morceaux_attendus} morceaux trouvés`,
    `${info.entrees} entrée(s) dans l'export`,
  ];
  if (info.doublons) lignes.push(`${info.doublons} doublon(s) ignoré(s)`);
  if (info.invalides) lignes.push(`${info.invalides} entrée(s) non LQR1 ignorée(s)`);
  if (info.autres_sauvegardes) {
    lignes.push(`${info.autres_sauvegardes} morceau(x) d'une autre sauvegarde ignoré(s)`);
  }
  if (!complet) {
    lignes.push(
      `Il manque ${info.manquants_total} morceau(x). Complétez les scans avant toute extraction.`
    );
    if (info.manquants?.length) {
      lignes.push(`Exemples manquants : ${info.manquants.slice(0, 8).join(", ")}…`);
    }
  } else {
    lignes.push("Tous les morceaux attendus sont présents.");
  }
  bloc.textContent = lignes.join(" · ");
  zone.append(bloc);
  if (complet) {
    const suite = document.createElement("button");
    suite.type = "button";
    suite.className = "bouton bouton-principal";
    suite.textContent = "Continuer vers la recherche";
    suite.addEventListener("click", () => afficherEtape("recherche"));
    zone.append(suite);
    window.setTimeout(() => {
      if (etat.session) afficherEtape("recherche");
    }, 600);
  }
}

async function envoyerScans(fichier) {
  if (!etat.session) return;
  if (!fichier) return;
  masquerMessage($("#cons-erreur-scans"));
  afficher($("#cons-nom-scans"), true);
  $("#cons-nom-scans").innerHTML = `${icone("fichier")}<div><strong>${echapper(
    fichier.name
  )}</strong><span>${octets(fichier.size)}</span></div>`;
  try {
    const donnees = await fichier.arrayBuffer();
    const reponse = await envoyer(
      `/api/consultation/${encodeURIComponent(etat.session.id)}/scans`,
      donnees,
      {
        "Content-Type": "application/json",
        "X-QR-Fichier": encodeURIComponent(fichier.name),
      },
      "POST"
    );
    etat.scans = reponse.scans;
    if (reponse.session) etat.session = reponse.session;
    etat.extraction = null;
    etat.requete = "";
    viderDetail();
    $("#cons-recherche").value = "";
    $("#cons-resultats").innerHTML = "";
    $("#cons-resultats-info").textContent =
      "Saisissez au moins un caractère. La recherche porte sur le nom (name/Title) et l'identifiant.";
    afficher($("#cons-restauration-resultat"), false);
    rendreInfosScans(reponse.scans);
    if (reponse.scans.morceaux_trouves === 0) {
      afficherMessage($("#cons-erreur-scans"), "Aucun morceau LQR1 exploitable dans cet export.");
    }
  } catch (erreur) {
    afficherMessage($("#cons-erreur-scans"), erreur.message);
  } finally {
    $("#cons-fichier-scans").value = "";
  }
}

function configurerDepotScans() {
  const zone = $("#zone-depot-scans");
  const entree = $("#cons-fichier-scans");
  zone.addEventListener("click", () => entree.click());
  zone.addEventListener("keydown", (evenement) => {
    if (evenement.key === "Enter" || evenement.key === " ") {
      evenement.preventDefault();
      entree.click();
    }
  });
  entree.addEventListener("change", () => {
    if (entree.files?.[0]) envoyerScans(entree.files[0]);
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
    if (fichier) envoyerScans(fichier);
  });
}

function viderDetail() {
  $("#cons-detail-titre").textContent = "";
  $("#cons-detail-metadonnees").innerHTML = "";
  $("#cons-champs-masques").innerHTML = "";
  $("#cons-erreur-extraction").hidden = true;
  afficher($("#cons-detail"), false);
  etat.extraction = null;
}

async function rechercher(requete) {
  etat.requete = requete;
  const sequence = ++etat.sequence;
  const zone = $("#cons-resultats");
  const info = $("#cons-resultats-info");
  if (!etat.session) return;
  if (!requete.trim()) {
    zone.innerHTML = "";
    info.textContent =
      "Saisissez au moins un caractère. La recherche porte sur le nom (name/Title) et l'identifiant.";
    return;
  }
  try {
    const reponse = await api(
      `/api/consultation/${encodeURIComponent(etat.session.id)}/recherche`,
      { method: "POST", json: { q: requete } }
    );
    if (sequence !== etat.sequence) return;
    rendreResultats(reponse);
  } catch (erreur) {
    if (sequence !== etat.sequence) return;
    zone.innerHTML = "";
    info.textContent = erreur.message;
  }
}

function suffixeVersNumero(valeur) {
  const resultat = /morceau_([a-z])([a-z])/.exec(String(valeur || ""));
  if (!resultat) return null;
  return (resultat[1].charCodeAt(0) - 97) * 26 + (resultat[2].charCodeAt(0) - 97) + 1;
}

function compterMorceaux(resultat) {
  const debut =
    suffixeVersNumero(resultat.morceau_debut) ?? suffixeVersNumero(resultat.morceaux);
  const fin = suffixeVersNumero(resultat.morceau_fin) ?? suffixeVersNumero(resultat.morceaux);
  if (debut === null || fin === null || fin < debut) return null;
  return fin - debut + 1;
}

function rendreResultats(reponse) {
  const zone = $("#cons-resultats");
  const info = $("#cons-resultats-info");
  zone.innerHTML = "";
  afficher($("#cons-detail"), false);
  if (!reponse.total) {
    info.textContent = "Aucune entrée ne correspond à cette recherche.";
    return;
  }
  info.textContent =
    reponse.total === 1
      ? "1 entrée trouvée."
      : `${reponse.total} entrées trouvées${reponse.tronque ? " — 50 premiers résultats affichés" : ""}.`;
  for (const resultat of reponse.resultats || []) {
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "resultat-recherche";
    const principal = document.createElement("span");
    principal.innerHTML = `<strong>${echapper(resultat.nom || "(sans nom)")}</strong><small>${echapper(
      resultat.uri || resultat.dossier || "—"
    )}</small>`;
    const identifiant = document.createElement("span");
    identifiant.className = "mono";
    identifiant.textContent = resultat.record_id;
    const action = document.createElement("span");
    action.className = "badge badge-neutre";
    const nombre = compterMorceaux(resultat);
    action.textContent = nombre === null ? "QR" : `${nombre} QR`;
    action.title = resultat.morceaux || "";
    bouton.append(principal, identifiant, action);
    bouton.addEventListener("click", () => extraire(resultat.record_id));
    zone.append(bouton);
  }
}

async function extraire(recordId) {
  if (!etat.session) return;
  masquerMessage($("#cons-erreur-globale"));
  try {
    const extraction = await api(
      `/api/consultation/${encodeURIComponent(etat.session.id)}/extraire`,
      { method: "POST", json: { record_id: recordId } }
    );
    etat.extraction = extraction;
    rendreExtraction(extraction);
    marquerEtape("resultat");
    document.getElementById("cons-detail")?.scrollIntoView({ block: "nearest" });
  } catch (erreur) {
    afficherMessage($("#cons-erreur-globale"), erreur.message);
  }
}

function rendreExtraction(extraction) {
  annulerMasquage();
  const premiere = extraction.lignes?.[0];
  const nom = premiere?.visibles?.find((champ) =>
    ["nom", "name", "title"].includes(String(champ.cle).toLowerCase())
  )?.valeur;
  $("#cons-detail-titre").textContent = `${extraction.record_id} — ${
    nom || "entrée extraite"
  }`;
  const metadonnees = $("#cons-detail-metadonnees");
  metadonnees.innerHTML = "";
  for (const champ of premiere?.visibles || []) {
    const bloc = document.createElement("div");
    const terme = document.createElement("dt");
    terme.textContent = champ.libelle;
    const valeur = document.createElement("dd");
    valeur.textContent = champ.valeur || "—";
    bloc.append(terme, valeur);
    metadonnees.append(bloc);
  }

  const zone = $("#cons-champs-masques");
  zone.innerHTML = "";
  (extraction.lignes || []).forEach((ligne, indexLigne) => {
    if ((extraction.lignes || []).length > 1) {
      const titre = document.createElement("h4");
      titre.textContent = `Ligne ${indexLigne + 1}`;
      zone.append(titre);
    }
    for (const champ of ligne.masques || []) {
      const bloc = document.createElement("div");
      bloc.className = "champ-masque";
      const libelle = document.createElement("span");
      libelle.className = "champ-masque-libelle";
      libelle.textContent = champ.libelle;
      const valeur = document.createElement("span");
      valeur.className = "champ-masque-valeur masquee";
      valeur.textContent = "••••••••";
      const bouton = document.createElement("button");
      bouton.type = "button";
      bouton.className = "champ-masque-bouton";
      bouton.dataset.ligne = String(indexLigne);
      bouton.dataset.cle = champ.cle;
      bouton.dataset.libelle = champ.libelle;
      bouton.setAttribute("aria-label", `Afficher ${champ.libelle}`);
      bouton.innerHTML = icone("oeil");
      bouton.addEventListener("click", () => basculerSecret(bouton));
      bloc.append(libelle, valeur, bouton);
      zone.append(bloc);
    }
  });
  afficher($("#cons-detail"), true);
  masquerMessage($("#cons-erreur-extraction"));
  const boutonTelecharger = $("#cons-bouton-telecharger-entree");
  boutonTelecharger.disabled = false;
  const boutonReveler = $("#cons-bouton-reveler");
  boutonReveler.innerHTML = `${icone("oeil")} Afficher les secrets`;
  boutonReveler.dataset.affiche = "0";
}

function blocsLigne(ligne) {
  return [...document.querySelectorAll("#cons-champs-masques .champ-masque")].filter(
    (element) => element.querySelector(".champ-masque-bouton")?.dataset.ligne === String(ligne)
  );
}

function tousLesBlocs() {
  return [...document.querySelectorAll("#cons-champs-masques .champ-masque")];
}

async function revelerLigne(ligne) {
  if (!etat.extraction || !etat.session) return;
  const blocs = blocsLigne(ligne);
  if (
    blocs.length &&
    blocs.every(
      (element) =>
        element.querySelector(".champ-masque-valeur")?.dataset.valeur !== undefined
    )
  ) {
    return;
  }
  const reponse = await api(
    `/api/consultation/${encodeURIComponent(etat.session.id)}/reveler`,
    {
      method: "POST",
      json: { extraction_id: etat.extraction.extraction_id, ligne },
    }
  );
  const champs = reponse.champs || [];
  blocs.forEach((element, index) => {
    const champ = champs[index];
    if (champ) {
      element.querySelector(".champ-masque-valeur").dataset.valeur = champ.valeur ?? "";
    }
  });
}

function afficherBloc(bloc, visible) {
  const valeur = bloc.querySelector(".champ-masque-valeur");
  const bouton = bloc.querySelector(".champ-masque-bouton");
  if (!valeur || !bouton) return;
  if (visible && valeur.dataset.valeur !== undefined) {
    valeur.textContent = valeur.dataset.valeur || "(vide)";
    valeur.classList.remove("masquee");
    valeur.dataset.affiche = "1";
    bouton.innerHTML = icone("oeil-barre");
    bouton.setAttribute("aria-label", "Masquer le secret");
  } else {
    valeur.textContent = "••••••••";
    valeur.classList.add("masquee");
    valeur.dataset.affiche = "0";
    delete valeur.dataset.valeur;
    bouton.innerHTML = icone("oeil");
    bouton.setAttribute(
      "aria-label",
      `Afficher ${bouton.dataset.libelle || "le secret"}`
    );
  }
}

function secondesTtl() {
  const valeur = Number(document.body.dataset.ttl);
  return Number.isFinite(valeur) && valeur > 0 ? valeur : 3600;
}

function planifierMasquage() {
  if (minuteurMasquage !== null) window.clearTimeout(minuteurMasquage);
  minuteurMasquage = window.setTimeout(() => {
    minuteurMasquage = null;
    const bouton = $("#cons-bouton-reveler");
    tousLesBlocs().forEach((element) => afficherBloc(element, false));
    if (bouton) {
      bouton.innerHTML = `${icone("oeil")} Afficher les secrets`;
      bouton.dataset.affiche = "0";
    }
    if (etat.extraction) {
      toast("Secrets masqués automatiquement après expiration de la session.", "attention", 9000);
    }
  }, secondesTtl() * 1000);
}

function annulerMasquage() {
  if (minuteurMasquage !== null) {
    window.clearTimeout(minuteurMasquage);
    minuteurMasquage = null;
  }
}

export function masquerSecretsConsultation() {
  annulerMasquage();
  tousLesBlocs().forEach((element) => afficherBloc(element, false));
  const bouton = $("#cons-bouton-reveler");
  if (bouton) {
    bouton.innerHTML = `${icone("oeil")} Afficher les secrets`;
    bouton.dataset.affiche = "0";
  }
}

async function basculerSecret(bouton) {
  const ligne = Number(bouton.dataset.ligne);
  const bloc = bouton.closest(".champ-masque");
  const valeur = bloc.querySelector(".champ-masque-valeur");
  if (valeur.dataset.affiche === "1") {
    afficherBloc(bloc, false);
    const resteVisible = tousLesBlocs().some(
      (element) => element.querySelector(".champ-masque-valeur")?.dataset.affiche === "1"
    );
    if (!resteVisible) annulerMasquage();
    return;
  }
  bouton.disabled = true;
  try {
    await revelerLigne(ligne);
    afficherBloc(bloc, true);
    planifierMasquage();
  } catch (erreur) {
    afficherMessage($("#cons-erreur-extraction"), erreur.message);
  } finally {
    bouton.disabled = false;
  }
}

async function basculerTousSecrets() {
  const bouton = $("#cons-bouton-reveler");
  const blocs = tousLesBlocs();
  if (!blocs.length) return;
  const tousAffiches = blocs.every(
    (element) => element.querySelector(".champ-masque-valeur")?.dataset.affiche === "1"
  );
  if (tousAffiches) {
    blocs.forEach((element) => afficherBloc(element, false));
    bouton.innerHTML = `${icone("oeil")} Afficher les secrets`;
    bouton.dataset.affiche = "0";
    annulerMasquage();
    return;
  }
  bouton.disabled = true;
  try {
    const lignes = [
      ...new Set(
        blocs
          .map((element) => element.querySelector(".champ-masque-bouton")?.dataset.ligne)
          .filter((valeur) => valeur !== undefined)
      ),
    ];
    for (const ligne of lignes) await revelerLigne(Number(ligne));
    blocs.forEach((element) => afficherBloc(element, true));
    bouton.innerHTML = `${icone("oeil-barre")} Masquer les secrets`;
    bouton.dataset.affiche = "1";
    planifierMasquage();
  } catch (erreur) {
    afficherMessage($("#cons-erreur-extraction"), erreur.message);
  } finally {
    bouton.disabled = false;
  }
}

async function telechargerExtraction() {
  if (!etat.session || !etat.extraction) return;
  const plusieurs = (etat.extraction.fichiers || []).length > 1;
  const nom = plusieurs
    ? `extraction_${etat.extraction.extraction_id}.zip`
    : etat.extraction.fichiers?.[0] || `entree_${etat.extraction.record_id || "extraction"}.csv`;
  try {
    await telecharger(
      `/api/consultation/${encodeURIComponent(etat.session.id)}/fichier/extraction`,
      nom
    );
  } catch (erreur) {
    afficherMessage($("#cons-erreur-extraction"), erreur.message);
  }
}

async function restaurer() {
  if (!etat.session) return;
  const bouton = $("#cons-bouton-restaurer");
  bouton.disabled = true;
  bouton.textContent = "Restauration en cours…";
  masquerMessage($("#cons-erreur-globale"));
  try {
    const resultat = await api(
      `/api/consultation/${encodeURIComponent(etat.session.id)}/restaurer`,
      { method: "POST" }
    );
    rendreRestauration(resultat);
    if (resultat.statut === "different") {
      toast("Restauration DIFFÉRENTE : ne supprimez pas l'original.", "erreur", 12000);
    } else if (resultat.statut === "nbsp") {
      toast("Restauration identique après normalisation NBSP.", "succes", 9000);
    } else {
      toast("Restauration identique au CSV d'origine.", "succes", 7000);
    }
  } catch (erreur) {
    afficherMessage($("#cons-erreur-globale"), erreur.message);
  } finally {
    bouton.disabled = false;
    bouton.textContent = "Restaurer tout le CSV";
  }
}

function rendreRestauration(resultat) {
  const zone = $("#cons-restauration-resultat");
  zone.innerHTML = "";
  const verdict = document.createElement("div");
  verdict.className = `verdict ${resultat.statut}`;
  const sceau = document.createElement("div");
  sceau.className = "sceau";
  sceau.innerHTML = icone(
    resultat.statut === "identique" ? "check" : resultat.statut === "nbsp" ? "alerte" : "croix"
  );
  const texte = document.createElement("div");
  const titre = document.createElement("strong");
  titre.textContent = resultat.libelle;
  const sousTitre = document.createElement("small");
  sousTitre.textContent =
    resultat.statut === "different"
      ? "Le CSV produit ne correspond pas au hash attendu. Conservez l'original et vérifiez les scans manquants."
      : resultat.statut === "nbsp"
        ? "Binary Eye a normalisé les espaces insécables U+00A0 ; les autres octets correspondent."
        : "Le SHA-256 et le nombre d'enregistrements correspondent exactement.";
  texte.append(titre, sousTitre);
  verdict.append(sceau, texte);
  zone.append(verdict);

  const tableau = document.createElement("table");
  tableau.className = "table-hash";
  const lignes = [
    ["SHA-256 attendu", resultat.sha_attendu],
    ["SHA-256 obtenu", resultat.sha_obtenu || "—"],
    ["Taille attendue", `${resultat.taille_attendue ?? "—"} octets`],
    ["Taille obtenue", `${resultat.taille_obtenue ?? "—"} octets`],
    ["Enregistrements attendus", resultat.enregistrements_attendus ?? "—"],
    ["Enregistrements obtenus", resultat.enregistrements_obtenus ?? "—"],
  ];
  if (resultat.statut === "nbsp") {
    lignes.push(["SHA sans NBSP attendu", resultat.sha_sans_nbsp_attendu]);
    lignes.push(["SHA sans NBSP obtenu", resultat.sha_sans_nbsp_obtenu || "—"]);
  }
  const corps = document.createElement("tbody");
  for (const [libelle, valeur] of lignes) {
    const ligne = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = libelle;
    const td = document.createElement("td");
    td.className = "mono";
    td.textContent = String(valeur ?? "—");
    ligne.append(th, td);
    corps.append(ligne);
  }
  tableau.append(corps);
  zone.append(tableau);

  if (resultat.fichier_disponible && etat.session) {
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "bouton bouton-secondaire";
    bouton.innerHTML = `${icone("telecharger")} Télécharger le CSV restauré (en clair)`;
    bouton.addEventListener("click", async () => {
      bouton.disabled = true;
      try {
        await telecharger(
          `/api/consultation/${encodeURIComponent(etat.session.id)}/fichier/restauration`,
          "restauration.csv"
        );
      } catch (erreur) {
        afficherMessage($("#cons-erreur-globale"), erreur.message);
      } finally {
        bouton.disabled = false;
      }
    });
    zone.append(bouton);
  }
  afficher(zone, true);
}

function reinitialiser() {
  annulerMasquage();
  etat.session = null;
  etat.scans = null;
  etat.extraction = null;
  etat.requete = "";
  $("#cons-recherche").value = "";
  $("#cons-resultats").innerHTML = "";
  $("#cons-resultats-info").textContent =
    "Saisissez au moins un caractère. La recherche porte sur le nom (name/Title) et l'identifiant.";
  $("#cons-scans-info").innerHTML = "";
  $("#cons-nom-scans").hidden = true;
  $("#cons-nom-scans").innerHTML = "";
  $("#cons-source-resume").innerHTML = "";
  $("#cons-fichier-zip").value = "";
  afficher($("#cons-restauration-resultat"), false);
  masquerMessage($("#cons-erreur-source"));
  masquerMessage($("#cons-erreur-scans"));
  masquerMessage($("#cons-erreur-globale"));
  masquerMessage($("#cons-erreur-extraction"));
  viderDetail();
  afficherEtape("source");
}

async function changerSource() {
  if (etat.session) {
    try {
      await api(`/api/consultation/${encodeURIComponent(etat.session.id)}`, {
        method: "DELETE",
      });
    } catch {
      // Session peut-être déjà expirée : le nettoyage local suffit.
    }
  }
  reinitialiser();
  await chargerSources();
}

async function purgerSession() {
  if (!etat.session) {
    reinitialiser();
    return;
  }
  const confirme = await confirmer({
    titre: "Purger cette consultation ?",
    message:
      "Les index copiés, les scans et les fichiers extraits en mémoire vive seront détruits immédiatement.",
    libelle: "Purger",
  });
  if (!confirme) return;
  try {
    await api(`/api/consultation/${encodeURIComponent(etat.session.id)}`, {
      method: "DELETE",
    });
  } catch {
    // La session a pu expirer : le résultat visible est de toute façon purgé.
  }
  reinitialiser();
  await chargerSources();
  toast("Consultation purgée de la mémoire vive.", "succes");
}

export function initialiserConsultation() {
  $("#cons-bouton-dossier")?.addEventListener("click", ouvrirDossier);
  $("#cons-chemin")?.addEventListener("keydown", (evenement) => {
    if (evenement.key === "Enter") ouvrirDossier();
  });
  $("#cons-bouton-zip")?.addEventListener("click", ouvrirArchive);
  $("#cons-bouton-changer-source")?.addEventListener("click", changerSource);
  $("#cons-bouton-purger")?.addEventListener("click", purgerSession);
  $("#cons-bouton-telecharger-entree")?.addEventListener("click", telechargerExtraction);
  $("#cons-bouton-reveler")?.addEventListener("click", basculerTousSecrets);
  $("#cons-bouton-restaurer")?.addEventListener("click", restaurer);
  configurerDepotScans();
  const recherche = debounce((valeur) => rechercher(valeur), 280);
  $("#cons-recherche")?.addEventListener("input", (evenement) => {
    recherche(evenement.target.value);
  });
  $("#cons-recherche")?.addEventListener("keydown", (evenement) => {
    if (evenement.key === "Enter") {
      evenement.preventDefault();
      rechercher(evenement.target.value);
    }
  });
}

export {
  chargerSources as rafraichirSources,
  reinitialiser as reinitialiserConsultation,
  purgerSession,
};
