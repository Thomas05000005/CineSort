/* views/settings.js — Configuration + wizard */

async function loadSettings() {
  const s = await apiCall("get_settings", () => window.pywebview.api.get_settings(), {
    statusId: "saveMsg", fallbackMessage: "Impossible de charger les parametres.",
  });
  if (!s || s.ok === false) return;
  state.settings = s;

  /* Populate form fields */
  _renderRootsList(s.roots || (s.root ? [s.root] : []));
  if ($("inState")) $("inState").value = s.state_dir || "";
  if ($("ckTmdbEnabled")) $("ckTmdbEnabled").checked = !!s.tmdb_enabled;
  if ($("inTimeout")) $("inTimeout").value = s.tmdb_timeout_s || 10;
  if ($("inApiKey")) $("inApiKey").value = s.tmdb_api_key || "";
  if ($("ckRememberKey")) $("ckRememberKey").checked = !!s.remember_key;
  if ($("ckCollectionMove")) $("ckCollectionMove").checked = !!s.collection_folder_enabled;
  if ($("inCollectionFolderName")) $("inCollectionFolderName").value = s.collection_folder_name || "_Collection";
  if ($("inEmptyFoldersFolderName")) $("inEmptyFoldersFolderName").value = s.empty_folders_folder_name || "_Vide";
  if ($("ckMoveEmptyFoldersEnabled")) $("ckMoveEmptyFoldersEnabled").checked = !!s.move_empty_folders_enabled;
  if ($("inResidualCleanupFolderName")) $("inResidualCleanupFolderName").value = s.cleanup_residual_folders_folder_name || "_Dossier Nettoyage";
  if ($("ckResidualCleanupEnabled")) $("ckResidualCleanupEnabled").checked = !!s.cleanup_residual_folders_enabled;
  if ($("selResidualCleanupScope")) $("selResidualCleanupScope").value = (s.cleanup_residual_folders_scope === "root_all") ? "root_all" : "touched_only";
  if ($("ckResidualIncludeNfo")) $("ckResidualIncludeNfo").checked = !!s.cleanup_residual_include_nfo;
  if ($("ckResidualIncludeImages")) $("ckResidualIncludeImages").checked = !!s.cleanup_residual_include_images;
  if ($("ckResidualIncludeSubtitles")) $("ckResidualIncludeSubtitles").checked = !!s.cleanup_residual_include_subtitles;
  if ($("ckResidualIncludeTexts")) $("ckResidualIncludeTexts").checked = !!s.cleanup_residual_include_texts;
  if ($("ckIncrementalScanEnabled")) $("ckIncrementalScanEnabled").checked = !!s.incremental_scan_enabled;
  if ($("ckEnableTvDetection")) $("ckEnableTvDetection").checked = !!s.enable_tv_detection;
  if ($("ckSubtitleDetection")) $("ckSubtitleDetection").checked = s.subtitle_detection_enabled !== false;
  if ($("inSubtitleLangs")) $("inSubtitleLangs").value = (Array.isArray(s.subtitle_expected_languages) ? s.subtitle_expected_languages.join(", ") : s.subtitle_expected_languages || "fr");
  if ($("ckJellyfinEnabled")) $("ckJellyfinEnabled").checked = !!s.jellyfin_enabled;
  if ($("inJellyfinUrl")) $("inJellyfinUrl").value = s.jellyfin_url || "";
  if ($("inJellyfinApiKey")) $("inJellyfinApiKey").value = s.jellyfin_api_key || "";
  if ($("ckJellyfinRefreshOnApply")) $("ckJellyfinRefreshOnApply").checked = s.jellyfin_refresh_on_apply !== false;
  if ($("selEmptyFoldersScope")) $("selEmptyFoldersScope").value = (s.empty_folders_scope === "touched_only") ? "touched_only" : "root_all";
  if ($("ckDryRun")) $("ckDryRun").checked = !!s.dry_run_apply;
  if ($("ckQuarantine")) $("ckQuarantine").checked = !!s.quarantine_unapproved;
  if ($("ckAutoApproveEnabled")) $("ckAutoApproveEnabled").checked = !!s.auto_approve_enabled;
  if ($("inAutoApproveThreshold")) $("inAutoApproveThreshold").value = String(s.auto_approve_threshold || 85);
  if ($("autoApproveThresholdLabel")) $("autoApproveThresholdLabel").textContent = `${s.auto_approve_threshold || 85}%`;
  if ($("selProbeBackend")) $("selProbeBackend").value = String(s.probe_backend || "auto");
  if ($("inProbeFfprobePath")) $("inProbeFfprobePath").value = String(s.ffprobe_path || "");
  if ($("inProbeMediainfoPath")) $("inProbeMediainfoPath").value = String(s.mediainfo_path || "");
  if ($("inProbeTimeoutS")) $("inProbeTimeoutS").value = String(s.probe_timeout_s || 30);
  if ($("ckNotificationsEnabled")) $("ckNotificationsEnabled").checked = !!s.notifications_enabled;
  if ($("ckNotifScanDone")) $("ckNotifScanDone").checked = s.notifications_scan_done !== false;
  if ($("ckNotifApplyDone")) $("ckNotifApplyDone").checked = s.notifications_apply_done !== false;
  if ($("ckNotifUndoDone")) $("ckNotifUndoDone").checked = s.notifications_undo_done !== false;
  if ($("ckNotifErrors")) $("ckNotifErrors").checked = s.notifications_errors !== false;
  if ($("ckWatchEnabled")) $("ckWatchEnabled").checked = !!s.watch_enabled;
  if ($("watchInterval")) $("watchInterval").value = String(s.watch_interval_minutes || 5);
  if ($("ckEmailEnabled")) $("ckEmailEnabled").checked = !!s.email_enabled;
  if ($("inEmailSmtpHost")) $("inEmailSmtpHost").value = s.email_smtp_host || "";
  if ($("inEmailSmtpPort")) $("inEmailSmtpPort").value = String(s.email_smtp_port || 587);
  if ($("inEmailSmtpUser")) $("inEmailSmtpUser").value = s.email_smtp_user || "";
  if ($("inEmailSmtpPassword")) $("inEmailSmtpPassword").value = s.email_smtp_password || "";
  if ($("ckEmailSmtpTls")) $("ckEmailSmtpTls").checked = s.email_smtp_tls !== false;
  if ($("inEmailTo")) $("inEmailTo").value = s.email_to || "";
  if ($("ckEmailOnScan")) $("ckEmailOnScan").checked = s.email_on_scan !== false;
  if ($("ckEmailOnApply")) $("ckEmailOnApply").checked = s.email_on_apply !== false;
  if ($("ckPlexEnabled")) $("ckPlexEnabled").checked = !!s.plex_enabled;
  if ($("inPlexUrl")) $("inPlexUrl").value = s.plex_url || "";
  if ($("inPlexToken")) $("inPlexToken").value = s.plex_token || "";
  if ($("selPlexLibrary") && s.plex_library_id) { const o = document.createElement("option"); o.value = s.plex_library_id; o.textContent = s.plex_library_id; o.selected = true; $("selPlexLibrary").appendChild(o); }
  if ($("ckPlexRefreshOnApply")) $("ckPlexRefreshOnApply").checked = s.plex_refresh_on_apply !== false;
  if ($("ckRadarrEnabled")) $("ckRadarrEnabled").checked = !!s.radarr_enabled;
  if ($("inRadarrUrl")) $("inRadarrUrl").value = s.radarr_url || "";
  if ($("inRadarrApiKey")) $("inRadarrApiKey").value = s.radarr_api_key || "";
  if ($("ckPluginsEnabled")) $("ckPluginsEnabled").checked = !!s.plugins_enabled;
  if ($("pluginsTimeout")) $("pluginsTimeout").value = String(s.plugins_timeout_s || 30);
  if ($("ckRestApiEnabled")) $("ckRestApiEnabled").checked = !!s.rest_api_enabled;
  if ($("inRestApiPort")) $("inRestApiPort").value = String(s.rest_api_port || 8642);
  if ($("inRestApiToken")) $("inRestApiToken").value = s.rest_api_token || "";
  if ($("ckRestHttpsEnabled")) $("ckRestHttpsEnabled").checked = !!s.rest_api_https_enabled;
  if ($("inRestCertPath")) $("inRestCertPath").value = s.rest_api_cert_path || "";
  if ($("inRestKeyPath")) $("inRestKeyPath").value = s.rest_api_key_path || "";
  if ($("ckPerceptualEnabled")) $("ckPerceptualEnabled").checked = !!s.perceptual_enabled;
  if ($("ckPerceptualAutoOnScan")) $("ckPerceptualAutoOnScan").checked = !!s.perceptual_auto_on_scan;
  if ($("ckPerceptualAutoOnQuality")) $("ckPerceptualAutoOnQuality").checked = s.perceptual_auto_on_quality !== false;
  if ($("inPerceptualTimeout")) $("inPerceptualTimeout").value = String(s.perceptual_timeout_per_film_s || 120);
  if ($("inPerceptualFrames")) $("inPerceptualFrames").value = String(s.perceptual_frames_count || 10);
  if ($("inPerceptualSkip")) $("inPerceptualSkip").value = String(s.perceptual_skip_percent || 5);
  if ($("inPerceptualDarkWeight")) $("inPerceptualDarkWeight").value = String(s.perceptual_dark_weight || 1.5);
  if ($("ckPerceptualAudioDeep")) $("ckPerceptualAudioDeep").checked = s.perceptual_audio_deep !== false;
  if ($("inPerceptualAudioSegment")) $("inPerceptualAudioSegment").value = String(s.perceptual_audio_segment_s || 30);
  if ($("inPerceptualCompFrames")) $("inPerceptualCompFrames").value = String(s.perceptual_comparison_frames || 20);
  if ($("inPerceptualCompTimeout")) $("inPerceptualCompTimeout").value = String(s.perceptual_comparison_timeout_s || 600);
  _loadNamingPreset(s);
  // Apparence
  if ($("selTheme")) $("selTheme").value = s.theme || "studio";
  if ($("selAnimationLevel")) $("selAnimationLevel").value = s.animation_level || "moderate";
  if ($("rangeEffectSpeed")) { $("rangeEffectSpeed").value = String(s.effect_speed || 50); if ($("lblEffectSpeed")) $("lblEffectSpeed").textContent = String(s.effect_speed || 50); }
  if ($("rangeGlowIntensity")) { $("rangeGlowIntensity").value = String(s.glow_intensity || 30); if ($("lblGlowIntensity")) $("lblGlowIntensity").textContent = String(s.glow_intensity || 30); }
  if ($("rangeLightIntensity")) { $("rangeLightIntensity").value = String(s.light_intensity || 20); if ($("lblLightIntensity")) $("lblLightIntensity").textContent = String(s.light_intensity || 20); }
  _applyThemeLive(s);

  setStatusMessage("saveMsg", "");
}

/* --- Multi-root editor ---------------------------------- */

function _gatherRoots() {
  const items = document.querySelectorAll("#rootsList .root-item-input");
  const roots = [];
  items.forEach(inp => { const v = (inp.value || "").trim(); if (v) roots.push(v); });
  return roots;
}

function _renderRootsList(roots) {
  const container = $("rootsList");
  if (!container) return;
  container.innerHTML = "";
  (roots || []).forEach((r, i) => {
    const row = document.createElement("div");
    row.className = "root-item";
    row.innerHTML = `<input class="root-item-input" value="${escapeHtml(r)}" readonly title="${escapeHtml(r)}" aria-label="Dossier racine ${i + 1}: ${escapeHtml(r)}"><button class="btn btn-sm btn-danger root-remove-btn" data-idx="${i}" title="Supprimer" aria-label="Supprimer le dossier ${escapeHtml(r)}">&times;</button>`;
    container.appendChild(row);
  });
  // M5 : event delegation (un seul listener sur le container, attache une seule fois)
  if (!container.dataset.delegated) {
    container.dataset.delegated = "1";
    container.addEventListener("click", (e) => {
      const btn = e.target.closest(".root-remove-btn");
      if (!btn) return;
      const idx = parseInt(btn.dataset.idx, 10);
      const cur = _gatherRoots();
      cur.splice(idx, 1);
      _renderRootsList(cur);
    });
  }
}

function _addRoot() {
  const inp = $("inNewRoot");
  const val = (inp?.value || "").trim();
  if (!val) return;
  const cur = _gatherRoots();
  cur.push(val);
  _renderRootsList(cur);
  if (inp) inp.value = "";
}

function gatherSettingsFromForm() {
  const roots = _gatherRoots();
  return {
    root: roots[0] || "",
    roots: roots,
    state_dir: $("inState")?.value || "",
    tmdb_enabled: !!$("ckTmdbEnabled")?.checked,
    tmdb_timeout_s: parseFloat($("inTimeout")?.value || "10"),
    tmdb_api_key: $("inApiKey")?.value || "",
    remember_key: !!$("ckRememberKey")?.checked,
    collection_folder_enabled: !!$("ckCollectionMove")?.checked,
    collection_folder_name: $("inCollectionFolderName")?.value || "",
    empty_folders_folder_name: $("inEmptyFoldersFolderName")?.value || "",
    move_empty_folders_enabled: !!$("ckMoveEmptyFoldersEnabled")?.checked,
    cleanup_residual_folders_folder_name: $("inResidualCleanupFolderName")?.value || "",
    cleanup_residual_folders_enabled: !!$("ckResidualCleanupEnabled")?.checked,
    cleanup_residual_folders_scope: $("selResidualCleanupScope")?.value || "touched_only",
    cleanup_residual_include_nfo: !!$("ckResidualIncludeNfo")?.checked,
    cleanup_residual_include_images: !!$("ckResidualIncludeImages")?.checked,
    cleanup_residual_include_subtitles: !!$("ckResidualIncludeSubtitles")?.checked,
    cleanup_residual_include_texts: !!$("ckResidualIncludeTexts")?.checked,
    incremental_scan_enabled: !!$("ckIncrementalScanEnabled")?.checked,
    enable_tv_detection: !!$("ckEnableTvDetection")?.checked,
    subtitle_detection_enabled: !!$("ckSubtitleDetection")?.checked,
    subtitle_expected_languages: ($("inSubtitleLangs")?.value || "fr").split(",").map(s => s.trim()).filter(Boolean),
    jellyfin_enabled: !!$("ckJellyfinEnabled")?.checked,
    jellyfin_url: $("inJellyfinUrl")?.value || "",
    jellyfin_api_key: $("inJellyfinApiKey")?.value || "",
    jellyfin_refresh_on_apply: !!$("ckJellyfinRefreshOnApply")?.checked,
    empty_folders_scope: $("selEmptyFoldersScope")?.value || "root_all",
    quarantine_unapproved: !!$("ckQuarantine")?.checked,
    dry_run_apply: !!$("ckDryRun")?.checked,
    auto_approve_enabled: !!$("ckAutoApproveEnabled")?.checked,
    auto_approve_threshold: parseInt($("inAutoApproveThreshold")?.value || "85", 10) || 85,
    probe_backend: $("selProbeBackend")?.value || "auto",
    ffprobe_path: $("inProbeFfprobePath")?.value || "",
    mediainfo_path: $("inProbeMediainfoPath")?.value || "",
    probe_timeout_s: Math.max(5, Math.min(300, parseInt($("inProbeTimeoutS")?.value || "30", 10) || 30)),
    notifications_enabled: !!$("ckNotificationsEnabled")?.checked,
    notifications_scan_done: !!$("ckNotifScanDone")?.checked,
    notifications_apply_done: !!$("ckNotifApplyDone")?.checked,
    notifications_undo_done: !!$("ckNotifUndoDone")?.checked,
    notifications_errors: !!$("ckNotifErrors")?.checked,
    plex_enabled: !!$("ckPlexEnabled")?.checked,
    plex_url: $("inPlexUrl")?.value || "",
    plex_token: $("inPlexToken")?.value || "",
    plex_library_id: $("selPlexLibrary")?.value || "",
    plex_refresh_on_apply: !!$("ckPlexRefreshOnApply")?.checked,
    radarr_enabled: !!$("ckRadarrEnabled")?.checked,
    radarr_url: $("inRadarrUrl")?.value || "",
    radarr_api_key: $("inRadarrApiKey")?.value || "",
    watch_enabled: !!$("ckWatchEnabled")?.checked,
    watch_interval_minutes: parseInt($("watchInterval")?.value || "5", 10) || 5,
    email_enabled: !!$("ckEmailEnabled")?.checked,
    email_smtp_host: $("inEmailSmtpHost")?.value || "",
    email_smtp_port: parseInt($("inEmailSmtpPort")?.value || "587", 10) || 587,
    email_smtp_user: $("inEmailSmtpUser")?.value || "",
    email_smtp_password: $("inEmailSmtpPassword")?.value || "",
    email_smtp_tls: !!$("ckEmailSmtpTls")?.checked,
    email_to: $("inEmailTo")?.value || "",
    email_on_scan: !!$("ckEmailOnScan")?.checked,
    email_on_apply: !!$("ckEmailOnApply")?.checked,
    plugins_enabled: !!$("ckPluginsEnabled")?.checked,
    plugins_timeout_s: parseInt($("pluginsTimeout")?.value || "30", 10) || 30,
    rest_api_enabled: !!$("ckRestApiEnabled")?.checked,
    rest_api_port: parseInt($("inRestApiPort")?.value || "8642", 10) || 8642,
    rest_api_token: $("inRestApiToken")?.value || "",
    rest_api_https_enabled: !!$("ckRestHttpsEnabled")?.checked,
    rest_api_cert_path: $("inRestCertPath")?.value || "",
    rest_api_key_path: $("inRestKeyPath")?.value || "",
    perceptual_enabled: !!$("ckPerceptualEnabled")?.checked,
    perceptual_auto_on_scan: !!$("ckPerceptualAutoOnScan")?.checked,
    perceptual_auto_on_quality: !!$("ckPerceptualAutoOnQuality")?.checked,
    perceptual_timeout_per_film_s: parseInt($("inPerceptualTimeout")?.value || "120", 10) || 120,
    perceptual_frames_count: parseInt($("inPerceptualFrames")?.value || "10", 10) || 10,
    perceptual_skip_percent: parseInt($("inPerceptualSkip")?.value || "5", 10) || 5,
    perceptual_dark_weight: parseFloat($("inPerceptualDarkWeight")?.value || "1.5") || 1.5,
    perceptual_audio_deep: !!$("ckPerceptualAudioDeep")?.checked,
    perceptual_audio_segment_s: parseInt($("inPerceptualAudioSegment")?.value || "30", 10) || 30,
    perceptual_comparison_frames: parseInt($("inPerceptualCompFrames")?.value || "20", 10) || 20,
    perceptual_comparison_timeout_s: parseInt($("inPerceptualCompTimeout")?.value || "600", 10) || 600,
    naming_preset: $("selNamingPreset")?.value || "default",
    naming_movie_template: $("inNamingMovie")?.value || "{title} ({year})",
    naming_tv_template: $("inNamingTv")?.value || "{series} ({year})",
    // Apparence
    theme: $("selTheme")?.value || "studio",
    animation_level: $("selAnimationLevel")?.value || "moderate",
    effect_speed: parseInt($("rangeEffectSpeed")?.value || "50", 10) || 50,
    glow_intensity: parseInt($("rangeGlowIntensity")?.value || "30", 10) || 30,
    light_intensity: parseInt($("rangeLightIntensity")?.value || "20", 10) || 20,
  };
}

async function saveSettings(opts = {}) {
  console.log("[settings] save");
  const btn = $("btnSaveSettings");
  const previousStateDir = String(state.settings?.state_dir || "").trim();
  const settings = gatherSettingsFromForm();

  const r = await apiCall("save_settings", () => window.pywebview.api.save_settings(settings), {
    statusId: "saveMsg", fallbackMessage: "Erreur d'enregistrement.",
  });

  if (!opts.silent) {
    const msg = r?.ok ? "Réglages enregistrés." : `Erreur : ${r?.message || "enregistrement impossible."}`;
    setStatusMessage("saveMsg", msg, { error: !r?.ok, success: !!r?.ok, clearMs: 2500 });
    flashActionButton(btn, r?.ok ? "ok" : "error");
  }

  if (r?.ok) {
    const nextStateDir = String(r.state_dir || settings.state_dir || "").trim();
    state.settings = { ...(state.settings || {}), ...settings, state_dir: nextStateDir };
    if (previousStateDir && nextStateDir && previousStateDir !== nextStateDir) {
      clearRunCachesForStateDirChange();
    }
  }
  return r;
}

/* --- TMDb / Jellyfin tests --------------------------------- */

async function testKey() {
  const key = ($("inApiKey")?.value || "").trim();
  if (!key) { setStatusMessage("tmdbTestMsg", "Saisissez une cle.", { error: true }); return; }
  setStatusMessage("tmdbTestMsg", "Test en cours...", { loading: true });
  const sd = ($("inState")?.value || "").trim();
  const timeout = parseFloat($("inTimeout")?.value || "10");
  const r = await apiCall("test_tmdb_key", () => window.pywebview.api.test_tmdb_key(key, sd, timeout));
  state.tmdbLastTestOk = !!r?.ok;
  setStatusMessage("tmdbTestMsg", r?.ok ? "Connexion reussie" : `Cle invalide — ${r?.message || ""}`, {
    success: !!r?.ok, error: !r?.ok, clearMs: 4000,
  });
}

async function testJellyfinConnection() {
  const url = ($("inJellyfinUrl")?.value || "").trim();
  const key = ($("inJellyfinApiKey")?.value || "").trim();
  if (!url || !key) { setStatusMessage("jellyfinTestMsg", "URL et cle requises.", { error: true }); return; }
  setStatusMessage("jellyfinTestMsg", "Test en cours...", { loading: true });
  const r = await apiCall("test_jellyfin", () => window.pywebview.api.test_jellyfin_connection(url, key, 10.0));
  setStatusMessage("jellyfinTestMsg", r?.ok ? "Connexion reussie" : `Echec — ${r?.message || ""}`, {
    success: !!r?.ok, error: !r?.ok, clearMs: 4000,
  });
}

/* --- Wizard ------------------------------------------------ */

let wizardStep = 1;

function wizShowStep(n) {
  wizardStep = n;
  for (let i = 1; i <= 5; i++) {
    const el = $(`wizStep${i}`);
    if (el) el.classList.toggle("active", i === n);
    const dot = document.querySelector(`.wizard-dot[data-step="${i}"]`);
    if (dot) { dot.classList.toggle("active", i === n); dot.classList.toggle("done", i < n); }
  }
}

async function wizValidateRoot() {
  const root = ($("wizRoot")?.value || "").trim();
  const fb = $("wizRootFeedback");
  const btn = $("wizBtn2Next");
  if (!root) { if (fb) fb.textContent = "Saisissez le chemin."; if (btn) btn.disabled = true; return; }
  if (fb) fb.textContent = "Verification...";
  const sd = ($("inState")?.value || "").trim() || undefined;
  const r = await apiCall("wiz_validate", () => window.pywebview.api.save_settings({ root, state_dir: sd, onboarding_completed: false }));
  if (r?.ok) {
    if (fb) fb.textContent = `Dossier valide : ${root}`;
    if (btn) btn.disabled = false;
    if ($("inRoot")) $("inRoot").value = root;
  } else {
    if (fb) fb.textContent = r?.message || "Dossier invalide.";
    if (btn) btn.disabled = true;
  }
}

async function wizTestTmdb() {
  const key = ($("wizTmdbKey")?.value || "").trim();
  const status = $("wizTmdbStatus");
  if (!key) { if (status) status.textContent = "Saisissez une cle."; return; }
  if (status) status.textContent = "Test en cours...";
  const sd = ($("inState")?.value || "").trim();
  const r = await apiCall("wiz_tmdb", () => window.pywebview.api.test_tmdb_key(key, sd, 10));
  if (r?.ok) {
    if (status) { status.textContent = "Connexion reussie"; status.className = "status-msg isSuccess"; }
    if ($("inApiKey")) $("inApiKey").value = key;
    if ($("ckTmdbEnabled")) $("ckTmdbEnabled").checked = true;
  } else {
    if (status) { status.textContent = `Cle invalide — ${r?.message || ""}`; status.className = "status-msg isError"; }
  }
}

async function wizRunQuickTest() {
  const root = ($("wizRoot")?.value || "").trim();
  const status = $("wizTestStatus");
  const results = $("wizTestResults");
  if (!root) { if (status) status.textContent = "Configurez d'abord le dossier."; return; }
  if (status) status.textContent = "Analyse rapide...";
  if (results) results.textContent = "Recherche de films...";

  const key = ($("wizTmdbKey")?.value || "").trim();
  const settings = {
    root,
    state_dir: ($("inState")?.value || "").trim() || undefined,
    tmdb_enabled: !!key, tmdb_api_key: key,
    collection_folder_enabled: true, incremental_scan_enabled: false,
  };
  const start = await apiCall("wiz_start", () => window.pywebview.api.start_plan(settings));
  if (!start?.ok) { if (status) status.textContent = "Erreur : " + (start?.message || ""); return; }
  const rid = start.run_id;
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 400));
    const s = await apiCall("wiz_poll", () => window.pywebview.api.get_status(rid, 0));
    if (s?.done) break;
  }
  const plan = await apiCall("wiz_plan", () => window.pywebview.api.get_plan(rid));
  if (!plan?.ok || !plan.rows?.length) {
    if (status) status.textContent = "Aucun film détecté.";
    if (results) results.textContent = "Verifiez que le dossier contient des fichiers video.";
    return;
  }
  const sample = plan.rows.slice(0, 5);
  const lines = sample.map((r, i) => `${i + 1}. ${r.proposed_title || "?"} (${r.proposed_year || "?"}) — ${r.confidence_label || "?"}, ${r.proposed_source || "?"}`);
  if (plan.rows.length > 5) lines.push(`... et ${plan.rows.length - 5} autres.`);
  if (results) results.textContent = lines.join("\n");
  if (status) status.textContent = `${plan.rows.length} film(s) détecté(s).`;
}

function wizBuildSummary() {
  const root = ($("wizRoot")?.value || "").trim();
  const key = ($("wizTmdbKey")?.value || "").trim();
  if ($("wizSummary")) {
    $("wizSummary").textContent = `Dossier : ${root || "non configuré"}\nTMDb : ${key ? "configuré" : "non configuré"}`;
  }
}

async function wizFinish(launchScan) {
  const key = ($("wizTmdbKey")?.value || "").trim();
  await apiCall("save_onboarding", () => window.pywebview.api.save_settings({
    root: ($("wizRoot")?.value || "").trim(),
    state_dir: ($("inState")?.value || "").trim() || undefined,
    tmdb_enabled: !!key, tmdb_api_key: key, remember_key: !!key,
    onboarding_completed: true,
  }));
  closeModal("wizardModal");
  await loadSettings();
  if (launchScan) await startPlan();
}

async function maybeShowWizard() {
  if (!state.settings) return;
  const completed = !!state.settings.onboarding_completed;
  const hasRoot = !!(state.settings.root && String(state.settings.root).trim());
  if (completed || hasRoot) return;
  openModal("wizardModal");
  wizShowStep(1);
}

function hookWizardEvents() {
  $("wizBtnStart")?.addEventListener("click", () => wizShowStep(2));
  $("wizBtn2Prev")?.addEventListener("click", () => wizShowStep(1));
  $("wizBtn2Next")?.addEventListener("click", () => wizShowStep(3));
  $("wizBtn3Prev")?.addEventListener("click", () => wizShowStep(2));
  $("wizBtn3Next")?.addEventListener("click", () => wizShowStep(4));
  $("wizBtn4Prev")?.addEventListener("click", () => wizShowStep(3));
  $("wizBtn4Next")?.addEventListener("click", () => { wizBuildSummary(); wizShowStep(5); });
  $("wizBtnSkipTest")?.addEventListener("click", () => { wizBuildSummary(); wizShowStep(5); });
  $("wizBtnRunTest")?.addEventListener("click", wizRunQuickTest);
  $("wizBtnTestTmdb")?.addEventListener("click", wizTestTmdb);
  $("wizBtnFinish")?.addEventListener("click", () => wizFinish(true));
  $("wizBtnClose")?.addEventListener("click", () => wizFinish(false));
  $("wizRoot")?.addEventListener("input", wizValidateRoot);
}

/* --- Auto-save discret (E5) ----------------------------------
 * Marquage "Modifications non enregistrees" + sauvegarde apres
 * 1.2 s d'inactivite sur n'importe quel champ du formulaire settings.
 * Toggleable via flag local _autoSaveEnabled (defaut true).
 */
let _autoSaveTimer = null;
let _autoSaveDirty = false;
let _autoSaveEnabled = true;

function _markDirty() {
  if (!_autoSaveEnabled) return;
  _autoSaveDirty = true;
  const indicator = $("settingsDirtyIndicator");
  if (indicator) indicator.classList.add("is-visible");
  clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(_autoSaveFlush, 1200);
}

async function _autoSaveFlush() {
  if (!_autoSaveDirty) return;
  _autoSaveDirty = false;
  const indicator = $("settingsDirtyIndicator");
  if (indicator) indicator.classList.add("is-saving");
  try {
    await saveSettings({ silent: true });
    if (indicator) {
      indicator.classList.remove("is-visible", "is-saving");
      if (typeof toast === "function") toast({ type: "info", text: "Réglages sauvegardés automatiquement.", duration: 1800 });
    }
  } catch (e) {
    if (indicator) indicator.classList.remove("is-saving");
    console.error("[autosave]", e);
  }
}

function _hookAutoSave() {
  const view = $("view-settings");
  if (!view) return;
  view.addEventListener("input", _markDirty);
  view.addEventListener("change", _markDirty);
}

/* --- P4.3 : Export / Import profil qualité ---------------- */

async function _exportQualityProfile() {
  const name = $("inProfileExchangeName")?.value || "";
  const desc = $("inProfileExchangeDesc")?.value || "";
  const msg = $("profileExchangeMsg");
  if (msg) { msg.textContent = "Export en cours..."; msg.className = "status-msg isLoading"; }
  const r = await apiCall("export_shareable_profile", () => window.pywebview.api.export_shareable_profile(name, "", desc), {
    fallbackMessage: "Export impossible.",
  });
  if (!r?.ok) {
    if (msg) { msg.textContent = r?.message || "Erreur"; msg.className = "status-msg isError"; }
    return;
  }
  const blob = new Blob([r.content], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = r.filename_suggestion || "cinesort_profile.cinesort.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  if (msg) { msg.textContent = `Profil exporté (${r.filename_suggestion}).`; msg.className = "status-msg isSuccess"; }
}

/* --- P4.1 : Rapport de calibration --------------------------- */

function _fmtStrength(s) {
  const m = { "none": "aucun", "weak": "faible", "moderate": "modéré", "strong": "marqué" };
  return m[s] || s || "?";
}

function _fmtDirection(d) {
  const m = { "neutral": "équilibré", "underscore": "système sous-évalue", "overscore": "système sur-évalue" };
  return m[d] || d || "?";
}

async function _showCalibrationReport() {
  const container = $("calibrationReportContent");
  if (!container) return;
  container.innerHTML = '<div class="text-secondary font-sm">Chargement du rapport...</div>';
  const r = await apiCall("get_calibration_report", () => window.pywebview.api.get_calibration_report(), {
    fallbackMessage: "Rapport indisponible.",
  });
  if (!r?.ok) {
    container.innerHTML = `<div class="font-sm" style="color:#EF4444">${escapeHtml(r?.message || "Erreur de chargement.")}</div>`;
    return;
  }
  const bias = r.bias || {};
  const suggestion = r.suggestion;
  const current = r.current_weights || {};
  const total = Number(bias.total_feedbacks || 0);

  if (total === 0) {
    container.innerHTML = '<div class="card font-sm" style="padding:.75em"><div class="text-muted">Aucun feedback enregistré pour le moment. Utilisez le bouton "Ce score vous semble-t-il juste ?" dans la modale de détail du score d\'un film pour commencer à calibrer votre profil.</div></div>';
    return;
  }

  const directionColor = bias.bias_direction === "underscore" ? "#34D399" : bias.bias_direction === "overscore" ? "#F59E0B" : "var(--text-muted)";
  let html = `<div class="card" style="padding:.75em">
    <div class="card__eyebrow">Rapport de calibration (${total} feedback${total > 1 ? "s" : ""})</div>
    <div class="font-sm" style="line-height:1.6">
      <div><strong>Accord global</strong> : ${bias.accord_pct ?? "?"}%</div>
      <div><strong>Biais détecté</strong> : <span style="color:${directionColor}; font-weight:600">${escapeHtml(_fmtDirection(bias.bias_direction))}</span> (intensité : ${escapeHtml(_fmtStrength(bias.bias_strength))})</div>
      <div><strong>Delta moyen</strong> : ${bias.mean_delta >= 0 ? "+" : ""}${bias.mean_delta || 0} tier(s)</div>
    </div>
    <div class="font-xs text-muted mt-2">
      Catégories pointées : vidéo ${bias.category_bias?.video || 0}, audio ${bias.category_bias?.audio || 0}, extras ${bias.category_bias?.extras || 0}
    </div>`;

  if (suggestion) {
    const from = suggestion.from || {};
    const to = suggestion.to || {};
    html += `<hr style="border:0; border-top:1px solid var(--border); margin:.7em 0">
    <div class="card__eyebrow">Suggestion d'ajustement</div>
    <div class="font-sm mb-2">${escapeHtml(suggestion.rationale || "")}</div>
    <div class="mono font-xs text-muted">
      Vidéo: ${from.video || 0} → <strong style="color:var(--accent)">${to.video || 0}</strong><br>
      Audio: ${from.audio || 0} → <strong style="color:var(--accent)">${to.audio || 0}</strong><br>
      Extras: ${from.extras || 0} → <strong style="color:var(--accent)">${to.extras || 0}</strong>
    </div>
    <p class="font-xs text-muted mt-2">L'application d'une suggestion modifie le profil actif. Les recommandations sont indicatives — ajustez manuellement via les poids du profil si besoin.</p>`;
  } else {
    html += `<div class="font-sm mt-2 text-muted">Biais trop faible pour une suggestion d'ajustement automatique. Continuez à donner des feedbacks pour affiner.</div>`;
  }
  html += '</div>';
  container.innerHTML = html;
}

async function _importQualityProfileFromFile(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const msg = $("profileExchangeMsg");
  if (msg) { msg.textContent = "Lecture du fichier..."; msg.className = "status-msg isLoading"; }
  try {
    const content = await file.text();
    // Confirmation utilisateur — import écrase le profil actif
    const proceed = typeof uiConfirm === "function"
      ? await uiConfirm({
          title: "Importer un profil qualité",
          text: `Le profil importé depuis "${file.name}" deviendra le profil actif. Le profil actuel sera conservé en historique. Continuer ?`,
          confirmLabel: "Importer et activer",
        })
      : window.confirm(`Importer "${file.name}" et l'activer ?`);
    if (!proceed) {
      if (msg) { msg.textContent = "Import annulé."; msg.className = "status-msg"; }
      e.target.value = "";
      return;
    }
    const r = await apiCall("import_shareable_profile", () => window.pywebview.api.import_shareable_profile(content, true), {
      fallbackMessage: "Import impossible.",
    });
    if (!r?.ok) {
      const metaInfo = r?.meta?.name ? ` (profil "${r.meta.name}")` : "";
      if (msg) { msg.textContent = (r?.message || "Erreur") + metaInfo; msg.className = "status-msg isError"; }
    } else {
      const author = r?.meta?.author ? ` par ${r.meta.author}` : "";
      if (msg) { msg.textContent = `Profil importé et activé : "${r.meta?.name || "(sans nom)"}" ${author}.`; msg.className = "status-msg isSuccess"; }
    }
  } catch (err) {
    if (msg) { msg.textContent = "Erreur de lecture : " + err; msg.className = "status-msg isError"; }
  } finally {
    e.target.value = "";
  }
}

function hookSettingsEvents() {
  $("btnSaveSettings")?.addEventListener("click", () => saveSettings());
  _hookAutoSave();

  // P4.3 : Export / Import profil qualité
  $("btnExportQualityProfile")?.addEventListener("click", _exportQualityProfile);
  $("btnImportQualityProfile")?.addEventListener("click", () => $("fileImportQualityProfile")?.click());
  $("fileImportQualityProfile")?.addEventListener("change", _importQualityProfileFromFile);
  // P4.1 : Rapport de calibration
  $("btnShowCalibration")?.addEventListener("click", _showCalibrationReport);

  $("btnAddRoot")?.addEventListener("click", _addRoot);
  $("inNewRoot")?.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); _addRoot(); } });
  $("btnTestKey")?.addEventListener("click", testKey);
  $("btnTestJellyfin")?.addEventListener("click", testJellyfinConnection);
  $("btnRevealKey")?.addEventListener("click", () => {
    const inp = $("inApiKey");
    if (inp) inp.type = inp.type === "password" ? "text" : "password";
  });
  $("inAutoApproveThreshold")?.addEventListener("input", () => {
    if ($("autoApproveThresholdLabel")) $("autoApproveThresholdLabel").textContent = `${$("inAutoApproveThreshold").value}%`;
  });
  $("btnRevealRestToken")?.addEventListener("click", () => {
    const inp = $("inRestApiToken");
    if (inp) inp.type = inp.type === "password" ? "text" : "password";
  });
  // BUG 1 : bouton copier le token dans le presse-papier
  $("btnCopyRestToken")?.addEventListener("click", async () => {
    const inp = $("inRestApiToken");
    const msg = $("restTokenMsg");
    if (!inp) return;
    const val = inp.value || "";
    if (!val) {
      if (msg) { msg.textContent = "Aucune cle a copier."; msg.className = "status-msg isError"; }
      return;
    }
    const ok = copyTextSafe(val);
    if (msg) {
      if (ok) { msg.textContent = "Cle d'acces copiee."; msg.className = "status-msg isSuccess"; }
      else { msg.textContent = "Impossible de copier (clipboard indisponible)."; msg.className = "status-msg isError"; }
    }
  });
  // Bouton regenerer la cle d'acces (cote client, sauvegarde a l'Enregistrer)
  $("btnRegenRestToken")?.addEventListener("click", () => {
    const inp = $("inRestApiToken");
    const msg = $("restTokenMsg");
    if (!inp) return;
    const bytes = new Uint8Array(24);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    const b64 = btoa(String.fromCharCode.apply(null, bytes))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    inp.value = b64;
    inp.type = "text";
    if (msg) { msg.textContent = "Nouvelle cle d'acces generee. N'oubliez pas d'enregistrer."; msg.className = "status-msg isSuccess"; }
  });
  $("btnRestartApi")?.addEventListener("click", async () => {
    const msg = $("restartApiMsg");
    if (msg) msg.textContent = "Redémarrage...";
    try {
      const r = await apiCall("restart_api_server", () => window.pywebview.api.restart_api_server());
      if (r?.ok) {
        if (msg) msg.textContent = "Service API redemarre.";
        _refreshDashboardUrl(r.dashboard_url);
      } else {
        if (msg) msg.textContent = r?.message || "Echec.";
      }
    } catch (err) { if (msg) msg.textContent = "Erreur : " + err; }
  });
  $("btnTestEmail")?.addEventListener("click", async () => {
    const msg = $("msgTestEmail");
    if (msg) { msg.textContent = "Envoi en cours..."; msg.className = "field-hint"; }
    try {
      const r = await apiCall("test_email_report", () => window.pywebview.api.test_email_report());
      if (r?.ok) {
        if (msg) { msg.textContent = "Email envoye avec succes."; msg.className = "status-msg isSuccess"; }
      } else {
        if (msg) { msg.textContent = "Echec : " + (r?.message || "verifiez SMTP."); msg.className = "status-msg isError"; }
      }
    } catch (err) { if (msg) { msg.textContent = "Erreur : " + err; msg.className = "status-msg isError"; } }
  });
  $("btnCopyDashUrl")?.addEventListener("click", () => {
    const url = $("restDashboardUrl")?.textContent || "";
    if (url && navigator.clipboard) {
      navigator.clipboard.writeText(url).then(
        () => setStatusMessage("settingsMsg", "Lien copie !", { success: true, clearMs: 2000 }),
        () => setStatusMessage("settingsMsg", "Impossible de copier.", { error: true }),
      );
    }
  });
  // Charger l'URL du dashboard au chargement des settings
  _loadServerInfo();
  $("btnTestPlex")?.addEventListener("click", async () => {
    const url = $("inPlexUrl")?.value || "";
    const token = $("inPlexToken")?.value || "";
    try {
      const r = await apiCall("test_plex_connection", () => window.pywebview.api.test_plex_connection(url, token));
      if (r?.ok) {
        setStatusMessage(`Plex OK — ${r.server_name} v${r.version}`);
        const lr = await apiCall("get_plex_libraries", () => window.pywebview.api.get_plex_libraries(url, token));
        if (lr?.ok && lr.libraries) {
          const sel = $("selPlexLibrary");
          if (sel) {
            sel.innerHTML = lr.libraries.map(l => `<option value="${l.id}">${escapeHtml(l.name)}</option>`).join("");
          }
        }
      } else { setStatusMessage(r?.error || r?.message || "Echec", true); }
    } catch (err) { setStatusMessage("Erreur : " + err, true); }
  });
  $("btnTestRadarr")?.addEventListener("click", async () => {
    const url = $("inRadarrUrl")?.value || "";
    const key = $("inRadarrApiKey")?.value || "";
    try {
      const r = await apiCall("test_radarr_connection", () => window.pywebview.api.test_radarr_connection(url, key));
      if (r?.ok) { setStatusMessage(`Radarr OK — ${r.server_name} v${r.version}`); }
      else { setStatusMessage(r?.error || r?.message || "Echec", true); }
    } catch (err) { setStatusMessage("Erreur : " + err, true); }
  });
  _hookNamingEvents();
  _hookThemeControls();
  _hookWatchlistImport();
  hookWizardEvents();
}

function _hookWatchlistImport() {
  const container = $("watchlistResults");
  function _import(source, file) {
    if (!file || !container) return;
    const reader = new FileReader();
    reader.onload = async () => {
      container.innerHTML = "<p>Analyse en cours...</p>";
      try {
        const r = await apiCall("import_watchlist", () => window.pywebview.api.import_watchlist(reader.result, source));
        if (!r || !r.ok) { container.innerHTML = `<p class="text-muted">${escapeHtml(r?.message || "Erreur")}</p>`; return; }
        let html = `<div class="flex gap-4 mb-3"><strong>${r.owned_count}</strong> possede(s) — <strong>${r.missing_count}</strong> manquant(s) — <strong>${r.coverage_pct}%</strong> couverture</div>`;
        if ((r.missing || []).length) {
          html += '<table class="table"><thead><tr><th>Titre</th><th>Annee</th></tr></thead><tbody>';
          for (const m of (r.missing || []).slice(0, 100)) html += `<tr><td>${escapeHtml(m.title || "")}</td><td>${m.year || ""}</td></tr>`;
          html += "</tbody></table>";
        } else {
          html += '<p class="text-muted">Tous les films de votre watchlist sont dans votre bibliothèque !</p>';
        }
        container.innerHTML = html;
      } catch (err) { container.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(String(err))}</p>`; }
    };
    reader.readAsText(file, "utf-8");
  }
  $("fileLetterboxd")?.addEventListener("change", e => _import("letterboxd", e.target.files[0]));
  $("fileImdb")?.addEventListener("change", e => _import("imdb", e.target.files[0]));
}

/* --- Profils de renommage --------------------------------- */

/* Presets connus (copie de naming.py pour eviter un appel API a chaque changement) */
const _NAMING_PRESETS = {
  default:  { movie: "{title} ({year})",                              tv: "{series} ({year})" },
  plex:     { movie: "{title} ({year}) {tmdb_tag}",                   tv: "{series} ({year})" },
  jellyfin: { movie: "{title} ({year}) [{resolution}]",               tv: "{series} ({year})" },
  quality:  { movie: "{title} ({year}) [{resolution} {video_codec}]", tv: "{series} ({year})" },
  custom:   { movie: "{title} ({year})",                              tv: "{series} ({year})" },
};

let _namingPreviewTimer = null;

function _loadNamingPreset(s) {
  const sel = $("selNamingPreset");
  const inMovie = $("inNamingMovie");
  const inTv = $("inNamingTv");
  if (sel) sel.value = s.naming_preset || "default";
  if (inMovie) inMovie.value = s.naming_movie_template || "{title} ({year})";
  if (inTv) inTv.value = s.naming_tv_template || "{series} ({year})";
  _updateNamingInputsState();
  _triggerNamingPreview();
}

function _updateNamingInputsState() {
  const sel = $("selNamingPreset");
  const inMovie = $("inNamingMovie");
  const inTv = $("inNamingTv");
  const isCustom = (sel?.value || "default") === "custom";
  if (inMovie) inMovie.readOnly = !isCustom;
  if (inTv) inTv.readOnly = !isCustom;
}

function _onPresetChange() {
  const sel = $("selNamingPreset");
  const preset = sel?.value || "default";
  const inMovie = $("inNamingMovie");
  const inTv = $("inNamingTv");
  if (preset !== "custom") {
    const p = _NAMING_PRESETS[preset] || _NAMING_PRESETS.default;
    if (inMovie) inMovie.value = p.movie;
    if (inTv) inTv.value = p.tv;
  }
  _updateNamingInputsState();
  _triggerNamingPreview();
}

function _triggerNamingPreview() {
  clearTimeout(_namingPreviewTimer);
  _namingPreviewTimer = setTimeout(_fetchNamingPreview, 300);
}

async function _fetchNamingPreview() {
  const previewEl = $("namingPreview");
  if (!previewEl) return;
  const template = $("inNamingMovie")?.value || "{title} ({year})";
  try {
    const res = await window.pywebview.api.preview_naming_template(template);
    if (res?.ok) {
      previewEl.innerHTML = `<span class="naming-preview-label">Aperçu :</span> <strong>${esc(res.result)}</strong>`;
      previewEl.className = "naming-preview";
    } else {
      const errs = (res?.errors || []).join(", ");
      previewEl.innerHTML = `<span class="naming-preview-error">${esc(errs || res?.message || "Template invalide")}</span>`;
      previewEl.className = "naming-preview naming-preview--error";
    }
  } catch (err) {
    previewEl.textContent = "";
  }
}

function _hookNamingEvents() {
  $("selNamingPreset")?.addEventListener("change", _onPresetChange);
  $("inNamingMovie")?.addEventListener("input", _triggerNamingPreview);
  $("inNamingTv")?.addEventListener("input", _triggerNamingPreview);
}

/* --- Server info (URL dashboard) --- */

async function _loadServerInfo() {
  try {
    // Charger le QR code (inclut aussi l'URL)
    const qr = await apiCall("get_dashboard_qr", () => window.pywebview.api.get_dashboard_qr());
    if (qr?.ok && qr.url) {
      _refreshDashboardUrl(qr.url);
      _refreshDashboardQr(qr.svg || "");
    } else {
      // Fallback : charger seulement l'URL sans QR
      const r = await apiCall("get_server_info", () => window.pywebview.api.get_server_info());
      if (r?.ok && r.dashboard_url) {
        _refreshDashboardUrl(r.dashboard_url);
      }
    }
  } catch { /* silencieux si serveur non demarre */ }
}

function _refreshDashboardUrl(url) {
  const row = $("restDashboardUrlRow");
  const link = $("restDashboardUrl");
  if (row && link && url) {
    link.href = url;
    link.textContent = url;
    row.style.display = "";
  }
}

function _refreshDashboardQr(svgStr) {
  const container = $("restQrContainer");
  if (container && svgStr) {
    container.innerHTML = svgStr;
  }
}

/* --- Theme controls --- */

function _mapRange(val, inMin, inMax, outMin, outMax) {
  return outMin + (val - inMin) * (outMax - outMin) / (inMax - inMin);
}

function _applyThemeLive(s) {
  const root = document.documentElement;
  const theme = s.theme || "luxe";
  const anim = s.animation_level || "moderate";
  document.body.dataset.theme = theme;
  document.body.dataset.animation = anim;
  root.dataset.theme = theme;
  root.dataset.animation = anim;
  root.style.setProperty("--animation-speed", _mapRange(s.effect_speed || 50, 1, 100, 0.3, 3));
  root.style.setProperty("--glow-intensity", _mapRange(s.glow_intensity || 30, 0, 100, 0, 0.5));
  root.style.setProperty("--light-intensity", _mapRange(s.light_intensity || 20, 0, 100, 0, 0.3));
  root.style.setProperty("--effect-opacity", _mapRange(s.light_intensity || 20, 0, 100, 0, 0.08));
}

function _hookThemeControls() {
  $("selTheme")?.addEventListener("change", () => {
    const theme = $("selTheme").value;
    document.body.dataset.theme = theme;
    document.documentElement.dataset.theme = theme;
  });
  $("selAnimationLevel")?.addEventListener("change", () => {
    const anim = $("selAnimationLevel").value;
    document.body.dataset.animation = anim;
    document.documentElement.dataset.animation = anim;
  });
  const _sliders = [
    { id: "rangeEffectSpeed", lbl: "lblEffectSpeed", prop: "--animation-speed", min: 0.3, max: 3 },
    { id: "rangeGlowIntensity", lbl: "lblGlowIntensity", prop: "--glow-intensity", min: 0, max: 0.5 },
    { id: "rangeLightIntensity", lbl: "lblLightIntensity", prop: "--light-intensity", min: 0, max: 0.3 },
  ];
  for (const s of _sliders) {
    const el = $(s.id);
    if (!el) continue;
    el.addEventListener("input", () => {
      const v = parseInt(el.value, 10);
      if ($(s.lbl)) $(s.lbl).textContent = String(v);
      document.documentElement.style.setProperty(s.prop, _mapRange(v, 0, 100, s.min, s.max));
      if (s.id === "rangeLightIntensity") {
        document.documentElement.style.setProperty("--effect-opacity", _mapRange(v, 0, 100, 0, 0.08));
      }
    });
  }
}
