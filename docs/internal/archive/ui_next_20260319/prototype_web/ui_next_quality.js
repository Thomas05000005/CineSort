/* global state, $, qsa, setRows, findRowById, getFilteredRows, currentContextRunId, currentContextRowId, setStatusMessage, clearStatusMessageLater, flashActionButton, apiCall, qualityInfoForRow, renderTable, openRunFilmSelector, currentContextFilmLabel, currentContextRunLabel, currentContextRowId, currentContextRunId, probeToolStatusLine, updateOnboardingStatus, loadSettings, setLastRunContext, setSelectedFilmContext, closeModal, setPill, resolveRunDirFor, openPathWithFeedback, shortPath, fmtDateTime, copyTextSafe, updateContextBar, openModal */

function qNum(id, fallback = 0){
  const el = $(id);
  if(!el) return fallback;
  const v = parseFloat(el.value || "");
  return Number.isFinite(v) ? v : fallback;
}

function buildQualityProfileFromForm(){
  const prev = state.qualityProfile || {};
  return {
    id: String(prev.id || "CinemaLux_v1"),
    version: parseInt(prev.version || "1", 10) || 1,
    engine_version: String(prev.engine_version || "CinemaLux_v1"),
    weights: {
      video: parseInt(qNum("qWeightVideo", 60), 10),
      audio: parseInt(qNum("qWeightAudio", 30), 10),
      extras: parseInt(qNum("qWeightExtras", 10), 10),
    },
    toggles: {
      include_metadata: !!($("qIncludeMetadata") && $("qIncludeMetadata").checked),
      include_naming: !!($("qIncludeNaming") && $("qIncludeNaming").checked),
      enable_4k_light: !!($("qEnable4kLight") && $("qEnable4kLight").checked),
    },
    video_thresholds: {
      bitrate_min_kbps_2160p: parseInt(qNum("qBitrate2160", 18000), 10),
      bitrate_min_kbps_1080p: parseInt(qNum("qBitrate1080", 8000), 10),
      penalty_low_bitrate: parseInt(qNum("qPenaltyLowBitrate", 14), 10),
      penalty_4k_light: parseInt(qNum("qPenalty4kLight", 7), 10),
      penalty_hdr_8bit: parseInt(qNum("qPenaltyHdr8bit", 8), 10),
    },
    hdr_bonuses: {
      dv_bonus: parseInt(qNum("qDvBonus", 12), 10),
      hdr10p_bonus: parseInt(qNum("qHdr10pBonus", 10), 10),
      hdr10_bonus: parseInt(qNum("qHdr10Bonus", 8), 10),
    },
    codec_bonuses: {
      hevc_bonus: parseInt(qNum("qHevcBonus", 8), 10),
      av1_bonus: parseInt(qNum("qAv1Bonus", 9), 10),
      avc_bonus: parseInt(qNum("qAvcBonus", 5), 10),
    },
    audio_bonuses: {
      truehd_atmos_bonus: parseInt(qNum("qTruehdBonus", 12), 10),
      dts_hd_ma_bonus: parseInt(qNum("qDtshdBonus", 10), 10),
      dts_bonus: parseInt(qNum("qDtsBonus", 6), 10),
      aac_bonus: parseInt(qNum("qAacBonus", 3), 10),
      channels_bonus_map: {
        "2.0": parseInt(qNum("qCh20Bonus", 2), 10),
        "5.1": parseInt(qNum("qCh51Bonus", 6), 10),
        "7.1": parseInt(qNum("qCh71Bonus", 8), 10),
      },
    },
    languages: {
      bonus_vo_present: parseInt(qNum("qVoBonus", 4), 10),
      bonus_vf_present: parseInt(qNum("qVfBonus", 2), 10),
    },
    tiers: {
      premium: parseInt(qNum("qTierPremium", 85), 10),
      bon: parseInt(qNum("qTierBon", 70), 10),
      moyen: parseInt(qNum("qTierMoyen", 55), 10),
    },
  };
}

function applyQualityProfileToForm(profile){
  const p = profile || {};
  const w = p.weights || {};
  const t = p.toggles || {};
  const vt = p.video_thresholds || {};
  const hb = p.hdr_bonuses || {};
  const cb = p.codec_bonuses || {};
  const ab = p.audio_bonuses || {};
  const ch = ab.channels_bonus_map || {};
  const lg = p.languages || {};
  const tiers = p.tiers || {};

  $("qProfileId").textContent = p.id || "CinemaLux_v1";
  $("qProfileVersion").textContent = String(p.version || 1);
  $("qWeightVideo").value = w.video ?? 60;
  $("qWeightAudio").value = w.audio ?? 30;
  $("qWeightExtras").value = w.extras ?? 10;
  $("qEnable4kLight").checked = t.enable_4k_light !== false;
  $("qIncludeMetadata").checked = !!t.include_metadata;
  $("qIncludeNaming").checked = !!t.include_naming;
  $("qBitrate2160").value = vt.bitrate_min_kbps_2160p ?? 18000;
  $("qBitrate1080").value = vt.bitrate_min_kbps_1080p ?? 8000;
  $("qPenaltyLowBitrate").value = vt.penalty_low_bitrate ?? 14;
  $("qPenalty4kLight").value = vt.penalty_4k_light ?? 7;
  $("qPenaltyHdr8bit").value = vt.penalty_hdr_8bit ?? 8;
  $("qDvBonus").value = hb.dv_bonus ?? 12;
  $("qHdr10pBonus").value = hb.hdr10p_bonus ?? 10;
  $("qHdr10Bonus").value = hb.hdr10_bonus ?? 8;
  $("qHevcBonus").value = cb.hevc_bonus ?? 8;
  $("qAv1Bonus").value = cb.av1_bonus ?? 9;
  $("qAvcBonus").value = cb.avc_bonus ?? 5;
  $("qTruehdBonus").value = ab.truehd_atmos_bonus ?? 12;
  $("qDtshdBonus").value = ab.dts_hd_ma_bonus ?? 10;
  $("qDtsBonus").value = ab.dts_bonus ?? 6;
  $("qAacBonus").value = ab.aac_bonus ?? 3;
  $("qCh20Bonus").value = ch["2.0"] ?? 2;
  $("qCh51Bonus").value = ch["5.1"] ?? 6;
  $("qCh71Bonus").value = ch["7.1"] ?? 8;
  $("qVoBonus").value = lg.bonus_vo_present ?? 4;
  $("qVfBonus").value = lg.bonus_vf_present ?? 2;
  $("qTierPremium").value = tiers.premium ?? 85;
  $("qTierBon").value = tiers.bon ?? 70;
  $("qTierMoyen").value = tiers.moyen ?? 55;
  renderQualityPresetButtons();
}

function renderQualityPresetButtons(){
  const presets = Array.isArray(state.qualityPresets) ? state.qualityPresets : [];
  const profileId = String(state.qualityProfile?.id || "").trim().toLowerCase();
  const currentFingerprint = qualityProfileFingerprint(state.qualityProfile);
  let hint = "Choisissez un preset pour charger un profil cohérent en un clic.";
  qsa(".qualityPresetBtn").forEach((btn) => {
    const presetId = String(btn.dataset.qualityPreset || "").trim();
    const preset = presets.find((p) => String(p?.preset_id || "").trim() === presetId);
    const presetFingerprint = qualityProfileFingerprint(preset?.profile_json || null);
    const presetProfileId = String(preset?.profile_id || "").trim().toLowerCase();
    const isActive = !!currentFingerprint && !!presetFingerprint && currentFingerprint === presetFingerprint;
    const isDerived = !isActive && !!profileId && !!presetProfileId && profileId === presetProfileId;
    btn.classList.toggle("active", isActive);
    btn.classList.toggle("derived", isDerived);
    btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    if(isActive){
      hint = `Preset actif : ${btn.textContent?.trim() || presetId}.`;
    } else if(isDerived && !hint.startsWith("Preset actif")){
      hint = `Profil dérivé du preset ${btn.textContent?.trim() || presetId}.`;
    }
  });
  if($("qualityPresetHint")){
    $("qualityPresetHint").textContent = hint;
  }
}

function qualityProfileFingerprint(profile){
  if(!profile || typeof profile !== "object"){
    return "";
  }
  const p = profile;
  const weights = p.weights && typeof p.weights === "object" ? p.weights : {};
  const toggles = p.toggles && typeof p.toggles === "object" ? p.toggles : {};
  const video = p.video_thresholds && typeof p.video_thresholds === "object" ? p.video_thresholds : {};
  const hdr = p.hdr_bonuses && typeof p.hdr_bonuses === "object" ? p.hdr_bonuses : {};
  const codec = p.codec_bonuses && typeof p.codec_bonuses === "object" ? p.codec_bonuses : {};
  const audio = p.audio_bonuses && typeof p.audio_bonuses === "object" ? p.audio_bonuses : {};
  const channels = audio.channels_bonus_map && typeof audio.channels_bonus_map === "object" ? audio.channels_bonus_map : {};
  const languages = p.languages && typeof p.languages === "object" ? p.languages : {};
  const tiers = p.tiers && typeof p.tiers === "object" ? p.tiers : {};
  return JSON.stringify({
    id: String(p.id || ""),
    version: Number(p.version || 0),
    engine_version: String(p.engine_version || ""),
    weights: {
      video: Number(weights.video || 0),
      audio: Number(weights.audio || 0),
      extras: Number(weights.extras || 0),
    },
    toggles: {
      include_metadata: !!toggles.include_metadata,
      include_naming: !!toggles.include_naming,
      enable_4k_light: !!toggles.enable_4k_light,
    },
    video_thresholds: {
      bitrate_min_kbps_2160p: Number(video.bitrate_min_kbps_2160p || 0),
      bitrate_min_kbps_1080p: Number(video.bitrate_min_kbps_1080p || 0),
      penalty_low_bitrate: Number(video.penalty_low_bitrate || 0),
      penalty_4k_light: Number(video.penalty_4k_light || 0),
      penalty_hdr_8bit: Number(video.penalty_hdr_8bit || 0),
    },
    hdr_bonuses: {
      dv_bonus: Number(hdr.dv_bonus || 0),
      hdr10p_bonus: Number(hdr.hdr10p_bonus || 0),
      hdr10_bonus: Number(hdr.hdr10_bonus || 0),
    },
    codec_bonuses: {
      hevc_bonus: Number(codec.hevc_bonus || 0),
      av1_bonus: Number(codec.av1_bonus || 0),
      avc_bonus: Number(codec.avc_bonus || 0),
    },
    audio_bonuses: {
      truehd_atmos_bonus: Number(audio.truehd_atmos_bonus || 0),
      dts_hd_ma_bonus: Number(audio.dts_hd_ma_bonus || 0),
      dts_bonus: Number(audio.dts_bonus || 0),
      aac_bonus: Number(audio.aac_bonus || 0),
      channels_bonus_map: {
        "2.0": Number(channels["2.0"] || 0),
        "5.1": Number(channels["5.1"] || 0),
        "7.1": Number(channels["7.1"] || 0),
      },
    },
    languages: {
      bonus_vo_present: Number(languages.bonus_vo_present || 0),
      bonus_vf_present: Number(languages.bonus_vf_present || 0),
    },
    tiers: {
      premium: Number(tiers.premium || 0),
      bon: Number(tiers.bon || 0),
      moyen: Number(tiers.moyen || 0),
    },
  });
}

async function loadQualityPresets(){
  const r = await apiCall("get_quality_presets", () => window.pywebview.api.get_quality_presets(), {
    statusId: "qualityMsg",
    fallbackMessage: "Impossible de charger les presets qualite.",
  });
  if(!r || !r.ok){
    return;
  }
  state.qualityPresets = Array.isArray(r.presets) ? r.presets : [];
  qsa(".qualityPresetBtn").forEach((btn) => {
    const presetId = String(btn.dataset.qualityPreset || "").trim();
    const preset = state.qualityPresets.find((p) => String(p?.preset_id || "") === presetId);
    const title = String(preset?.description || "");
    if(title){
      btn.title = title;
    }
  });
  renderQualityPresetButtons();
}

async function applyQualityPresetFromUI(presetId, triggerEl = null){
  const pid = String(presetId || "").trim();
  if(!pid){
    setStatusMessage("qualityMsg", "Preset qualite invalide.", { error: true });
    flashActionButton(triggerEl, "error");
    return;
  }
  setStatusMessage("qualityMsg", "Application du preset qualite...", { loading: true });
  const r = await apiCall("apply_quality_preset", () => window.pywebview.api.apply_quality_preset(pid), {
    statusId: "qualityMsg",
    fallbackMessage: "Impossible d'appliquer le preset qualite.",
  });
  if(!r || !r.ok){
    setStatusMessage("qualityMsg", `Erreur preset : ${r?.message || "inconnue"}`, { error: true });
    flashActionButton(triggerEl, "error");
    return;
  }
  state.qualityProfile = (r.profile_json && typeof r.profile_json === "object") ? r.profile_json : state.qualityProfile;
  if(state.qualityProfile){
    applyQualityProfileToForm(state.qualityProfile);
  }
  setStatusMessage("qualityMsg", "Preset qualite applique.", { success: true });
  flashActionButton(triggerEl, "ok");
  clearStatusMessageLater("qualityMsg", 2200);
}

async function loadQualityProfile(){
  setStatusMessage("qualityMsg", "Chargement du profil...", { loading: true });
  try {
    const r = await apiCall("get_quality_profile", () => window.pywebview.api.get_quality_profile(), {
      statusId: "qualityMsg",
      fallbackMessage: "Impossible de charger le profil qualité.",
    });
    if(!r || !r.ok){
      setStatusMessage("qualityMsg", `Erreur profil : ${r?.message || ""}`, { error: true });
      return;
    }
    state.qualityProfile = r.profile_json || {};
    applyQualityProfileToForm(state.qualityProfile);
    $("qProfileJson").value = "";
    setStatusMessage("qualityMsg", "Profil chargé.", { success: true });
    clearStatusMessageLater("qualityMsg", 1800);
  } catch(err){
    setStatusMessage("qualityMsg", `Erreur profil : ${String(err || "")}`, { error: true });
  }
}

function renderProbeToolsStatus(payload){
  const p = (payload && typeof payload === "object") ? payload : {};
  const tools = (p.tools && typeof p.tools === "object") ? p.tools : {};
  const installer = (p.installer && typeof p.installer === "object") ? p.installer : {};
  const ff = tools.ffprobe || {};
  const mi = tools.mediainfo || {};
  const hybridReady = !!p.hybrid_ready;
  const degradedMode = String(p.degraded_mode || "none");
  const canManage = !!installer.supported && !!installer.winget_available;
  const installerNote = canManage
    ? ""
    : " Installation assistée indisponible (winget non détecté). Utilisez les chemins manuels ci-dessous.";

  $("probeFfprobeStatus").textContent = probeToolStatusLine("ffprobe", ff);
  $("probeMediainfoStatus").textContent = probeToolStatusLine("MediaInfo", mi);
  $("probeHybridStatus").textContent = `Mode hybride: ${hybridReady ? "actif" : "partiel/indisponible"} (${degradedMode}). ${String(p.message || "")}${installerNote}`;

  if(state.settings){
    $("inProbeFfprobePath").value = String(state.settings.ffprobe_path || "");
    $("inProbeMediainfoPath").value = String(state.settings.mediainfo_path || "");
    $("selProbeBackend").value = String(state.settings.probe_backend || "auto");
  }
  const btnInstall = $("btnProbeInstall");
  const btnUpdate = $("btnProbeUpdate");
  const btnSave = $("btnProbeSavePaths");
  const btnRecheck = $("btnProbeRecheck");
  if(btnInstall){
    btnInstall.disabled = state.probeToolsInFlight || !canManage;
    btnInstall.title = canManage ? "" : "winget non disponible";
  }
  if(btnUpdate){
    btnUpdate.disabled = state.probeToolsInFlight || !canManage;
    btnUpdate.title = canManage ? "" : "winget non disponible";
  }
  if(btnSave){
    btnSave.disabled = state.probeToolsInFlight;
  }
  if(btnRecheck){
    btnRecheck.disabled = state.probeToolsInFlight;
  }
  updateOnboardingStatus();
}

async function loadProbeToolsStatus(force = false, triggerEl = null){
  const endpoint = force ? "recheck_probe_tools" : "get_probe_tools_status";
  const msg = force ? "Réanalyse des outils..." : "Lecture du diagnostic outils...";
  setStatusMessage("probeToolsMsg", msg, { loading: true });
  const call = force
    ? () => window.pywebview.api.recheck_probe_tools()
    : () => window.pywebview.api.get_probe_tools_status();
  const res = await apiCall(endpoint, call, {
    statusId: "probeToolsMsg",
    fallbackMessage: "Impossible de lire l'état des outils d'analyse.",
  });
  if(!res || !res.ok){
    setStatusMessage("probeToolsMsg", `Erreur outils: ${res?.message || "inconnue"}`, { error: true });
    flashActionButton(triggerEl, "error");
    updateOnboardingStatus();
    return;
  }
  state.probeToolsStatus = res;
  renderProbeToolsStatus(res);
  setStatusMessage("probeToolsMsg", "Diagnostic outils mis à jour.", { success: true });
  flashActionButton(triggerEl, "ok");
  clearStatusMessageLater("probeToolsMsg", 2200);
}

async function saveProbeToolPathsFromUI(){
  const btn = $("btnProbeSavePaths");
  const payload = {
    ffprobe_path: String($("inProbeFfprobePath").value || "").trim(),
    mediainfo_path: String($("inProbeMediainfoPath").value || "").trim(),
    probe_backend: String($("selProbeBackend").value || "auto").trim(),
  };
  setStatusMessage("probeToolsMsg", "Validation des chemins outils...", { loading: true });
  const res = await apiCall("set_probe_tool_paths", () => window.pywebview.api.set_probe_tool_paths(payload), {
    statusId: "probeToolsMsg",
    fallbackMessage: "Impossible d'enregistrer les chemins outils.",
  });
  if(!res || !res.ok){
    setStatusMessage("probeToolsMsg", `Erreur chemins outils : ${res?.message || "inconnue"}`, { error: true });
    flashActionButton(btn, "error");
    return;
  }
  state.settings = { ...(state.settings || {}), ...payload };
  state.probeToolsStatus = res;
  renderProbeToolsStatus(res);
  setStatusMessage("probeToolsMsg", "Chemins outils enregistrés.", { success: true });
  flashActionButton(btn, "ok");
  clearStatusMessageLater("probeToolsMsg", 2200);
}

async function runProbeToolsAction(action){
  const actionBtn = action === "update" ? $("btnProbeUpdate") : $("btnProbeInstall");
  if(state.probeToolsInFlight){
    setStatusMessage("probeToolsMsg", "Une opération outils est déjà en cours.", { error: true });
    flashActionButton(actionBtn, "error");
    return;
  }
  const installer = (state.probeToolsStatus && typeof state.probeToolsStatus === "object" && typeof state.probeToolsStatus.installer === "object")
    ? state.probeToolsStatus.installer
    : {};
  if(!(installer.supported && installer.winget_available)){
    setStatusMessage("probeToolsMsg", "Installation assistée indisponible: winget non détecté. Utilisez les chemins manuels.", { error: true });
    flashActionButton(actionBtn, "error");
    return;
  }
  state.probeToolsInFlight = true;
  $("btnProbeInstall").disabled = true;
  $("btnProbeUpdate").disabled = true;
  $("btnProbeSavePaths").disabled = true;
  $("btnProbeRecheck").disabled = true;
  try {
    const verb = action === "update" ? "Mise à jour" : "Installation";
    setStatusMessage("probeToolsMsg", `${verb} en cours (scope utilisateur)...`, { loading: true });
    const fn = action === "update"
      ? () => window.pywebview.api.update_probe_tools({ scope: "user" })
      : () => window.pywebview.api.install_probe_tools({ scope: "user" });
    const res = await apiCall(`${action}_probe_tools`, fn, {
      statusId: "probeToolsMsg",
      fallbackMessage: `${verb} des outils impossible.`,
    });
    if(!res || !res.ok){
      setStatusMessage("probeToolsMsg", `${verb} incomplète : ${res?.message || "erreur inconnue"}`, { error: true });
      if(res?.status){
        state.probeToolsStatus = res.status;
        renderProbeToolsStatus(res.status);
      }
      flashActionButton(actionBtn, "error");
      return;
    }
    if(res.status){
      state.probeToolsStatus = res.status;
      renderProbeToolsStatus(res.status);
    }
    await loadSettings();
    setStatusMessage("probeToolsMsg", `${verb} terminée.`, { success: true });
    flashActionButton(actionBtn, "ok");
    clearStatusMessageLater("probeToolsMsg", 2400);
  } finally {
    state.probeToolsInFlight = false;
    renderProbeToolsStatus(state.probeToolsStatus || {});
  }
}

async function saveQualityProfileFromUI(){
  const btn = $("btnQualitySave");
  const profile = buildQualityProfileFromForm();
  setStatusMessage("qualityMsg", "Sauvegarde du profil...", { loading: true });
  const r = await apiCall("save_quality_profile", () => window.pywebview.api.save_quality_profile(profile), {
    statusId: "qualityMsg",
    fallbackMessage: "Impossible d'enregistrer le profil qualité.",
  });
  if(!r || !r.ok){
    const details = Array.isArray(r?.errors) ? ` (${r.errors.join(" | ")})` : "";
    setStatusMessage("qualityMsg", `Erreur profil : ${r?.message || ""}${details}`, { error: true });
    flashActionButton(btn, "error");
    return;
  }
  state.qualityProfile = profile;
  $("qProfileId").textContent = r.profile_id || profile.id || "CinemaLux_v1";
  $("qProfileVersion").textContent = String(r.profile_version || profile.version || 1);
  setStatusMessage("qualityMsg", "Profil qualité enregistré.", { success: true });
  flashActionButton(btn, "ok");
  clearStatusMessageLater("qualityMsg", 2200);
}

async function resetQualityProfileFromUI(){
  const btn = $("btnQualityReset");
  setStatusMessage("qualityMsg", "Réinitialisation du profil...", { loading: true });
  const r = await apiCall("reset_quality_profile", () => window.pywebview.api.reset_quality_profile(), {
    statusId: "qualityMsg",
    fallbackMessage: "Impossible de réinitialiser le profil qualité.",
  });
  if(!r || !r.ok){
    setStatusMessage("qualityMsg", `Erreur de réinitialisation : ${r?.message || ""}`, { error: true });
    flashActionButton(btn, "error");
    return;
  }
  state.qualityProfile = r.profile_json || {};
  applyQualityProfileToForm(state.qualityProfile);
  setStatusMessage("qualityMsg", "Profil réinitialisé.", { success: true });
  flashActionButton(btn, "ok");
  clearStatusMessageLater("qualityMsg", 2200);
}

async function exportQualityProfileFromUI(){
  const btn = $("btnQualityExport");
  const r = await apiCall("export_quality_profile", () => window.pywebview.api.export_quality_profile(), {
    statusId: "qualityMsg",
    fallbackMessage: "Impossible d'exporter le profil qualité.",
  });
  if(!r || !r.ok){
    setStatusMessage("qualityMsg", `Erreur d'export : ${r?.message || ""}`, { error: true });
    flashActionButton(btn, "error");
    return;
  }
  $("qProfileJson").value = r.json || "";
  setStatusMessage("qualityMsg", "Profil exporté dans le bloc JSON.", { success: true });
  flashActionButton(btn, "ok");
  clearStatusMessageLater("qualityMsg", 2200);
}

async function importQualityProfileFromUI(){
  const btn = $("btnQualityImport");
  const txt = $("qProfileJson").value || "";
  if(!txt.trim()){
    setStatusMessage("qualityMsg", "Collez un profil JSON avant l'import.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  setStatusMessage("qualityMsg", "Import du profil...", { loading: true });
  const r = await apiCall("import_quality_profile", () => window.pywebview.api.import_quality_profile(txt), {
    statusId: "qualityMsg",
    fallbackMessage: "Impossible d'importer le profil qualité.",
  });
  if(!r || !r.ok){
    const details = Array.isArray(r?.errors) ? ` (${r.errors.join(" | ")})` : "";
    setStatusMessage("qualityMsg", `Erreur d'import : ${r?.message || ""}${details}`, { error: true });
    flashActionButton(btn, "error");
    return;
  }
  await loadQualityProfile();
  setStatusMessage("qualityMsg", "Profil importé.", { success: true });
  flashActionButton(btn, "ok");
  clearStatusMessageLater("qualityMsg", 2200);
}

async function runQualityTest(runId, rowId, triggerEl = null){
  const out = $("qualityTestOut");
  const rid = String(runId || "").trim();
  const row = String(rowId || "").trim();
  if(!rid || !row){
    setStatusMessage("qualityTestMsg", "Choisissez un run et un film.", { error: true });
    flashActionButton(triggerEl, "error");
    return { ok: false };
  }
  setStatusMessage("qualityTestMsg", "Chargement du score qualité...", { loading: true });
  out.textContent = "Chargement...";
  const forceReanalyze = !!$("ckQualityForceReanalyze")?.checked;
  const reuseExisting = forceReanalyze ? false : true;
  const r = await apiCall("get_quality_report", () => window.pywebview.api.get_quality_report(rid, row, { reuse_existing: reuseExisting }), {
    statusId: "qualityTestMsg",
    fallbackMessage: "Impossible de calculer le score qualité.",
  });
  if(!r || !r.ok){
    setStatusMessage("qualityTestMsg", `Impossible de charger le score : ${r?.message || "erreur inconnue"}`, { error: true });
    out.textContent = r?.message || "Erreur";
    flashActionButton(triggerEl, "error");
    return { ok: false };
  }
  const reasons = Array.isArray(r.reasons) ? r.reasons : [];
  const confidence = (r && typeof r.confidence === "object" && r.confidence) ? r.confidence : {};
  const confidenceLabel = String(confidence.label || "—");
  const confidenceValue = Number(confidence.value || 0);
  const explanation = (r && typeof r.explanation === "object" && r.explanation) ? r.explanation : {};
  const narrative = String(explanation.narrative || "").trim();
  const topPositive = Array.isArray(explanation.top_positive) ? explanation.top_positive : [];
  const topNegative = Array.isArray(explanation.top_negative) ? explanation.top_negative : [];
  const factors = Array.isArray(explanation.factors) ? explanation.factors : [];
  const factorsSorted = [...factors]
    .filter((f) => f && typeof f === "object")
    .sort((a, b) => Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0)))
    .slice(0, 8);
  out.textContent = [
    `Score: ${r.score}/100 (${r.tier})`,
    `Confiance du score: ${confidenceLabel} (${confidenceValue}/100)`,
    `Profil : ${r.profile_id} v${r.profile_version}`,
    `Probe: ${r.probe_quality || "—"} (cache=${r.cache_hit_probe ? "oui" : "non"})`,
    narrative ? `Résumé: ${narrative}` : "",
    topPositive.length ? `Points forts: ${topPositive.map((x) => String(x?.label || "")).filter(Boolean).join(" | ")}` : "",
    topNegative.length ? `Freins principaux: ${topNegative.map((x) => String(x?.label || "")).filter(Boolean).join(" | ")}` : "",
    factorsSorted.length ? "Impacts détaillés:" : "",
    ...factorsSorted.map((f) => {
      const d = Number(f?.delta || 0);
      const sign = d > 0 ? "+" : "";
      const cat = String(f?.category || "global");
      const label = String(f?.label || "");
      return `- ${sign}${d} [${cat}] ${label}`;
    }),
    "",
    "Raisons:",
    ...reasons.map(x => `- ${x}`),
  ].filter((line) => String(line || "").trim().length > 0).join("\n");
  state.qualityByRow.set(row, {
    status: String(r.status || "analyzed"),
    score: Number(r.score || 0),
    tier: String(r.tier || ""),
  });
  setStatusMessage("qualityTestMsg", "Score qualité chargé.", { success: true });
  flashActionButton(triggerEl, "ok");
  return { ok: true, payload: r };
}

async function testQualityOnFilm(){
  const btn = $("btnQualityTest");
  const runId = ($("qTestRunId").value || currentContextRunId() || "").trim();
  const rowId = ($("qTestRowId").value || "").trim();
  if(!runId || !rowId){
    setStatusMessage("qualityTestMsg", "Mode avancé : choisissez un run et un film, ou utilisez Sélectionner…", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  await runQualityTest(runId, rowId, btn);
}

async function testQualityOnSelectedFilm(){
  const btn = $("btnQualityTestSelected");
  const rid = currentContextRunId();
  const rowId = currentContextRowId();
  if(rid && rowId){
    await runQualityTest(rid, rowId, btn);
    return;
  }
  if(state.lastRunId){
    setStatusMessage("qualityTestMsg", "Choisissez un film dans le dernier run.");
    await openRunFilmSelector(state.lastRunId);
    return;
  }
  setStatusMessage("qualityTestMsg", "Aucun run disponible. Lancez une analyse puis sélectionnez un film.", { error: true });
  flashActionButton(btn, "error");
  await openRunFilmSelector("");
}

function qualityBatchRowLabel(rowId){
  const row = findRowById(rowId);
  if(!row){
    return String(rowId || "ligne inconnue");
  }
  const title = String(row.proposed_title || row.video || row.folder || row.row_id || "film").trim();
  const year = Number(row.proposed_year || 0);
  return year > 0 ? `${title} (${year})` : title;
}

function validatedRowIdsForQualityBatch(){
  return state.rows
    .map((row) => String(row.row_id || "").trim())
    .filter((rowId) => {
      const d = state.decisions[rowId];
      return !!(d && d.ok === true);
    });
}

function filteredRowIdsForQualityBatch(){
  return getFilteredRows()
    .map((row) => String(row.row_id || "").trim())
    .filter(Boolean);
}

function setQualityBatchButtonsDisabled(disabled){
  [
    "btnQualityBatchSelection",
    "btnQualityBatchFiltered",
    "btnQualityTestSelected",
    "btnQualityTest",
    "ckQualityReuseExisting",
    "ckQualityForceReanalyze",
    "qualityStateFilter",
    "qualityTierFilter",
    "qualityScoreFilter",
  ].forEach((id) => {
    const el = $(id);
    if(el){
      el.disabled = !!disabled;
    }
  });
}

async function ensureQualityRowsForRun(runId){
  const rid = String(runId || "").trim();
  if(!rid){
    return false;
  }
  if(String(state.rowsRunId || "") === rid && state.rows.length > 0){
    return true;
  }
  const plan = await apiCall("get_plan(quality_batch)", () => window.pywebview.api.get_plan(rid), {
    statusId: "qualityBatchMsg",
    fallbackMessage: "Impossible de charger les films du run pour l'analyse qualité.",
  });
  if(!plan || !plan.ok){
    setRows([], null);
    state.decisions = {};
    clearSelectedFilmContext();
    resetRunDetailPanels();
    persistContextToStorage();
    updateContextBar();
    setStatusMessage("qualityBatchMsg", `Impossible de charger le run : ${plan?.message || "erreur inconnue"}.`, { error: true });
    return false;
  }
  if(String(state.runId || "") !== rid){
    setLastRunContext(rid, null);
  } else if(String(state.rowsRunId || "") !== rid){
    state.duplicates = null;
    state.qualityByRow = new Map();
    clearSelectedFilmContext();
  }
  setRows(plan.rows || [], rid);
  state.decisions = {};
  state.selectedRunId = rid;
  state.lastRunId = rid;
  persistContextToStorage();
  updateContextBar();

  const v = await apiCall("load_validation(quality_batch)", () => window.pywebview.api.load_validation(rid), {
    fallbackMessage: "Impossible de charger la validation pour l'analyse qualité.",
  });
  if(v && v.ok && v.decisions && typeof v.decisions === "object"){
    state.decisions = v.decisions;
  }
  syncSelectedFilmContextForLoadedRows();
  updateContextBar();
  return true;
}

function appendQualityBatchLine(lines, rowId, status, details = ""){
  const label = qualityBatchRowLabel(rowId);
  if(status === "ok"){
    lines.push(`OK      ${label}${details ? ` — ${details}` : ""}`);
    return;
  }
  if(status === "ignored"){
    lines.push(`IGNORE  ${label}${details ? ` — ${details}` : ""}`);
    return;
  }
  lines.push(`ERREUR  ${label}${details ? ` — ${details}` : ""}`);
}

async function runQualityBatch(rowIds, sourceLabel, triggerEl = null){
  if(state.qualityBatchInFlight){
    setStatusMessage("qualityBatchMsg", "Analyse qualité déjà en cours.", { error: true });
    flashActionButton(triggerEl, "error");
    return;
  }
  const runId = currentContextRunId();
  if(!runId){
    setStatusMessage("qualityBatchMsg", "Choisissez un run avant de lancer l'analyse qualité en lot.", { error: true });
    flashActionButton(triggerEl, "error");
    return;
  }
  const ids = Array.from(new Set((Array.isArray(rowIds) ? rowIds : []).map((x) => String(x || "").trim()).filter(Boolean)));
  if(!ids.length){
    setStatusMessage("qualityBatchMsg", "Analyse qualité impossible : aucune ligne sélectionnée.", { error: true });
    flashActionButton(triggerEl, "error");
    return;
  }

  const out = $("qualityBatchOut");
  const forceReanalyze = !!$("ckQualityForceReanalyze")?.checked;
  const reuseExisting = forceReanalyze ? false : !!$("ckQualityReuseExisting")?.checked;
  const lines = [];
  let analyzed = 0;
  let ignored = 0;
  let errors = 0;

  state.qualityBatchInFlight = true;
  setQualityBatchButtonsDisabled(true);
  if(out) out.textContent = `Source: ${sourceLabel}\n---`;
  try {
    for(let i = 0; i < ids.length; i += 1){
      const rowId = ids[i];
      const label = qualityBatchRowLabel(rowId);
      setStatusMessage(
        "qualityBatchMsg",
        `Analyse qualité en cours (${sourceLabel}) : ${i + 1}/${ids.length} • ${label} (OK ${analyzed} · ignorés ${ignored} · erreurs ${errors}).`,
        { loading: true },
      );
      const r = await apiCall(
        "analyze_quality_batch",
        () => window.pywebview.api.analyze_quality_batch(runId, [rowId], { reuse_existing: reuseExisting, continue_on_error: true }),
        {
          statusId: "qualityBatchMsg",
          fallbackMessage: "Impossible de lancer l'analyse qualité en lot.",
        },
      );
      if(!r || !r.ok){
        errors += 1;
        appendQualityBatchLine(lines, rowId, "error", r?.message || "erreur inconnue");
        if(out) out.textContent = lines.join("\n");
        continue;
      }

      analyzed += Number(r.analyzed || 0);
      ignored += Number(r.ignored || 0);
      errors += Number(r.errors || 0);
      const first = Array.isArray(r.results) && r.results.length ? r.results[0] : null;
      const st = String(first?.status || "analyzed");
      if(st === "ignored_existing"){
        appendQualityBatchLine(lines, rowId, "ignored", "déjà analysé (cache)");
      } else if(st === "error"){
        appendQualityBatchLine(lines, rowId, "error", first?.message || "erreur");
      } else {
        appendQualityBatchLine(lines, rowId, "ok", `score ${first?.score ?? "—"}`);
      }
      state.qualityByRow.set(String(rowId), {
        status: st,
        score: Number(first?.score || 0),
        tier: String(first?.tier || ""),
      });
      if(out) out.textContent = lines.join("\n");
    }

    setStatusMessage(
      "qualityBatchMsg",
      `Analyse qualité terminée (${sourceLabel}) : ${analyzed} analysés, ${ignored} ignorés, ${errors} erreurs.`,
      { error: errors > 0, success: errors === 0 },
    );
    flashActionButton(triggerEl, errors > 0 ? "error" : "ok");
  } finally {
    state.qualityBatchInFlight = false;
    setQualityBatchButtonsDisabled(false);
    renderTable();
  }
}

async function runQualityBatchOnSelection(){
  const btn = $("btnQualityBatchSelection");
  const rid = currentContextRunId();
  if(!rid){
    setStatusMessage("qualityBatchMsg", "Choisissez un run avant de lancer l'analyse qualité en lot.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  const loaded = await ensureQualityRowsForRun(rid);
  if(!loaded){
    return;
  }
  const ids = validatedRowIdsForQualityBatch();
  if(!ids.length){
    setStatusMessage("qualityBatchMsg", "Analyse qualité impossible : aucune ligne validée.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  await runQualityBatch(ids, "films validés", btn);
}

async function runQualityBatchOnFiltered(){
  const btn = $("btnQualityBatchFiltered");
  const rid = currentContextRunId();
  if(!rid){
    setStatusMessage("qualityBatchMsg", "Choisissez un run avant de lancer l'analyse qualité en lot.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  const loaded = await ensureQualityRowsForRun(rid);
  if(!loaded){
    return;
  }
  const ids = filteredRowIdsForQualityBatch();
  if(!ids.length){
    setStatusMessage("qualityBatchMsg", "Analyse qualité impossible : aucun film visible avec le filtre actuel.", { error: true });
    flashActionButton(btn, "error");
    return;
  }
  await runQualityBatch(ids, "filtre", btn);
}

function syncQualityReuseControls(){
  const reuse = $("ckQualityReuseExisting");
  const force = $("ckQualityForceReanalyze");
  if(!reuse || !force){
    return;
  }
  if(force.checked){
    reuse.checked = false;
    reuse.disabled = true;
  } else {
    reuse.disabled = false;
  }
}

function createNextQualityBlockHead(eyebrow, title){
  const head = document.createElement("div");
  head.className = "qualityPanelHead";

  const left = document.createElement("div");
  const eyebrowEl = document.createElement("div");
  eyebrowEl.className = "panelEyebrow";
  eyebrowEl.textContent = eyebrow;
  const titleEl = document.createElement("div");
  titleEl.className = "qualityPanelTitle";
  titleEl.textContent = title;

  left.appendChild(eyebrowEl);
  left.appendChild(titleEl);
  head.appendChild(left);
  return head;
}

function ensureNextQualityCardHeader(card, eyebrow){
  if(!card || card.querySelector(".panelEyebrow")){
    return;
  }
  const title = card.querySelector(".cardTitle");
  if(!title){
    return;
  }
  const eyebrowEl = document.createElement("div");
  eyebrowEl.className = "panelEyebrow";
  eyebrowEl.textContent = eyebrow;
  title.parentNode?.insertBefore(eyebrowEl, title);
  title.classList.add("qualityPanelTitle");
}

function enhanceNextQualityLayout(){
  const view = $("view-quality");
  if(!view || view.dataset.nextEnhanced === "1"){
    return;
  }
  view.dataset.nextEnhanced = "1";
  view.classList.add("qualityNextView");

  const hero = view.querySelector(".qualityHubHero");
  hero?.classList.add("qualityNextHero");
  hero?.querySelector(".row.spread.wrap > div:first-child")?.classList.add("qualityNextHeroMain");
  hero?.querySelector(".row.spread.wrap > .muted")?.classList.add("qualityNextHeroMeta");
  view.querySelector(".qualityHubTabs")?.classList.add("nextSectionTabs");

  const overviewPanel = $("quality-panel-overview");
  const overviewCard = overviewPanel?.querySelector(".card");
  if(overviewPanel && overviewCard){
    const actionRow = $("btnQualityTestSelected")?.closest(".row");
    const batchRow = $("btnQualityBatchSelection")?.closest(".row");
    const manualIds = $("qualityManualIds");
    const batchMsg = $("qualityBatchMsg");
    const batchOut = $("qualityBatchOut");
    const testMsg = $("qualityTestMsg");
    const testOut = $("qualityTestOut");

    const grid = document.createElement("div");
    grid.className = "qualityNextGrid";

    const actionCard = document.createElement("div");
    actionCard.className = "card qualityActionCard nextWorkbenchCard nextActionZone";
    actionCard.appendChild(createNextQualityBlockHead("Action principale", "Lancer un test ou un batch"));
    const actionCopy = document.createElement("div");
    actionCopy.className = "muted";
    actionCopy.textContent = "Choisissez un film précis ou déclenchez un batch pour prioriser les cas à relire.";
    actionCard.appendChild(actionCopy);
    if(actionRow){
      actionRow.classList.add("qualityPrimaryActions", "mt12");
      actionCard.appendChild(actionRow);
    }
    if(batchRow){
      batchRow.classList.add("qualityBatchRail", "mt12");
      actionCard.appendChild(batchRow);
    }
    if(manualIds){
      actionCard.appendChild(manualIds);
    }

    const resultStack = document.createElement("div");
    resultStack.className = "qualityResultStack";

    const batchCard = document.createElement("div");
    batchCard.className = "card qualityResultCard nextWorkbenchCard nextDataZone";
    const batchHead = createNextQualityBlockHead("Résultat batch", "Progression et synthèse");
    if(batchMsg){
      batchMsg.classList.add("qualityInlineStatus");
      batchHead.appendChild(batchMsg);
    }
    batchCard.appendChild(batchHead);
    if(batchOut){
      batchCard.appendChild(batchOut);
    }

    const testCard = document.createElement("div");
    testCard.className = "card qualityResultCard nextWorkbenchCard nextDataZone";
    const testHead = createNextQualityBlockHead("Résultat unitaire", "Détail du film ciblé");
    if(testMsg){
      testMsg.classList.add("qualityInlineStatus");
      testHead.appendChild(testMsg);
    }
    testCard.appendChild(testHead);
    if(testOut){
      testCard.appendChild(testOut);
    }

    resultStack.appendChild(batchCard);
    resultStack.appendChild(testCard);
    grid.appendChild(actionCard);
    grid.appendChild(resultStack);

    overviewPanel.replaceChildren(grid);
  }

  const filtersCard = $("quality-panel-filters")?.querySelector(".card");
  if(filtersCard){
    filtersCard.classList.add("qualityFilterCard", "nextWorkbenchCard", "nextFilterZone");
    ensureNextQualityCardHeader(filtersCard, "Filtres");
    filtersCard.querySelector(".qualityBatchRow")?.classList.add("qualityFilterGrid");
  }

  const toolsCard = $("quality-panel-tools")?.querySelector(".card");
  if(toolsCard){
    toolsCard.classList.add("qualityToolsCard", "nextWorkbenchCard", "nextSupportZone");
    ensureNextQualityCardHeader(toolsCard, "Outils d’analyse");
    toolsCard.querySelector(".grid2")?.classList.add("qualityToolsGrid");
    toolsCard.querySelectorAll(".grid2 > .field").forEach((el) => {
      el.classList.add("qualityToolStatus");
    });
    toolsCard.querySelector(".row.mt10.wrap")?.classList.add("qualitySecondaryActions");
    toolsCard.querySelector(".row.mt8.wrap")?.classList.add("qualityManualToolRow");
  }

  const profileCard = $("quality-panel-profile")?.querySelector(".card");
  if(profileCard){
    profileCard.classList.add("qualityProfileCard", "nextWorkbenchCard", "nextSupportZone");
    ensureNextQualityCardHeader(profileCard, "Profil scoring");
    profileCard.querySelector(".qualityPresetRow")?.classList.add("qualityPresetRowNext");
    profileCard.querySelector(".row.mt12.wrap")?.classList.add("qualityProfileActions");
  }
}

