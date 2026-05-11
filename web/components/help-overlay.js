/* components/help-overlay.js — Hints contextuels au long-press ? (H10)
 *
 * Registry par vue. Maintien de ? pendant 400 ms → projette des badges
 * violet a cote de chaque element interactif visible.
 */

(function () {
  const _HINTS = {
    home: [
      { selector: "#btnStartPlan", text: "Alt+1 · Scan" },
      { selector: "#btnLoadTable", text: "Apres scan" },
    ],
    validation: [
      { selector: "#btnCheckVisible", text: "Ctrl+A" },
      { selector: "#btnUncheckVisible", text: "" },
      { selector: "#btnFocusMode", text: "F · Focus" },
      { selector: "#btnSaveValidation", text: "Ctrl+S" },
    ],
    execution: [
      { selector: "#btnApply", text: "Apply" },
      { selector: "#ckDryRun", text: "Dry-run" },
    ],
    quality: [
      { selector: "#btnQualityAnalyze", text: "Analyser" },
    ],
    settings: [
      { selector: "#btnSaveSettings", text: "Ctrl+S" },
    ],
  };

  let _overlay = null;
  let _timer = null;
  let _pressed = false;

  function _projectHints() {
    const view = (window.state && window.state.view) || "home";
    const list = _HINTS[view] || [];
    _overlay = document.createElement("div");
    _overlay.className = "help-overlay";
    _overlay.setAttribute("aria-hidden", "true");
    document.body.appendChild(_overlay);

    let placed = 0;
    for (const h of list) {
      const target = document.querySelector(h.selector);
      if (!target) continue;
      const rect = target.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      const badge = document.createElement("div");
      badge.className = "help-hint";
      badge.textContent = h.text || h.selector;
      badge.style.left = `${Math.round(rect.left + rect.width / 2)}px`;
      badge.style.top = `${Math.round(rect.top - 8)}px`;
      _overlay.appendChild(badge);
      placed++;
    }
    if (placed === 0) {
      const tip = document.createElement("div");
      tip.className = "help-hint help-hint--center";
      tip.textContent = "Aucun raccourci contextuel pour cette vue.";
      _overlay.appendChild(tip);
    }
  }

  function _clear() {
    if (_overlay) _overlay.remove();
    _overlay = null;
    _timer = null;
    _pressed = false;
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "?" && !_pressed && !e.ctrlKey && !e.altKey) {
      const t = (document.activeElement?.tagName || "").toUpperCase();
      if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT") return;
      _pressed = true;
      _timer = setTimeout(_projectHints, 400);
    }
  });

  document.addEventListener("keyup", (e) => {
    if (e.key === "?") {
      if (_timer) clearTimeout(_timer);
      _clear();
    }
  });
})();
