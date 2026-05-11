/* views/about.js — Modale "A propos" supervision web (V1-12)
 *
 * Port ES module du desktop. Utilise showModal du dashboard pour rendre la modale.
 *
 * NOTE : les endpoints get_app_version / open_logs_dir n'existent pas (V1-12).
 * Fallback : version hardcoded + path logs affiche pour copie manuelle.
 */

import { showModal, closeModal } from "../components/modal.js";
import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";

const STYLE_ID = "aboutModalStyleDash";
const STYLE_CSS = `
  #dashModal .about-section { margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); }
  #dashModal .about-section:last-child { border-bottom: none; padding-bottom: 0; }
  #dashModal .about-section__title { margin: 0 0 8px 0; font-size: 0.85em; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--accent, #4DA3FF); }
  #dashModal .about-version { font-size: 1.05em; margin: 0; }
  #dashModal .about-privacy { display: flex; align-items: flex-start; gap: 8px; }
  #dashModal .about-privacy__badge { flex: 0 0 auto; padding: 2px 8px; border-radius: 999px; font-size: 0.75em; font-weight: 600; background: rgba(46, 204, 113, 0.15); color: #2ECC71; border: 1px solid rgba(46, 204, 113, 0.35); white-space: nowrap; }
  #dashModal .about-logs { margin-top: 8px; }
  #dashModal .about-logs__label { font-size: 0.85em; color: var(--text-muted, #9aa0a6); margin-bottom: 4px; }
  #dashModal .about-logs__path { display: block; padding: 6px 10px; background: rgba(0,0,0,0.25); border: 1px solid var(--border, rgba(255,255,255,0.08)); border-radius: 6px; font-family: var(--font-mono, "Cascadia Code", "Fira Code", Menlo, monospace); font-size: 0.85em; word-break: break-all; }
  #dashModal .about-logs__hint { margin-top: 6px; }
  #dashModal .about-deps { list-style: none; padding: 0; margin: 0 0 8px 0; }
  #dashModal .about-deps li { padding: 4px 0; }
`;

function _ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = STYLE_CSS;
  document.head.appendChild(style);
}

const PROJECT_GITHUB_URL = "https://github.com/PLACEHOLDER/cinesort";
const PROJECT_ISSUES_URL = `${PROJECT_GITHUB_URL}/issues`;
const FALLBACK_VERSION = "7.6.0-dev"; // TODO: remplacer par apiPost("get_app_version") une fois expose
const LOGS_PATH_HINT = "%LOCALAPPDATA%\\CineSort\\logs\\cinesort.log";
const DEPENDENCIES_TOP5 = [
  { name: "pywebview", license: "BSD-3-Clause", role: "interface graphique embarquee" },
  { name: "requests", license: "Apache-2.0", role: "client HTTP (TMDb, Jellyfin, Plex, Radarr)" },
  { name: "rapidfuzz", license: "MIT", role: "matching de titres flou" },
  { name: "segno", license: "BSD-3-Clause", role: "generation de QR codes" },
  { name: "onnxruntime", license: "MIT", role: "moteur ML LPIPS (analyse perceptuelle)" },
];

async function _readAppVersion() {
  // Tente d'appeler l'endpoint REST si jamais expose un jour.
  try {
    const res = await apiPost("get_app_version", {});
    if (res && typeof res === "object") {
      const v = res.version || res.app_version || res.value;
      if (typeof v === "string" && v.trim()) return v.trim();
    }
    if (typeof res === "string" && res.trim()) return res.trim();
  } catch (err) {
    console.warn("[about] get_app_version unavailable, using fallback", err);
  }
  return FALLBACK_VERSION;
}

function _depsHtml() {
  return DEPENDENCIES_TOP5.map((dep) => {
    return `<li><strong>${escapeHtml(dep.name)}</strong> <span class="text-muted font-sm">(${escapeHtml(dep.license)})</span> — ${escapeHtml(dep.role)}</li>`;
  }).join("");
}

function _bodyHtml(version) {
  const v = escapeHtml(version || FALLBACK_VERSION);
  const issuesHref = escapeHtml(PROJECT_ISSUES_URL);
  const repoHref = escapeHtml(PROJECT_GITHUB_URL);
  const logsPath = escapeHtml(LOGS_PATH_HINT);
  return `
    <section class="about-section">
      <h4 class="about-section__title">Version</h4>
      <p class="about-version" data-testid="about-version">CineSort <strong>${v}</strong></p>
    </section>

    <section class="about-section">
      <h4 class="about-section__title">Licence</h4>
      <p>Distribue sous <strong>licence MIT</strong>. Code libre, modifiable et redistribuable. <a href="${repoHref}" target="_blank" rel="noopener noreferrer">Voir le depot GitHub</a>.</p>
    </section>

    <section class="about-section">
      <h4 class="about-section__title">Confidentialite</h4>
      <p class="about-privacy">
        <span class="about-privacy__badge">No telemetry</span>
        <span>Aucune collecte, aucun tracking, aucun envoi a des tiers. <strong>100% local</strong>. Les seules connexions reseau sont celles que vous configurez : TMDb, Jellyfin/Plex/Radarr, et le serveur web local pour cette supervision a distance.</span>
      </p>
    </section>

    <section class="about-section">
      <h4 class="about-section__title">Support</h4>
      <p>Un bug ? Une suggestion ? <a href="${issuesHref}" target="_blank" rel="noopener noreferrer">Ouvrir une issue sur GitHub</a>.</p>
      <div class="about-logs">
        <div class="about-logs__label">Fichier de logs (sur la machine hote) :</div>
        <code class="about-logs__path" data-testid="about-logs-path">${logsPath}</code>
        <div class="flex gap-2 mt-2">
          <button class="btn btn--compact btn--ghost" id="aboutBtnCopyLogs" data-testid="about-btn-copy-logs" type="button">Copier le chemin</button>
        </div>
        <div class="about-logs__hint text-muted font-sm mt-1">En cas de probleme, copiez ce chemin et joignez le fichier au rapport de bug.</div>
      </div>
    </section>

    <section class="about-section">
      <h4 class="about-section__title">Composants tiers</h4>
      <ul class="about-deps">
        ${_depsHtml()}
      </ul>
      <p class="text-muted font-sm">Toutes les dependances sont sous licence permissive (MIT, BSD ou Apache-2.0).</p>
    </section>
  `;
}

function _hookCopyLogs() {
  const btn = document.getElementById("aboutBtnCopyLogs");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(LOGS_PATH_HINT);
      btn.textContent = "Copie !";
      setTimeout(() => { btn.textContent = "Copier le chemin"; }, 1500);
    } catch (err) {
      console.warn("[about] clipboard write failed", err);
      btn.textContent = "Echec copie";
      setTimeout(() => { btn.textContent = "Copier le chemin"; }, 1500);
    }
  });
}

/**
 * Ouvre la modale "A propos".
 * Exporte pour permettre l'attache du bouton depuis le shell HTML.
 */
export async function openAboutModal() {
  _ensureStyle();
  // Affiche d'abord avec la valeur de fallback pour ne pas bloquer
  showModal({
    title: "A propos de CineSort",
    body: _bodyHtml(FALLBACK_VERSION),
    actions: [
      { label: "Fermer", cls: "btn--primary", onClick: () => closeModal() },
    ],
  });
  _hookCopyLogs();
  // Puis raffraichit la version asynchrone
  const version = await _readAppVersion();
  if (version && version !== FALLBACK_VERSION) {
    const body = document.querySelector("#dashModal .modal-body");
    if (body) {
      body.innerHTML = _bodyHtml(version);
      _hookCopyLogs();
    }
  }
}

/**
 * Initialise les hooks click pour les boutons "A propos" presents dans le shell.
 * Ecoute aussi les futurs ajouts dynamiques.
 */
export function initAbout() {
  const ids = ["btnDashAbout", "linkDashAbout"];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el && !el.dataset.aboutHooked) {
      el.dataset.aboutHooked = "1";
      el.addEventListener("click", (e) => {
        e.preventDefault();
        openAboutModal();
      });
    }
  });
}

// Auto-init pour permettre l'usage sans modifier app.js
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAbout);
} else {
  initAbout();
}

// Expose globalement pour permettre invocation depuis onclick="..." si necessaire
window.openAboutModal = openAboutModal;
