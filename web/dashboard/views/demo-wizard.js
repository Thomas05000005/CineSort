/* V3-05 — Wizard mode démo (premier-run pour nouveaux utilisateurs).
 *
 * Affiche un overlay au tout premier lancement (pas de roots, pas de runs)
 * proposant de tester l'app avec 15 films fictifs. Une bannière persistante
 * rappelle que le mode démo est actif et permet d'en sortir.
 */

import { apiPost } from "../core/api.js";
import { navigateTo } from "../core/router.js";

const OVERLAY_ID = "demoWizardOverlay";
const BANNER_ID = "demoBanner";

/**
 * Affiche le wizard si premier-run et non déjà en mode démo.
 * @param {object} settings - payload de get_settings
 * @param {object} globalStats - payload de get_global_stats
 */
export async function showDemoWizardIfFirstRun(settings, globalStats) {
  const roots = (settings && (settings.roots || (settings.root ? [settings.root] : []))) || [];
  const noRoots = roots.length === 0;
  const summary = (globalStats && globalStats.summary) || {};
  const noRuns = !summary || Number(summary.total_runs || 0) === 0;
  if (!noRoots || !noRuns) return false;

  const res = await apiPost("is_demo_mode_active");
  if (res?.data?.active) return false;

  if (document.getElementById(OVERLAY_ID)) return false;
  _renderWizardOverlay();
  return true;
}

function _renderWizardOverlay() {
  const overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  overlay.className = "demo-wizard-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", "demoWizardTitle");
  overlay.innerHTML = `
    <div class="demo-wizard-card">
      <h2 id="demoWizardTitle">Bienvenue dans CineSort</h2>
      <p>Tu n'as pas encore configuré tes dossiers de films.</p>
      <p>Tu peux <strong>tester l'app avec 15 films fictifs</strong> pour explorer la bibliothèque, le scoring qualité et le dashboard sans rien toucher à tes vrais fichiers.</p>
      <div class="demo-wizard-actions">
        <button type="button" class="btn btn-primary" id="btnStartDemo">Tester avec 15 films démo</button>
        <button type="button" class="btn" id="btnSkipDemo">Configurer mes dossiers</button>
      </div>
      <p class="demo-wizard-note">Tu pourras désactiver le mode démo à tout moment depuis la bannière en haut de l'écran.</p>
    </div>
  `;
  document.body.appendChild(overlay);

  const btnStart = overlay.querySelector("#btnStartDemo");
  const btnSkip = overlay.querySelector("#btnSkipDemo");

  btnStart?.addEventListener("click", async () => {
    btnStart.disabled = true;
    btnStart.textContent = "Création...";
    try {
      const res = await apiPost("start_demo_mode");
      const payload = res?.data || {};
      if (payload.ok) {
        overlay.remove();
        await renderDemoBanner();
        navigateTo("/library");
      } else {
        btnStart.disabled = false;
        btnStart.textContent = "Tester avec 15 films démo";
        const msg = payload.error || payload.message || "Erreur inconnue";
        alert("Création du mode démo échouée : " + msg);
      }
    } catch (err) {
      btnStart.disabled = false;
      btnStart.textContent = "Tester avec 15 films démo";
      console.error("[demo-wizard] start_demo_mode", err);
      alert("Erreur réseau lors de la création du mode démo.");
    }
  });

  btnSkip?.addEventListener("click", () => {
    overlay.remove();
    navigateTo("/settings");
  });

  // Cf issue #92 quick win #10 : Esc ferme le wizard + toast info.
  // Power user heureux, alternative au flow lineaire impose.
  const escHandler = (e) => {
    if (e.key !== "Escape") return;
    if (!document.getElementById(OVERLAY_ID)) {
      document.removeEventListener("keydown", escHandler);
      return;
    }
    overlay.remove();
    document.removeEventListener("keydown", escHandler);
    if (typeof window.toast === "function") {
      window.toast({
        type: "info",
        text: "Wizard fermé. Vous pouvez configurer vos dossiers depuis Paramètres.",
        duration: 4000,
      });
    }
  };
  document.addEventListener("keydown", escHandler);
}

/**
 * Affiche la bannière persistante si le mode démo est actif.
 * Idempotent : ne crée pas de doublon.
 */
export async function renderDemoBanner() {
  const existing = document.getElementById(BANNER_ID);
  let active = false;
  try {
    const res = await apiPost("is_demo_mode_active");
    active = !!(res?.data?.active);
  } catch (err) {
    console.warn("[demo-wizard] is_demo_mode_active", err);
    return;
  }

  if (!active) {
    if (existing) existing.remove();
    document.body.classList.remove("demo-mode-active");
    return;
  }

  if (existing) return;

  const banner = document.createElement("div");
  banner.id = BANNER_ID;
  banner.className = "demo-banner";
  banner.setAttribute("role", "status");
  banner.innerHTML = `
    <span class="demo-banner__text">Mode démo actif — données fictives. Configure tes vrais dossiers dans <a href="#/settings">Paramètres</a>.</span>
    <button type="button" class="btn demo-banner__btn" id="btnStopDemo">Sortir du mode démo</button>
    <button type="button" class="demo-banner__close" id="btnDismissDemoBanner" aria-label="Masquer la banniere demo" title="Masquer (sans sortir du mode demo)">×</button>
  `;
  document.body.insertBefore(banner, document.body.firstChild);
  document.body.classList.add("demo-mode-active");

  // Cf issue #92 quick win #8 : bouton X qui masque le banner sans sortir du
  // mode demo (sortie evidente sans engagement). Le banner reapparait au
  // prochain init si toujours en mode demo.
  const btnDismiss = banner.querySelector("#btnDismissDemoBanner");
  btnDismiss?.addEventListener("click", () => {
    banner.remove();
    document.body.classList.remove("demo-mode-active");
  });

  const btnStop = banner.querySelector("#btnStopDemo");
  btnStop?.addEventListener("click", async () => {
    if (!confirm("Supprimer toutes les données démo ?")) return;
    btnStop.disabled = true;
    btnStop.textContent = "Suppression...";
    try {
      const res = await apiPost("stop_demo_mode");
      if (res?.data?.ok) {
        banner.remove();
        document.body.classList.remove("demo-mode-active");
        navigateTo("/status");
      } else {
        btnStop.disabled = false;
        btnStop.textContent = "Sortir du mode démo";
        alert("Suppression échouée : " + (res?.data?.error || "inconnue"));
      }
    } catch (err) {
      btnStop.disabled = false;
      btnStop.textContent = "Sortir du mode démo";
      console.error("[demo-wizard] stop_demo_mode", err);
      alert("Erreur réseau lors de la sortie du mode démo.");
    }
  });
}
