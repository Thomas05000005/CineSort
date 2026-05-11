(function(){
  const SUPPORTED_VIEWS = [
    { id: "home", label: "Accueil" },
    { id: "validation", label: "Validation" },
    { id: "execution", label: "Execution" },
    { id: "quality", label: "Qualite" },
    { id: "history", label: "Historique" },
    { id: "settings", label: "Reglages" },
  ];

  function normalizeView(view){
    const raw = String(view || "").trim().toLowerCase();
    const alias = {
      accueil: "home",
      home: "home",
      validation: "validation",
      validate: "validation",
      decisions: "validation",
      "décisions": "validation",
      "cas à revoir": "validation",
      "cas a revoir": "validation",
      review: "validation",
      execution: "execution",
      "exécution": "execution",
      apply: "execution",
      application: "execution",
      qualite: "quality",
      "qualité": "quality",
      quality: "quality",
      historique: "history",
      history: "history",
      logs: "history",
      journaux: "history",
      reglages: "settings",
      "réglages": "settings",
      parametres: "settings",
      "paramètres": "settings",
      settings: "settings",
      /* Legacy v1 aliases */
      dashboard: "quality",
      "vue du run": "quality",
      duplicates: "execution",
      conflits: "execution",
      plan: "home",
    };
    return alias[raw] || "home";
  }

  function updateUrl(params, replace){
    const url = new URL(window.location.href);
    Object.keys(params || {}).forEach((key) => {
      const value = params[key];
      if(value === undefined || value === null || String(value) === ""){
        url.searchParams.delete(key);
      } else {
        url.searchParams.set(key, String(value));
      }
    });
    if(replace){
      window.history.replaceState({}, "", url.toString());
      return;
    }
    window.location.assign(url.toString());
  }

  function copyUrl(button){
    const target = String(window.location.href || "");
    if(navigator.clipboard && typeof navigator.clipboard.writeText === "function"){
      navigator.clipboard.writeText(target).then(() => {
        if(button){
          button.textContent = "URL copiee";
          window.setTimeout(() => {
            button.textContent = "Copier URL";
          }, 1200);
        }
      }).catch(() => {});
    }
  }

  function mount(opts){
    const runtime = opts && opts.runtime ? opts.runtime : window.CineSortPreview;
    if(!runtime || document.getElementById("previewToolbar")){
      return;
    }

    const toolbar = document.createElement("div");
    toolbar.id = "previewToolbar";
    toolbar.className = "previewToolbar";
    const currentView = normalizeView(opts && opts.initialView || runtime.store.defaultView || "home");
    const scenarioMap = new Map((runtime.scenarios || []).map((entry) => [entry.id, entry]));
    const scenarioOptions = (runtime.scenarios || []).map((entry) => {
      const selected = entry.id === runtime.scenarioId ? " selected" : "";
      return `<option value="${entry.id}"${selected}>${entry.label}</option>`;
    }).join("");
    const viewOptions = SUPPORTED_VIEWS.map((entry) => {
      const selected = entry.id === currentView ? " selected" : "";
      return `<option value="${entry.id}"${selected}>${entry.label}</option>`;
    }).join("");
    toolbar.innerHTML = [
      '<div class="previewToolbarBadge">Preview UI</div>',
      '<div class="previewToolbarMeta">',
      `  <strong>${runtime.store.scenarioLabel}</strong>`,
      `  <span>${runtime.store.scenarioDescription}</span>`,
      "</div>",
      '<label class="previewToolbarField" for="previewScenarioSelect">',
      "  <span>Scenario</span>",
      `  <select id="previewScenarioSelect" class="select">${scenarioOptions}</select>`,
      "</label>",
      '<label class="previewToolbarField" for="previewViewSelect">',
      "  <span>Vue</span>",
      `  <select id="previewViewSelect" class="select">${viewOptions}</select>`,
      "</label>",
      '<button class="btn btn--ghost btn--compact" type="button" id="previewCopyUrl">Copier URL</button>',
      '<button class="btn btn--ghost btn--compact" type="button" id="previewResetPreview">Recharger scenario</button>',
    ].join("");
    document.body.prepend(toolbar);

    const scenarioSelect = document.getElementById("previewScenarioSelect");
    const viewSelect = document.getElementById("previewViewSelect");
    const copyButton = document.getElementById("previewCopyUrl");
    const resetButton = document.getElementById("previewResetPreview");

    scenarioSelect.addEventListener("change", () => {
      const selectedScenario = scenarioMap.get(String(scenarioSelect.value || ""));
      const defaultView = normalizeView(selectedScenario && selectedScenario.defaultView || "home");
      updateUrl({
        scenario: scenarioSelect.value,
        view: defaultView,
        preview: "1",
      }, false);
    });

    viewSelect.addEventListener("change", async () => {
      const nextView = normalizeView(viewSelect.value);
      updateUrl({ view: nextView, preview: "1" }, true);
      if(window.CineSortBridge && typeof window.CineSortBridge.navigateTo === "function"){
        await window.CineSortBridge.navigateTo(nextView);
      } else if(window.CineSortBridge && typeof window.CineSortBridge.showView === "function"){
        window.CineSortBridge.showView(nextView);
      }
    });

    copyButton.addEventListener("click", () => {
      copyUrl(copyButton);
    });

    resetButton.addEventListener("click", () => {
      window.location.reload();
    });

    window.setInterval(() => {
      if(!window.CineSortBridge || typeof window.CineSortBridge.getStateSnapshot !== "function"){
        return;
      }
      const snapshot = window.CineSortBridge.getStateSnapshot();
      const liveView = normalizeView(snapshot && snapshot.view || "home");
      if(viewSelect.value !== liveView){
        viewSelect.value = liveView;
        updateUrl({ view: liveView, preview: "1" }, true);
      }
    }, 400);
  }

  window.CineSortPreviewToolbar = {
    mount: mount,
    normalizeView: normalizeView,
  };
})();
