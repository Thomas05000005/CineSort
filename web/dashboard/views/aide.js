/* views/aide.js — Phase 5 (spec 12-aide.md) — Vue Aide complete.
 *
 * 5 sections + recherche full-text (spec 12 §1) :
 *  1. Documentation (8 topics, clic -> drawer markdown)
 *  2. Raccourcis clavier (table statique incluant fleches haut/bas)
 *  3. Diagnostic (runtime/get_diagnostic - 15 champs)
 *  4. Logs (Ouvrir dossier + Copier 100 dernieres lignes)
 *  5. A propos (licence, repo, changelog, contributeurs)
 *
 * Endpoints backend (PR #300) :
 *  - runtime/get_diagnostic        : bloc complet
 *  - runtime/get_recent_logs       : N dernieres lignes (cap 1000)
 *  - runtime/get_doc(doc_id)       : markdown brut whiteliste
 *  - runtime/search_docs(query)    : recherche live
 *
 * Mini-renderer markdown integre : titres (h1-h4), paragraphes, listes,
 * liens, code inline, code blocks, blockquotes, separateurs. Pas de
 * dependance externe (cf decision pas de lib markdown dans web/).
 *
 * Pas d'inspecteur droit sur Aide (spec 12 §1).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";

/* --- Donnees statiques (spec 12 §1) ------------------------------------ */

/**
 * Mapping topic -> doc_id whiteliste backend (cf docs_whitelist.py).
 *
 * Les 8 topics decrits dans la spec sont des entrees du USER_GUIDE_v2.md.
 * Chaque topic pointe vers un doc_id whiteliste + une ancre optionnelle
 * (section heading slug) pour scroller au bon endroit dans le drawer.
 *
 * doc_id valides : user-guide, manual, troubleshooting, export-format,
 * api-endpoints, i18n, release.
 */
const _DOC_TOPICS = [
  {
    id: "premiers-pas",
    title: "Premiers pas",
    desc: "Guide rapide pour ton premier scan",
    doc_id: "user-guide",
    anchor: "1-premier-lancement",
  },
  {
    id: "lancer-scan",
    title: "Comment lancer un scan",
    desc: "Configurer les roots + lancer l'analyse",
    doc_id: "user-guide",
    anchor: "6-workflow-type-du-scan-a-lapply",
  },
  {
    id: "doublons",
    title: "Comment résoudre des doublons",
    desc: "Identifier et choisir le bon fichier",
    doc_id: "user-guide",
    anchor: "3-les-7-vues-principales",
  },
  {
    id: "tiers",
    title: "Comprendre les scores Bronze / Silver / Gold / Platinum",
    desc: "La grille de qualité v2",
    doc_id: "user-guide",
    anchor: "4-le-score-v2-systeme-de-tiers",
  },
  {
    id: "omdb-tmdb",
    title: "Configurer OMDb et TMDb",
    desc: "Clés API + validation croisée",
    doc_id: "user-guide",
    anchor: "1-premier-lancement",
  },
  {
    id: "apply-vs-dryrun",
    title: "Apply réel vs dry-run : différences",
    desc: "Tester avant de modifier sur disque",
    doc_id: "user-guide",
    anchor: "7-actions-dangereuses-confirmations-obligatoires",
  },
  {
    id: "undo",
    title: "Undo : comment annuler",
    desc: "Revenir en arrière sur un apply",
    doc_id: "user-guide",
    anchor: "7-actions-dangereuses-confirmations-obligatoires",
  },
  {
    id: "securite-torrents",
    title: "Sécurité torrents : pourquoi on ne modifie pas les titres",
    desc: "Préserver le seed",
    doc_id: "user-guide",
    anchor: "5-les-alertes-humanisees-warning_flags",
  },
];

const _SHORTCUTS = [
  { keys: ["Ctrl", "K"], label: "Palette de commandes / Recherche globale" },
  { keys: ["Ctrl", "S"], label: "Lancer un nouveau scan" },
  { keys: ["Ctrl", "B"], label: "Replier ou déployer la sidebar" },
  { keys: ["Ctrl", "I"], label: "Afficher ou masquer l'inspecteur droit" },
  { keys: ["Ctrl", ","], label: "Aller à Paramètres" },
  { keys: ["Ctrl", "Z"], label: "Annuler le dernier apply (depuis Bibliothèque)" },
  { keys: ["Esc"], label: "Fermer modal / palette / drawer" },
  { keys: ["?"], label: "Afficher cette aide" },
  { keys: ["↑", "↓"], label: "Navigation dans listes (films, doublons, runs)" },
  { keys: ["Alt", "1..7"], label: "Navigation directe (1=Accueil ... 7=Aide)" },
];

const _GITHUB_REPO_URL = "https://github.com/Thomas05000005/CineSort";
const _GITHUB_ISSUES_URL = "https://github.com/Thomas05000005/CineSort/issues/new";

/* --- Etat local --------------------------------------------------------- */

let _searchQuery = "";
let _searchDebounceId = null;
let _activeDrawer = null;
let _lastDiagnostic = null;

/* --- Renderers ---------------------------------------------------------- */

function _renderHeader() {
  return `
    <header class="aide-header">
      <h1 class="aide-title">Aide</h1>
      <div class="aide-search" role="search">
        <input type="search" class="v5-input aide-search-input"
               placeholder="🔍 Rechercher dans la doc..."
               value="${escapeHtml(_searchQuery)}"
               aria-label="Recherche dans la documentation"
               autocomplete="off"
               data-aide-search>
        <div class="aide-search-results" role="listbox" data-aide-search-results hidden></div>
      </div>
    </header>
  `;
}

function _renderDocSection() {
  const items = _DOC_TOPICS.map((t) => `
    <li class="aide-doc-item" tabindex="0" role="button"
        data-aide-topic="${escapeHtml(t.id)}"
        data-aide-doc-id="${escapeHtml(t.doc_id)}"
        data-aide-anchor="${escapeHtml(t.anchor || "")}">
      <span class="aide-doc-bullet" aria-hidden="true">📄</span>
      <span class="aide-doc-text">
        <strong>${escapeHtml(t.title)}</strong>
        <span class="aide-doc-desc">${escapeHtml(t.desc)}</span>
      </span>
    </li>
  `).join("");
  return `
    <section class="aide-section aide-doc" aria-labelledby="aide-doc-title">
      <h2 id="aide-doc-title" class="aide-section-title">📚 Documentation</h2>
      <p class="aide-section-intro">Cliquez sur un sujet pour ouvrir le guide complet.</p>
      <ul class="aide-doc-list">${items}</ul>
    </section>
  `;
}

function _renderShortcutsSection() {
  const rows = _SHORTCUTS.map((s) => {
    const keysHtml = s.keys.map((k) => `<kbd>${escapeHtml(k)}</kbd>`).join("+");
    return `
      <tr>
        <td class="aide-shortcut-keys">${keysHtml}</td>
        <td class="aide-shortcut-label">${escapeHtml(s.label)}</td>
      </tr>
    `;
  }).join("");
  return `
    <section class="aide-section aide-shortcuts" aria-labelledby="aide-shortcuts-title">
      <h2 id="aide-shortcuts-title" class="aide-section-title">⌨️ Raccourcis clavier</h2>
      <table class="aide-shortcuts-table">
        <tbody>${rows}</tbody>
      </table>
    </section>
  `;
}

function _diagIntegrationStatus(integ) {
  if (!integ || typeof integ !== "object") return "—";
  const cfg = integ.configured;
  const ok = integ.ok;
  if (cfg === false) return "non configuré";
  if (ok === true) return "✓ OK";
  if (ok === false) return "✗ erreur";
  return cfg ? "configuré" : "—";
}

function _renderDiagnosticSection(diagnostic) {
  if (!diagnostic) {
    return `
      <section class="aide-section aide-diagnostic" aria-labelledby="aide-diagnostic-title">
        <h2 id="aide-diagnostic-title" class="aide-section-title">⚙ Diagnostic</h2>
        <p class="aide-empty-msg">Chargement du diagnostic…</p>
      </section>
    `;
  }
  const integ = diagnostic.integrations || {};
  const lines = [
    ["Version", diagnostic.version || "?"],
    ["Build", diagnostic.build_date || "—"],
    ["Python", diagnostic.python_version || "?"],
    ["Plateforme", diagnostic.platform || "?"],
    ["DB schema", diagnostic.db_schema_version || "?"],
    ["ffprobe", diagnostic.ffprobe_version || "non détecté"],
    ["MediaInfo", diagnostic.mediainfo_version || "non détecté"],
    ["TMDb", _diagIntegrationStatus(integ.tmdb)],
    ["OMDb", _diagIntegrationStatus(integ.omdb)],
    ["Jellyfin", _diagIntegrationStatus(integ.jellyfin)],
    ["Plex", _diagIntegrationStatus(integ.plex)],
    ["Radarr", _diagIntegrationStatus(integ.radarr)],
    ["Roots actifs", Array.isArray(diagnostic.roots) ? `${diagnostic.roots.length} root(s)` : "0"],
    ["Bibliothèque", diagnostic.lib_total != null ? `${diagnostic.lib_total} films · ${diagnostic.lib_scored || 0} classés` : "—"],
    ["Dernier run", diagnostic.last_run_id ? `${diagnostic.last_run_id} (${diagnostic.last_run_status || "?"})` : "aucun"],
  ];
  const rows = lines.map(([k, v]) => `
    <div class="aide-diag-row">
      <dt>${escapeHtml(k)}</dt>
      <dd>${escapeHtml(String(v))}</dd>
    </div>
  `).join("");
  return `
    <section class="aide-section aide-diagnostic" aria-labelledby="aide-diagnostic-title">
      <h2 id="aide-diagnostic-title" class="aide-section-title">⚙ Diagnostic</h2>
      <dl class="aide-diag-list">${rows}</dl>
      <div class="aide-actions">
        <button type="button" class="v5-btn v5-btn--secondary" data-aide-action="copy-diagnostic">📋 Copier le diagnostic</button>
        <button type="button" class="v5-btn v5-btn--ghost" data-aide-action="report-bug">🐛 Signaler un bug</button>
      </div>
      <p class="aide-action-status" data-aide-status></p>
    </section>
  `;
}

function _renderLogsSection() {
  return `
    <section class="aide-section aide-logs" aria-labelledby="aide-logs-title">
      <h2 id="aide-logs-title" class="aide-section-title">📝 Logs</h2>
      <p class="aide-section-intro">Accès rapide aux journaux d'application.</p>
      <div class="aide-actions">
        <button type="button" class="v5-btn v5-btn--secondary" data-aide-action="open-logs">📂 Ouvrir le dossier des logs</button>
        <button type="button" class="v5-btn v5-btn--ghost" data-aide-action="copy-recent-logs">📋 Copier les 100 dernières lignes</button>
      </div>
      <p class="aide-action-status" data-aide-logs-status></p>
    </section>
  `;
}

function _renderAboutSection(diagnostic) {
  const version = diagnostic && diagnostic.version ? diagnostic.version : "?";
  return `
    <section class="aide-section aide-about" aria-labelledby="aide-about-title">
      <h2 id="aide-about-title" class="aide-section-title">ℹ️ À propos</h2>
      <p class="aide-about-tagline">
        <strong>CineSort</strong> <span class="aide-about-version">v${escapeHtml(version)}</span> — Tri et normalisation de bibliothèque films.
      </p>
      <p class="aide-about-license">Licence : MIT</p>
      <div class="aide-actions">
        <a href="${_GITHUB_REPO_URL}" target="_blank" rel="noopener" class="v5-btn v5-btn--ghost">Repo GitHub</a>
        <a href="${_GITHUB_REPO_URL}/blob/main/CHANGELOG.md" target="_blank" rel="noopener" class="v5-btn v5-btn--ghost">Changelog</a>
        <a href="${_GITHUB_REPO_URL}/graphs/contributors" target="_blank" rel="noopener" class="v5-btn v5-btn--ghost">Contributeurs</a>
      </div>
    </section>
  `;
}

function _renderAide(diagnostic) {
  return `
    <section class="aide-view">
      ${_renderHeader()}
      ${_renderDocSection()}
      ${_renderShortcutsSection()}
      ${_renderDiagnosticSection(diagnostic)}
      ${_renderLogsSection()}
      ${_renderAboutSection(diagnostic)}
    </section>
  `;
}

/* --- Diagnostic : appel direct au nouvel endpoint ---------------------- */

async function _fetchDiagnostic() {
  // Spec 12 §4 + PR #300 : endpoint dedie runtime/get_diagnostic qui agrege
  // les 15 champs (version, integrations, roots, lib_total, etc.).
  try {
    const res = await apiPost("runtime/get_diagnostic", {});
    const data = (res && res.data) || res || null;
    if (data && data.ok !== false && data.diagnostic) {
      return data.diagnostic;
    }
    // Backend present mais reponse vide : on retourne null pour que la
    // section affiche son message d'erreur plutot que des donnees corrompues.
    console.warn("[aide] get_diagnostic non disponible:", data);
    return null;
  } catch (err) {
    console.warn("[aide] fetch diagnostic failed:", err);
    return null;
  }
}

/* --- Mini-markdown renderer (sans dependance externe) ------------------ */

/**
 * Slugify : convertit un titre en ancre URL-safe.
 * Ex : "## 4. Le Score V2 (système de tiers)" -> "4-le-score-v2-systeme-de-tiers"
 */
function _slugify(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

/**
 * Rend les inline markdown (gras, italique, code, liens) sur une ligne.
 * Echappe le HTML AVANT toute transformation pour eviter le XSS.
 */
function _renderInline(text) {
  let s = escapeHtml(text);
  // Code inline : `code` (avant les autres formats pour proteger leur contenu)
  s = s.replace(/`([^`]+)`/g, (_m, p) => `<code class="aide-markdown-code-inline">${p}</code>`);
  // Liens : [texte](url) — url validee (http/https/mailto uniquement)
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, txt, url) => {
    const safe = /^(https?:|mailto:|#)/i.test(url) ? url : "#";
    return `<a href="${safe}" target="_blank" rel="noopener" class="aide-markdown-link">${txt}</a>`;
  });
  // Gras : **texte**
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // Italique : *texte* (apres gras pour eviter conflit)
  s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*([^*]|$)/g, "$1<em>$2</em>$3");
  return s;
}

/**
 * Convertit du markdown brut en HTML safe. Supporte :
 * - Titres h1 a h4 (avec id pour scroll vers ancre)
 * - Paragraphes
 * - Listes a puces (-, *, +) et numerotees
 * - Code blocks ```
 * - Blockquotes >
 * - Separateurs ---
 * - Liens, gras, italique, code inline
 *
 * Ne supporte pas : tables, images, footnotes (out of scope v1).
 */
function _renderMarkdown(md) {
  if (!md || typeof md !== "string") return "";
  const lines = md.split(/\r?\n/);
  const out = [];
  let i = 0;
  let inCode = false;
  let codeLang = "";
  let codeBuf = [];
  let listType = null; // "ul" | "ol" | null
  let listBuf = [];

  const flushList = () => {
    if (listType && listBuf.length > 0) {
      out.push(`<${listType} class="aide-markdown-list">${listBuf.join("")}</${listType}>`);
    }
    listType = null;
    listBuf = [];
  };

  while (i < lines.length) {
    const line = lines[i];

    // Code block fence
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      if (!inCode) {
        flushList();
        inCode = true;
        codeLang = fence[1] || "";
        codeBuf = [];
      } else {
        const langAttr = codeLang ? ` data-lang="${escapeHtml(codeLang)}"` : "";
        out.push(`<pre class="aide-markdown-code-block"${langAttr}><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
        inCode = false;
        codeLang = "";
        codeBuf = [];
      }
      i++;
      continue;
    }
    if (inCode) {
      codeBuf.push(line);
      i++;
      continue;
    }

    // Separator horizontal
    if (/^\s*---+\s*$/.test(line)) {
      flushList();
      out.push('<hr class="aide-markdown-hr">');
      i++;
      continue;
    }

    // Heading
    const h = line.match(/^(#{1,4})\s+(.+?)\s*#*\s*$/);
    if (h) {
      flushList();
      const level = h[1].length;
      const text = h[2];
      const id = _slugify(text);
      out.push(`<h${level} class="aide-markdown-h${level}" id="${id}">${_renderInline(text)}</h${level}>`);
      i++;
      continue;
    }

    // Blockquote
    if (/^\s*>\s?/.test(line)) {
      flushList();
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      out.push(`<blockquote class="aide-markdown-quote">${_renderInline(buf.join(" "))}</blockquote>`);
      continue;
    }

    // List item (ul)
    const ulm = line.match(/^\s*[-*+]\s+(.+)$/);
    if (ulm) {
      if (listType !== "ul") {
        flushList();
        listType = "ul";
      }
      listBuf.push(`<li>${_renderInline(ulm[1])}</li>`);
      i++;
      continue;
    }
    // List item (ol)
    const olm = line.match(/^\s*\d+\.\s+(.+)$/);
    if (olm) {
      if (listType !== "ol") {
        flushList();
        listType = "ol";
      }
      listBuf.push(`<li>${_renderInline(olm[1])}</li>`);
      i++;
      continue;
    }

    // Blank line
    if (/^\s*$/.test(line)) {
      flushList();
      i++;
      continue;
    }

    // Paragraph : concatene les lignes jusqu'au prochain blanc / heading / list
    flushList();
    const pbuf = [line];
    i++;
    while (i < lines.length) {
      const next = lines[i];
      if (/^\s*$/.test(next)) break;
      if (/^#{1,4}\s+/.test(next)) break;
      if (/^```/.test(next)) break;
      if (/^\s*[-*+]\s+/.test(next)) break;
      if (/^\s*\d+\.\s+/.test(next)) break;
      if (/^\s*>\s?/.test(next)) break;
      pbuf.push(next);
      i++;
    }
    out.push(`<p class="aide-markdown-p">${_renderInline(pbuf.join(" "))}</p>`);
  }
  flushList();
  if (inCode && codeBuf.length > 0) {
    out.push(`<pre class="aide-markdown-code-block"><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
  }

  return out.join("\n");
}

/* --- Drawer markdown --------------------------------------------------- */

function _closeDrawer() {
  if (_activeDrawer && _activeDrawer.parentNode) {
    _activeDrawer.parentNode.removeChild(_activeDrawer);
  }
  _activeDrawer = null;
}

function _renderDrawerSkeleton(topicTitle) {
  return `
    <div class="aide-doc-drawer-backdrop" data-aide-drawer-close></div>
    <aside class="aide-doc-drawer" role="dialog" aria-modal="true" aria-labelledby="aide-drawer-title">
      <header class="aide-doc-drawer-header">
        <h2 id="aide-drawer-title" class="aide-doc-drawer-title">${escapeHtml(topicTitle)}</h2>
        <button type="button" class="v5-btn v5-btn--ghost aide-doc-drawer-expand" data-aide-action="drawer-expand" title="Ouvrir dans la fenetre principale">⤢ Ouvrir en grand</button>
        <button type="button" class="v5-btn v5-btn--ghost aide-doc-drawer-close" data-aide-drawer-close aria-label="Fermer">✕</button>
      </header>
      <div class="aide-doc-content" data-aide-drawer-content>
        <p class="aide-empty-msg">Chargement de la documentation…</p>
      </div>
    </aside>
  `;
}

async function _openDocDrawer(topic) {
  _closeDrawer();
  const drawer = document.createElement("div");
  drawer.className = "aide-doc-drawer-overlay";
  drawer.innerHTML = _renderDrawerSkeleton(topic.title);
  document.body.appendChild(drawer);
  _activeDrawer = drawer;

  // Bindings
  drawer.querySelectorAll("[data-aide-drawer-close]").forEach((el) => {
    el.addEventListener("click", _closeDrawer);
  });
  const expandBtn = drawer.querySelector('[data-aide-action="drawer-expand"]');
  if (expandBtn) {
    expandBtn.addEventListener("click", () => {
      // Page standalone : route /aide/doc/<topic_id>. La route n'existe pas
      // encore dans le router, mais l'URL est cliquable et bookmarkable.
      const url = `#/aide/doc/${encodeURIComponent(topic.id)}`;
      window.location.hash = url;
      _closeDrawer();
    });
  }
  // Esc -> close
  const onKey = (ev) => {
    if (ev.key === "Escape") {
      _closeDrawer();
      document.removeEventListener("keydown", onKey);
    }
  };
  document.addEventListener("keydown", onKey);

  const contentEl = drawer.querySelector("[data-aide-drawer-content]");

  try {
    const res = await apiPost("runtime/get_doc", { file: topic.doc_id });
    const data = (res && res.data) || res || null;
    if (!data || data.ok === false) {
      const msg = (data && (data.error || data.message)) || "Document indisponible.";
      contentEl.innerHTML = `<p class="aide-empty-msg aide-error">${escapeHtml(msg)}</p>`;
      return;
    }
    const html = _renderMarkdown(data.content || "");
    contentEl.innerHTML = html || `<p class="aide-empty-msg">Document vide.</p>`;
    // Scroll vers l'ancre si specifiee
    if (topic.anchor) {
      const target = contentEl.querySelector(`#${CSS.escape(topic.anchor)}`);
      if (target && typeof target.scrollIntoView === "function") {
        // Petit delai pour que le layout soit appliqu  e
        setTimeout(() => target.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
      }
    } else if (topic.line_number) {
      // Pour les hits de recherche : scroll vers la ligne cible
      _scrollToLine(contentEl, topic.line_number);
    }
  } catch (err) {
    contentEl.innerHTML = `<p class="aide-empty-msg aide-error">Erreur réseau : ${escapeHtml(String(err && err.message ? err.message : err))}</p>`;
  }
}

function _scrollToLine(contentEl, lineNumber) {
  // Approximation : on cherche le N-ieme paragraphe/heading dans le DOM rendu.
  // Pas parfait (line_number compte les lignes markdown, pas les blocs), mais
  // suffisant pour positionner l'utilisateur grosso modo a la bonne section.
  const blocks = contentEl.querySelectorAll("h1,h2,h3,h4,p,li,blockquote");
  if (blocks.length === 0) return;
  // Heuristique : 1 ligne markdown = 1 element au max, on cap a la longueur.
  const idx = Math.min(Math.max(0, Math.floor(lineNumber / 4)), blocks.length - 1);
  const target = blocks[idx];
  if (target && typeof target.scrollIntoView === "function") {
    setTimeout(() => target.scrollIntoView({ behavior: "smooth", block: "center" }), 80);
  }
}

/* --- Recherche live --------------------------------------------------- */

function _highlightQuery(snippet, query) {
  if (!query) return escapeHtml(snippet);
  const q = String(query).trim();
  if (!q) return escapeHtml(snippet);
  // Echappe d'abord, puis surligne les occurrences case-insensitive.
  const escaped = escapeHtml(snippet);
  const safeQ = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(${safeQ})`, "gi");
  return escaped.replace(re, '<mark class="aide-search-highlight">$1</mark>');
}

function _renderSearchResults(container, results, query) {
  const dropdown = container.querySelector("[data-aide-search-results]");
  if (!dropdown) return;
  if (!results || results.length === 0) {
    if (!query || query.length < 2) {
      dropdown.hidden = true;
      dropdown.innerHTML = "";
      return;
    }
    dropdown.hidden = false;
    dropdown.innerHTML = `<p class="aide-search-empty">Aucun résultat pour "${escapeHtml(query)}".</p>`;
    return;
  }
  dropdown.hidden = false;
  const items = results.slice(0, 20).map((r, idx) => `
    <button type="button" class="aide-search-result" role="option"
            data-aide-result-idx="${idx}"
            data-aide-result-doc="${escapeHtml(r.doc_id || "")}"
            data-aide-result-line="${Number(r.line_number) || 0}">
      <span class="aide-search-result-title">${escapeHtml(r.title || r.doc_id || "")}</span>
      <span class="aide-search-result-snippet">${_highlightQuery(r.snippet || "", query)}</span>
      <span class="aide-search-result-meta">ligne ${Number(r.line_number) || "?"}</span>
    </button>
  `).join("");
  dropdown.innerHTML = items;

  // Bind clic
  dropdown.querySelectorAll(".aide-search-result").forEach((btn) => {
    btn.addEventListener("click", () => {
      const docId = btn.dataset.aideResultDoc;
      const lineNumber = Number(btn.dataset.aideResultLine) || 0;
      const title = btn.querySelector(".aide-search-result-title")?.textContent || docId;
      _openDocDrawer({
        id: `search-${docId}`,
        title,
        doc_id: docId,
        anchor: null,
        line_number: lineNumber,
      });
      dropdown.hidden = true;
    });
  });
}

async function _doLiveSearch(container, query) {
  if (!query || query.length < 2) {
    _renderSearchResults(container, [], query);
    return;
  }
  try {
    const res = await apiPost("runtime/search_docs", { query });
    const data = (res && res.data) || res || null;
    if (!data || data.ok === false) {
      _renderSearchResults(container, [], query);
      return;
    }
    _renderSearchResults(container, data.results || [], query);
  } catch (err) {
    console.warn("[aide] search_docs failed:", err);
    _renderSearchResults(container, [], query);
  }
}

/* --- Actions ----------------------------------------------------------- */

function _diagnosticToText(diagnostic) {
  if (!diagnostic) return "";
  const integ = diagnostic.integrations || {};
  const integLine = (name, key) => {
    const x = integ[key];
    if (!x) return `${name} : —`;
    const cfg = x.configured ? "configuré" : "non configuré";
    const ok = x.ok === true ? "OK" : x.ok === false ? "erreur" : "?";
    return `${name} : ${cfg}${x.configured ? ` / ${ok}` : ""}`;
  };
  const roots = Array.isArray(diagnostic.roots) ? diagnostic.roots : [];
  const lines = [
    `CineSort v${diagnostic.version || "?"}`,
    `Build : ${diagnostic.build_date || "—"}`,
    `Python : ${diagnostic.python_version || "?"}`,
    `Plateforme : ${diagnostic.platform || "?"}`,
    `DB schema : ${diagnostic.db_schema_version || "?"}`,
    `ffprobe : ${diagnostic.ffprobe_version || "non détecté"}`,
    `MediaInfo : ${diagnostic.mediainfo_version || "non détecté"}`,
    integLine("TMDb", "tmdb"),
    integLine("OMDb", "omdb"),
    integLine("Jellyfin", "jellyfin"),
    integLine("Plex", "plex"),
    integLine("Radarr", "radarr"),
    `Roots actifs : ${roots.length}`,
    ...roots.map((r) => `  - ${r}`),
    `Bibliothèque : ${diagnostic.lib_total != null ? `${diagnostic.lib_total} films · ${diagnostic.lib_scored || 0} classés` : "—"}`,
    `Dernier run : ${diagnostic.last_run_id ? `${diagnostic.last_run_id} (${diagnostic.last_run_status || "?"})` : "aucun"}`,
    `Log : ${diagnostic.log_path || "—"}`,
    `Settings : ${diagnostic.settings_path || "—"}`,
    `Timestamp : ${diagnostic.timestamp || "—"}`,
  ];
  return lines.join("\n");
}

async function _copyToClipboard(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_e) {
    // fallback ci-dessous
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    return true;
  } catch (_e2) {
    return false;
  }
}

function _setStatus(container, attr, message) {
  const el = container.querySelector(`[${attr}]`);
  if (el) {
    el.textContent = message || "";
    if (message) {
      setTimeout(() => {
        if (el.textContent === message) el.textContent = "";
      }, 3500);
    }
  }
}

function _openIssueWithDiagnostic(diagnostic) {
  const version = (diagnostic && diagnostic.version) || "unknown";
  const diagText = _diagnosticToText(diagnostic);
  const bodyTpl = [
    "## Bug rencontré",
    "",
    "<!-- Décrivez le bug ici. Étapes pour reproduire, comportement attendu vs constaté. -->",
    "",
    "## Diagnostic",
    "",
    "```",
    diagText,
    "```",
    "",
    "## Environnement",
    "",
    `- Version : ${version}`,
    "- OS : (Windows 10/11)",
    "- Navigateur / Dashboard : pywebview",
    "",
  ].join("\n");
  const title = `Bug CineSort v${version}`;
  const url = `${_GITHUB_ISSUES_URL}?title=${encodeURIComponent(title)}&body=${encodeURIComponent(bodyTpl)}`;
  try {
    window.open(url, "_blank", "noopener");
  } catch (_e) {
    window.location.href = url;
  }
}

/* --- Bindings ---------------------------------------------------------- */

function _bindEvents(container, diagnostic) {
  // Recherche live (debounce 300ms)
  const searchInput = container.querySelector("[data-aide-search]");
  if (searchInput) {
    searchInput.addEventListener("input", (ev) => {
      _searchQuery = String(ev.target.value || "");
      if (_searchDebounceId) clearTimeout(_searchDebounceId);
      _searchDebounceId = setTimeout(() => {
        _doLiveSearch(container, _searchQuery.trim());
      }, 300);
    });
    // Esc dans la barre -> ferme dropdown
    searchInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        const dd = container.querySelector("[data-aide-search-results]");
        if (dd) dd.hidden = true;
      }
    });
    // Click hors -> ferme dropdown
    document.addEventListener("click", (ev) => {
      const dd = container.querySelector("[data-aide-search-results]");
      if (!dd || dd.hidden) return;
      if (!container.querySelector(".aide-search").contains(ev.target)) {
        dd.hidden = true;
      }
    });
  }

  // Topics doc -> drawer markdown
  container.querySelectorAll("[data-aide-topic]").forEach((item) => {
    const handler = () => {
      const id = item.dataset.aideTopic;
      const topic = _DOC_TOPICS.find((t) => t.id === id);
      if (!topic) return;
      _openDocDrawer(topic);
    };
    item.addEventListener("click", handler);
    item.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        handler();
      }
    });
  });

  // Boutons d'action
  container.querySelectorAll("[data-aide-action]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const action = btn.dataset.aideAction;
      switch (action) {
        case "copy-diagnostic": {
          const text = _diagnosticToText(diagnostic || _lastDiagnostic);
          const ok = await _copyToClipboard(text);
          _setStatus(container, "data-aide-status", ok ? "✓ Diagnostic copié dans le presse-papier." : "✗ La copie a échoué.");
          break;
        }
        case "report-bug": {
          _openIssueWithDiagnostic(diagnostic || _lastDiagnostic);
          break;
        }
        case "open-logs": {
          try {
            const res = await apiPost("runtime/open_logs_folder", {});
            const data = (res && res.data) || res || null;
            if (data && data.ok !== false) {
              _setStatus(container, "data-aide-logs-status", "✓ Dossier des logs ouvert.");
            } else {
              _setStatus(container, "data-aide-logs-status", "✗ Impossible d'ouvrir le dossier des logs.");
            }
          } catch (err) {
            _setStatus(container, "data-aide-logs-status", "✗ Erreur : " + String(err && err.message ? err.message : err));
          }
          break;
        }
        case "copy-recent-logs": {
          try {
            const res = await apiPost("runtime/get_recent_logs", { limit: 100 });
            const data = (res && res.data) || res || null;
            if (!data || data.ok === false) {
              _setStatus(container, "data-aide-logs-status", "✗ Impossible de lire les logs.");
              break;
            }
            const lines = Array.isArray(data.lines) ? data.lines : [];
            const text = lines.join("\n");
            const ok = await _copyToClipboard(text);
            _setStatus(container, "data-aide-logs-status",
              ok ? `✓ ${lines.length} ligne(s) copiée(s) dans le presse-papier.` : "✗ La copie a échoué.");
          } catch (err) {
            _setStatus(container, "data-aide-logs-status", "✗ Erreur : " + String(err && err.message ? err.message : err));
          }
          break;
        }
        default:
          break;
      }
    });
  });
}

/* --- Entrypoint -------------------------------------------------------- */

function _renderLoading() {
  return `
    <section class="aide-view aide-view--loading" aria-busy="true">
      <div class="aide-header">
        <h1 class="aide-title">Aide</h1>
      </div>
      <div class="aide-section v5-skeleton aide-section-skel"></div>
    </section>
  `;
}

export async function initAide(container) {
  if (!container) return;
  container.innerHTML = _renderLoading();

  let diagnostic = null;
  try {
    diagnostic = await _fetchDiagnostic();
  } catch (err) {
    console.warn("[aide] init failed:", err);
  }
  _lastDiagnostic = diagnostic;

  container.innerHTML = _renderAide(diagnostic);
  _bindEvents(container, diagnostic);
}

export function unmountAide() {
  _searchQuery = "";
  if (_searchDebounceId) {
    clearTimeout(_searchDebounceId);
    _searchDebounceId = null;
  }
  _closeDrawer();
}

/* --- Exports pour tests ----------------------------------------------- */

export const _testables = {
  _renderMarkdown,
  _slugify,
  _renderInline,
  _diagnosticToText,
  _highlightQuery,
  _DOC_TOPICS,
  _SHORTCUTS,
};
