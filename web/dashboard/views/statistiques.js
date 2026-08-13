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

const ONGLETS = [
  { id: "podiums", label: "Podiums", titre: "Les groupes, codecs et sources les plus presents" },
  { id: "timeline", label: "Chronologie", titre: "Films ajoutes mois par mois" },
  { id: "rollup", label: "Scores", titre: "Score moyen par franchise, decennie, codec..." },
];

/**
 * Dimensions de `get_scoring_rollup`, MIROIR de `library_support.py:
 * SCORING_ROLLUP_DIMENSIONS`. `tests/test_statistiques_dimensions.py` refuse
 * que les deux listes divergent, ET qu'une entree ne produise aucun groupe.
 *
 * « Réalisateur » a ete retire : la branche backend rendait `None` pour TOUTE
 * row (aucune ne porte de realisateur), donc le bouton repondait « Aucun groupe
 * sur cette dimension » quoi que fasse l'utilisateur. Enumerer les branches
 * `if dim == ...` — ce qu'avait fait la premiere version de ce commentaire — ne
 * dit pas si elles rendent quelque chose.
 *
 * « Résolution » a ete ajoutee : le backend la groupait deja, l'ecran ne
 * l'offrait pas.
 */
const DIMENSIONS = [
  { id: "franchise", label: "Franchise" },
  { id: "decade", label: "Décennie" },
  { id: "codec", label: "Codec" },
  { id: "era_grain", label: "Grain d'époque" },
  { id: "resolution", label: "Résolution" },
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
  const L = 44; // largeur naturelle d'un mois
  const H = 168;
  const HAUT = 26; // place reservee aux etiquettes de valeur
  const BAS = 22; // place reservee aux etiquettes de mois
  const GOUTTIERE = 34; // colonne de gauche : l'echelle
  const PLEIN = H - HAUT - BAS; // hauteur utile d'une barre a 100 %
  const base = H - BAS;
  const largeur = GOUTTIERE + mois.length * L;
  const y = (v) => base - Math.round((v / max) * PLEIN);

  // L'ECHELLE. Sans elle, une barre deux fois plus haute qu'une autre se lit,
  // mais « 88 films » ne se lit pas : le graphe montre des proportions et cache
  // les grandeurs. Deux graduations suffisent (le maximum et sa moitie) ; au-dela
  // le fond devient plus bavard que les donnees. `Set` evite la graduation en
  // double quand max vaut 1.
  const graduations = [...new Set([max, Math.round(max / 2)])].filter((v) => v > 0);
  const echelle = graduations
    .map(
      (v) => `<g>
        <line x1="${GOUTTIERE}" y1="${y(v)}" x2="${largeur}" y2="${y(v)}" class="stats-grille-ligne"/>
        <text x="${GOUTTIERE - 6}" y="${y(v) + 3}" text-anchor="end" class="stats-axe">${v}</text>
      </g>`
    )
    .join("");

  const barres = mois
    .map((m, i) => {
      const n = Number(m.count) || 0;
      const h = base - y(n);
      const x = GOUTTIERE + i * L + 8;
      const l = L - 16;
      // ZERO EST UNE MESURE, PAS UNE ABSENCE — mais une barre de 2 px a la
      // couleur d'accent se lit « quelques films ». Le mois creux garde donc une
      // marque, dans une classe qui la montre comme un creux.
      const vide = n <= 0;
      return `<g class="stats-mois">
        <title>${escapeHtml(_moisCourt(m.month))} : ${n} film(s)</title>
        <rect x="${x}" y="${vide ? base - 2 : y(n)}" width="${l}" height="${vide ? 2 : Math.max(h, 2)}"
              rx="3" class="${vide ? "stats-barre-vide" : "stats-barre-pleine"}"/>
        <text x="${x + l / 2}" y="${H - 6}" text-anchor="middle" class="stats-axe">${escapeHtml(
          _moisCourt(m.month)
        )}</text>
        ${n > 0 ? `<text x="${x + l / 2}" y="${y(n) - 6}" text-anchor="middle" class="stats-valeur-barre">${n}</text>` : ""}
      </g>`;
    })
    .join("");

  const note = _SOURCES[String(d.source || "")] || "";
  // LE GRAPHE S'ADAPTE A SON CONTENEUR. Mesure au navigateur : a taille fixe,
  // 12 mois faisaient deja apparaitre une barre de defilement dans la colonne
  // centrale (inspecteur ouvert), alors que la page avait de la place en
  // hauteur. Il se contracte donc jusqu'a son minimum lisible, et ne defile
  // qu'au-dela ; il ne grandit jamais au-dela de sa taille naturelle, sinon
  // 6 mois donneraient six pavés.
  const minimum = GOUTTIERE + mois.length * 26;
  return `<div class="stats-corps">
    <div class="stats-choix-barre">${boutons}</div>
    <div class="stats-graphe-hote">
      <svg class="stats-graphe" viewBox="0 0 ${largeur} ${H}" style="--stats-large: ${largeur}px; --stats-min: ${minimum}px"
           role="img" aria-label="Films ajoutés par mois, maximum ${max}">
        ${echelle}
        <line x1="${GOUTTIERE}" y1="${base}" x2="${largeur}" y2="${base}" class="stats-base"/>
        ${barres}
      </svg>
    </div>
    ${note ? `<p class="stats-note">ⓘ ${escapeHtml(note)}</p>` : ""}
  </div>`;
}

/* Libelles de tier — les MEMES que /bibliotheque et /accueil. Un ecran n'invente
   pas son vocabulaire : « Platine » ici et « Platinum » ailleurs donnerait deux
   noms au meme objet. */
const _TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
  unknown: "Non identifié",
};

/** Ordre d'affichage, du meilleur au pire. `unknown` ferme la marche. */
const _TIERS_ORDONNES = ["platinum", "gold", "silver", "bronze", "reject", "unknown"];

/**
 * Repartition des tiers d'un groupe, telle que le BACKEND l'a comptee.
 *
 * POURQUOI CETTE VUE NE CALCULE PLUS LE TIER ELLE-MEME. Une premiere version
 * derivait le tier du score moyen avec une grille ecrite en dur (85/70/55/40).
 * Deux defauts, tous deux mesures :
 *
 *   1. LA GRILLE ETAIT FAUSSE. La grille canonique de l'application est
 *      70/66/55/40 — `default_quality_profile()["tiers"]`, et `_DEFAULT_TIERS`
 *      dans `parametres.js:510` la reprend a l'identique. Un film a 72 s'affichait
 *      « Gold » ici et « Platinum » partout ailleurs.
 *   2. SURTOUT, CES SEUILS SONT REGLABLES PAR L'UTILISATEUR. C'est l'objet meme
 *      du profil de qualite. AUCUNE grille en dur ne peut etre juste : celle-ci
 *      aurait menti pour tout utilisateur ayant touche a ses seuils.
 *
 * Le backend envoie DEJA `tier_distribution` — les tiers reels, comptes film par
 * film avec le profil actif. Les afficher est a la fois plus juste et plus
 * informatif : une moyenne de 60 ne dit pas si le groupe est homogene ou s'il
 * melange des Platinum et des Reject.
 *
 * LE NOMBRE ACCOMPAGNE TOUJOURS LA COULEUR. `silver` et `platinum` sont proches
 * a l'oeil nu, et indistinguables pour un daltonien comme en impression noir et
 * blanc — WCAG 1.4.1 : aucune information ne passe par la seule couleur. Chaque
 * segment porte donc son compte en infobulle, et la ligne son detail en texte.
 */
function _celluleDeRepartition(groupe) {
  const dist = groupe && typeof groupe.tier_distribution === "object" ? groupe.tier_distribution : null;
  if (!dist) return `<span class="stats-vide-cellule">—</span>`;
  const parts = _TIERS_ORDONNES.map((t) => ({ tier: t, n: Number(dist[t]) || 0 })).filter((p) => p.n > 0);
  const total = parts.reduce((s, p) => s + p.n, 0);
  if (!total) return `<span class="stats-vide-cellule">—</span>`;
  const segments = parts
    .map(
      (p) => `<span class="stats-part stats-part--${p.tier}" style="--part: ${p.n / total}"
        title="${escapeHtml(_TIER_LABELS[p.tier] || p.tier)} : ${p.n}"></span>`
    )
    .join("");
  const texte = parts.map((p) => `${_TIER_LABELS[p.tier] || p.tier} ${p.n}`).join(" · ");
  return `<span class="stats-repartition" role="img" aria-label="${escapeHtml(texte)}">
    <span class="stats-parts">${segments}</span>
    <span class="stats-repartition-texte">${escapeHtml(texte)}</span>
  </span>`;
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
      // UN SCORE NON NUMERIQUE N'EST PAS UN SCORE. `Number("abc")` rend NaN, et
      // `NaN.toFixed(1)` rend la chaine « NaN » — affichee telle quelle dans la
      // colonne. `Number.isFinite` couvre du meme geste NaN, Infinity et les
      // valeurs non convertibles ; toutes se lisent alors « — », comme une
      // absence, ce qu'elles sont.
      const brut = g.avg_score == null ? null : Number(g.avg_score);
      const score = Number.isFinite(brut) ? brut : null;
      // `group_name` EST LA CLE REELLE — verifiee dans
      // `library_support.py:_get_scoring_rollup_impl`, qui construit
      // `{"group_name", "count", "avg_score", "tier_distribution", "top_film_ids"}`.
      // La premiere version lisait `g.group || g.name || g.key` : AUCUNE de ces
      // trois cles n'existe, donc chaque ligne du tableau se serait affichee
      // « — ». Le test ne l'a pas vu parce qu'il INVENTAIT `group` dans son
      // echantillon : une fixture qui ne vient pas de la production ne prouve
      // que la coherence du test avec lui-meme.
      const nom = g.group_name || "—";
      return `<tr>
        <td class="stats-nom" title="${escapeHtml(String(nom))}">${escapeHtml(String(nom))}</td>
        <td class="stats-num">${(Number(g.count) || 0).toLocaleString("fr-FR")}</td>
        <td class="stats-num">${score == null ? "—" : score.toFixed(1)}</td>
        <td>${_celluleDeRepartition(g)}</td>
      </tr>`;
    })
    .join("");
  return `<div class="stats-corps">
    <div class="stats-choix-barre">${choix}</div>
    <table class="stats-table">
      <thead><tr><th>Groupe</th><th class="stats-num">Films</th><th class="stats-num">Score</th><th>Répartition des niveaux</th></tr></thead>
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

// UNE `Map`, PAS UN OBJET LITTERAL. `onglet` vient du `dataset` d'un bouton,
// donc du DOM. Sur un objet litteral, une recherche par cle non statique
// traverse aussi le PROTOTYPE : `_ROUTES["constructor"]` rend `Object`, valeur
// VRAIE, donc appelee. Une `Map` n'a pas de cles heritees — la classe entiere de
// probleme disparait au lieu d'etre gardee au cas par cas.
const _ROUTES = new Map([
  ["podiums", () => ["library/get_library_podiums", {}]],
  ["timeline", () => ["library/get_library_timeline", { months: _state.mois }]],
  ["rollup", () => ["library/get_scoring_rollup", { by: _state.dimension }]],
]);

//: Numero de la derniere requete emise, par onglet. Une reponse dont le numero
//: n'est plus le dernier est PERIMEE : elle a ete doublee par une autre.
const _jetons = {};

async function _charger(onglet, hote) {
  const fabrique = _ROUTES.get(onglet);
  if (!fabrique) return;
  const [route, params] = fabrique();

  // POURQUOI UN JETON. Deux clics rapides sur « 6 mois » puis « 24 mois »
  // emettent deux requetes ; rien ne garantit qu'elles reviennent dans l'ordre.
  // Sans jeton, la reponse LENTE ecrase la rapide et l'ecran affiche 6 mois
  // alors que le bouton 24 est actif — un chiffre faux sous une etiquette juste,
  // et rien pour le signaler. Le demontage de la vue a le meme probleme : une
  // reponse en vol ecrit dans un etat qu'on vient de quitter.
  const jeton = (_jetons[onglet] = (_jetons[onglet] || 0) + 1);
  const estPerimee = () => _jetons[onglet] !== jeton || _hote !== hote;

  _state.chargement[onglet] = true;
  _state.erreurs[onglet] = "";
  _rendre(hote);
  try {
    const res = await apiPost(route, params);
    if (estPerimee()) return;
    const data = (res && res.data) || res || {};
    if (data.ok === false) {
      _state.erreurs[onglet] = data.user_message || data.message || "Chargement impossible.";
    } else {
      _state.data[onglet] = data;
    }
  } catch {
    if (estPerimee()) return;
    _state.erreurs[onglet] = "Le serveur n'a pas répondu.";
  } finally {
    if (!estPerimee()) {
      _state.chargement[onglet] = false;
      _rendre(hote);
    }
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
    // LES IDS VIENNENT DU DOM, DONC ON LES VALIDE ICI — a l'entree, pas plus
    // bas. Sans cette validation, `_state.onglet` prenait la valeur recue telle
    // quelle : un id inconnu vidait l'ecran (aucune donnee pour cet onglet), et
    // un nom herite du prototype comme `constructor` faisait rendre `Object` a
    // la table `_ROUTES` — valeur VRAIE, donc appelee, puis destructuree en
    // tableau, donc rejet de promesse non traite. Valider en amont supprime les
    // deux d'un coup.
    if (cible.dataset.statsOnglet) {
      const demande = cible.dataset.statsOnglet;
      if (!ONGLETS.some((o) => o.id === demande)) return;
      _state.onglet = demande;
      if (!_state.data[_state.onglet]) _charger(_state.onglet, _hote);
      else _rendre(_hote);
      return;
    }
    if (cible.dataset.statsDimension) {
      const dim = cible.dataset.statsDimension;
      if (!DIMENSIONS.some((d) => d.id === dim)) return;
      _state.dimension = dim;
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

// `_charger` est expose parce que la SECONDE barriere (le garde de la table
// `_ROUTES`) n'est pas atteignable depuis un clic : la validation d'entree la
// couvre deja. Une garde qu'aucun test ne peut voir n'en est pas une — on
// l'eprouve donc a son propre niveau.
export const __test = {
  _state,
  _rendrePodiums,
  _rendreTimeline,
  _rendreRollup,
  _moisCourt,
  _celluleDeRepartition,
  _barre,
  _charger,
};
