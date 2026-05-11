(function(){
  const ROOT = "D:\\Media\\Movies";
  const STATE = "D:\\Media\\CineSortState";
  const FF = "C:\\Tools\\ffprobe.exe";
  const MI = "C:\\Tools\\MediaInfo.exe";

  function clone(v){ return JSON.parse(JSON.stringify(v)); }
  function merge(base, patch){
    const out = clone(base);
    const src = patch && typeof patch === "object" ? patch : {};
    Object.keys(src).forEach((k) => {
      const a = out[k];
      const b = src[k];
      if(a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)){
        out[k] = merge(a, b);
      } else {
        out[k] = clone(b);
      }
    });
    return out;
  }

  function qualityProfile(id, version, patch){
    return merge({
      id,
      version,
      engine_version: "CinemaLux_v1",
      weights: { video: 60, audio: 30, extras: 10 },
      toggles: { include_metadata: true, include_naming: true, enable_4k_light: true },
      video_thresholds: {
        bitrate_min_kbps_2160p: 18000,
        bitrate_min_kbps_1080p: 8000,
        penalty_low_bitrate: 14,
        penalty_4k_light: 7,
        penalty_hdr_8bit: 8,
      },
      hdr_bonuses: { dv_bonus: 12, hdr10p_bonus: 10, hdr10_bonus: 8 },
      codec_bonuses: { hevc_bonus: 8, av1_bonus: 9, avc_bonus: 5 },
      audio_bonuses: {
        truehd_atmos_bonus: 12,
        dts_hd_ma_bonus: 10,
        dts_bonus: 6,
        aac_bonus: 3,
        channels_bonus_map: { "2.0": 2, "5.1": 6, "7.1": 8 },
      },
      languages: { bonus_vo_present: 4, bonus_vf_present: 2 },
      tiers: { premium: 85, bon: 70, moyen: 55 },
    }, patch || {});
  }

  function presets(){
    return [
      {
        preset_id: "cinelux_balanced",
        profile_id: "CinemaLux_v1",
        description: "Profil equilibre pour les runs de production.",
        profile_json: qualityProfile("CinemaLux_v1", 3),
      },
      {
        preset_id: "cinelux_prudent",
        profile_id: "CinemaLux_v1",
        description: "Version plus stricte pour isoler les editions faibles.",
        profile_json: qualityProfile("CinemaLux_v1", 4, {
          video_thresholds: {
            bitrate_min_kbps_2160p: 22000,
            bitrate_min_kbps_1080p: 9000,
            penalty_low_bitrate: 18,
            penalty_4k_light: 10,
            penalty_hdr_8bit: 10,
          },
        }),
      },
    ];
  }

  function settings(kind){
    const ready = {
      root: ROOT,
      state_dir: STATE,
      tmdb_enabled: true,
      tmdb_timeout_s: 12,
      tmdb_api_key: "preview_tmdb_demo_key",
      remember_key: true,
      collection_folder_enabled: true,
      collection_folder_name: "_Collection",
      empty_folders_folder_name: "_Vide",
      move_empty_folders_enabled: true,
      cleanup_residual_folders_folder_name: "_Dossier Nettoyage",
      cleanup_residual_folders_enabled: true,
      cleanup_residual_folders_scope: "touched_only",
      cleanup_residual_include_nfo: true,
      cleanup_residual_include_images: false,
      cleanup_residual_include_subtitles: false,
      cleanup_residual_include_texts: true,
      incremental_scan_enabled: true,
      empty_folders_scope: "touched_only",
      quarantine_unapproved: true,
      dry_run_apply: true,
      ffprobe_path: FF,
      mediainfo_path: MI,
      probe_backend: "auto",
    };
    if(kind === "first_launch"){
      return merge(ready, {
        root: "",
        state_dir: "",
        tmdb_api_key: "",
        remember_key: false,
        incremental_scan_enabled: false,
        empty_folders_scope: "root_all",
        ffprobe_path: "",
        mediainfo_path: "",
      });
    }
    if(kind === "apply_real"){
      return merge(ready, { dry_run_apply: false });
    }
    return ready;
  }

  function probe(kind){
    const ready = {
      ok: true,
      hybrid_ready: true,
      degraded_mode: "none",
      message: "Diagnostic preview stable.",
      installer: { supported: true, winget_available: false },
      tools: {
        ffprobe: { available: true, status: "ok", version: "7.0", source: "configured", message: "" },
        mediainfo: { available: true, status: "ok", version: "24.02", source: "configured", message: "" },
      },
    };
    if(kind === "first_launch"){
      return merge(ready, {
        hybrid_ready: false,
        message: "Aucun outil configure dans ce scenario.",
        tools: {
          ffprobe: { available: false, status: "missing", version: "", source: "none", message: "Chemin manquant." },
          mediainfo: { available: false, status: "missing", version: "", source: "none", message: "Chemin manquant." },
        },
      });
    }
    if(kind === "quality_partial"){
      return merge(ready, {
        hybrid_ready: false,
        degraded_mode: "ffprobe_only",
        message: "Preview degrade: MediaInfo absent dans ce scenario.",
        tools: {
          mediainfo: { available: false, status: "missing", version: "", source: "none", message: "Chemin non fourni dans ce scenario." },
        },
      });
    }
    return ready;
  }

  function rows(runId, flavor){
    const safe = flavor === "safe";
    const quality = flavor === "quality_anomalies";
    return [
      {
        row_id: runId + "-row-001",
        kind: "single",
        folder: ROOT + "\\Dune Part Two",
        video: "Dune.Part.Two.2024.2160p.UHD.BluRay.DV.TrueHD.Atmos.mkv",
        proposed_title: "Dune: Part Two",
        proposed_year: 2024,
        proposed_source: "nfo",
        confidence_label: "high",
        confidence: 96,
        detected_year: 2024,
        notes: "NFO coherente, nommage stable, cible de dossier propre.",
        warning_flags: [],
        candidates: [
          { title: "Dune: Part Two", year: 2024, score: 99, source: "nfo", tmdb_id: 693134 },
          { title: "Dune Part 2", year: 2024, score: 91, source: "tmdb", tmdb_id: 693134 },
        ],
      },
      {
        row_id: runId + "-row-002",
        kind: "single",
        folder: ROOT + "\\Blade Runner 2049 (2016)",
        video: "Blade.Runner.2049.2017.2160p.HDR10.AC3.mkv",
        proposed_title: "Blade Runner 2049",
        proposed_year: quality ? 2016 : 2017,
        proposed_source: safe ? "nfo" : "tmdb",
        confidence_label: safe ? "high" : "med",
        confidence: safe ? 91 : (quality ? 61 : 72),
        detected_year: 2017,
        notes: safe ? "Titre et annee consolides. Cible plausible." : (quality ? "Conflit dossier/fichier. dY=1 via TMDb. 4K SDR, debit faible." : "Conflit dossier/fichier. dY=1 via TMDb."),
        warning_flags: safe ? [] : ["year_conflict_folder_file", "tmdb_year_delta"],
        candidates: [
          { title: "Blade Runner 2049", year: 2017, score: 92, source: "tmdb", tmdb_id: 335984 },
          { title: "Blade Runner 2049", year: 2016, score: 64, source: "name" },
        ],
      },
      {
        row_id: runId + "-row-003",
        kind: "single",
        folder: ROOT + "\\Alien Romulus",
        video: "Alien.Romulus.2024.2160p.WEB-DL.SDR.AAC.mkv",
        proposed_title: "Alien: Romulus",
        proposed_year: 2024,
        proposed_source: safe ? "tmdb" : "name",
        confidence_label: safe ? "med" : "low",
        confidence: safe ? 68 : (quality ? 41 : 52),
        detected_year: 2024,
        notes: safe ? "Cas moyen mais plausible. Relire si besoin." : (quality ? "NFO ignore: annee incoherente. VO absente, probe partiel." : "NFO ignore: annee incoherente."),
        warning_flags: safe ? [] : ["nfo_year_mismatch"],
        candidates: [
          { title: "Alien: Romulus", year: 2024, score: 76, source: "tmdb", tmdb_id: 945961 },
          { title: "Alien Romulus", year: 2024, score: 68, source: "name" },
        ],
      },
      {
        row_id: runId + "-row-004",
        kind: "collection",
        folder: ROOT + "\\Christopher Nolan Collection",
        video: "",
        proposed_title: "Christopher Nolan Collection",
        proposed_year: 0,
        proposed_source: "name",
        confidence_label: safe ? "high" : "med",
        confidence: safe ? 86 : 70,
        detected_year: 0,
        notes: "Ligne collection. Verification visuelle rapide recommande.",
        warning_flags: [],
        candidates: [{ title: "Christopher Nolan Collection", year: 0, score: 88, source: "name" }],
      },
    ];
  }

  function qualityReports(runId, flavor){
    const quality = flavor === "quality_anomalies";
    return {
      [runId + "-row-001"]: {
        ok: true, status: "analyzed", score: 91, tier: "premium", profile_id: "CinemaLux_v1", profile_version: 3, probe_quality: "hybrid", cache_hit_probe: true,
        confidence: { label: "elevee", value: 92 },
        explanation: { narrative: "Master UHD tres solide, HDR haut de gamme et audio premium.", top_positive: [{ label: "Dolby Vision" }, { label: "TrueHD Atmos" }], top_negative: [], factors: [{ category: "video", label: "HDR Dolby Vision", delta: 12 }, { category: "audio", label: "Piste TrueHD Atmos", delta: 10 }, { category: "codec", label: "HEVC propre", delta: 8 }] },
        reasons: ["Source stable via NFO", "Bitrate 4K conforme au profil", "Audio premium detecte"],
      },
      [runId + "-row-002"]: {
        ok: true, status: "analyzed", score: quality ? 46 : (flavor === "safe" ? 74 : 58), tier: quality ? "faible" : (flavor === "safe" ? "bon" : "moyen"), profile_id: "CinemaLux_v1", profile_version: 3, probe_quality: "hybrid", cache_hit_probe: true,
        confidence: { label: quality ? "moyenne" : "elevee", value: quality ? 67 : 84 },
        explanation: { narrative: quality ? "Cas relecture: annee a verifier et HDR moins convaincant que prevu." : "Edition stable, vigilance mineure seulement.", top_positive: [{ label: "Resolution 2160p" }], top_negative: quality ? [{ label: "Conflit annee" }, { label: "4K SDR" }] : [], factors: quality ? [{ category: "video", label: "4K SDR", delta: -9 }, { category: "metadata", label: "Delta annee dossier/fichier", delta: -8 }] : [{ category: "video", label: "Encode propre", delta: 6 }] },
        reasons: quality ? ["Annee TMDb et dossier divergentes", "Signal 4K SDR a relire", "Validation manuelle conseillee"] : ["Edition saine", "Verification annee recommandee mais non bloquante"],
      },
      [runId + "-row-003"]: {
        ok: true, status: "analyzed", score: quality ? 39 : (flavor === "safe" ? 57 : 43), tier: quality ? "faible" : (flavor === "safe" ? "moyen" : "faible"), profile_id: "CinemaLux_v1", profile_version: 3, probe_quality: quality ? "partial" : "hybrid", cache_hit_probe: true,
        confidence: { label: "moyenne", value: quality ? 60 : 72 },
        explanation: { narrative: quality ? "Edition faible: debit bas, piste VO absente et fiabilite metadata limitee." : "Edition moyenne, exploitable mais non premium.", top_positive: [{ label: "Titre retrouve" }], top_negative: quality ? [{ label: "VO absente" }, { label: "Debit 4K faible" }] : [{ label: "Audio limite" }], factors: quality ? [{ category: "video", label: "Bitrate faible", delta: -14 }, { category: "audio", label: "VO absente", delta: -10 }, { category: "metadata", label: "NFO incoherent", delta: -6 }] : [{ category: "video", label: "Bitrate moyen", delta: -4 }] },
        reasons: quality ? ["Probe incomplet ou degrade", "Edition 4K faible", "Relire avant validation"] : ["Edition moyenne", "Peut rester a verifier selon la politique"],
      },
      [runId + "-row-004"]: {
        ok: true, status: "analyzed", score: 73, tier: "bon", profile_id: "CinemaLux_v1", profile_version: 3, probe_quality: "n/a", cache_hit_probe: true,
        confidence: { label: "moyenne", value: 71 },
        explanation: { narrative: "Ligne collection correcte, a conserver comme regroupement logique.", top_positive: [{ label: "Regroupement stable" }], top_negative: [], factors: [{ category: "metadata", label: "Structure collection claire", delta: 6 }] },
        reasons: ["Collection detectee proprement"],
      },
    };
  }

  function decisions(runId, flavor){
    const safe = flavor === "safe";
    const quality = flavor === "quality_anomalies";
    return {
      [runId + "-row-001"]: { ok: true, title: "Dune: Part Two", year: 2024 },
      [runId + "-row-002"]: { ok: safe, title: "Blade Runner 2049", year: quality ? 2016 : 2017 },
      [runId + "-row-003"]: { ok: false, title: "Alien: Romulus", year: 2024 },
      [runId + "-row-004"]: { ok: safe, title: "Christopher Nolan Collection", year: 0 },
    };
  }

  function dashboard(runId, runDir, runsHistory, flavor, totalRows){
    const safe = flavor === "safe";
    const quality = flavor === "quality_anomalies";
    return {
      ok: true,
      run_id: runId,
      run_dir: runDir,
      runs_history: clone(runsHistory),
      kpis: {
        total_movies: totalRows,
        scored_movies: totalRows,
        score_avg: quality ? 52.3 : (safe ? 79.6 : 66.8),
        score_premium_pct: quality ? 12.5 : (safe ? 50.0 : 25.0),
        probe_partial_count: quality ? 2 : (safe ? 0 : 1),
      },
      anomalies_top: quality ? [
        { severity: "ERROR", row_id: runId + "-row-003", code: "LOW_SCORE", message: "Edition 4K faible et VO absente", recommended_action: "Passer par A verifier puis relire la cible", path: ROOT + "\\Alien Romulus" },
        { severity: "WARN", row_id: runId + "-row-002", code: "YEAR_CONFLICT", message: "Conflit dossier/fichier et delta annee TMDb", recommended_action: "Confirmer l'annee avant validation", path: ROOT + "\\Blade Runner 2049 (2016)" },
        { severity: "WARN", row_id: runId + "-row-004", code: "COLLECTION_CHECK", message: "Collection a verifier avant apply reel", recommended_action: "Controle rapide du regroupement", path: ROOT + "\\Christopher Nolan Collection" },
      ] : (safe ? [
        { severity: "INFO", row_id: runId + "-row-003", code: "MINOR_REVIEW", message: "Un cas moyen reste disponible pour relecture rapide", recommended_action: "Verification optionnelle", path: ROOT + "\\Alien Romulus" },
      ] : [
        { severity: "WARN", row_id: runId + "-row-002", code: "YEAR_CONFLICT", message: "Conflit dossier/fichier sur l'annee retenue", recommended_action: "Relire le dossier avant validation", path: ROOT + "\\Blade Runner 2049 (2016)" },
        { severity: "WARN", row_id: runId + "-row-003", code: "LOW_BITRATE", message: "Edition faible detectee sur Alien Romulus", recommended_action: "Verifier la qualite et la source", path: ROOT + "\\Alien Romulus" },
      ]),
      outliers: {
        low_bitrate: quality ? [{ title: "Alien: Romulus", year: 2024, bitrate_kbps: 9700, path: ROOT + "\\Alien Romulus" }] : [],
        sdr_4k: quality ? [{ title: "Blade Runner 2049", year: 2017, path: ROOT + "\\Blade Runner 2049 (2016)" }] : [],
        vo_missing: quality ? [{ title: "Alien: Romulus", year: 2024, path: ROOT + "\\Alien Romulus" }] : [],
      },
      distributions: {
        score_bins: quality ? [{ label: "0-44", count: 1 }, { label: "45-59", count: 2 }, { label: "60-74", count: 1 }, { label: "75-84", count: 0 }, { label: "85-100", count: 1 }] : (safe ? [{ label: "0-44", count: 0 }, { label: "45-59", count: 0 }, { label: "60-74", count: 2 }, { label: "75-84", count: 1 }, { label: "85-100", count: 1 }] : [{ label: "0-44", count: 1 }, { label: "45-59", count: 1 }, { label: "60-74", count: 2 }, { label: "75-84", count: 0 }, { label: "85-100", count: 1 }]),
        resolutions: { "2160p": 3, "1080p": 1 },
        hdr: quality ? { "DV": 1, "HDR10": 1, "SDR": 2 } : { "DV": 1, "HDR10": 1, "SDR": 1, "HDR10+": 1 },
        audio_codecs: [{ label: "TrueHD/Atmos", count: 1 }, { label: "DTS-HD MA", count: 1 }, { label: "AAC", count: 2 }],
      },
    };
  }

  function cleanupPreview(kind){
    return {
      ok: true,
      preview: {
        enabled: true,
        status: "ready",
        reason_code: "",
        inspected_count: kind === "apply_result" ? 7 : 6,
        eligible_count: kind === "quality_anomalies" ? 1 : 2,
        has_video_count: 0,
        target_folder_name: "_Dossier Nettoyage",
        scope: "touched_only",
        sample_candidate_dirs: [ROOT + "\\Temp Residual 1", ROOT + "\\Temp Residual 2"],
        sample_video_blocked_dirs: [],
      },
    };
  }

  function undoPreview(runId, kind){
    return kind === "apply_result"
      ? { ok: true, run_id: runId, batch_id: "preview-apply-002", can_undo: true, undo_available: true, counts: { total: 12, reversible: 12, irreversible: 0, conflicts_predicted: 0 }, categories: { empty_folder_dirs: 1, cleanup_residual_dirs: 2 }, message: "Dernier apply simule disponible pour undo." }
      : { ok: true, run_id: runId, batch_id: "preview-apply-001", can_undo: false, undo_available: false, counts: { total: 0, reversible: 0, irreversible: 0, conflicts_predicted: 0 }, categories: { empty_folder_dirs: 0, cleanup_residual_dirs: 0 }, message: kind === "apply_dry_run" ? "Dry-run uniquement: aucun undo reel disponible." : "Pas d'undo reel dans ce scenario." };
  }

  function duplicates(runId, flavor){
    if(flavor === "safe"){
      return { ok: true, total_groups: 0, checked_rows: 3, groups: [] };
    }
    return {
      ok: true,
      total_groups: 1,
      checked_rows: 2,
      groups: [{
        title: "Alien: Romulus",
        year: 2024,
        plan_conflict: false,
        existing_paths: [ROOT + "\\Alien Romulus (2024)"],
        rows: [{ row_id: runId + "-row-003", kind: "single", source_folder: ROOT + "\\Alien Romulus", target: ROOT + "\\Alien Romulus (2024)" }],
      }],
    };
  }

  function uiSeed(runId, kind){
    if(kind !== "apply_result"){ return {}; }
    return {
      runId,
      pillStatus: "Apply simulé",
      applyResultText: ["Application réelle", "", "- Renommages de dossiers : 3", "- Déplacements de fichiers : 9", "- Dossiers créés (Collection, _review, sous-dossiers) : 4", "- Dossiers de collection déplacés dans le dossier collections : 1", "- Éléments placés en _review : 1", "- Éléments non appliqués : 1", "- Erreurs : 0"].join("\n"),
      cleanupResidualLastResult: {
        run_id: runId,
        dry_run: false,
        diagnostic: { enabled: true, status_post: "executed", moved_count: 2, untouched_count: 1, inspected_count: 7, eligible_count: 2, target_folder_name: "_Dossier Nettoyage", scope: "touched_only", has_video_count: 0 },
      },
    };
  }

  function emptyScenario(id, label, description, view, settingsKind, probeKind){
    const p = presets();
    return {
      id, label, description, defaultView: view, activeRunId: "",
      settings: settings(settingsKind),
      probeToolsStatus: probe(probeKind),
      qualityPresets: clone(p),
      qualityProfile: clone(p[0].profile_json),
      runsHistory: [],
      dashboardsByRunId: {
        latest: {
          ok: true, run_id: "", run_dir: "", runs_history: [],
          kpis: { total_movies: 0, scored_movies: 0, score_avg: 0, score_premium_pct: 0, probe_partial_count: 0 },
          anomalies_top: [], outliers: { low_bitrate: [], sdr_4k: [], vo_missing: [] },
          distributions: { score_bins: [], resolutions: {}, hdr: {}, audio_codecs: [] },
        },
      },
      plansByRunId: {}, validationsByRunId: {}, duplicatesByRunId: {}, cleanupPreviewByRunId: {}, undoPreviewByRunId: {}, qualityReportsByRunId: {}, uiSeed: {},
      simulatedPlanRunId: "preview-run-2026-03-09-first",
      simulatedPlanLogs: [{ ts: "09:30:01", level: "INFO", msg: "Premier run preview initialise." }, { ts: "09:30:02", level: "INFO", msg: "Plan READY." }],
    };
  }

  function runScenario(cfg){
    const runId = cfg.runId;
    const prevRun = cfg.prevRunId || "preview-run-2026-03-05-z";
    const runDir = STATE + "\\runs\\tri_films_" + runId;
    const prevRunDir = STATE + "\\runs\\tri_films_" + prevRun;
    const rowFlavor = cfg.rowFlavor || "review";
    const mainRows = rows(runId, rowFlavor);
    const prevRows = rows(prevRun, "safe").slice(0, 3);
    const history = [
      { run_id: runId, run_dir: runDir, started_ts: cfg.startedTs || 1773027000, duration_s: cfg.durationS || 241, total_rows: mainRows.length, applied_rows: cfg.appliedRows || 0, errors_count: 0, anomalies_count: cfg.anomaliesCount || 0 },
      { run_id: prevRun, run_dir: prevRunDir, started_ts: 1772686800, duration_s: 198, total_rows: prevRows.length, applied_rows: 3, errors_count: 0, anomalies_count: 1 },
    ];
    if(cfg.extraHistory){
      history.push(
        { run_id: "preview-run-2026-03-01-k", run_dir: STATE + "\\runs\\tri_films_preview-run-2026-03-01-k", started_ts: 1772337600, duration_s: 214, total_rows: 5, applied_rows: 4, errors_count: 0, anomalies_count: 2 },
        { run_id: "preview-run-2026-02-25-c", run_dir: STATE + "\\runs\\tri_films_preview-run-2026-02-25-c", started_ts: 1771992000, duration_s: 189, total_rows: 6, applied_rows: 6, errors_count: 0, anomalies_count: 0 },
      );
    }
    const p = presets();
    const dash = dashboard(runId, runDir, history, cfg.qualityFlavor || rowFlavor, mainRows.length);
    return {
      id: cfg.id,
      label: cfg.label,
      description: cfg.description,
      defaultView: cfg.defaultView,
      activeRunId: runId,
      settings: settings(cfg.settingsKind || "ready"),
      probeToolsStatus: probe(cfg.probeKind || "ready"),
      qualityPresets: clone(p),
      qualityProfile: clone(p[0].profile_json),
      runsHistory: clone(history),
      dashboardsByRunId: {
        latest: clone(dash),
        [runId]: clone(dash),
        [prevRun]: dashboard(prevRun, prevRunDir, history, "safe", prevRows.length),
      },
      plansByRunId: { [runId]: { ok: true, rows: clone(mainRows) }, [prevRun]: { ok: true, rows: clone(prevRows) } },
      validationsByRunId: { [runId]: { ok: true, decisions: decisions(runId, cfg.validationFlavor || rowFlavor) } },
      duplicatesByRunId: { [runId]: duplicates(runId, cfg.duplicateFlavor || rowFlavor) },
      cleanupPreviewByRunId: { [runId]: cleanupPreview(cfg.cleanupKind || rowFlavor) },
      undoPreviewByRunId: { [runId]: undoPreview(runId, cfg.undoKind || rowFlavor) },
      qualityReportsByRunId: { [runId]: qualityReports(runId, cfg.qualityFlavor || rowFlavor) },
      uiSeed: uiSeed(runId, cfg.uiSeedKind || ""),
      simulatedPlanRunId: "preview-run-2026-03-09-live",
      simulatedPlanLogs: [{ ts: "09:12:01", level: "INFO", msg: "Scan preview demarre." }, { ts: "09:12:02", level: "INFO", msg: "Indexation des dossiers video." }, { ts: "09:12:03", level: "INFO", msg: "Matching TMDb simule." }, { ts: "09:12:04", level: "INFO", msg: "Plan READY." }],
    };
  }

  const firstLaunch = emptyScenario("first_launch", "Premier lancement", "Aucun run, configuration incomplete, onboarding visible.", "home", "first_launch", "first_launch");
  const appReady = emptyScenario("app_ready", "App prête", "Environnement complet et sain, mais aucun run encore lance.", "home", "ready", "ready");
  const runRecentSafe = runScenario({ id: "run_recent_safe", label: "Run récent sûr", description: "Run récent avec majorité de cas sûrs et environnement stable.", defaultView: "home", runId: "preview-run-2026-03-09-safe", rowFlavor: "safe", validationFlavor: "safe", qualityFlavor: "safe", duplicateFlavor: "safe", anomaliesCount: 1 });
  const runToReview = runScenario({ id: "run_to_review", label: "Run à vérifier", description: "Run récent avec plusieurs cas à relire avant validation.", defaultView: "home", runId: "preview-run-2026-03-09-review", rowFlavor: "review", validationFlavor: "review", qualityFlavor: "review", anomaliesCount: 2 });
  const qualityAnomalies = runScenario({ id: "quality_anomalies", label: "Qualité avec anomalies", description: "Vue Qualité chargée avec signaux forts, outliers et probe partiel.", defaultView: "quality", runId: "preview-run-2026-03-09-quality", rowFlavor: "quality_anomalies", validationFlavor: "review", qualityFlavor: "quality_anomalies", probeKind: "quality_partial", anomaliesCount: 3 });
  const validationLoaded = runScenario({ id: "validation_loaded", label: "Validation chargée", description: "Table de validation chargée avec cas sûrs et cas à relire.", defaultView: "validation", runId: "preview-run-2026-03-09-validate", rowFlavor: "review", validationFlavor: "review", qualityFlavor: "review", anomaliesCount: 2 });
  const applyDryRun = runScenario({ id: "apply_dry_run", label: "Application dry-run", description: "Vue Execution en mode test avec nettoyage résiduel prévisualisé.", defaultView: "execution", runId: "preview-run-2026-03-09-dry", rowFlavor: "review", validationFlavor: "review", qualityFlavor: "review", undoKind: "apply_dry_run", anomaliesCount: 2 });
  const applyResult = runScenario({ id: "apply_result", label: "Application avec résultat", description: "Etat post-apply avec résumé visible, nettoyage exécuté et undo disponible.", defaultView: "execution", runId: "preview-run-2026-03-09-apply", rowFlavor: "review", validationFlavor: "review", qualityFlavor: "review", settingsKind: "apply_real", cleanupKind: "apply_result", undoKind: "apply_result", uiSeedKind: "apply_result", appliedRows: 3, anomaliesCount: 1 });
  const settingsComplete = runScenario({ id: "settings_complete", label: "Paramètres complets", description: "Configuration opérateur complète avec environnement prêt et prudence active.", defaultView: "settings", runId: "preview-run-2026-03-09-settings", rowFlavor: "safe", validationFlavor: "safe", qualityFlavor: "safe", duplicateFlavor: "safe", anomaliesCount: 0 });
  const logsArtifacts = runScenario({ id: "logs_artifacts", label: "Journaux et artefacts", description: "Historique étendu avec plusieurs runs récents et exports disponibles.", defaultView: "history", runId: "preview-run-2026-03-09-logs", rowFlavor: "review", validationFlavor: "review", qualityFlavor: "review", anomaliesCount: 2, appliedRows: 2, extraHistory: true });

  window.CineSortPreviewScenarios = {
    defaultScenarioId: "run_recent_safe",
    scenarios: {
      first_launch: firstLaunch,
      app_ready: appReady,
      run_recent_safe: runRecentSafe,
      run_to_review: runToReview,
      quality_anomalies: qualityAnomalies,
      validation_loaded: validationLoaded,
      apply_dry_run: applyDryRun,
      apply_result: applyResult,
      settings_complete: settingsComplete,
      logs_artifacts: logsArtifacts,
      baseline: runRecentSafe,
      quality_focus: qualityAnomalies,
      no_run: firstLaunch,
    },
  };
})();
