/* views/about.js — Modale "A propos" desktop (V1-12)
 *
 * Version, licence MIT, privacy "no telemetry", support (GitHub + logs), credits.
 * Pattern IIFE expose window.AboutModal.{open, close, refresh}.
 *
 * NOTE : les endpoints get_app_version / open_logs_dir n'existent pas (V1-12).
 * Fallback : version hardcoded + path logs affiche pour copie manuelle.
 */

(function () {
  "use strict";

  const STYLE_ID = "aboutModalStyle";
  const STYLE_CSS = `
    #modalAbout .about-card { max-width: 640px; }
    #modalAbout .about-section { margin-bottom: var(--sp-4, 16px); padding-bottom: var(--sp-3, 12px); border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); }
    #modalAbout .about-section:last-child { border-bottom: none; padding-bottom: 0; }
    #modalAbout .about-section__title { margin: 0 0 var(--sp-2, 8px) 0; font-size: 0.85em; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--accent, #4DA3FF); }
    #modalAbout .about-version { font-size: 1.05em; margin: 0; }
    #modalAbout .about-privacy { display: flex; align-items: flex-start; gap: var(--sp-2, 8px); }
    #modalAbout .about-privacy__badge { flex: 0 0 auto; padding: 2px 8px; border-radius: 999px; font-size: 0.75em; font-weight: 600; background: rgba(46, 204, 113, 0.15); color: #2ECC71; border: 1px solid rgba(46, 204, 113, 0.35); white-space: nowrap; }
    #modalAbout .about-logs { margin-top: var(--sp-2, 8px); }
    #modalAbout .about-logs__label { font-size: 0.85em; color: var(--text-muted, #9aa0a6); margin-bottom: 4px; }
    #modalAbout .about-logs__path { display: block; padding: 6px 10px; background: rgba(0,0,0,0.25); border: 1px solid var(--border, rgba(255,255,255,0.08)); border-radius: 6px; font-family: var(--font-mono, "Cascadia Code", "Fira Code", Menlo, monospace); font-size: 0.85em; word-break: break-all; }
    #modalAbout .about-logs__hint { margin-top: 6px; }
    #modalAbout .about-deps { list-style: none; padding: 0; margin: 0 0 var(--sp-2, 8px) 0; }
    #modalAbout .about-deps li { padding: 4px 0; }
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
  const FALLBACK_VERSION = "7.6.0-dev"; // TODO: remplacer par window.pywebview.api.get_app_version() une fois expose
  const LOGS_PATH_HINT = "%LOCALAPPDATA%\\CineSort\\logs\\cinesort.log";
  const DEPENDENCIES_TOP5 = [
    { name: "pywebview", license: "BSD-3-Clause", role: "interface graphique embarquee" },
    { name: "requests", license: "Apache-2.0", role: "client HTTP (TMDb, Jellyfin, Plex, Radarr)" },
    { name: "rapidfuzz", license: "MIT", role: "matching de titres flou" },
    { name: "segno", license: "BSD-3-Clause", role: "generation de QR codes" },
    { name: "onnxruntime", license: "MIT", role: "moteur ML LPIPS (analyse perceptuelle)" },
  ];

  const MODAL_ID = "modalAbout";

  if (!window.AboutModal) window.AboutModal = {};

  function _esc(s) {
    if (window.escapeHtml) return window.escapeHtml(s);
    return String(s ?? "").replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  async function _readAppVersion() {
    // Tente d'appeler l'endpoint Python si jamais expose un jour.
    try {
      const api = (window.pywebview && window.pywebview.api) || null;
      if (api && typeof api.get_app_version === "function") {
        const v = await api.get_app_version();
        if (typeof v === "string" && v.trim()) return v.trim();
      }
    } catch (err) {
      console.warn("[about] get_app_version unavailable, using fallback", err);
    }
    return FALLBACK_VERSION;
  }

  function _depsHtml() {
    return DEPENDENCIES_TOP5.map((dep) => {
      return `<li><strong>${_esc(dep.name)}</strong> <span class="text-muted font-sm">(${_esc(dep.license)})</span> — ${_esc(dep.role)}</li>`;
    }).join("");
  }

  function _bodyHtml(version) {
    const v = _esc(version || FALLBACK_VERSION);
    const issuesHref = _esc(PROJECT_ISSUES_URL);
    const repoHref = _esc(PROJECT_GITHUB_URL);
    const logsPath = _esc(LOGS_PATH_HINT);
    return `
      <section class="about-section">
        <h4 class="about-section__title">Version</h4>
        <p class="about-version" data-testid="about-version">CineSort <strong>${v}</strong></p>
      </section>

      <section class="about-section">
        <h4 class="about-section__title">Licence</h4>
        <p>Distribue sous <strong>licence MIT</strong>. Vous pouvez copier, modifier et redistribuer ce logiciel librement. <a href="${repoHref}" target="_blank" rel="noopener noreferrer">Voir le depot GitHub</a>.</p>
      </section>

      <section class="about-section">
        <h4 class="about-section__title">Confidentialite</h4>
        <p class="about-privacy">
          <span class="about-privacy__badge">No telemetry</span>
          <span>Aucune collecte, aucun tracking, aucun envoi a des tiers. <strong>100% local</strong>. Les seules connexions reseau sont celles que vous configurez vous-meme : TMDb (recherche metadata), Jellyfin/Plex/Radarr (vos serveurs), et le serveur web local pour la supervision a distance.</span>
        </p>
      </section>

      <section class="about-section">
        <h4 class="about-section__title">Support</h4>
        <p>Un bug ? Une suggestion ? <a href="${issuesHref}" target="_blank" rel="noopener noreferrer">Ouvrir une issue sur GitHub</a>.</p>
        <div class="about-logs">
          <div class="about-logs__label">Fichier de logs :</div>
          <code class="about-logs__path" id="aboutLogsPath" data-testid="about-logs-path">${logsPath}</code>
          <div class="flex gap-2 mt-2">
            <button class="btn btn--compact btn--ghost" id="aboutBtnCopyLogs" data-testid="about-btn-copy-logs" type="button">Copier le chemin</button>
            <button class="btn btn--compact btn--ghost" id="aboutBtnOpenLogs" data-testid="about-btn-open-logs" type="button">Ouvrir le dossier</button>
          </div>
          <div class="about-logs__hint text-muted font-sm mt-1">En cas de probleme, joignez ce fichier a votre rapport de bug.</div>
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

  function _ensureMarkup() {
    _ensureStyle();
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement("div");
    modal.className = "modal hidden";
    modal.id = MODAL_ID;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "modalAboutTitle");
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML = `
      <div class="modal-card about-card">
        <div class="modal-header">
          <span class="modal-title" id="modalAboutTitle">A propos de CineSort</span>
          <button class="modal-close" data-close="${MODAL_ID}" aria-label="Fermer">&times;</button>
        </div>
        <div class="modal-body" id="aboutBody"></div>
        <div class="modal-footer">
          <button class="btn btn--primary" data-close="${MODAL_ID}" data-testid="about-btn-close">Fermer</button>
        </div>
      </div>`;
    document.body.appendChild(modal);

    // Hook fermeture (data-close declenche par le hook global dans app.js, mais on l'attache aussi
    // explicitement pour resister a un timing where about.js charge tard).
    modal.querySelectorAll("[data-close]").forEach((btn) => {
      btn.addEventListener("click", () => close());
    });
    modal.addEventListener("click", (e) => {
      if (e.target === modal) close();
    });
    return modal;
  }

  async function refresh() {
    const modal = _ensureMarkup();
    const body = modal.querySelector("#aboutBody");
    if (!body) return;
    const version = await _readAppVersion();
    body.innerHTML = _bodyHtml(version);
    _hookActions();
  }

  function _hookActions() {
    const btnCopy = document.getElementById("aboutBtnCopyLogs");
    if (btnCopy) {
      btnCopy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(LOGS_PATH_HINT);
          btnCopy.textContent = "Copie !";
          setTimeout(() => { btnCopy.textContent = "Copier le chemin"; }, 1500);
        } catch (err) {
          console.warn("[about] clipboard write failed", err);
          btnCopy.textContent = "Echec copie";
          setTimeout(() => { btnCopy.textContent = "Copier le chemin"; }, 1500);
        }
      });
    }
    const btnOpen = document.getElementById("aboutBtnOpenLogs");
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        // TODO V2 : utiliser window.pywebview.api.open_logs_dir() une fois l'endpoint Python expose.
        // Fallback : tente open_path sur le chemin LOGS resolu cote OS si dispo.
        try {
          const api = (window.pywebview && window.pywebview.api) || null;
          if (api && typeof api.open_path === "function") {
            // %LOCALAPPDATA% n'est pas resolu cote Python sans expansion, mais beaucoup de
            // systemes (Explorer) le resolvent. On essaie d'abord, fallback message si echec.
            const res = await api.open_path(LOGS_PATH_HINT);
            if (res && res.ok) return;
          }
        } catch (err) {
          console.warn("[about] open_path logs failed", err);
        }
        // Fallback : afficher une astuce
        btnOpen.textContent = "Copiez le chemin";
        setTimeout(() => { btnOpen.textContent = "Ouvrir le dossier"; }, 1800);
      });
    }
  }

  async function open() {
    const modal = _ensureMarkup();
    await refresh();
    if (typeof window.openModal === "function") {
      window.openModal(MODAL_ID);
    } else {
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }
  }

  function close() {
    const modal = document.getElementById(MODAL_ID);
    if (!modal) return;
    if (typeof window.closeModal === "function") {
      window.closeModal(MODAL_ID);
    } else {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }
  }

  function _hookFooterLink() {
    const link = document.getElementById("btnAbout");
    if (link && !link.dataset.aboutHooked) {
      link.dataset.aboutHooked = "1";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        open();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _hookFooterLink);
  } else {
    _hookFooterLink();
  }

  window.AboutModal.open = open;
  window.AboutModal.close = close;
  window.AboutModal.refresh = refresh;
})();
