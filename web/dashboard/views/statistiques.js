/**
 * Vue Statistiques — vague C.
 *
 * Trois analyses qui existaient cote backend, testees, et qu'AUCUN code du
 * dashboard n'appelait : `library/get_library_podiums`,
 * `library/get_library_timeline`, `library/get_scoring_rollup`.
 *
 * POURQUOI UN SEUL ECRAN A TROIS ONGLETS, plutot que trois entrees de menu :
 * ce sont trois lectures de la MEME bibliotheque. Trois entrees auraient
 * suggere trois taches distinctes, et dilue une barre laterale qui compte deja
 * huit items.
 *
 * LES GRAPHIQUES SONT EN SVG, pas en `<div>` empiles. Un graphe en boites CSS
 * ne se met pas a l'echelle, ne s'imprime pas, et rend l'alignement des
 * etiquettes dependant de la police. Le SVG est aussi le seul moyen d'avoir un
 * `<title>` par barre — donc une infobulle native et un contenu accessible.
 *
 * TOUTE VALEUR AFFICHEE VIENT DU PAYLOAD. Aucun compteur n'est reconstruit,
 * aucune absence n'est rendue « 0 » : une cle manquante n'est pas une mesure
 * nulle, et l'ecran le dit plutot que de l'inventer.
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { showToast } from "../components/toast.js";

const ONGLETS = [
  { id: "podiums", label: "Podiums", titre: "Les groupes, codecs et sources les plus presents" },
  { id: "timeline", label: "Chronologie", titre: "Films ajoutes mois par mois" },
  { id: "rollup", label: "Scores", titre: "Score moyen par franchise, realisateur, decennie..." },
];

/** Dimensions REELLES de `get_scoring_rollup` (library_support.py:2253-2268). */
const DIMENSIONS = [
  { id: "franchise", label: "Franchise" },
  { id: "director", label: "Réalisateur" },
  { id: "decade", label: "Décennie" },
  { id: "codec", label: "Codec" },
  { id: "era_grain", label: "Grain d'époque" },
];

const FENETRES = [6, 12, 24];

const _state = {
  onglet: "podiums",
  dimension: "franchise",
  mois: 12,
  data: {},
  chargement: {},
  erreurs: {},
};

/* ===========================================================
 * Rendu
 * =========================================================== */

function _entete() {
  const onglets = ONGLETS.map(
    (o) => `<button type="button" role="tab"
        class="stats-onglet${o.id === _state.onglet ? " is-active" : ""}"
        aria-selected="${o.id === _state.onglet ? "true" : "false"}"
        data-stats-onglet="${escapeHtml(o.id)}"
        title="${escapeHtml(o.titre)}">${escapeHtml(o.label)}</button>`
  ).join("");
  return `<header class="stats-entete">
    <h2 class="stats-titre">Statistiques</h2>
    <div class="stats-onglets" role="tablist">${onglets}</div>
  </header>`;
}

/** Barre horizontale proportionnelle, en SVG, avec son infobulle native. */
function _barre(valeur, max, largeur = 120) {
  const ratio = max > 0 ? Math.max(0, Math.min(1, valeur / max)) : 0;
  const w = Math.round(ratio * largeur);
  return `<svg class="stats-barre" width="${largeur}" height="8" viewBox="0 0 ${largeur} 8"
      role="img" aria-label="${escapeHtml(String(valeur))}">
      <rect x="0" y="0" width="${largeur}" height="8" rx="4" class="stats-barre-fond"/>
      <rect x="0" y="0" width="${w}" height="8" rx="4" class="stats-barre-pleine"/>
    </svg>`;
}

const _MEDAILLES = ["①", "②", "③"];

function _podium(titre, entrees) {
  const liste = Array.isArray(entrees) ? entrees : [];
  if (!liste.length) {
    return `<section class="stats-carte">
      <h3 class="stats-carte-titre">${escapeHtml(titre)}</h3>
      <p class="stats-vide">Aucune donnée pour ce run.</p>
    </section>`;
  }
  const max = Math.max(...liste.map((e) => Number(e.count) || 0));
  const lignes = liste
    .map((e, i) => {
      const n = Number(e.count) || 0;
      return `<li class="stats-ligne">
        <span class="stats-rang">${_MEDAILLES[i] || i + 1}</span>
        <span class="stats-nom" title="${escapeHtml(String(e.name))}">${escapeHtml(String(e.name))}</span>
        ${_barre(n, max)}
        <span class="stats-valeur">${n.toLocaleString("fr-FR")}</span>
      </li>`;
    })
    .join("");
  return `<section class="stats-carte">
    <h3 class="stats-carte-titre">${escapeHtml(titre)}</h3>
    <ol class="stats-liste">${lignes}</ol>
  </section>`;
}

function _rendrePodiums(d) {
  const total = Number(d.total_films) || 0;
  return `<div class="stats-corps">
    <p class="stats-resume">${total.toLocaleString("fr-FR")} film(s) analysé(s)${
      d.run_id ? ` · run ${escapeHtml(String(d.run_id))}` : ""
    }</p>
    <div class="stats-grille">
      ${_podium("Groupes de release", d.release_groups)}
      ${_podium("Codecs", d.codecs)}
      ${_podium("Sources", d.sources)}
    </div>
  </div>`;
}

/** Libelle court d'un mois `2026-08` -> `août 26`. */
function _moisCourt(iso) {
  const m = String(iso || "").match(/^(\d{4})-(\d{2})$/);
  if (!m) return String(iso || "");
  const noms = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"];
  return `${noms[Number(m[2]) - 1] || m[2]} ${m[1].slice(2)}`;
}

const _SOURCES = {
  jellyfin: "Dates lues depuis Jellyfin.",
  filesystem: "Dates lues sur le disque (date du fichier).",
  mixed: "Dates lues depuis Jellyfin, complétées par la date du fichier.",
};

function _rendreTimeline(d) {
  const mois = Array.isArray(d.months) ? d.months : [];
  const boutons = FENETRES.map(
    (n) => `<button type="button" class="stats-choix${n === _state.mois ? " is-active" : ""}"
      data-stats-mois="${n}">${n} mois</button>`
  ).join("");
  if (!mois.length) {
    return `<div class="stats-corps"><div class="stats-choix-barre">${boutons}</div>
      <p class="stats-vide">Aucun film daté sur cette fenêtre.</p></div>`;
  }
  const max = Math.max(...mois.map((m) => Number(m.count) || 0), 1);
  const L = 44;
  const H = 140;
  const largeur = mois.length * L;
  const barres = mois
    .map((m, i) => {
      const n = Number(m.count) || 0;
      const h = Math.round((n / max) * (H - 28));
      const x = i * L + 8;
      const y = H - 20 - h;
      return `<g class="stats-mois">
        <title>${escapeHtml(_moisCourt(m.month))} : ${n} film(s)</title>
        <rect x="${x}" y="${y}" width="${L - 16}" height="${Math.max(h, 2)}" rx="3" class="stats-barre-pleine"/>
        <text x="${x + (L - 16) / 2}" y="${H - 6}" text-anchor="middle" class="stats-axe">${escapeHtml(
          _moisCourt(m.month)
        )}</text>
        ${n > 0 ? `<text x="${x + (L - 16) / 2}" y="${y - 4}" text-anchor="middle" class="stats-valeur-barre">${n}</text>` : ""}
      </g>`;
    })
    .join("");
  const note = _SOURCES[String(d.source || "")] || "";
  return `<div class="stats-corps">
    <div class="stats-choix-barre">${boutons}</div>
    <div class="stats-graphe-hote">
      <svg class="stats-graphe" width="${largeur}" height="${H}" viewBox="0 0 ${largeur} ${H}"
           role="img" aria-label="Films ajoutés par mois">${barres}</svg>
    </div>
    ${note ? `<p class="stats-note">ⓘ ${escapeHtml(note)}</p>` : ""}
  </div>`;
}

/** Couleur de tier a partir d'un score : les memes seuils que la vue Qualité. */
function _tierDuScore(score) {
  if (score == null) return "unknown";
  if (score >= 85) return "platinum";
  if (score >= 70) return "gold";
  if (score >= 55) return "silver";
  if (score >= 40) return "bronze";
  return "reject";
}

function _rendreRollup(d) {
  const groupes = Array.isArray(d.groups) ? d.groups : [];
  const choix = DIMENSIONS.map(
    (dim) => `<button type="button" class="stats-choix${dim.id === _state.dimension ? " is-active" : ""}"
      data-stats-dimension="${escapeHtml(dim.id)}">${escapeHtml(dim.label)}</button>`
  ).join("");
  if (!groupes.length) {
    return `<div class="stats-corps"><div class="stats-choix-barre">${choix}</div>
      <p class="stats-vide">Aucun groupe sur cette dimension.</p></div>`;
  }
  const lignes = groupes
    .map((g) => {
      const score = g.avg_score == null ? null : Number(g.avg_score);
      const nom = g.group || g.name || g.key || "—";
      return `<tr>
        <td class="stats-nom" title="${escapeHtml(String(nom))}">${escapeHtml(String(nom))}</td>
        <td class="stats-num">${(Number(g.count) || 0).toLocaleString("fr-FR")}</td>
        <td class="stats-num">${score == null ? "—" : score.toFixed(1)}</td>
        <td>${score == null ? "" : `<span class="stats-tier stats-tier--${_tierDuScore(score)}">${_barre(score, 100, 96)}</span>`}</td>
      </tr>`;
    })
    .join("");
  return `<div class="stats-corps">
    <div class="stats-choix-barre">${choix}</div>
    <table class="stats-table">
      <thead><tr><th>Groupe</th><th class="stats-num">Films</th><th class="stats-num">Score</th><th>Répartition</th></tr></thead>
      <tbody>${lignes}</tbody>
    </table>
    <p class="stats-note">Trié par nombre de films, puis par score.</p>
  </div>`;
}

function _rendreContenu() {
  const o = _state.onglet;
  if (_state.chargement[o]) return `<div class="stats-corps"><p class="stats-vide">Chargement…</p></div>`;
  if (_state.erreurs[o]) {
    return `<div class="stats-corps"><p class="stats-erreur" role="alert">${escapeHtml(_state.erreurs[o])}</p></div>`;
  }
  const d = _state.data[o];
  if (!d) return `<div class="stats-corps"><p class="stats-vide">—</p></div>`;
  if (o === "podiums") return _rendrePodiums(d);
  if (o === "timeline") return _rendreTimeline(d);
  return _rendreRollup(d);
}

function _rendre(hote) {
  if (!hote) return;
  hote.innerHTML = `<section class="stats-vue">${_entete()}${_rendreContenu()}</section>`;
}

/* ===========================================================
 * Chargement
 * =========================================================== */

const _ROUTES = {
  podiums: () => ["library/get_library_podiums", {}],
  timeline: () => ["library/get_library_timeline", { months: _state.mois }],
  rollup: () => ["library/get_scoring_rollup", { by: _state.dimension }],
};

async function _charger(onglet, hote) {
  const fab = _ROUTES[onglet];
  if (!fab) return;
  const [route, params] = fab();
  _state.chargement[onglet] = true;
  _state.erreurs[onglet] = "";
  _rendre(hote);
  try {
    const res = await apiPost(route, params);
    const data = (res && res.data) || res || {};
    if (data.ok === false) {
      _state.erreurs[onglet] = data.user_message || data.message || "Chargement impossible.";
    } else {
      _state.data[onglet] = data;
    }
  } catch (e) {
    _state.erreurs[onglet] = "Le serveur n'a pas répondu.";
  } finally {
    _state.chargement[onglet] = false;
    _rendre(hote);
  }
}

/* ===========================================================
 * Cycle de vie
 * =========================================================== */

let _hote = null;
let _onClick = null;

export function initStatistiques(container) {
  _hote = container;
  _rendre(_hote);
  _onClick = (ev) => {
    const cible = ev.target && ev.target.closest && ev.target.closest("[data-stats-onglet],[data-stats-dimension],[data-stats-mois]");
    if (!cible) return;
    if (cible.dataset.statsOnglet) {
      _state.onglet = cible.dataset.statsOnglet;
      if (!_state.data[_state.onglet]) _charger(_state.onglet, _hote);
      else _rendre(_hote);
      return;
    }
    if (cible.dataset.statsDimension) {
      _state.dimension = cible.dataset.statsDimension;
      _charger("rollup", _hote);
      return;
    }
    if (cible.dataset.statsMois) {
      _state.mois = Number(cible.dataset.statsMois) || 12;
      _charger("timeline", _hote);
    }
  };
  _hote.addEventListener("click", _onClick);
  _charger(_state.onglet, _hote);
}

export function unmountStatistiques() {
  // Le detachement est EXPLICITE : sans lui, chaque retour sur la vue empilerait
  // un ecouteur de plus sur le meme hote, et un clic finirait par declencher N
  // chargements. C'est la meme discipline que les autres vues.
  if (_hote && _onClick) _hote.removeEventListener("click", _onClick);
  _hote = null;
  _onClick = null;
}

export const __test = { _state, _rendrePodiums, _rendreTimeline, _rendreRollup, _moisCourt, _tierDuScore, _barre };
