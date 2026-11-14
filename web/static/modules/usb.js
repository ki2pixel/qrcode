// Module « Coffre USB » : détection, démontage non privilégié via udisksctl
// et génération de commandes. Aucune commande privilégiée n'est exécutée.

import {
  $,
  $$,
  afficher,
  afficherMessage,
  api,
  copier,
  echapper,
  icone,
  masquerMessage,
  octets,
  toast,
} from "../ui.js";

const etat = {
  donnees: null,
  selection: null,
  chargement: false,
  commandes: null,
};

async function chargerPeripheriques(force = false) {
  if (etat.chargement) return;
  if (etat.donnees && !force) return;
  etat.chargement = true;
  masquerMessage($("#usb-erreur"));
  const bouton = $("#usb-bouton-rafraichir");
  if (bouton) bouton.disabled = true;
  try {
    const donnees = await api("/api/usb/peripheriques");
    etat.donnees = donnees;
    if (etat.selection) {
      const tous = [...(donnees.candidats || []), ...(donnees.tests || [])];
      etat.selection = tous.find((item) => item.chemin === etat.selection.chemin) || null;
    }
    rendreDependances(donnees.dependances || []);
    rendrePeripheriques(donnees);
    if (etat.selection) rendreSelection();
    else {
      afficher($("#usb-etape-operation"), false);
      afficher($("#usb-etape-commandes"), false);
    }
    const candidats = etat.donnees.candidats?.length || 0;
    const tests = etat.donnees.tests?.length || 0;
    const aDemonter = etat.donnees.a_demonter?.length || 0;
    if (!candidats && !tests && aDemonter) {
      toast(
        "Une clé amovible est détectée, mais une partition est montée. Démontez-la ci-dessous pour continuer.",
        "info",
        8000
      );
    } else if (!candidats && !tests && !aDemonter) {
      toast(
        "Aucun support sûr détecté. Vérifiez que la clé est branchée.",
        "attention",
        8000
      );
    }
  } catch (erreur) {
    afficherMessage($("#usb-erreur"), erreur.message);
  } finally {
    if (bouton) bouton.disabled = false;
    etat.chargement = false;
  }
}

function rendreDependances(dependances) {
  const zone = $("#usb-dependances");
  zone.innerHTML = "";
  for (const dependance of dependances) {
    const element = document.createElement("span");
    element.className = `dependance ${dependance.disponible ? "ok" : "absent"}`;
    element.innerHTML = `${icone(dependance.disponible ? "check" : "alerte")} ${echapper(
      dependance.commande
    )}`;
    element.title = `${dependance.description} : ${
      dependance.disponible ? "disponible" : "absent"
    }`;
    zone.append(element);
  }
  const manquantes = dependances.filter((element) => !element.disponible);
  if (manquantes.length) {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent = `Dépendances absentes : ${manquantes
      .map((element) => element.commande)
      .join(", ")}. Installez-les avant de lancer une opération.`;
    zone.append(bloc);
  }
}

function rendrePeripheriques(donnees) {
  const zone = $("#usb-peripheriques");
  zone.innerHTML = "";
  const groupes = [
    ["candidats", "Supports amovibles sûrs", "propose"],
    ["a_demonter", "Supports sûrs à libérer — partition montée", "a-demonter"],
    ["tests", "Images loopback de test", "propose"],
  ];
  for (const [cle, titre, classe] of groupes) {
    const elements = donnees[cle] || [];
    if (!elements.length) continue;
    const titreBloc = document.createElement("h3");
    titreBloc.textContent = titre;
    zone.append(titreBloc);
    for (const appareil of elements) {
      zone.append(construireCarteAppareil(appareil, classe));
    }
  }
  const autres = donnees.autres || [];
  if (autres.length) {
    const details = document.createElement("details");
    details.className = "details-techniques";
    const resume = document.createElement("summary");
    resume.textContent = `Périphériques écartés (${autres.length}) — cliquez pour vérifier pourquoi un support est refusé`;
    details.append(resume);
    for (const appareil of autres) {
      details.append(construireCarteAppareil(appareil, ""));
    }
    zone.append(details);
  }
  if (!zone.children.length) {
    const vide = document.createElement("p");
    vide.className = "aide";
    vide.textContent = "Aucun disque ou image loopback détecté.";
    zone.append(vide);
  }
  const hygiène = document.createElement("div");
  hygiène.className = "pile-messages";
  if (donnees.swap_disque_actif) {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent =
      "Un swap disque est actif. Les scripts le désactivent temporairement, mais fermez les applications sensibles pendant l'opération.";
    hygiène.append(bloc);
  }
  const montes = Object.entries(donnees.montages_actifs || {}).filter(([, actif]) => actif);
  if (montes.length) {
    const bloc = document.createElement("div");
    bloc.className = "message info";
    bloc.textContent = `Points de montage déjà actifs : ${montes
      .map(([chemin]) => chemin)
      .join(", ")}.`;
    hygiène.append(bloc);
  }
  const mappeurs = Object.entries(donnees.mappeurs_actifs || {}).filter(([, actif]) => actif);
  if (mappeurs.length) {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent = `Mappeurs LUKS déjà ouverts : ${mappeurs
      .map(([nom]) => `/dev/mapper/${nom}`)
      .join(", ")}. Fermez-les avant de réutiliser le coffre.`;
    hygiène.append(bloc);
  }
  if (donnees.header_age_existe) {
    const bloc = document.createElement("div");
    bloc.className = "message info";
    bloc.textContent =
      "Une sauvegarde d'en-tête ~/luks_header_qr.bak.age existe déjà. Toute initialisation sera refusée tant qu'elle n'aura pas été déplacée.";
    hygiène.append(bloc);
  }
  if (hygiène.children.length) zone.append(hygiène);
}

function construireCarteAppareil(appareil, classe) {
  const carte = document.createElement("article");
  carte.className = `peripherique ${classe}`;
  carte.dataset.chemin = appareil.chemin;
  if (appareil.a_demonter) carte.classList.add("a-demonter");
  if (etat.selection?.chemin === appareil.chemin) carte.classList.add("choisi");
  const entete = document.createElement("div");
  entete.className = "peripherique-entete";
  const texte = document.createElement("div");
  const nom = document.createElement("strong");
  nom.textContent = `${appareil.chemin} — ${appareil.modele || "Modèle inconnu"}`;
  const detail = document.createElement("small");
  detail.textContent = `${octets(appareil.taille)} · ${appareil.transport || "transport inconnu"}${
    appareil.serie ? ` · série ${appareil.serie}` : ""
  }`;
  texte.append(nom, detail);
  const badge = document.createElement("span");
  const sur = appareil.candidat || appareil.test;
  badge.className = `badge ${
    sur ? "badge-vert" : appareil.a_demonter ? "badge-ambre" : "badge-rouge"
  }`;
  badge.textContent = appareil.test
    ? "test loopback"
    : appareil.candidat
      ? "Prête / Sûre"
      : appareil.a_demonter
        ? "Partition montée (accès verrouillé)"
        : "écarté";
  entete.append(texte, badge);
  carte.append(entete);

  const details = document.createElement("div");
  details.className = "peripherique-details";
  const elements = [
    ["Type", appareil.type],
    ["Amovible", appareil.amovible ? "oui" : "non"],
    ["Monté", appareil.monte ? "oui" : "non"],
    ["Système", appareil.systeme ? "oui" : "non"],
    ["Swap", appareil.swap ? "oui" : "non"],
    ["Protégé", appareil.ro ? "oui" : "non"],
  ];
  for (const [libelle, valeur] of elements) {
    const span = document.createElement("span");
    span.textContent = `${libelle} : ${valeur}`;
    details.append(span);
  }
  carte.append(details);

  if (appareil.partitions?.length) {
    const partitions = document.createElement("div");
    partitions.className = "partitions";
    partitions.textContent = `Partitions : ${appareil.partitions
      .map(
        (partition) =>
          `${partition.chemin} (${partition.fstype || "non formatée"}${
            partition.mountpoints?.length ? `, monté sur ${partition.mountpoints.join(", ")}` : ""
          })`
      )
      .join(" · ")}`;
    carte.append(partitions);
  }

  if (appareil.raisons?.length) {
    const liste = document.createElement("ul");
    liste.className = "peripherique-raisons";
    for (const raison of appareil.raisons) {
      const element = document.createElement("li");
      element.textContent = raison;
      liste.append(element);
    }
    carte.append(liste);
  }

  const actions = document.createElement("div");
  actions.className = "peripherique-actions";
  if (sur) {
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "bouton bouton-principal bouton-petit";
    bouton.textContent = "Choisir ce support";
    bouton.addEventListener("click", () => choisirAppareil(appareil));
    actions.append(bouton);
  } else if (appareil.a_demonter) {
    for (const partition of appareil.partitions_montees || []) {
      const bouton = document.createElement("button");
      bouton.type = "button";
      bouton.className = "bouton bouton-secondaire bouton-petit";
      bouton.innerHTML = `${icone("cle")} Démonter la partition`;
      bouton.title = `Démonter ${partition.chemin} avec udisksctl, sans sudo`;
      bouton.setAttribute("aria-label", `Démonter la partition ${partition.chemin}`);
      bouton.addEventListener("click", () =>
        demonterPartition(partition.chemin, carte, bouton)
      );
      actions.append(bouton);
    }
    const note = document.createElement("span");
    note.className = "aide";
    note.textContent =
      "Le démontage est tenté sans privilèges. Aucun démontage forcé n'est exécuté.";
    actions.append(note);
  } else {
    const note = document.createElement("span");
    note.className = "badge badge-neutre";
    note.textContent = "non sélectionnable";
    actions.append(note);
  }
  carte.append(actions);
  return carte;
}

async function demonterPartition(partition, carte, bouton) {
  const contenu = bouton.innerHTML;
  bouton.disabled = true;
  bouton.textContent = "Démontage…";
  masquerMessage($("#usb-erreur"));
  try {
    const reponse = await api("/api/usb/demonter", {
      method: "POST",
      json: { partition },
    });
    if (reponse.ok) {
      toast(
        `${partition} a été démontée. La clé est revalidée automatiquement.`,
        "succes",
        6000
      );
      etat.donnees = null;
      await chargerPeripheriques(true);
      const libere = (etat.donnees?.candidats || []).find(
        (appareil) =>
          appareil.chemin === partition ||
          (appareil.partitions || []).some((element) => element.chemin === partition)
      );
      if (libere && !etat.selection) choisirAppareil(libere);
      return;
    }
    if (reponse.code === "partition_non_montee") {
      toast(reponse.message, "info", 6000);
      etat.donnees = null;
      await chargerPeripheriques(true);
      return;
    }
    afficherAideDemonter(carte, reponse);
    toast(reponse.message || "Le démontage a échoué.", "attention", 8000);
  } catch (erreur) {
    // Erreur HTTP (validation ou refus de sécurité) : ne jamais proposer de
    // commande pour une cible qui n'a pas été revalidée comme sûre.
    afficherMessage($("#usb-erreur"), erreur.message);
    toast(erreur.message, "attention", 8000);
  } finally {
    if (bouton.isConnected) {
      bouton.disabled = false;
      bouton.innerHTML = contenu;
    }
  }
}

function afficherAideDemonter(carte, reponse) {
  carte.querySelector(".aide-demonter")?.remove();
  const bloc = document.createElement("div");
  bloc.className = "message attention aide-demonter";
  const titre = document.createElement("strong");
  titre.textContent = "Démontage automatique impossible";
  const explication = document.createElement("p");
  explication.textContent =
    reponse.message ||
    "Utilisez la commande ci-dessous dans un terminal, puis rafraîchissez la détection.";
  bloc.append(titre, explication);

  const commandes = [];
  if (reponse.commande) {
    commandes.push({
      titre:
        reponse.code === "udisksctl_absent"
          ? "Commande manuelle (avec sudo, dans un terminal)"
          : "Commande à exécuter dans un terminal",
      texte: reponse.commande,
    });
  }
  if (reponse.commande_alternative) {
    commandes.push({
      titre: "Solution de secours (avec sudo, dans un terminal)",
      texte: reponse.commande_alternative,
    });
  }
  for (const commande of commandes) {
    const ligne = document.createElement("div");
    ligne.className = "aide-demonter-commande";
    const libelle = document.createElement("span");
    libelle.textContent = commande.titre;
    const code = document.createElement("code");
    code.textContent = commande.texte;
    const copierBouton = document.createElement("button");
    copierBouton.type = "button";
    copierBouton.className = "bouton bouton-secondaire bouton-petit";
    copierBouton.innerHTML = `${icone("copier")} Copier`;
    copierBouton.setAttribute("aria-label", `Copier la commande : ${commande.texte}`);
    copierBouton.addEventListener("click", () =>
      copier(
        commande.texte,
        "Commande copiée. Collez-la dans un terminal, puis rafraîchissez."
      )
    );
    ligne.append(libelle, code, copierBouton);
    bloc.append(ligne);
  }

  if (reponse.details?.length) {
    const details = document.createElement("details");
    details.className = "details-techniques";
    const resume = document.createElement("summary");
    resume.textContent = "Détails techniques du démontage";
    const pre = document.createElement("pre");
    pre.textContent = reponse.details.join("\n");
    details.append(resume, pre);
    bloc.append(details);
  }

  const actions = document.createElement("div");
  actions.className = "aide-demonter-actions";
  const rafraichir = document.createElement("button");
  rafraichir.type = "button";
  rafraichir.className = "bouton bouton-principal bouton-petit";
  rafraichir.innerHTML = `${icone("rafraichir")} Rafraîchir la détection`;
  const contenu = rafraichir.innerHTML;
  rafraichir.addEventListener("click", () => {
    const boutons = [...carte.querySelectorAll("button")];
    boutons.forEach((bouton) => {
      bouton.disabled = true;
    });
    rafraichir.textContent = "Lecture…";
    etat.donnees = null;
    chargerPeripheriques(true).finally(() => {
      if (!rafraichir.isConnected) return;
      rafraichir.innerHTML = contenu;
      boutons.forEach((bouton) => {
        bouton.disabled = false;
      });
    });
  });
  actions.append(rafraichir);
  bloc.append(actions);
  carte.append(bloc);
}

function choisirAppareil(appareil) {
  etat.selection = appareil;
  etat.commandes = null;
  $$(".peripherique").forEach((element) => {
    element.classList.toggle("choisi", element.dataset.chemin === appareil.chemin);
  });
  afficher($("#usb-etape-commandes"), false);
  rendreSelection();
  afficher($("#usb-etape-operation"), true);
  $$('input[name="usb-operation"]').forEach((entree) => {
    entree.checked = false;
  });
  $$(".options-usb").forEach((element) => {
    element.hidden = true;
  });
  afficher($("#usb-champs-communs"), false);
  afficher($("#usb-confirmation-bloc"), false);
  $("#usb-confirmation").value = "";
  const test = $("#usb-mode-test");
  test.checked = appareil.type === "loop";
  afficher($("#usb-mode-test-label"), appareil.type === "loop");
  masquerMessage($("#usb-erreur-operation"));
  document.getElementById("usb-etape-operation")?.scrollIntoView({ block: "start" });
}

function rendreSelection() {
  const zone = $("#usb-appareil-selectionne");
  zone.innerHTML = "";
  zone.className = "recap-usb";
  const appareil = etat.selection;
  if (!appareil) return;

  const pret = Boolean(appareil.candidat || appareil.test);
  if (!pret) zone.classList.add("attention");

  const ligneCible = document.createElement("div");
  ligneCible.className = "recap-usb-ligne";
  const libelleCible = document.createElement("span");
  libelleCible.className = "recap-usb-libelle";
  libelleCible.textContent = "Cible";
  const cible = document.createElement("strong");
  cible.textContent = appareil.chemin;
  const details = document.createElement("span");
  details.textContent = `${appareil.modele || "Modèle inconnu"} · ${octets(appareil.taille)}`;
  ligneCible.append(libelleCible, cible, details);

  const ligneEtat = document.createElement("div");
  ligneEtat.className = "recap-usb-ligne";
  const libelleEtat = document.createElement("span");
  libelleEtat.className = "recap-usb-libelle";
  libelleEtat.textContent = "État";
  const badge = document.createElement("span");
  badge.className = `badge ${pret ? "badge-vert" : "badge-ambre"}`;
  badge.setAttribute("role", "status");
  badge.innerHTML = `${icone(pret ? "check" : "alerte")} ${
    pret ? "Partitions démontées" : "Montage détecté"
  }`;
  const source = document.createElement("span");
  source.className = "aide";
  source.textContent = pret
    ? "Contrôlé par le serveur à la dernière détection ; revalidé à la génération."
    : "Démontez la partition et rafraîchissez avant de continuer.";
  ligneEtat.append(libelleEtat, badge, source);

  zone.append(ligneCible, ligneEtat);

  $("#usb-confirmation").placeholder = appareil.nom
    ? `Ex. ${appareil.nom} ou /dev/${appareil.nom}`
    : "Nom, chemin ou numéro de série";
  const commande = $("#usb-commande-verification");
  if (commande) {
    commande.textContent = `lsblk -o NAME,MODEL,SERIAL ${appareil.chemin}`;
  }
}

function operationChoisie() {
  return $('input[name="usb-operation"]:checked')?.value || null;
}

function majOptions() {
  const operation = operationChoisie();
  const options = {
    init: "#usb-options-init",
    sauvegarde: "#usb-options-sauvegarde",
    consulter: "#usb-options-consulter",
    restaurer: "#usb-options-restaurer",
  };
  $$(".options-usb").forEach((element) => {
    element.hidden = true;
  });
  if (operation) {
    afficher($(options[operation]), true);
    afficher($("#usb-champs-communs"), true);
    masquerMessage($("#usb-erreur-operation"));
    afficher($("#usb-etape-commandes"), false);
  } else {
    afficher($("#usb-champs-communs"), false);
  }
  const initialisation = operation === "init";
  afficher($("#usb-confirmation-bloc"), initialisation);
  if (!initialisation) $("#usb-confirmation").value = "";
  if (operation === "sauvegarde") {
    majChampCsv();
  }
  if (operation === "consulter") {
    majChampsAction();
  }
}

function majChampCsv() {
  const sansCsv = $("#usb-sans-csv").checked;
  afficher($("#usb-csv-champ"), !sansCsv);
}

function majChampsAction() {
  const action = $("#usb-action").value;
  afficher($("#usb-record-id-champ"), action === "id");
  afficher($("#usb-nom-champ"), action === "nom");
  afficher($("#usb-afficher-champ"), action === "id" || action === "nom");
}

function insererConfirmation() {
  if (!etat.selection) return;
  const valeur =
    etat.selection.nom || etat.selection.serie || etat.selection.chemin;
  const champ = $("#usb-confirmation");
  champ.value = valeur;
  champ.focus();
  toast("Confirmation pré-remplie. Vérifiez la cible avant de générer.", "info", 4000);
}

function construireRequete() {
  const operation = operationChoisie();
  if (!etat.selection) throw new Error("Choisissez d'abord un support.");
  if (!operation) throw new Error("Choisissez une opération.");
  const donnees = {
    operation,
    peripherique: etat.selection.chemin,
    mode_test: !$("#usb-mode-test-label").hidden && $("#usb-mode-test").checked,
  };
  if (operation === "init") {
    const confirmation = $("#usb-confirmation").value.trim();
    if (!confirmation) {
      throw new Error(
        "Saisissez le nom du disque, son chemin complet ou son numéro de série pour confirmer l'initialisation."
      );
    }
    donnees.confirmation = confirmation;
    if ($("#usb-argon2-mib").value) donnees.argon2_mib = $("#usb-argon2-mib").value;
    if ($("#usb-argon2-threads").value) {
      donnees.argon2_threads = $("#usb-argon2-threads").value;
    }
  }
  if (operation === "sauvegarde") {
    donnees.ram_size = $("#usb-ram-size").value.trim() || undefined;
    donnees.no_print = $("#usb-no-print").checked;
    donnees.garder_source = $("#usb-garder-source").checked;
    donnees.sans_csv = $("#usb-sans-csv").checked;
    if (!donnees.sans_csv) donnees.csv_path = $("#usb-csv-path").value.trim() || undefined;
  }
  if (operation === "consulter" || operation === "restaurer") {
    donnees.ram_size =
      (operation === "consulter" ? $("#usb-ram-size-consulter") : $("#usb-ram-size-restaurer")).value.trim() ||
      undefined;
    donnees.export_path =
      (operation === "consulter" ? $("#usb-export-path") : $("#usb-export-path-restaurer")).value.trim() ||
      undefined;
  }
  if (operation === "consulter") {
    donnees.action = $("#usb-action").value;
    if (donnees.action === "id") donnees.record_id = $("#usb-record-id").value.trim();
    if (donnees.action === "nom") donnees.nom = $("#usb-nom").value.trim();
    donnees.afficher = $("#usb-afficher").checked;
  }
  return donnees;
}

async function genererCommandes() {
  masquerMessage($("#usb-erreur-operation"));
  let charge;
  try {
    charge = construireRequete();
  } catch (erreur) {
    afficherMessage($("#usb-erreur-operation"), erreur.message);
    return;
  }
  const bouton = $("#usb-bouton-generer");
  bouton.disabled = true;
  try {
    const reponse = await api("/api/usb/commandes", { method: "POST", json: charge });
    etat.commandes = reponse;
    rendreCommandes(reponse);
    afficher($("#usb-etape-operation"), false);
    afficher($("#usb-etape-commandes"), true);
    document.getElementById("usb-etape-commandes")?.scrollIntoView({ block: "start" });
  } catch (erreur) {
    afficherMessage($("#usb-erreur-operation"), erreur.message);
    toast(erreur.message, "attention", 8000);
    if (/partition.*mont[ée]e/i.test(erreur.message)) {
      etat.donnees = null;
      await chargerPeripheriques(true);
    }
  } finally {
    bouton.disabled = false;
  }
}

function rendreCommandes(reponse) {
  const zone = $("#usb-commandes");
  zone.innerHTML = "";
  const appareil = reponse.appareil || {};
  const controle = reponse.controle || {};
  const rappel = document.createElement("div");
  rappel.className = "message info";
  const etatControle = controle.partitions_demontees
    ? "partitions démontées vérifiées par le serveur"
    : "état des partitions à vérifier";
  rappel.textContent = `Support ${appareil.chemin} (${appareil.modele || "modèle inconnu"}) : ${etatControle}. Le web n'exécute aucune commande : copiez-les une par une dans un terminal.`;
  zone.append(rappel);

  (reponse.commandes || []).forEach((commande, index) => {
    const bloc = document.createElement("div");
    bloc.className = "commande";
    const entete = document.createElement("div");
    entete.className = "commande-entete";
    const titre = document.createElement("strong");
    titre.textContent = commande.titre;
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "bouton";
    bouton.innerHTML = `${icone("copier")} Copier la commande`;
    bouton.addEventListener("click", () => {
      const prefixe = index === 2 ? "set +o history\n" : "";
      copier(
        `${prefixe}${commande.texte}`,
        index === 2
          ? "Commande copiée avec « set +o history » en première ligne."
          : "Commande copiée. Collez-la dans le terminal."
      );
    });
    entete.append(titre, bouton);
    const pre = document.createElement("pre");
    pre.className = "commande-texte";
    pre.textContent = commande.texte;
    const description = document.createElement("p");
    description.className = "commande-description";
    description.textContent = commande.description;
    bloc.append(entete, pre, description);
    zone.append(bloc);
  });

  const checkliste = $("#usb-checkliste");
  checkliste.innerHTML = "";
  const liste = document.createElement("ul");
  for (const element of reponse.checklist || []) {
    const item = document.createElement("li");
    item.textContent = element;
    liste.append(item);
  }
  checkliste.append(liste);

  const avertissements = $("#usb-avertissements");
  avertissements.innerHTML = "";
  for (const texte of reponse.avertissements || []) {
    const bloc = document.createElement("div");
    bloc.className = "message attention";
    bloc.textContent = texte;
    avertissements.append(bloc);
  }
}

function revenirOperation() {
  afficher($("#usb-etape-commandes"), false);
  if (etat.selection) afficher($("#usb-etape-operation"), true);
}

export function reinitialiserUsb() {
  etat.donnees = null;
  etat.selection = null;
  etat.commandes = null;
  $("#usb-peripheriques").innerHTML = "";
  $("#usb-dependances").innerHTML = "";
  $("#usb-appareil-selectionne").innerHTML = "";
  $("#usb-commandes").innerHTML = "";
  $("#usb-checkliste").innerHTML = "";
  $("#usb-avertissements").innerHTML = "";
  afficher($("#usb-etape-operation"), false);
  afficher($("#usb-etape-commandes"), false);
  masquerMessage($("#usb-erreur"));
  masquerMessage($("#usb-erreur-operation"));
}

export function initialiserUsb() {
  $("#usb-bouton-rafraichir")?.addEventListener("click", () => {
    etat.donnees = null;
    chargerPeripheriques(true);
  });
  $$('input[name="usb-operation"]').forEach((entree) => {
    entree.addEventListener("change", majOptions);
  });
  $("#usb-sans-csv")?.addEventListener("change", majChampCsv);
  $("#usb-action")?.addEventListener("change", majChampsAction);
  $("#usb-bouton-inserer")?.addEventListener("click", insererConfirmation);
  $("#usb-bouton-generer")?.addEventListener("click", genererCommandes);
  $("#usb-bouton-changer")?.addEventListener("click", revenirOperation);
  majOptions();
  majChampCsv();
  majChampsAction();
}

export { chargerPeripheriques as rafraichirPeripheriques };
