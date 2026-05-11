/* views/library.js — Hub workflow 5 etapes (parite dashboard).
 *
 * Non-destructif : cette vue est un point d'entree unifie qui oriente vers
 * les vues existantes (home, validation, execution). Elle affiche l'etat
 * courant de chaque etape (KPIs) et un bouton pour y acceder.
 *
 * libState est maintenu en synchro avec state global pour parite dashboard.
 */
(function () {
  "use strict";

  const libState = {
    advancedMode: false,
    activeStep: 1,
  };

  function _updateHeader() {
    const label = document.getElementById("libRunLabel");
    if (label) label.textContent = state.runId || "Aucun run";
  }

  function _fmtKpi(label, value, color) {
    const c = color || "var(--accent)";
    return `<div class="kpi" style="border-left-color:${c}">
      <div class="kpi__label">${label}</div>
      <div class="kpi__value">${value == null ? "—" : value}</div>
    </div>`;
  }

  async function _loadLibrary(opts) {
    opts = opts || {};
    _updateHeader();
    try {
      const dashRes = await apiCall("get_dashboard(library)", () => window.pywebview.api.get_dashboard("latest"), {
        silent: true,
      });
      const d = dashRes || {};
      const totals = d.totals || {};
      const dist = d.tier_distribution || {};
      const dup = d.duplicates_count || 0;
      const apply = d.last_apply || {};

      // 1. Analyse
      const rowsTotal = Number(totals.rows || 0);
      const scored = Number(totals.scored || 0);
      document.getElementById("libAnalyseKpis").innerHTML =
        _fmtKpi("Films detectes", rowsTotal) +
        _fmtKpi("Films scores", scored, "var(--gold)") +
        _fmtKpi("Statut", state.runId ? "En cours / termine" : "Pas de run", state.runId ? "var(--success)" : "var(--warning)");

      // 2. Verification (U1 audit : tiers modernes + fallback anciens)
      const platinum = Number(dist.platinum ?? dist.premium ?? 0);
      const gold = Number(dist.gold ?? dist.bon ?? 0);
      const silver = Number(dist.silver ?? dist.moyen ?? 0);
      const bronze = Number(dist.bronze ?? dist.faible ?? 0);
      const reject = Number(dist.reject ?? dist.mauvais ?? 0);
      const avgScore = Number(d.avg_score || 0);
      document.getElementById("libVerificationKpis").innerHTML =
        _fmtKpi("Score moyen", avgScore.toFixed(0), "var(--accent)") +
        _fmtKpi("Platinum", platinum, "var(--success)") +
        _fmtKpi("Gold / Silver", `${gold} / ${silver}`, "var(--info)") +
        _fmtKpi("Bronze / Reject", `${bronze} / ${reject}`, "var(--danger)");

      // 3. Validation
      const approved = Number((state.decisions && Object.values(state.decisions).filter(d => d === "approve").length) || 0);
      const rejected = Number((state.decisions && Object.values(state.decisions).filter(d => d === "reject").length) || 0);
      const pending = rowsTotal > 0 ? (rowsTotal - approved - rejected) : 0;
      document.getElementById("libValidationKpis").innerHTML =
        _fmtKpi("Approuves", approved, "var(--success)") +
        _fmtKpi("Rejetes", rejected, "var(--danger)") +
        _fmtKpi("En attente", pending > 0 ? pending : 0, "var(--warning)");

      // 4. Doublons
      document.getElementById("libDuplicatesKpis").innerHTML =
        _fmtKpi("Groupes detectes", dup, dup > 0 ? "var(--warning)" : "var(--success)");

      // 5. Application
      const done = Number(apply.done || 0);
      const total = Number(apply.total || 0);
      const canUndo = apply.can_undo ? "Oui" : "Non";
      document.getElementById("libApplyKpis").innerHTML =
        _fmtKpi("Applique", total > 0 ? `${done} / ${total}` : "0", "var(--accent)") +
        _fmtKpi("Dry-run strict", apply.dry_run ? "Oui" : "Non", apply.dry_run ? "var(--info)" : "var(--warning)") +
        _fmtKpi("Undo disponible", canUndo, canUndo === "Oui" ? "var(--success)" : "var(--neutral)");
    } catch (err) {
      console.warn("[library] loadLibrary error", err);
    }
  }

  function _hookEvents() {
    const host = document.getElementById("view-library");
    if (!host || host.dataset.hooked === "1") return;
    host.dataset.hooked = "1";

    // Steps scroll-to
    host.addEventListener("click", (ev) => {
      const step = ev.target.closest("[data-lib-step]");
      if (step) {
        const n = +step.dataset.libStep;
        libState.activeStep = n;
        document.querySelectorAll("#libWorkflowSteps .step").forEach(b => b.classList.toggle("active", +b.dataset.libStep === n));
        const sections = document.querySelectorAll("#view-library .lib-section");
        const target = sections[n - 1];
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      const goto = ev.target.closest("[data-lib-goto]");
      if (goto) {
        const view = goto.dataset.libGoto;
        if (typeof navigateTo === "function") navigateTo(view);
        else if (typeof showView === "function") showView(view);
      }
    });

    // Mode avance
    const ck = document.getElementById("ckLibAdvanced");
    if (ck) {
      ck.checked = !!state.advancedMode;
      ck.addEventListener("change", () => {
        libState.advancedMode = ck.checked;
        state.advancedMode = ck.checked;
        document.querySelectorAll(".lib-advanced").forEach(el => el.classList.toggle("hidden", !ck.checked));
      });
    }

    // Intersection observer pour actualiser le step actif au scroll
    const sections = host.querySelectorAll(".lib-section");
    if ("IntersectionObserver" in window && sections.length) {
      const obs = new IntersectionObserver((entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            const idx = Array.from(sections).indexOf(e.target) + 1;
            document.querySelectorAll("#libWorkflowSteps .step").forEach(b => b.classList.toggle("active", +b.dataset.libStep === idx));
          }
        }
      }, { threshold: 0.3 });
      sections.forEach(s => obs.observe(s));
    }
  }

  async function refreshLibraryView(opts) {
    _hookEvents();
    await _loadLibrary(opts || {});
  }

  window.refreshLibraryView = refreshLibraryView;
  window._libState = libState;
})();
