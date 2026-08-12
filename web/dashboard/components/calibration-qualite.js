/**
 * Réglages fins du profil : options, calibration et partage — vague D4.
 *
 * L'INTERFACE PROMETTAIT LE RAPPORT SANS L'AFFICHER NULLE PART.
 * `film-detail.js` dit a l'utilisateur : « votre feedback alimente le rapport de
 * calibration ». `quality/get_calibration_report` existait, testee, et aucun
 * ecran ne la montrait. Le feedback partait donc dans un rapport que personne
 * ne pouvait lire.
 *
 * CE QUE LE BACKEND REND VRAIMENT (mesure, pas suppose) :
 *
 *     bias : { total_feedbacks, accord_pct, mean_delta, bias_direction,
 *              bias_strength, category_bias: { video, audio, extras } }
 *     current_weights : { video, audio, extras }
 *     suggestion      : { ... } ou **null**
 *     sample_feedbacks: [...]
 *
 * `suggestion` VAUT `null` TANT QU'IL N'Y A PAS ASSEZ DE RETOURS. Un ecran qui
 * n'affiche alors rien a l'air casse. Il DIT donc pourquoi, et ou en est le
 * compte — c'est la seule facon de transformer une absence en information.
 *
 * LES TOGGLES VIENNENT DU PROFIL, pas d'une liste ecrite ici : meme regle que
 * pour les regles custom (vague D3) et les poids (vague D1), et pour la meme
 * raison — une liste figee dans le front finit par decrire autre chose que ce
 * que le backend applique.
 *
 * UN IMPORT REMPLACE LE PROFIL DE L'UTILISATEUR. Il montre donc son DIFF avant
 * d'ecrire : ce qui change, et de combien. Sans cela, « Importer » est un pari.
 */

import { apiPost } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { showModal, closeModal, dangerConfirmModal } from "./modal.js";
import { showToast } from "./toast.js";

/** En deca, le backend ne suggere rien — on l'explique plutot que de rester vide. */
const RETOURS_REQUIS = 20;

const LIBELLES_TOGGLES = {
  include_metadata: "Métadonnées (NFO, TMDb)",
  include_naming: "Nommage du dossier",
  enable_4k_light: "4K allégé (pénalise un 4K au bitrate faible)",
  include_subtitles: "Sous-titres",
};

const LIBELLES_BIAIS = {
  up: "Vous notez PLUS HAUT que le profil",
  down: "Vous notez PLUS BAS que le profil",
  neutral: "Vos notes suivent le profil",
};

const LIBELLES_FORCE = { none: "", weak: "biais léger", moderate: "biais net", strong: "biais fort" };

const _etat = {
  profil: null,
  rapport: null,
  diffImport: null,
  chargement: false,
  erreur: "",
};

function _nombre(n, decimales = 1) {
  const v = Number(n) || 0;
  return Number.isInteger(v) ? String(v) : v.toFixed(decimales).replace(".", ",");
}

function _signe(n) {
  const v = Number(n) || 0;
  if (v > 0) return `+${_nombre(v)}`;
  if (v < 0) return `−${_nombre(Math.abs(v))}`;
  return "0";
}

/* ===========================================================
 * Options
 * =========================================================== */

function _rendreToggles() {
  const t = (_etat.profil && _etat.profil.toggles) || null;
  if (!t || typeof t !== "object") {
    return `<p class="stats-vide">Les options n'ont pas pu être lues.</p>`;
  }
  // LES CLES VIENNENT DU PROFIL. Une liste ecrite ici finirait par proposer une
  // option que le scoring n'applique plus, ou par en cacher une nouvelle.
  const lignes = Object.keys(t)
    .map(
      (cle) => `<label class="calib-toggle">
        <input type="checkbox" data-calib-toggle="${escapeHtml(cle)}" ${t[cle] ? "checked" : ""}>
        <span>${escapeHtml(LIBELLES_TOGGLES[cle] || cle)}</span>
      </label>`
    )
    .join("");
  return `<div class="calib-toggles">${lignes}</div>`;
}

/* ===========================================================
 * Calibration
 * =========================================================== */

function _rendreCalibration() {
  const r = _etat.rapport;
  if (!r) return `<p class="stats-vide">Rapport de calibration indisponible.</p>`;
  const b = r.bias || {};
  const total = Number(b.total_feedbacks) || 0;

  if (total < RETOURS_REQUIS) {
    // UNE ABSENCE EXPLIQUEE VAUT MIEUX QU'UN ECRAN VIDE. Sans ce message,
    // l'utilisateur croit l'ecran casse alors qu'il manque seulement des
    // donnees — et il ignore ce qu'il pourrait faire pour en avoir.
    return `<div class="calib-bloc">
      <p class="stats-resume">${total} retour(s) enregistré(s).</p>
      <p class="stats-note">
        Pas encore assez de corrections pour suggérer un réglage.
        Continuez à corriger des scores depuis la fiche d'un film : ${total} / ${RETOURS_REQUIS}.
      </p>
    </div>`;
  }

  const cat = b.category_bias || {};
  const parCategorie = Object.keys(cat)
    .map((k) => `<span class="calib-cat">${escapeHtml(k)} <strong>${_signe(cat[k])}</strong></span>`)
    .join("");
  const s = r.suggestion;
  const actuels = r.current_weights || {};
  const suggestion = s
    ? `<div class="calib-suggestion">
        <p class="calib-suggestion-titre">Suggestion</p>
        ${Object.keys(s.weights || s)
          .map((k) => {
            const avant = Number(actuels[k]);
            const apres = Number((s.weights || s)[k]);
            if (!Number.isFinite(avant) || !Number.isFinite(apres) || avant === apres) return "";
            return `<p class="calib-ligne">${escapeHtml(k)} <span class="calib-avant">${_nombre(avant)}</span> → <strong>${_nombre(apres)}</strong></p>`;
          })
          .join("")}
        <div class="calib-actions">
          <button type="button" class="v5-btn v5-btn--ghost" data-calib-ignorer>Ignorer</button>
          <button type="button" class="v5-btn v5-btn--primary" data-calib-appliquer>Appliquer</button>
        </div>
      </div>`
    : `<p class="stats-note">Vos corrections suivent le profil : aucun réglage à suggérer.</p>`;

  const force = LIBELLES_FORCE[String(b.bias_strength || "none")] || "";
  return `<div class="calib-bloc">
    <p class="stats-resume">
      ${total} retour(s) · accord ${_nombre(b.accord_pct, 0)} % · écart moyen ${_signe(b.mean_delta)}
    </p>
    <p class="calib-direction">
      ${escapeHtml(LIBELLES_BIAIS[String(b.bias_direction || "neutral")] || "")}${force ? ` (${escapeHtml(force)})` : ""}
    </p>
    <p class="calib-categories">${parCategorie}</p>
    ${suggestion}
  </div>`;
}

/* ===========================================================
 * Partage
 * =========================================================== */

/** Ce qu'un import CHANGERAIT, compare au profil actif. */
function _calculerLeDiff(entrant, actuel) {
  const lignes = [];
  const cmp = (groupe, libelle) => {
    const a = (actuel && actuel[groupe]) || {};
    const b = (entrant && entrant[groupe]) || {};
    for (const cle of new Set([...Object.keys(a), ...Object.keys(b)])) {
      if (String(a[cle]) === String(b[cle])) continue;
      lignes.push({ groupe: libelle, cle, avant: a[cle], apres: b[cle] });
    }
  };
  cmp("weights", "Poids");
  cmp("tiers", "Seuils");
  cmp("toggles", "Options");
  const regA = (actuel && actuel.custom_rules) || [];
  const regB = (entrant && entrant.custom_rules) || [];
  if (regA.length !== regB.length) {
    lignes.push({ groupe: "Règles", cle: "nombre", avant: regA.length, apres: regB.length });
  }
  return lignes;
}

function _rendreDiff() {
  const d = _etat.diffImport;
  if (!d) return "";
  if (!d.lignes.length) {
    return `<p class="stats-note">Ce profil est identique au vôtre : rien ne changerait.</p>`;
  }
  const lignes = d.lignes
    .map(
      (l) => `<tr>
        <td>${escapeHtml(l.groupe)}</td>
        <td>${escapeHtml(String(l.cle))}</td>
        <td class="stats-num calib-avant">${escapeHtml(String(l.avant ?? "—"))}</td>
        <td class="stats-num"><strong>${escapeHtml(String(l.apres ?? "—"))}</strong></td>
      </tr>`
    )
    .join("");
  return `<div class="calib-diff">
    <p class="calib-suggestion-titre">Ce qui changerait (${d.lignes.length})</p>
    <table class="stats-table"><tbody>${lignes}</tbody></table>
    <div class="calib-actions">
      <button type="button" class="v5-btn v5-btn--ghost" data-calib-annuler-import>Annuler</button>
      <button type="button" class="v5-btn v5-btn--primary" data-calib-confirmer-import>Remplacer mon profil</button>
    </div>
  </div>`;
}

/* ===========================================================
 * Rendu
 * =========================================================== */

function _corps() {
  if (_etat.chargement) return `<div class="calib-vue"><p class="stats-resume">Chargement…</p></div>`;
  if (_etat.erreur) return `<div class="calib-vue"><p class="stats-erreur" role="alert">${escapeHtml(_etat.erreur)}</p></div>`;
  return `<div class="calib-vue">
    <h4 class="parametres-subheading">Options</h4>
    ${_rendreToggles()}
    <h4 class="parametres-subheading">Calibration — d'après vos corrections</h4>
    ${_rendreCalibration()}
    <h4 class="parametres-subheading">Partage</h4>
    <div class="calib-actions calib-actions--gauche">
      <button type="button" class="v5-btn v5-btn--secondary" data-calib-exporter>⬇ Exporter mon profil</button>
      <label class="v5-btn v5-btn--secondary calib-import">
        ⬆ Importer un profil…
        <input type="file" accept=".json,.cinesort.json" data-calib-fichier hidden>
      </label>
    </div>
    ${_rendreDiff()}
  </div>`;
}

/* ===========================================================
 * Actions
 * =========================================================== */

async function _charger() {
  _etat.chargement = true;
  _etat.erreur = "";
  _reouvrir();
  try {
    const [p, c] = await Promise.all([
      apiPost("quality/get_quality_profile", {}),
      apiPost("quality/get_calibration_report", {}),
    ]);
    const dp = (p && p.data) || p || {};
    const dc = (c && c.data) || c || {};
    const profil = dp.profile_json || dp.profile;
    if (dp.ok === false || !profil || typeof profil !== "object") {
      _etat.erreur = dp.user_message || dp.message || "Votre profil n'a pas pu être lu.";
    } else {
      _etat.profil = profil;
      // Un rapport indisponible ne doit pas emporter les options avec lui : ce
      // sont deux lectures independantes.
      _etat.rapport = dc.ok === false ? null : dc;
    }
  } catch {
    _etat.erreur = "Le serveur n'a pas répondu.";
  } finally {
    _etat.chargement = false;
    _reouvrir();
  }
}

async function _ecrireLeProfil(profil, messageSucces) {
  const res = await apiPost("quality/save_quality_profile", { profile_json: profil });
  const data = (res && res.data) || res || {};
  if (data.ok === false) {
    showToast({ type: "error", text: data.user_message || data.message || "L'enregistrement a échoué." });
    return false;
  }
  _etat.profil = profil;
  showToast({ type: "success", text: messageSucces });
  return true;
}

async function _basculerToggle(cle, valeur) {
  if (!_etat.profil) return;
  const suivant = { ..._etat.profil, toggles: { ...(_etat.profil.toggles || {}), [cle]: !!valeur } };
  await _ecrireLeProfil(suivant, "Option enregistrée.");
  _reouvrir();
}

async function _appliquerLaSuggestion() {
  const s = _etat.rapport && _etat.rapport.suggestion;
  if (!s || !_etat.profil) return;
  const poids = s.weights || s;
  const suivant = { ..._etat.profil, weights: { ...(_etat.profil.weights || {}), ...poids } };
  if (await _ecrireLeProfil(suivant, "Poids ajustés d'après vos corrections.")) {
    _etat.rapport = { ..._etat.rapport, suggestion: null };
  }
  _reouvrir();
}

async function _exporter() {
  const res = await apiPost("quality/export_shareable_profile", {});
  const data = (res && res.data) || res || {};
  if (data.ok === false || typeof data.content !== "string") {
    showToast({ type: "error", text: data.user_message || data.message || "L'export a échoué." });
    return;
  }
  // Le contenu part TEL QUEL : le reserialiser perdrait la mise en forme que le
  // backend produit, et c'est ce qu'un destinataire relira.
  const blob = new Blob([data.content], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = data.filename_suggestion || "cinesort-profil.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  showToast({ type: "success", text: "Profil exporté." });
}

/**
 * Prepare un import : on montre le DIFF, on n'ecrit pas.
 *
 * Un import REMPLACE le profil de l'utilisateur. Ecrire d'abord et prevenir
 * ensuite serait le contraire de la regle du depot sur les actions
 * destructives — ici la perte n'est pas un fichier, c'est un reglage.
 */
function _preparerImport(contenu) {
  let entrant = null;
  try {
    const brut = JSON.parse(contenu);
    entrant = brut && typeof brut === "object" ? brut.profile || brut.profile_json || brut : null;
  } catch {
    entrant = null;
  }
  // « OBJET » NE SUFFIT PAS A RECONNAITRE UN PROFIL. En JS, `[1,2,3]` est un
  // objet et `{}` en est un aussi : les deux passaient, produisant un diff VIDE
  // qu'on aurait pu confirmer — donc un profil ecrase par du neant. Trouve par
  // le test avant l'ecran. Un profil PORTE au moins un de ses groupes connus.
  //
  // Pas de `Array.isArray` ici : un tableau issu de `JSON.parse` ne peut pas
  // porter de propriete nommee, donc il echoue deja sur `GROUPES.some`. Ce garde
  // a ete ecrit puis RETIRE — aucune mutation ne pouvait le faire rougir, et une
  // garde qu'aucun test ne peut voir n'en est pas une.
  const GROUPES = ["weights", "tiers", "toggles", "custom_rules"];
  const ressembleAUnProfil =
    entrant &&
    typeof entrant === "object" &&
    GROUPES.some((g) => Object.prototype.hasOwnProperty.call(entrant, g));
  if (!ressembleAUnProfil) {
    showToast({ type: "error", text: "Ce fichier n'est pas un profil CineSort lisible." });
    return;
  }
  _etat.diffImport = { contenu, lignes: _calculerLeDiff(entrant, _etat.profil || {}) };
  _reouvrir();
}

function _confirmerImport() {
  const d = _etat.diffImport;
  if (!d) return;
  dangerConfirmModal({
    title: "Remplacer votre profil de qualité ?",
    items: d.lignes.map((l) => `${l.groupe} · ${l.cle} : ${l.avant ?? "—"} → ${l.apres ?? "—"}`),
    consequence:
      `Votre profil actuel sera REMPLACÉ par celui du fichier (${d.lignes.length} changement(s)). ` +
      `Vos films ne sont pas modifiés, mais leurs scores seront recalculés avec le nouveau profil.`,
    confirmLabel: "Remplacer",
    onConfirm: async () => {
      const res = await apiPost("quality/import_shareable_profile", { content: d.contenu, activate: true });
      const data = (res && res.data) || res || {};
      if (data.ok === false) {
        showToast({ type: "error", text: data.user_message || data.message || "L'import a échoué." });
        return;
      }
      _etat.diffImport = null;
      showToast({ type: "success", text: "Profil importé et activé." });
      _charger();
    },
  });
}

/* ===========================================================
 * Liaison
 * =========================================================== */

function _brancher() {
  const hote = document.querySelector(".calib-vue");
  if (!hote) return;

  hote.addEventListener("click", (ev) => {
    const c = ev.target && ev.target.closest && ev.target.closest("[data-calib-exporter],[data-calib-appliquer],[data-calib-ignorer],[data-calib-annuler-import],[data-calib-confirmer-import]");
    if (!c) return;
    if (c.dataset.calibExporter !== undefined) return _exporter();
    if (c.dataset.calibAppliquer !== undefined) return _appliquerLaSuggestion();
    if (c.dataset.calibIgnorer !== undefined) {
      _etat.rapport = { ...(_etat.rapport || {}), suggestion: null };
      return _reouvrir();
    }
    if (c.dataset.calibAnnulerImport !== undefined) {
      _etat.diffImport = null;
      return _reouvrir();
    }
    return _confirmerImport();
  });

  hote.addEventListener("change", (ev) => {
    const t = ev.target;
    if (!t || !t.dataset) return;
    if (t.dataset.calibToggle !== undefined) return _basculerToggle(t.dataset.calibToggle, t.checked);
    if (t.dataset.calibFichier !== undefined) {
      const f = t.files && t.files[0];
      if (!f) return undefined;
      const lecteur = new FileReader();
      lecteur.onload = () => _preparerImport(String(lecteur.result || ""));
      lecteur.readAsText(f);
      return undefined;
    }
    return undefined;
  });
}

function _reouvrir() {
  showModal({
    title: "Réglages fins du profil",
    body: _corps(),
    actions: [{ label: "Fermer", cls: "", onClick: () => closeModal() }],
  });
  _brancher();
}

/** Point d'entree. */
export function ouvrirCalibrationQualite() {
  _etat.profil = null;
  _etat.rapport = null;
  _etat.diffImport = null;
  _etat.erreur = "";
  _charger();
}

export const __test = {
  _etat,
  _corps,
  _charger,
  _rendreToggles,
  _rendreCalibration,
  _calculerLeDiff,
  _rendreDiff,
  _preparerImport,
  _confirmerImport,
  _basculerToggle,
  _appliquerLaSuggestion,
  _exporter,
  RETOURS_REQUIS,
};
