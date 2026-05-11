(function(){
  function isPreviewMode(){
    const url = new URL(window.location.href);
    return url.searchParams.get("preview") === "1";
  }

  function setStoredText(key, value){
    try {
      if(value === undefined || value === null || String(value) === ""){
        window.localStorage.removeItem(key);
      } else {
        window.localStorage.setItem(key, String(value));
      }
    } catch(_err){
      // no-op
    }
  }

  function ensurePreviewStyles(){
    if(document.querySelector('link[data-preview-style="1"]')){
      return;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "./preview/preview.css";
    link.dataset.previewStyle = "1";
    document.head.appendChild(link);
  }

  if(!isPreviewMode()){
    return;
  }

  const params = new URL(window.location.href).searchParams;
  const scenarioId = String(params.get("scenario") || "");
  const runtime = window.CineSortPreviewApi.createRuntime({ scenarioId: scenarioId });
  const normalizeView = window.CineSortPreviewToolbar && typeof window.CineSortPreviewToolbar.normalizeView === "function"
    ? window.CineSortPreviewToolbar.normalizeView
    : function(value){ return String(value || "home"); };
  const requestedView = normalizeView(params.get("view") || runtime.store.defaultView || "home");

  window.CineSortPreview = runtime;
  window.pywebview = {
    api: runtime.api,
  };

  setStoredText("cinesort.lastRunId", runtime.store.activeRunId || "");
  setStoredText("cinesort.selectedRunId", runtime.store.activeRunId || "");
  setStoredText("cinesort.selectedRowId", "");
  setStoredText("cinesort.selectedTitle", "");
  setStoredText("cinesort.selectedYear", "");
  setStoredText("cinesort.selectedFolder", "");
  setStoredText("cinesort.advancedMode", "0");

  window.addEventListener("load", () => {
    document.documentElement.dataset.preview = "1";
    if(document.body){
      document.body.classList.add("previewMode");
    }
    ensurePreviewStyles();
    window.dispatchEvent(new Event("pywebviewready"));
  }, { once: true });

  window.addEventListener("cinesortready", async () => {
    if(document.body){
      document.body.classList.add("previewMode");
    }
    ensurePreviewStyles();
    if(window.CineSortPreviewToolbar && typeof window.CineSortPreviewToolbar.mount === "function"){
      window.CineSortPreviewToolbar.mount({
        runtime: runtime,
        initialView: requestedView,
      });
    }
    /* Navigate to the requested view using v2 bridge */
    if(window.CineSortBridge && typeof window.CineSortBridge.navigateTo === "function"){
      await window.CineSortBridge.navigateTo(requestedView);
    } else if(window.CineSortBridge && typeof window.CineSortBridge.showView === "function"){
      window.CineSortBridge.showView(requestedView);
    }
  }, { once: true });
})();
