/* Mock window.pywebview.api riche pour audit visuel UI principale.
 *
 * Injection : page.add_init_script() AVANT chargement de index.html.
 * Le mock simule toutes les methodes API avec des donnees realistes
 * permettant a l'app de rendre toutes ses vues sans crash.
 *
 * Strategie : 3 niveaux
 *  1. Methodes critiques (get_settings, get_dashboard, ...) avec donnees riches.
 *  2. Methodes connues (apply, undo, ...) avec ok:true minimal.
 *  3. Fallback proxy : toute methode inconnue retourne {ok:true} pour eviter crash.
 */
(function () {
  "use strict";

  // -- Fixtures realistes --------------------------------------------------

  const FILMS = [
    { row_id: "r1", title: "Inception", year: 2010, res: "1080p", score: 87, tier: "Platinum" },
    { row_id: "r2", title: "Interstellar", year: 2014, res: "2160p", score: 92, tier: "Platinum" },
    { row_id: "r3", title: "Avengers Endgame", year: 2019, res: "1080p", score: 78, tier: "Gold" },
    { row_id: "r4", title: "The Matrix", year: 1999, res: "1080p", score: 81, tier: "Gold" },
    { row_id: "r5", title: "Pulp Fiction", year: 1994, res: "1080p", score: 75, tier: "Gold" },
    { row_id: "r6", title: "The Room", year: 2003, res: "720p", score: 35, tier: "Bronze" },
    { row_id: "r7", title: "Cats", year: 2019, res: "1080p", score: 28, tier: "Reject" },
    { row_id: "r8", title: "Parasite", year: 2019, res: "2160p", score: 89, tier: "Platinum" },
    { row_id: "r9", title: "Old Boy", year: 2003, res: "1080p", score: 70, tier: "Silver" },
    { row_id: "r10", title: "Old Boy", year: 2013, res: "720p", score: 42, tier: "Bronze" },
    { row_id: "r11", title: "Captain America Civil War", year: 2016, res: "1080p", score: 68, tier: "Silver" },
    { row_id: "r12", title: "Iron Man", year: 2008, res: "1080p", score: 80, tier: "Gold" },
    { row_id: "r13", title: "Thor", year: 2011, res: "1080p", score: 58, tier: "Silver" },
    { row_id: "r14", title: "Black Panther", year: 2018, res: "2160p", score: 86, tier: "Platinum" },
    { row_id: "r15", title: "Spider Man Far From Home", year: 2019, res: "1080p", score: 73, tier: "Gold" },
  ];

  function _row(f, idx) {
    return {
      row_id: f.row_id,
      kind: "single",
      folder: `D:/Films/${f.title.replace(/ /g, ".")}`,
      video: `${f.title.replace(/ /g, ".")}.${f.year}.${f.res}.mkv`,
      proposed_title: f.title,
      proposed_year: f.year,
      proposed_source: "name",
      confidence: f.score,
      confidence_label: f.score >= 80 ? "high" : f.score >= 60 ? "med" : "low",
      candidates: [{ title: f.title, year: f.year, source: "name", tmdb_id: 10000 + idx, score: 0.9 }],
      warning_flags: [],
      tmdb_collection_id: null,
      tmdb_collection_name: null,
      edition: null,
      source_root: null,
      subtitle_count: 2,
      subtitle_languages: ["fr", "en"],
      subtitle_formats: ["srt"],
      subtitle_missing_langs: [],
      subtitle_orphans: 0,
      tv_series_name: null,
      tv_season: null,
      tv_episode: null,
      tv_episode_title: null,
      tv_tmdb_series_id: null,
      _score: f.score,
      _resolution: f.res,
      _codec: "hevc",
      _audio: "eac3",
    };
  }

  const ROWS = FILMS.map((f, i) => _row(f, i));
  const RUN_ID = "20260429_audit_001";
  const TOKEN = "audit_visual_token_xxxxxxxxxxxxxxxx_32";

  // -- Donnees agregees (KPIs, distribution) -------------------------------

  function _tierDistribution() {
    const counts = {};
    for (const f of FILMS) counts[f.tier] = (counts[f.tier] || 0) + 1;
    return counts;
  }

  function _avgScore() {
    return Math.round(FILMS.reduce((s, f) => s + f.score, 0) / FILMS.length);
  }

  function _premiumPct() {
    const n = FILMS.filter((f) => f.tier === "Platinum").length;
    return Math.round((n / FILMS.length) * 100);
  }

  // -- Methodes API mockees ------------------------------------------------

  const SETTINGS = {
    root: "D:/Films",
    roots: ["D:/Films", "E:/NAS/Cinema"],
    state_dir: "C:/Users/Demo/AppData/Local/CineSort",
    tmdb_enabled: true,
    tmdb_api_key: "***mocked***",
    enable_collection_folder: true,
    collection_root_name: "_Collection",
    enable_tv_detection: false,
    incremental_scan_enabled: true,
    quality_preset: "default",
    naming_preset: "plex",
    naming_movie_template: "{title} ({year}) {tmdb_tag}",
    naming_tv_template: "{series} ({year})",
    theme: "studio",
    animation_level: "moderate",
    effect_speed: 1.0,
    glow_intensity: 1.0,
    light_intensity: 1.0,
    notifications_enabled: true,
    notifications_scan_done: true,
    notifications_apply_done: true,
    notifications_undo_done: true,
    notifications_errors: true,
    rest_api_enabled: false,
    rest_api_port: 8642,
    rest_api_token: TOKEN,
    rest_api_https_enabled: false,
    watch_enabled: false,
    watch_interval_minutes: 5,
    plugins_enabled: false,
    plugins_timeout_s: 30,
    perceptual_enabled: true,
    perceptual_auto_on_quality: true,
    jellyfin_enabled: false,
    plex_enabled: false,
    radarr_enabled: false,
    auto_approve_enabled: true,
    auto_approve_threshold: 85,
    onboarding_completed: true,
  };

  const QUALITY_REPORTS = {};
  for (const f of FILMS) {
    QUALITY_REPORTS[f.row_id] = {
      score: f.score,
      tier: f.tier,
      reasons: ["Resolution OK", "Codec moderne", "Audio premium"],
      metrics: {
        resolution: f.res,
        video_codec: "hevc",
        audio_codec: "eac3",
        channels: "5.1",
        hdr: f.res === "2160p" ? "HDR10" : "SDR",
        bitrate_kbps: f.res === "2160p" ? 18000 : 9000,
        duration_s: 7200,
      },
    };
  }

  const HOME_INSIGHTS = [
    {
      code: "lib.health",
      severity: "info",
      title: "Bibliotheque saine",
      message: "Aucun probleme critique detecte sur les 15 films analyses.",
      ts: Date.now() / 1000 - 3600,
    },
    {
      code: "lib.upgrade_candidates",
      severity: "warning",
      title: "2 candidats a l'upgrade",
      message: "2 films ont un score < 60 et pourraient beneficier d'une meilleure version.",
      ts: Date.now() / 1000 - 7200,
    },
  ];

  const RUNS_SUMMARY = [
    {
      run_id: RUN_ID,
      status: "DONE",
      started_ts: Date.now() / 1000 - 1800,
      ended_ts: Date.now() / 1000 - 1500,
      total_rows: FILMS.length,
      score_avg: _avgScore(),
      premium_count: FILMS.filter((f) => f.tier === "Platinum").length,
      health_snapshot: { health_score: 92, subtitle_coverage_pct: 100, resolution_4k_pct: 27, codec_modern_pct: 100 },
    },
    {
      run_id: "20260428_old_001",
      status: "DONE",
      started_ts: Date.now() / 1000 - 86400,
      ended_ts: Date.now() / 1000 - 86100,
      total_rows: FILMS.length - 5,
      score_avg: _avgScore() - 3,
      premium_count: 3,
      health_snapshot: { health_score: 88, subtitle_coverage_pct: 95, resolution_4k_pct: 20, codec_modern_pct: 95 },
    },
  ];

  const API = {
    // -- Initialisation ----
    get_settings: () => ({ ...SETTINGS }),
    save_settings: (settings) => ({ ok: true, settings: { ...SETTINGS, ...(settings || {}) } }),

    // -- Probe / Outils ----
    get_probe_tools_status: () => ({
      tools: {
        ffprobe: { status: "ok", version: "6.1", path: "C:/Tools/ffprobe.exe" },
        mediainfo: { status: "ok", version: "23.10", path: "C:/Tools/mediainfo.exe" },
      },
    }),
    install_probe_tools: () => ({ ok: true, installed: ["ffprobe", "mediainfo"] }),
    auto_install_probe_tools: () => ({ ok: true }),
    recheck_probe_tools: () => ({ ok: true }),
    get_probe: () => ({ ok: true, data: {} }),

    // -- Server / dashboard ----
    get_server_info: () => ({ ip: "192.168.1.50", port: 8642, dashboard_url: "http://192.168.1.50:8642/dashboard/" }),
    get_dashboard_qr: () => ({ ok: true, svg: '<svg width="160" height="160"><rect width="160" height="160" fill="#222"/><text x="50%" y="50%" fill="#fff" text-anchor="middle">QR</text></svg>' }),
    restart_api_server: () => ({ ok: true, message: "Serveur redemarre" }),

    // -- Plan / Scan ----
    start_plan: () => ({ ok: true, run_id: RUN_ID }),
    cancel_run: () => ({ ok: true }),
    get_status: () => ({
      run_id: RUN_ID,
      status: "DONE",
      idx: FILMS.length,
      total: FILMS.length,
      logs: [
        { ts: Date.now() / 1000 - 1500, level: "INFO", message: "Scan termine avec succes." },
        { ts: Date.now() / 1000 - 1600, level: "INFO", message: `${FILMS.length} films analyses.` },
      ],
      stats: {
        scanned: FILMS.length,
        skipped: 0,
        errors: 0,
        duplicates: 0,
        cache_folder_hits: 0,
        cache_row_hits: 0,
        cache_row_misses: FILMS.length,
      },
      progress: 1.0,
      speed_per_min: 30,
      eta_seconds: 0,
    }),
    get_plan: () => ({ ok: true, rows: ROWS }),
    reset_incremental_cache: () => ({ ok: true, cleared: 100 }),

    // -- Validation ----
    load_validation: () => ({ ok: true, decisions: {} }),
    save_validation: () => ({ ok: true }),
    get_auto_approved_summary: () => ({ ok: true, total: 12, auto_approved: 9, to_review: 3 }),

    // -- Apply / Undo ----
    build_apply_preview: () => ({
      ok: true,
      moves: ROWS.slice(0, 8).map((r) => ({ src: r.folder, dst: `D:/Films/${r.proposed_title} (${r.proposed_year})` })),
      conflicts: [],
      total: 8,
    }),
    apply: () => ({ ok: true, moved: 8, errors: 0, batch_id: "batch_audit_001" }),
    check_duplicates: () => ({ ok: true, duplicates: [] }),
    undo_last_apply_preview: () => ({ ok: true, ops_count: 8, conflicts: [] }),
    undo_last_apply: () => ({ ok: true, undone: 8, errors: 0 }),
    undo_by_row_preview: () => ({ ok: true, batches: [], films: [] }),
    undo_selected_rows: () => ({ ok: true, undone: 0 }),
    list_apply_history: () => ({ ok: true, batches: [] }),

    // -- Quality / Perceptual ----
    get_quality_report: (runId, rowId) => ({ ok: true, ...(QUALITY_REPORTS[rowId] || {}) }),
    analyze_quality_batch: () => ({ ok: true, scored: FILMS.length }),
    get_quality_profile: () => ({ id: "default", name: "Standard", weights: { video: 0.6, audio: 0.3, extras: 0.1 } }),
    save_quality_profile: () => ({ ok: true }),
    apply_quality_preset: () => ({ ok: true }),
    simulate_quality_preset: () => ({ ok: true, projected: { avg_score: _avgScore() + 2 } }),
    validate_custom_rules: () => ({ ok: true, errors: [] }),
    get_custom_rules_templates: () => ({ ok: true, templates: [] }),
    save_custom_quality_preset: () => ({ ok: true }),
    get_quality_presets: () => ({
      ok: true,
      presets: [
        { id: "default", name: "Standard" },
        { id: "strict", name: "Strict" },
        { id: "lenient", name: "Tolerant" },
      ],
    }),
    get_perceptual_report: () => ({ ok: true }),
    analyze_perceptual_batch: () => ({ ok: true }),
    compare_perceptual: () => ({ ok: true }),

    // -- Dashboard / library / film ----
    get_dashboard: () => ({
      ok: true,
      kpis: {
        total_movies: FILMS.length,
        avg_score: _avgScore(),
        premium_pct: _premiumPct(),
        last_run_ts: Date.now() / 1000 - 1500,
      },
      tier_distribution: _tierDistribution(),
      activity: HOME_INSIGHTS.slice(0, 3),
      runs_summary: RUNS_SUMMARY,
      rows: ROWS,
    }),
    get_global_stats: () => ({
      ok: true,
      total_movies: FILMS.length,
      avg_score: _avgScore(),
      premium_pct: _premiumPct(),
      trend: "stable",
      tier_distribution: _tierDistribution(),
      timeline: RUNS_SUMMARY.map((r) => ({
        run_id: r.run_id,
        ts: r.started_ts,
        avg_score: r.score_avg,
        total_rows: r.total_rows,
        health_snapshot: r.health_snapshot,
      })),
      runs_summary: RUNS_SUMMARY,
      space_analysis: {
        total_bytes: 1.2e12,
        avg_bytes: 8e10,
        archivable_bytes: 1.5e11,
        by_tier: { Platinum: 5e11, Gold: 4e11, Silver: 1.5e11, Bronze: 1e11, Reject: 5e10 },
        top_wasters: [],
      },
      librarian: {
        health_score: 92,
        suggestions: [
          { type: "low_resolution", priority: "low", message: "1 film en 720p", count: 1, films: [] },
          { type: "duplicates", priority: "high", message: "2 doublons potentiels detectes", count: 2, films: [] },
        ],
      },
    }),
    get_library_filtered: () => ({ ok: true, rows: ROWS, total: ROWS.length }),
    get_film_full: (rowId) => ({
      ok: true,
      row: ROWS.find((r) => r.row_id === rowId) || ROWS[0],
      probe: { width: 1920, height: 1080, codec: "hevc", duration: 7200 },
      perceptual: null,
      history: [],
      tmdb_poster_url: "",
    }),
    get_film_history: () => ({ ok: true, events: [] }),
    list_films_with_history: () => ({ ok: true, films: [] }),
    get_smart_playlists: () => ({ ok: true, playlists: [] }),
    save_smart_playlist: () => ({ ok: true }),
    delete_smart_playlist: () => ({ ok: true }),

    // -- Notifications ----
    get_notifications: () => ({ ok: true, notifications: HOME_INSIGHTS }),
    get_notifications_unread_count: () => ({ ok: true, count: 1 }),
    dismiss_notification: () => ({ ok: true }),
    mark_notification_read: () => ({ ok: true }),
    mark_all_notifications_read: () => ({ ok: true }),
    clear_notifications: () => ({ ok: true }),

    // -- Integrations ----
    test_tmdb_key: () => ({ ok: true, message: "Cle valide" }),
    get_tmdb_posters: () => ({ ok: true, posters: [] }),
    test_jellyfin_connection: () => ({ ok: false, message: "Jellyfin non configure" }),
    get_jellyfin_libraries: () => ({ ok: true, libraries: [] }),
    get_jellyfin_sync_report: () => ({ ok: false, message: "Jellyfin non configure" }),
    test_plex_connection: () => ({ ok: false, message: "Plex non configure" }),
    get_plex_libraries: () => ({ ok: true, libraries: [] }),
    get_plex_sync_report: () => ({ ok: false, message: "Plex non configure" }),
    test_radarr_connection: () => ({ ok: false, message: "Radarr non configure" }),
    get_radarr_status: () => ({ ok: true, configured: false }),
    request_radarr_upgrade: () => ({ ok: true }),

    // -- Naming ----
    preview_naming_template: () => ({
      ok: true,
      preview: "Inception (2010) {tmdb-27205}",
      warnings: [],
    }),
    get_naming_presets: () => ({
      ok: true,
      presets: [
        { id: "default", name: "Standard", template: "{title} ({year})" },
        { id: "plex", name: "Plex", template: "{title} ({year}) {tmdb_tag}" },
        { id: "jellyfin", name: "Jellyfin", template: "{title} ({year}) [{resolution}]" },
      ],
    }),

    // -- Export ----
    export_run_report: () => ({ ok: true, content: "<html><body>Mock</body></html>", format: "html" }),
    export_run_nfo: () => ({ ok: true, files: [] }),
    export_apply_audit: () => ({ ok: true, content: "" }),

    // -- Watchlist + misc ----
    import_watchlist: () => ({ ok: true, owned: 5, missing: 10, coverage_pct: 33 }),
    submit_score_feedback: () => ({ ok: true }),
    delete_score_feedback: () => ({ ok: true }),
    get_calibration_report: () => ({ ok: true, samples: 0 }),
    export_shareable_profile: () => ({ ok: true, json: "{}" }),
    import_shareable_profile: () => ({ ok: true }),
    test_email_report: () => ({ ok: true, message: "Email envoye" }),

    // -- Scoring rollup (V7 QIJ) ----
    get_scoring_rollup: () => ({ ok: true, items: [] }),

    // -- Utilities ----
    open_path: () => ({ ok: true }),
    log_api_exception: () => null,
    test_reset: () => ({ ok: true }),
    validate_dropped_path: (p) => ({ ok: !!p, message: p ? "OK" : "Path requis" }),
    get_event_ts: () => Date.now() / 1000,
  };

  // -- Proxy fallback : tout ce qui n'est pas defini retourne {ok:true} ----
  const PROXY = new Proxy(API, {
    get(target, prop) {
      if (prop in target) return target[prop];
      // Methode inconnue : log + ok stub
      return function (...args) {
        try {
          console.debug("[mock api] unknown method:", String(prop), args);
        } catch (_) {}
        return { ok: true, _mock_unknown: String(prop) };
      };
    },
  });

  // -- Wrap : pywebview attend des promesses ; ici on retourne valeur sync ----
  // En realite pywebview js_api retourne directement le retour Python. Le code JS
  // de l'app fait souvent `await window.pywebview.api.method()`. Si la valeur est
  // synchrone, await la convertit. OK.

  // -- Installation -------------------------------------------------------
  window.pywebview = window.pywebview || {};
  window.pywebview.api = PROXY;

  // Dispatch pywebviewready apres que le DOM soit pret (l'app ecoute cet event)
  function _dispatchReady() {
    try {
      const evt = new Event("pywebviewready");
      window.dispatchEvent(evt);
    } catch (e) {
      try {
        document.dispatchEvent(new Event("pywebviewready"));
      } catch (_) {}
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(_dispatchReady, 50));
  } else {
    setTimeout(_dispatchReady, 50);
  }

  // Marqueur pour debug
  window.__CINESORT_API_MOCK__ = true;
})();
