/* views/aide.js — Phase 3.5 (spec 12-aide.md) — Vue Aide refondue.
 *
 * 5 sections + recherche (spec 12 §1) :
 *  1. Documentation (FAQ + glossaire + topics — liens vers le guide)
 *  2. Raccourcis clavier (table statique alignee sur core/keyboard.js)
 *  3. Diagnostic (version, python, db schema, ffprobe, roots, lib total)
 *  4. Logs (bouton "Ouvrir dossier logs" + "Copier 100 dernieres lignes")
 *  5. A propos (licence, repo, changelog, contributeurs)
 *
 * Pour cette PR squelette, on cable les actions cote frontend mais on lit
 * les donnees disponibles via les endpoints existants (settings, server_info).
 * Les nouveaux endpoints (get_diagnostic, get_recent_logs, get_doc, search_docs)
 * seront ajoutes en PR backend separee.
 *
 * Pas d'inspecteur droit sur Aide (spec 12 §1).
 * Route cible : /aide (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { navigateTo } from "../core/router.js";

/* --- Donnees statiques (spec 12 §1) ------------------------------------ */

const _DOC_TOPICS = [
  { id: "premiers-pas", title: "Premiers pas", desc: "Guide rapide pour ton premier scan" },
  { id: "lancer-scan", title: "Comment lancer un scan", desc: "Configurer les roots + lancer l'analyse" },
  { id: "doublons", title: "Comment résoudre des doublons", desc: "Identifier et choisir le bon fichier" },
  { id: "tiers", title: "Comprendre les scores Bronze / Silver / Gold / Platinum", desc: "La grille de qualité v2" },
  { id: "omdb-tmdb", title: "Configurer OMDb et TMDb", desc: "Clés API + validation croisée" },
  { id: "apply-vs-dryrun", title: "Apply réel vs dry-run : différences", desc: "Tester avant de modifier sur disque" },
  { id: "undo", title: "Undo : comment annuler", desc: "Revenir en arrière sur un apply" },
  { id: "securite-torrents", title: "Sécurité torrents : pourquoi on ne modifie pas les titres", desc: "Préserver le seed" },
];

const _SHORTCUTS = [
  { keys: ["Ctrl", "K"], label: "Palette de commandes / Recherche globale" },
  { keys: ["Ctrl", "S"], label: "Lancer un nouveau scan" },
  { keys: ["Ctrl", "B"], label: "Replier ou déployer la sidebar" },
  { keys: ["Ctrl", "I"], label: "Afficher ou masquer l'inspecteur droit" },
  { keys: ["Ctrl", ","], label: "Aller à Paramètres" },
  { keys: ["Ctrl", "Z"], label: "Annuler le dernier apply (depuis Bibliothèque)" },
  { keys: ["Esc"], label: "Fermer modal / palette" },
  { keys: ["?"], label: "Afficher cette aide" },
  { keys: ["Alt", "1..7"], label: "Navigation directe (1=Accueil ... 7=Aide)" },
];

const _GITHUB_REPO_URL = "https://github.com/Thomas05000005/CineSort";
const _GITHUB_ISSUES_URL = "https://github.com/Thomas05000005/CineSort/issues/new";

/* --- Etat local --------------------------------------------------------- */

let _searchQuery = "";

/* --- Renderers ---------------------------------------------------------- */

function _renderHeader() {
  return `
    <header class="aide-header">
      <h1 class="aide-title">Aide</h1>
      <div class="aide-search">
        <input type="search" class="v5-input aide-search-input"
               placeholder="🔍 Rechercher dans la doc..."
               value="${escapeHtml(_searchQuery)}"
               data-aide-search>
      </div>
    </header>
  `;
}

function _renderDocSection() {
  const items = _DOC_TOPICS.map((t) => `
    <li class="aide-doc-item" tabindex="0" data-aide-topic="${escapeHtml(t.id)}">
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
      <p class="aide-section-intro">Sujets fréquents. La doc complète est en cours de rédaction (USER_GUIDE_v2.md, Phase 3.5).</p>
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

function _renderDiagnosticSection(diagnostic) {
  if (!diagnostic) {
    return `
      <section class="aide-section aide-diagnostic" aria-labelledby="aide-diagnostic-title">
        <h2 id="aide-diagnostic-title" class="aide-section-title">⚙ Diagnostic</h2>
        <p class="aide-empty-msg">Chargement du diagnostic...</p>
      </section>
    `;
  }
  const lines = [
    ["Version", diagnostic.version || "?"],
    ["Python", diagnostic.python_version || "?"],
    ["DB schema", diagnostic.db_schema_version != null ? `v${diagnostic.db_schema_version}` : "?"],
    ["ffprobe", diagnostic.ffprobe_path ? "✓ " + diagnostic.ffprobe_path : "non configuré"],
    ["MediaInfo", diagnostic.mediainfo_path ? "✓ " + diagnostic.mediainfo_path : "non configuré"],
    ["Roots actifs", Array.isArray(diagnostic.roots) ? `${diagnostic.roots.length} root(s)` : "0"],
    ["Bibliothèque", diagnostic.lib_total != null ? `${diagnostic.lib_total} films · ${diagnostic.lib_scored || 0} classés` : "—"],
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
        <a href="${_GITHUB_ISSUES_URL}" target="_blank" rel="noopener" class="v5-btn v5-btn--ghost">🐛 Signaler un bug</a>
      </div>
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
      <p class="aide-action-status" data-aide-status></p>
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

/* --- Diagnostic agreggation depuis endpoints existants ------------------ */

async function _fetchDiagnostic() {
  // Spec 12 §4 prevoit un endpoint dedie runtime/get_diagnostic. En attendant
  // sa creation backend, on agrege depuis les endpoints existants. Best-effort :
  // si un endpoint fail, on retourne partiel.
  const out = {
    version: null,
    python_version: null,
    db_schema_version: null,
    ffprobe_path: null,
    mediainfo_path: null,
    roots: [],
    lib_total: null,
    lib_scored: null,
  };
  try {
    const [serverInfo, settings, stats] = await Promise.all([
      apiPost("get_server_info", {}).catch(() => null),
      apiPost("settings/get_settings", {}).catch(() => null),
      apiPost("get_global_stats", {}).catch(() => null),
    ]);
    if (serverInfo && serverInfo.ok !== false) {
      const data = serverInfo.data || serverInfo;
      out.version = data.version || data.app_version || null;
      out.python_version = data.python_version || null;
      out.db_schema_version = data.db_schema_version != null ? data.db_schema_version : null;
    }
    if (settings && settings.ok !== false) {
      const data = settings.data || settings;
      out.ffprobe_path = data.ffprobe_path || null;
      out.mediainfo_path = data.mediainfo_path || null;
      out.roots = Array.isArray(data.roots) ? data.roots : [];
    }
    if (stats && stats.ok !== false) {
      const data = stats.data || stats;
      out.lib_total = (data.summary && data.summary.total_films) || null;
      out.lib_scored = data.total_scored || (data.v2_tier_distribution && data.v2_tier_distribution.scored_total) || null;
    }
  } catch (err) {
    console.warn("[aide] fetch diagnostic failed:", err);
  }
  return out;
}

/* --- Actions ------------------------------------------------------------ */

function _diagnosticToText(diagnostic) {
  if (!diagnostic) return "";
  const lines = [
    `CineSort v${diagnostic.version || "?"}`,
    `Python : ${diagnostic.python_version || "?"}`,
    `DB schema : v${diagnostic.db_schema_version != null ? diagnostic.db_schema_version : "?"}`,
    `ffprobe : ${diagnostic.ffprobe_path || "non configuré"}`,
    `MediaInfo : ${diagnostic.mediainfo_path || "non configuré"}`,
    `Roots : ${Array.isArray(diagnostic.roots) ? diagnostic.roots.length : 0} actif(s)`,
    `Bibliothèque : ${diagnostic.lib_total != null ? `${diagnostic.lib_total} films · ${diagnostic.lib_scored || 0} classés` : "—"}`,
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

function _setStatusMessage(container, message) {
  const el = container.querySelector("[data-aide-status]");
  if (el) {
    el.textContent = message || "";
    if (message) {
      setTimeout(() => {
        if (el.textContent === message) el.textContent = "";
      }, 3000);
    }
  }
}

function _bindEvents(container, diagnostic) {
  // Recherche (placeholder pour Phase future).
  const searchInput = container.querySelector("[data-aide-search]");
  if (searchInput) {
    searchInput.addEventListener("input", (ev) => {
      _searchQuery = String(ev.target.value || "");
    });
  }

  // Topics doc -> placeholder (la doc complete arrive en PR USER_GUIDE_v2).
  container.querySelectorAll("[data-aide-topic]").forEach((item) => {
    item.addEventListener("click", () => {
      _setStatusMessage(container, "La doc complète arrive bientôt (USER_GUIDE_v2.md).");
    });
  });

  // Boutons d'action
  container.querySelectorAll("[data-aide-action]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const action = btn.dataset.aideAction;
      switch (action) {
        case "copy-diagnostic": {
          const text = _diagnosticToText(diagnostic);
          const ok = await _copyToClipboard(text);
          _setStatusMessage(container, ok ? "✓ Diagnostic copié dans le presse-papier." : "✗ La copie a échoué.");
          break;
        }
        case "open-logs": {
          try {
            const res = await apiPost("open_logs_folder", {});
            if (res && res.ok !== false) {
              _setStatusMessage(container, "✓ Dossier des logs ouvert.");
            } else {
              _setStatusMessage(container, "✗ Impossible d'ouvrir le dossier des logs.");
            }
          } catch (err) {
            _setStatusMessage(container, "✗ Erreur : " + String(err && err.message ? err.message : err));
          }
          break;
        }
        case "copy-recent-logs": {
          // Endpoint runtime/get_recent_logs sera ajoute backend en PR future.
          _setStatusMessage(container, "Endpoint backend non encore disponible (à venir).");
          break;
        }
        default:
          break;
      }
    });
  });
}

/* --- Entrypoint --------------------------------------------------------- */

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

  container.innerHTML = _renderAide(diagnostic);
  _bindEvents(container, diagnostic);
}

export function unmountAide() {
  _searchQuery = "";
}
