/**
 * Simulateur de profil qualité — vague D2.
 *
 * L'INTERFACE ORDONNAIT DEJA DE S'EN SERVIR SANS L'OFFRIR. `parametres.js`
 * avertit, a propos de la hierarchie qualite : « Activer ce mode peut
 * redistribuer 30-40 % de votre bibliotheque actuelle — utilisez la simulation
 * avant d'activer. » `quality/simulate_quality_preset` existait, testee, et
 * aucun code du dashboard ne l'appelait.
 *
 * CE QUE LE BACKEND REND VRAIMENT (mesure sur
 * `quality_simulator_support.py`, pas suppose) :
 *
 *     before / after : { avg_score, tiers, profile_name }
 *     delta          : { avg_score_delta, net_tier_improvement,
 *                        net_tier_degradation, unchanged_count, ... }
 *     top_winners / top_losers : lignes { title, year, score_before,
 *                                score_after, delta, tier_before, tier_after }
 *     films_count, elapsed_ms, warnings, scope, preset_label
 *
 * DEUX PIEGES DE FORME, RELEVES AVANT D'ECRIRE LA VUE :
 *
 *   1. LES TIERS SONT CAPITALISES ICI (`Platinum`), la ou les classes CSS et le
 *      reste de l'application sont en minuscules. C'est exactement la forme du
 *      defaut `group_name` de la vague C — une cle qui ne correspond a rien
 *      n'echoue pas, elle affiche du vide. On normalise A L'ENTREE.
 *   2. `warnings` doit etre affiche. Sans lui, deux colonnes presque identiques
 *      laissent l'utilisateur conclure seul que « le preset ne change rien »,
 *      alors que le backend a une raison precise a lui donner.
 *
 * RIEN N'EST ECRIT PAR CET ECRAN tant qu'on ne clique pas « Enregistrer comme
 * profil » : la simulation est une LECTURE. C'est ce qui permet de l'ouvrir
 * sans confirmation.
 */

import { apiPost } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { showModal, closeModal } from "./modal.js";
import { showToast } from "./toast.js";

/** Presets REELS de `list_quality_presets()` — verifies, pas supposes. */
const PRESETS = [
  { id: "remux_strict", label: "Remux strict" },
  { id: "equilibre", label: "CinemaLux (équilibré)" },
  { id: "light", label: "Light" },
  { id: "streaming_optimal", label: "Streaming optimal" },
  { id: "compact", label: "Compact" },
];

const PORTEES = [
  { id: "run", label: "Ce run" },
  { id: "library", label: "Toute la bibliothèque" },
];

/** Ordre d'affichage, du meilleur au pire. */
const TIERS = ["platinum", "gold", "silver", "bronze", "reject"];

const TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
};

const _etat = {
  preset: "equilibre",
  portee: "run",
  resultat: null,
  chargement: false,
  erreur: "",
};

/**
 * Compte des tiers, ramene aux cles MINUSCULES de l'application.
 *
 * `_count_tiers` (backend) rend « Platinum », « Gold »… avec une majuscule.
 * Lire `tiers.platinum` sur cette reponse rendrait `undefined` pour chaque
 * niveau, et l'ecran afficherait cinq zeros sans jamais echouer.
 */
function _normaliserTiers(brut) {
  const out = {};
  for (const t of TIERS) out[t] = 0;
  if (!brut || typeof brut !== "object") return out;
  for (const [cle, valeur] of Object.entries(brut)) {
    const k = String(cle).toLowerCase();
    if (Object.prototype.hasOwnProperty.call(out, k)) out[k] = Number(valeur) || 0;
  }
  return out;
}

/** `+7,3` / `−5` / `0` — le signe est porteur, il ne se devine pas. */
function _signe(n) {
  const v = Number(n) || 0;
  if (v > 0) return `+${_nombre(v)}`;
  if (v < 0) return `−${_nombre(Math.abs(v))}`;
  return "0";
}

function _nombre(n) {
  const v = Number(n) || 0;
  return Number.isInteger(v) ? String(v) : v.toFixed(1).replace(".", ",");
}

function _classeDelta(n) {
  const v = Number(n) || 0;
  if (v > 0) return "simu-delta--haut";
  if (v < 0) return "simu-delta--bas";
  return "simu-delta--nul";
}

function _choix(liste, actif, attribut) {
  return liste
    .map(
      (o) => `<button type="button" class="stats-choix${o.id === actif ? " is-active" : ""}"
        ${attribut}="${escapeHtml(o.id)}">${escapeHtml(o.label)}</button>`
    )
    .join("");
}

function _lignesDeTier(avant, apres) {
  const max = Math.max(1, ...TIERS.map((t) => Math.max(avant[t], apres[t])));
  return TIERS.map((t) => {
    const a = avant[t];
    const b = apres[t];
    const d = b - a;
    return `<tr>
      <td class="simu-tier"><span class="stats-part stats-part--${t}"></span>${escapeHtml(TIER_LABELS[t])}</td>
      <td class="stats-num">${a}</td>
      <td><span class="simu-barre" style="--part: ${a / max}"></span></td>
      <td class="stats-num">${b}</td>
      <td><span class="simu-barre simu-barre--apres" style="--part: ${b / max}"></span></td>
      <td class="stats-num ${_classeDelta(d)}">${_signe(d)}</td>
    </tr>`;
  }).join("");
}

function _colonneDeFilms(titre, lignes, classe) {
  const items = (Array.isArray(lignes) ? lignes : []).slice(0, 10);
  if (!items.length) return `<div class="simu-colonne"><h4>${escapeHtml(titre)}</h4><p class="stats-vide">Aucun.</p></div>`;
  const html = items
    .map(
      (f) => `<li>
        <span class="stats-nom" title="${escapeHtml(String(f.title || ""))}">${escapeHtml(String(f.title || "Sans titre"))}${
          f.year ? ` (${escapeHtml(String(f.year))})` : ""
        }</span>
        <span class="simu-scores">${_nombre(f.score_before)} → ${_nombre(f.score_after)}</span>
        <span class="stats-num ${classe}">${_signe(f.delta)}</span>
      </li>`
    )
    .join("");
  return `<div class="simu-colonne"><h4>${escapeHtml(titre)} (${items.length})</h4><ul class="simu-liste">${html}</ul></div>`;
}

function _rendreResultat(r) {
  const avant = _normaliserTiers(r.before && r.before.tiers);
  const apres = _normaliserTiers(r.after && r.after.tiers);
  const d = r.delta || {};
  const avertissements = (Array.isArray(r.warnings) ? r.warnings : [])
    .map((w) => `<p class="stats-note">⚠ ${escapeHtml(String(w))}</p>`)
    .join("");
  return `<div class="simu-resultat">
    <p class="stats-resume">
      ${(Number(r.films_count) || 0).toLocaleString("fr-FR")} film(s) · calculé en ${_nombre(
        (Number(r.elapsed_ms) || 0) / 1000
      )} s
    </p>
    <table class="stats-table simu-table">
      <thead><tr>
        <th>Niveau</th>
        <th class="stats-num" colspan="2">Avant — ${escapeHtml(String((r.before && r.before.profile_name) || "Actuel"))}</th>
        <th class="stats-num" colspan="2">Après — ${escapeHtml(String((r.after && r.after.profile_name) || r.preset_label || ""))}</th>
        <th class="stats-num">Δ</th>
      </tr></thead>
      <tbody>
        <tr class="simu-ligne-score">
          <td>Score moyen</td>
          <td class="stats-num" colspan="2">${_nombre(r.before && r.before.avg_score)}</td>
          <td class="stats-num" colspan="2">${_nombre(r.after && r.after.avg_score)}</td>
          <td class="stats-num ${_classeDelta(d.avg_score_delta)}">${_signe(d.avg_score_delta)}</td>
        </tr>
        ${_lignesDeTier(avant, apres)}
      </tbody>
    </table>
    <p class="stats-resume">
      ↑ ${Number(d.net_tier_improvement) || 0} film(s) montent de niveau ·
      ↓ ${Number(d.net_tier_degradation) || 0} descendent ·
      ${(Number(d.unchanged_count) || 0).toLocaleString("fr-FR")} inchangé(s)
    </p>
    <div class="simu-colonnes">
      ${_colonneDeFilms("▲ Montent le plus", r.top_winners, "simu-delta--haut")}
      ${_colonneDeFilms("▼ Descendent le plus", r.top_losers, "simu-delta--bas")}
    </div>
    ${avertissements}
  </div>`;
}

function _corps() {
  let centre = "";
  if (_etat.chargement) centre = `<p class="stats-resume">Simulation en cours…</p>`;
  else if (_etat.erreur) centre = `<p class="stats-erreur" role="alert">${escapeHtml(_etat.erreur)}</p>`;
  else if (_etat.resultat) centre = _rendreResultat(_etat.resultat);
  else centre = `<p class="stats-vide">Choisissez un preset, puis lancez la simulation. Rien n'est modifié.</p>`;

  return `<div class="simu-vue">
    <div class="stats-choix-barre" role="group" aria-label="Preset à simuler">
      ${_choix(PRESETS, _etat.preset, "data-simu-preset")}
    </div>
    <div class="stats-choix-barre" role="group" aria-label="Portée de la simulation">
      ${_choix(PORTEES, _etat.portee, "data-simu-portee")}
      <button type="button" class="v5-btn v5-btn--primary" data-simu-lancer
              ${_etat.chargement ? "disabled" : ""}>Simuler</button>
    </div>
    ${centre}
  </div>`;
}

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

async function _simuler() {
  const perimee = _prendreLaMain();
  _etat.chargement = true;
  _etat.erreur = "";
  _reouvrir();
  try {
    const res = await apiPost("quality/simulate_quality_preset", {
      preset_id: _etat.preset,
      scope: _etat.portee,
      run_id: "latest",
    });
    // Une reponse perimee n'ecrit RIEN : sans cette garde, l'ecran montre la
    // simulation du preset COURANT pendant que `_etat.resultat` porte celle du
    // precedent — et « Enregistrer ce preset » fige les mauvais chiffres.
    if (perimee()) return;
    const data = (res && res.data) || res || {};
    if (data.ok === false) {
      _etat.resultat = null;
      _etat.erreur = data.user_message || data.message || "La simulation a échoué.";
    } else {
      _etat.resultat = data;
    }
  } catch {
    _etat.resultat = null;
    _etat.erreur = "Le serveur n'a pas répondu.";
  } finally {
    // Une generation perimee ne touche plus a rien : c'est la generation
    // COURANTE qui detient `chargement` et l'ecran.
    if (!perimee()) {
      _etat.chargement = false;
      _reouvrir();
    }
  }
}

/** Profil REEL d'un preset, lu la ou il vit : `get_quality_presets`. */
async function _profilDuPreset(presetId) {
  try {
    const res = await apiPost("quality/get_quality_presets", {});
    const data = (res && res.data) || res || {};
    const liste = Array.isArray(data.presets) ? data.presets : [];
    const trouve = liste.find(
      (p) => String(p.preset_id) === String(presetId) || String(p.profile_id) === String(presetId)
    );
    const profil = trouve && trouve.profile_json;
    return profil && typeof profil === "object" ? profil : null;
  } catch {
    return null;
  }
}

/**
 * Enregistre le preset simule comme profil personnalise.
 *
 * IL N'Y A RIEN A ENREGISTRER TANT QU'ON N'A PAS SIMULE : proposer le bouton
 * avant donnerait un profil dont personne n'a vu l'effet, ce qui est exactement
 * ce que l'avertissement de l'interface demande d'eviter.
 */
async function _enregistrer() {
  if (!_etat.resultat) {
    showToast({ type: "info", text: "Lancez d'abord une simulation." });
    return;
  }
  const nom = String(_etat.resultat.preset_label || _etat.preset || "").trim();
  if (!nom) {
    showToast({ type: "error", text: "Ce preset n'a pas de nom ; rien n'a été enregistré." });
    return;
  }
  try {
    // LE PROFIL N'EST PAS DANS LA REPONSE DE SIMULATION. Sa charge utile porte
    // `before`/`after`/`delta`/`top_winners`… mais AUCUNE cle `profile` (mesure
    // sur `quality_simulator_support.py`). Une premiere version envoyait
    // `_etat.resultat.profile || {}` : elle enregistrait donc un profil VIDE
    // sous le nom du preset, sans jamais echouer. On le RESOUT ici, a la source
    // qui le porte.
    const profil = await _profilDuPreset(_etat.resultat.preset_id || _etat.preset);
    if (!profil) {
      showToast({ type: "error", text: "Le profil de ce preset n'a pas pu être lu ; rien n'a été enregistré." });
      return;
    }
    const res = await apiPost("quality/save_custom_quality_preset", {
      name: nom,
      profile_json: profil,
    });
    const data = (res && res.data) || res || {};
    if (data.ok === false) {
      showToast({ type: "error", text: data.user_message || data.message || "L'enregistrement a échoué." });
      return;
    }
    showToast({ type: "success", text: `Profil « ${nom} » enregistré.` });
  } catch {
    showToast({ type: "error", text: "Le serveur n'a pas répondu." });
  }
}

function _brancher() {
  const hote = document.querySelector(".simu-vue");
  if (!hote) return;
  hote.addEventListener("click", (ev) => {
    const cible = ev.target && ev.target.closest && ev.target.closest("[data-simu-preset],[data-simu-portee],[data-simu-lancer]");
    if (!cible) return;
    if (cible.dataset.simuPreset) {
      const demande = cible.dataset.simuPreset;
      if (!PRESETS.some((p) => p.id === demande)) return;
      _etat.preset = demande;
      // LE RESULTAT AFFICHE DEVIENT FAUX DES QU'ON CHANGE DE PRESET. Le garder
      // laisserait des chiffres d'un preset sous le nom d'un autre — et
      // « Enregistrer » porterait alors sur celui qu'on ne regarde plus.
      _etat.resultat = null;
      _etat.erreur = "";
      _reouvrir();
      return;
    }
    if (cible.dataset.simuPortee) {
      const demande = cible.dataset.simuPortee;
      if (!PORTEES.some((p) => p.id === demande)) return;
      _etat.portee = demande;
      _etat.resultat = null;
      _etat.erreur = "";
      _reouvrir();
      return;
    }
    _simuler();
  });
}

function _reouvrir() {
  showModal({
    title: "Simuler un profil",
    body: _corps(),
    actions: [
      { label: "Fermer", cls: "", onClick: () => closeModal() },
      { label: "Enregistrer comme profil…", cls: "btn-primary", onClick: () => _enregistrer() },
    ],
  });
  _brancher();
}

/** Point d'entree : ouvre le simulateur. La simulation elle-meme est un choix. */
export function ouvrirSimulateurQualite() {
  _etat.resultat = null;
  _etat.erreur = "";
  _etat.chargement = false;
  _reouvrir();
}

export const __test = {
  _etat,
  _normaliserTiers,
  _signe,
  _nombre,
  _rendreResultat,
  _corps,
  _simuler,
  _enregistrer,
  PRESETS,
  PORTEES,
};
