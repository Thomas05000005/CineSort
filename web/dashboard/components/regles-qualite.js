/**
 * Builder de règles qualité personnalisées — vague D3.
 *
 * LES REGLES MODIFIENT REELLEMENT SCORE ET TIER, et elles etaient INCREABLES
 * depuis l'application. `save_quality_profile` est l'unique chemin d'ecriture ;
 * l'interface passait par `settings/save_profile`, qui ne transmet ni regles ni
 * toggles. Meme classe de defaut que les verrous de champs de la vague B1 : une
 * capacite complete cote backend, sans aucune porte d'entree.
 *
 * TOUT LE VOCABULAIRE VIENT DU BACKEND. `get_custom_rules_catalog` rend les
 * champs, les operateurs et les actions ; ce module n'en ecrit AUCUN. C'est la
 * lecon de la vague D1, ou six poids ecrits dans le front decrivaient un modele
 * que le scoring ne lisait pas. Mesure du catalogue reel :
 *
 *     20 champs      video_codec, resolution_rank, has_dv, subtitle_langs,
 *                    warning_flags, tmdb_in_collection…
 *     11 operateurs  =, !=, <, <=, >, >=, between, in, not_in,
 *                    contains, not_contains
 *      7 actions     score_delta, score_multiplier, force_score, force_tier,
 *                    cap_max, cap_min, flag_warning
 *
 * LA VALIDATION EST CELLE DU BACKEND, pas une reimplementation. Il rend des
 * erreurs numerotees par regle (« Regle 1: au moins une condition requise »),
 * affichees telles quelles : il sait mieux que ce module ce qui cloche, et deux
 * validations qui divergent valent moins qu'une seule.
 */

import { apiPost } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { showModal, closeModal, dangerConfirmModal } from "./modal.js";
import { showToast } from "./toast.js";

/**
 * Operateurs dont la VALEUR n'est pas un scalaire.
 *
 * Ce n'est pas un doublon du catalogue : le catalogue dit QUELS operateurs
 * existent, ceci dit COMMENT saisir leur operande. Un `between` attend deux
 * bornes, un `in` une liste — les proposer dans le meme champ texte qu'un `=`
 * produirait des regles invalides que l'utilisateur ne saurait pas corriger.
 */
const OPERANDE = {
  between: { forme: "paire", aide: "deux bornes, ex. 2000 et 2010" },
  in: { forme: "liste", aide: "valeurs séparées par des virgules" },
  not_in: { forme: "liste", aide: "valeurs séparées par des virgules" },
};

const _etat = {
  catalogue: null,
  modeles: [],
  regles: [],
  erreurs: [],
  brouillon: null,
  chargement: false,
  erreurChargement: "",
};

function _brouillonVierge() {
  const champs = (_etat.catalogue && _etat.catalogue.fields) || [];
  const ops = (_etat.catalogue && _etat.catalogue.operators) || [];
  const actions = (_etat.catalogue && _etat.catalogue.actions) || [];
  return {
    name: "",
    enabled: true,
    priority: 10,
    match: "all",
    conditions: [{ field: champs[0] || "", op: ops[0] || "=", value: "" }],
    action: { type: actions[0] || "", value: "", reason: "" },
  };
}

function _formeDeLOperande(op) {
  return (OPERANDE[op] && OPERANDE[op].forme) || "scalaire";
}

/** Texte lisible d'une condition, dans les mots du catalogue. */
function _phraseCondition(c) {
  const v = Array.isArray(c.value) ? c.value.join(", ") : String(c.value ?? "");
  return `${c.field} ${c.op} ${v}`;
}

function _phraseAction(a) {
  if (!a || !a.type) return "—";
  const v = a.value === undefined || a.value === "" ? "" : ` ${a.value}`;
  const motif = a.reason ? ` « ${a.reason} »` : "";
  return `${a.type}${v}${motif}`;
}

function _rendreRegle(r, i) {
  const conditions = (Array.isArray(r.conditions) ? r.conditions : [])
    .map((c) => `<li>${escapeHtml(_phraseCondition(c))}</li>`)
    .join("");
  const liaison = r.match === "any" ? "au moins une" : "toutes";
  return `<li class="regle${r.enabled === false ? " regle--inactive" : ""}" data-regle-index="${i}">
    <div class="regle-entete">
      <label class="regle-actif">
        <input type="checkbox" data-regle-basculer="${i}" ${r.enabled === false ? "" : "checked"}
               aria-label="Activer la règle ${escapeHtml(String(r.name || i + 1))}">
        <span class="regle-nom">${escapeHtml(String(r.name || `Règle ${i + 1}`))}</span>
      </label>
      <span class="regle-priorite" title="Priorité : la plus basse s'applique d'abord">prio ${Number(r.priority) || 0}</span>
      <button type="button" class="v5-btn v5-btn--ghost regle-supprimer" data-regle-supprimer="${i}"
              aria-label="Supprimer la règle ${escapeHtml(String(r.name || i + 1))}">🗑</button>
    </div>
    <p class="regle-si">SI (${escapeHtml(liaison)}) :</p>
    <ul class="regle-conditions">${conditions}</ul>
    <p class="regle-alors">ALORS ${escapeHtml(_phraseAction(r.action))}</p>
  </li>`;
}

function _rendreFormulaire() {
  const b = _etat.brouillon;
  if (!b) return "";
  const cat = _etat.catalogue || {};
  const options = (liste, actif) =>
    (liste || []).map((v) => `<option value="${escapeHtml(v)}"${v === actif ? " selected" : ""}>${escapeHtml(v)}</option>`).join("");

  const conditions = b.conditions
    .map((c, i) => {
      const forme = _formeDeLOperande(c.op);
      const aide = (OPERANDE[c.op] && OPERANDE[c.op].aide) || "";
      return `<div class="regle-condition-saisie" data-condition-index="${i}">
        <select data-condition-champ="${i}" aria-label="Champ">${options(cat.fields, c.field)}</select>
        <select data-condition-op="${i}" aria-label="Opérateur">${options(cat.operators, c.op)}</select>
        <input type="text" data-condition-valeur="${i}" value="${escapeHtml(String(c.value ?? ""))}"
               placeholder="${escapeHtml(aide || "valeur")}" aria-label="Valeur"
               class="parametres-input" data-forme="${escapeHtml(forme)}">
        ${b.conditions.length > 1 ? `<button type="button" class="v5-btn v5-btn--ghost" data-condition-retirer="${i}" aria-label="Retirer cette condition">✕</button>` : ""}
      </div>`;
    })
    .join("");

  return `<form class="regle-formulaire" data-regle-formulaire>
    <div class="regle-ligne">
      <input type="text" data-regle-nom value="${escapeHtml(b.name)}" placeholder="Nom de la règle"
             aria-label="Nom de la règle" class="parametres-input">
      <input type="number" data-regle-prio value="${Number(b.priority) || 0}" min="0" max="999"
             aria-label="Priorité" class="parametres-input parametres-input--court">
      <label class="regle-actif">
        <input type="checkbox" data-regle-brouillon-actif ${b.enabled ? "checked" : ""}> active
      </label>
    </div>
    <div class="regle-conditions-saisie">${conditions}</div>
    <div class="regle-ligne">
      <button type="button" class="v5-btn v5-btn--ghost" data-condition-ajouter>+ condition</button>
      <span class="regle-liaison">
        <label><input type="radio" name="regle-match" value="all" ${b.match === "any" ? "" : "checked"}> toutes</label>
        <label><input type="radio" name="regle-match" value="any" ${b.match === "any" ? "checked" : ""}> au moins une</label>
      </span>
    </div>
    <div class="regle-ligne">
      <span class="regle-alors-libelle">ALORS</span>
      <select data-action-type aria-label="Action">${options(cat.actions, b.action.type)}</select>
      <input type="text" data-action-valeur value="${escapeHtml(String(b.action.value ?? ""))}"
             placeholder="valeur" aria-label="Valeur de l'action" class="parametres-input parametres-input--court">
      <input type="text" data-action-motif value="${escapeHtml(String(b.action.reason ?? ""))}"
             placeholder="Motif (affiché à l'utilisateur)" aria-label="Motif" class="parametres-input">
      <button type="button" class="v5-btn v5-btn--primary" data-regle-ajouter>Ajouter</button>
    </div>
  </form>`;
}

function _corps() {
  if (_etat.chargement) return `<div class="regles-vue"><p class="stats-resume">Chargement du catalogue…</p></div>`;
  if (_etat.erreurChargement) {
    return `<div class="regles-vue"><p class="stats-erreur" role="alert">${escapeHtml(_etat.erreurChargement)}</p></div>`;
  }
  const actives = _etat.regles.filter((r) => r.enabled !== false).length;
  const modeles = _etat.modeles
    .map(
      (m) => `<button type="button" class="stats-choix" data-regle-modele="${escapeHtml(String(m.id))}"
        title="${escapeHtml(String(m.description || ""))}">${escapeHtml(String(m.name || m.id))}</button>`
    )
    .join("");
  const liste = _etat.regles.length
    ? `<ol class="regles-liste">${_etat.regles.map(_rendreRegle).join("")}</ol>`
    : `<p class="stats-vide">Aucune règle. Partez d'un modèle, ou ajoutez la vôtre.</p>`;
  const erreurs = _etat.erreurs.length
    ? `<ul class="regles-erreurs" role="alert">${_etat.erreurs.map((e) => `<li>✗ ${escapeHtml(String(e))}</li>`).join("")}</ul>`
    : "";

  return `<div class="regles-vue">
    <p class="stats-resume">${_etat.regles.length} règle(s) · ${actives} active(s)</p>
    <div class="regles-modeles">
      <span class="regles-modeles-libelle">Partir d'un modèle :</span>
      <span class="stats-choix-barre">${modeles}</span>
      <span class="parametres-hint">Remplace les règles courantes.</span>
    </div>
    ${liste}
    <h4 class="parametres-subheading">Ajouter une règle</h4>
    ${_rendreFormulaire()}
    ${erreurs}
  </div>`;
}

/* ===========================================================
 * Actions
 * =========================================================== */

/**
 * Generation de la modale : une reponse en vol n'a le droit d'ecrire que si SA
 * modale est encore celle qui est ouverte.
 *
 * LES TROIS MODALES DE LA VAGUE D PARTAGENT UN CONTENEUR UNIQUE : `showModal`
 * commence par `closeModal()` (modal.js), donc ouvrir l'une detruit l'autre.
 * Sans ce jeton, une reponse arrivee apres la fermeture rappelle `_reouvrir()`,
 * qui ROUVRE une modale que l'utilisateur avait fermee — et detruit au passage
 * celle qu'il venait d'ouvrir, brouillon de saisie compris.
 *
 * C'est le meme defaut que la reponse perimee de la vue Statistiques, garde
 * la-bas par `_hote !== hote`. La protection avait ete ecrite pour la vague C
 * et jamais portee aux modales de la vague D, ou le point de montage est
 * pourtant PLUS etroit encore.
 */
let _generation = 0;

/** Marque cette ouverture comme la courante, et rend le test de peremption. */
function _prendreLaMain() {
  const mienne = ++_generation;
  return () => _generation !== mienne;
}

async function _charger() {
  const perimee = _prendreLaMain();
  _etat.chargement = true;
  _etat.erreurChargement = "";
  _reouvrir();
  try {
    // LE BUILDER LIT SES REGLES A LA MEME SOURCE QU'IL ECRIT. Une premiere
    // version les recevait en parametre depuis `parametres.js`, qui les prenait
    // dans `_state.profileDraft.custom_rules` — une cle que ce brouillon ne
    // porte JAMAIS : il est construit en cinq endroits avec exactement
    // {id, label, tiers, weights, tier_hierarchy}, et `grep custom_rules` sur
    // parametres.js ne rendait QUE le site de lecture.
    //
    // Consequence : l'ecran s'ouvrait TOUJOURS vide. Ajouter une regle puis
    // « Enregistrer » relisait le vrai profil et y ecrivait `custom_rules: [la
    // seule regle]` — DETRUISANT les regles preexistantes, avec un toast de
    // succes. Et le `dangerConfirmModal` d'application d'un modele etait
    // INATTEIGNABLE, sa condition de saut `if (!_etat.regles.length)` etant
    // toujours vraie a l'ouverture.
    const [cat, mod, prof] = await Promise.all([
      apiPost("quality/get_custom_rules_catalog", {}),
      apiPost("quality/get_custom_rules_templates", {}),
      apiPost("quality/get_quality_profile", {}),
    ]);
    const c = (cat && cat.data) || cat || {};
    const m = (mod && mod.data) || mod || {};
    const dp = (prof && prof.data) || prof || {};
    const profil = dp.profile_json || dp.profile;
    if (c.ok === false || !Array.isArray(c.fields) || !c.fields.length) {
      _etat.erreurChargement =
        c.user_message || c.message || "Le catalogue des règles n'a pas pu être lu ; rien ne peut être édité.";
    } else {
      _etat.catalogue = { fields: c.fields, operators: c.operators || [], actions: c.actions || [] };
      _etat.modeles = Array.isArray(m.templates) ? m.templates : [];
      const regles = profil && Array.isArray(profil.custom_rules) ? profil.custom_rules : [];
      _etat.regles = regles.map((r) => ({ ...r }));
      _etat.brouillon = _brouillonVierge();
    }
  } catch {
    _etat.erreurChargement = "Le serveur n'a pas répondu.";
  } finally {
    _etat.chargement = false;
    if (!perimee()) _reouvrir();
  }
}

/** Valide au BACKEND et garde ses erreurs telles quelles. */
async function _valider(regles) {
  try {
    const res = await apiPost("quality/validate_custom_rules", { rules: regles });
    const data = (res && res.data) || res || {};
    return {
      ok: data.ok !== false,
      erreurs: Array.isArray(data.errors) ? data.errors : [],
      normalisees: Array.isArray(data.normalized) ? data.normalized : [],
    };
  } catch {
    return { ok: false, erreurs: ["Le serveur n'a pas répondu."], normalisees: [] };
  }
}

function _valeurSaisie(brute, forme) {
  const t = String(brute ?? "").trim();
  if (forme === "liste" || forme === "paire") {
    return t
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
  }
  return t;
}

async function _ajouterLaRegle() {
  const b = _etat.brouillon;
  if (!b) return;
  const candidate = {
    name: b.name.trim() || `Règle ${_etat.regles.length + 1}`,
    enabled: !!b.enabled,
    priority: Number(b.priority) || 0,
    match: b.match === "any" ? "any" : "all",
    conditions: b.conditions.map((c) => ({
      field: c.field,
      op: c.op,
      value: _valeurSaisie(c.value, _formeDeLOperande(c.op)),
    })),
    action: {
      type: b.action.type,
      value: b.action.value === "" ? undefined : Number.isNaN(Number(b.action.value)) ? b.action.value : Number(b.action.value),
      reason: b.action.reason || "",
    },
  };
  // ON VALIDE AVANT D'AJOUTER : une regle invalide dans la liste ne se voit
  // qu'a l'enregistrement, quand l'utilisateur a deja oublie ce qu'il a saisi.
  const v = await _valider([..._etat.regles, candidate]);
  _etat.erreurs = v.erreurs;
  if (!v.ok) {
    _reouvrir();
    return;
  }
  _etat.regles = v.normalisees.length ? v.normalisees : [..._etat.regles, candidate];
  _etat.brouillon = _brouillonVierge();
  _reouvrir();
}

function _appliquerLeModele(id) {
  const modele = _etat.modeles.find((m) => String(m.id) === String(id));
  if (!modele) return;
  const regles = Array.isArray(modele.rules) ? modele.rules : [];
  // REMPLACER N'EST PAS AJOUTER : les regles courantes disparaissent. C'est une
  // perte de travail, donc une confirmation — meme si rien n'est ecrit sur
  // disque avant « Enregistrer ».
  if (!_etat.regles.length) {
    _etat.regles = regles;
    _etat.erreurs = [];
    _reouvrir();
    return;
  }
  dangerConfirmModal({
    title: `Appliquer le modèle « ${modele.name || id} » ?`,
    items: _etat.regles.map((r) => String(r.name || "")),
    consequence: `Vos ${_etat.regles.length} règle(s) actuelles seront REMPLACÉES par les ${regles.length} du modèle. Rien n'est écrit sur disque tant que vous n'enregistrez pas.`,
    confirmLabel: "Remplacer",
    onConfirm: () => {
      _etat.regles = regles;
      _etat.erreurs = [];
      _reouvrir();
    },
  });
}

async function _enregistrer() {
  const v = await _valider(_etat.regles);
  _etat.erreurs = v.erreurs;
  if (!v.ok) {
    _reouvrir();
    showToast({ type: "error", text: "Des règles sont invalides ; rien n'a été enregistré." });
    return;
  }
  try {
    const actuel = await apiPost("quality/get_quality_profile", {});
    const dactuel = (actuel && actuel.data) || actuel || {};
    const profil = dactuel.profile_json || dactuel.profile;
    if (!profil || typeof profil !== "object") {
      showToast({ type: "error", text: "Votre profil n'a pas pu être lu ; rien n'a été enregistré." });
      return;
    }
    const res = await apiPost("quality/save_quality_profile", {
      profile_json: { ...profil, custom_rules: v.normalisees },
    });
    const data = (res && res.data) || res || {};
    if (data.ok === false) {
      showToast({ type: "error", text: data.user_message || data.message || "L'enregistrement a échoué." });
      return;
    }
    showToast({ type: "success", text: `${v.normalisees.length} règle(s) enregistrée(s).` });
  } catch {
    showToast({ type: "error", text: "Le serveur n'a pas répondu." });
  }
}

/* ===========================================================
 * Liaison
 * =========================================================== */

function _brancher() {
  const hote = document.querySelector(".regles-vue");
  if (!hote) return;

  hote.addEventListener("click", (ev) => {
    const c = ev.target && ev.target.closest && ev.target.closest("[data-regle-modele],[data-regle-supprimer],[data-condition-ajouter],[data-condition-retirer],[data-regle-ajouter]");
    if (!c) return;
    if (c.dataset.regleModele) return _appliquerLeModele(c.dataset.regleModele);
    if (c.dataset.regleSupprimer !== undefined) {
      _etat.regles.splice(Number(c.dataset.regleSupprimer), 1);
      _etat.erreurs = [];
      return _reouvrir();
    }
    if (c.dataset.conditionAjouter !== undefined && _etat.brouillon) {
      const cat = _etat.catalogue || {};
      _etat.brouillon.conditions.push({ field: (cat.fields || [])[0] || "", op: (cat.operators || [])[0] || "=", value: "" });
      return _reouvrir();
    }
    if (c.dataset.conditionRetirer !== undefined && _etat.brouillon) {
      _etat.brouillon.conditions.splice(Number(c.dataset.conditionRetirer), 1);
      return _reouvrir();
    }
    if (c.dataset.regleAjouter !== undefined) return _ajouterLaRegle();
    return undefined;
  });

  hote.addEventListener("change", (ev) => {
    const t = ev.target;
    if (!t || !t.dataset) return;
    const b = _etat.brouillon;
    if (t.dataset.regleBasculer !== undefined) {
      const r = _etat.regles[Number(t.dataset.regleBasculer)];
      if (r) r.enabled = !!t.checked;
      return _reouvrir();
    }
    if (!b) return;
    if (t.dataset.regleNom !== undefined) b.name = t.value;
    else if (t.dataset.reglePrio !== undefined) b.priority = Number(t.value) || 0;
    else if (t.dataset.regleBrouillonActif !== undefined) b.enabled = !!t.checked;
    else if (t.dataset.conditionChamp !== undefined) b.conditions[Number(t.dataset.conditionChamp)].field = t.value;
    else if (t.dataset.conditionOp !== undefined) {
      b.conditions[Number(t.dataset.conditionOp)].op = t.value;
      return _reouvrir(); // la forme de l'operande change avec l'operateur
    } else if (t.dataset.conditionValeur !== undefined) b.conditions[Number(t.dataset.conditionValeur)].value = t.value;
    else if (t.dataset.actionType !== undefined) b.action.type = t.value;
    else if (t.dataset.actionValeur !== undefined) b.action.value = t.value;
    else if (t.dataset.actionMotif !== undefined) b.action.reason = t.value;
    else if (t.name === "regle-match") b.match = t.value;
    return undefined;
  });
}

function _reouvrir() {
  showModal({
    title: "Règles personnalisées",
    body: _corps(),
    actions: [
      { label: "Fermer", cls: "", onClick: () => closeModal() },
      { label: "Enregistrer", cls: "btn-primary", onClick: () => _enregistrer() },
    ],
  });
  _brancher();
}

/**
 * Point d'entree : ouvre le builder.
 *
 * IL NE PREND AUCUN PARAMETRE, ET C'EST DELIBERE. Recevoir les regles de
 * l'appelant l'obligeait a les connaitre — or `parametres.js` ne les avait pas,
 * et passait silencieusement une liste vide. Le builder les lit lui-meme, a la
 * MEME source qu'il ecrit (`quality/get_quality_profile`) : lecture et ecriture
 * ne peuvent plus diverger.
 */
export function ouvrirReglesQualite() {
  _etat.regles = [];
  _etat.erreurs = [];
  _etat.catalogue = null;
  _etat.brouillon = null;
  _charger();
}

export const __test = {
  _etat,
  _corps,
  _rendreRegle,
  _charger,
  _valider,
  _ajouterLaRegle,
  _appliquerLeModele,
  _enregistrer,
  _valeurSaisie,
  _formeDeLOperande,
  _brouillonVierge,
};
