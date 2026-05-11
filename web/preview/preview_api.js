(function(){
  function clone(value){
    return JSON.parse(JSON.stringify(value));
  }

  function scenarioRegistry(){
    return window.CineSortPreviewScenarios || { defaultScenarioId: "baseline", scenarios: {} };
  }

  function scenarioList(){
    const scenarios = scenarioRegistry().scenarios || {};
    return Object.keys(scenarios).map((id) => {
      const entry = scenarios[id] || {};
      return {
        id: id,
        label: String(entry.label || id),
        description: String(entry.description || ""),
        defaultView: String(entry.defaultView || "home"),
      };
    });
  }

  function pickScenario(id){
    const registry = scenarioRegistry();
    const scenarios = registry.scenarios || {};
    const wanted = String(id || registry.defaultScenarioId || "baseline").trim();
    if(scenarios[wanted]){
      return clone(scenarios[wanted]);
    }
    const fallbackId = String(registry.defaultScenarioId || "").trim();
    if(fallbackId && scenarios[fallbackId]){
      return clone(scenarios[fallbackId]);
    }
    const firstId = Object.keys(scenarios)[0];
    return firstId ? clone(scenarios[firstId]) : {
      id: "empty",
      label: "Empty",
      defaultView: "home",
      settings: {},
      probeToolsStatus: {
        ok: true,
        hybrid_ready: false,
        degraded_mode: "none",
        message: "No preview data.",
        installer: { supported: false, winget_available: false },
        tools: {},
      },
      qualityPresets: [],
      qualityProfile: {},
      runsHistory: [],
      dashboardsByRunId: {},
      plansByRunId: {},
      validationsByRunId: {},
      duplicatesByRunId: {},
      cleanupPreviewByRunId: {},
      undoPreviewByRunId: {},
      qualityReportsByRunId: {},
      simulatedPlanLogs: [],
    };
  }

  function createRuntime(opts){
    const scenario = pickScenario(opts && opts.scenarioId);
    const store = {
      scenarioId: String(scenario.id || "baseline"),
      scenarioLabel: String(scenario.label || scenario.id || "baseline"),
      scenarioDescription: String(scenario.description || ""),
      defaultView: String(scenario.defaultView || "home"),
      initialQualityProfile: clone(scenario.qualityProfile || {}),
      settings: clone(scenario.settings || {}),
      probeToolsStatus: clone(scenario.probeToolsStatus || {}),
      qualityPresets: clone(scenario.qualityPresets || []),
      qualityProfile: clone(scenario.qualityProfile || {}),
      runsHistory: clone(scenario.runsHistory || []),
      dashboardsByRunId: clone(scenario.dashboardsByRunId || {}),
      plansByRunId: clone(scenario.plansByRunId || {}),
      validationsByRunId: clone(scenario.validationsByRunId || {}),
      duplicatesByRunId: clone(scenario.duplicatesByRunId || {}),
      cleanupPreviewByRunId: clone(scenario.cleanupPreviewByRunId || {}),
      undoPreviewByRunId: clone(scenario.undoPreviewByRunId || {}),
      qualityReportsByRunId: clone(scenario.qualityReportsByRunId || {}),
      uiSeed: clone(scenario.uiSeed || {}),
      activeRunId: String(scenario.activeRunId || ""),
      simulatedPlanRunId: String(scenario.simulatedPlanRunId || ""),
      simulatedPlanLogs: clone(scenario.simulatedPlanLogs || []),
      simulatedStatusByRunId: {},
    };

    function resolveRunId(requested){
      const raw = String(requested || "").trim();
      if(!raw || raw === "latest"){
        if(store.activeRunId){
          return store.activeRunId;
        }
        return String(store.runsHistory[0] && store.runsHistory[0].run_id || "");
      }
      return raw;
    }

    function resolveRunDir(runId){
      const rid = String(runId || "").trim();
      if(!rid){
        return "";
      }
      const dashboard = store.dashboardsByRunId[rid];
      if(dashboard && dashboard.run_dir){
        return String(dashboard.run_dir);
      }
      const run = store.runsHistory.find((entry) => String(entry && entry.run_id || "") === rid);
      if(run && run.run_dir){
        return String(run.run_dir);
      }
      return store.settings.state_dir
        ? String(store.settings.state_dir) + "\\runs\\tri_films_" + rid
        : "";
    }

    function emptyDashboard(){
      return {
        ok: true,
        run_id: "",
        run_dir: "",
        runs_history: clone(store.runsHistory),
        kpis: {
          total_movies: 0,
          scored_movies: 0,
          score_avg: 0,
          score_premium_pct: 0,
          probe_partial_count: 0,
        },
        anomalies_top: [],
        outliers: {
          low_bitrate: [],
          sdr_4k: [],
          vo_missing: [],
        },
        distributions: {
          score_bins: [],
          resolutions: {},
          hdr: {},
          audio_codecs: [],
        },
      };
    }

    function dashboardFor(requested){
      const runId = resolveRunId(requested);
      if(!runId){
        return emptyDashboard();
      }
      const payload = clone(store.dashboardsByRunId[runId] || store.dashboardsByRunId.latest || emptyDashboard());
      payload.ok = true;
      payload.run_id = String(payload.run_id || runId);
      payload.run_dir = String(payload.run_dir || resolveRunDir(runId));
      payload.runs_history = clone(store.runsHistory);
      return payload;
    }

    function planFor(runId){
      const rid = resolveRunId(runId);
      const payload = clone(store.plansByRunId[rid] || { ok: true, rows: [] });
      payload.ok = payload.ok !== false;
      payload.rows = Array.isArray(payload.rows) ? payload.rows : [];
      return payload;
    }

    function validationFor(runId){
      const rid = resolveRunId(runId);
      const payload = clone(store.validationsByRunId[rid] || { ok: true, decisions: {} });
      payload.ok = payload.ok !== false;
      if(!payload.decisions || typeof payload.decisions !== "object"){
        payload.decisions = {};
      }
      return payload;
    }

    function duplicatesFor(runId){
      const rid = resolveRunId(runId);
      const payload = clone(store.duplicatesByRunId[rid] || {
        ok: true,
        total_groups: 0,
        checked_rows: 0,
        groups: [],
      });
      payload.ok = payload.ok !== false;
      return payload;
    }

    function cleanupPreviewFor(runId){
      const rid = resolveRunId(runId);
      const targetFolder = String(store.settings.cleanup_residual_folders_folder_name || "_Dossier Nettoyage");
      const scope = String(store.settings.cleanup_residual_folders_scope || "touched_only");
      const payload = clone(store.cleanupPreviewByRunId[rid] || {
        ok: true,
        preview: {
          enabled: !!store.settings.cleanup_residual_folders_enabled,
          status: "empty",
          reason_code: "no_candidates",
          inspected_count: 0,
          eligible_count: 0,
          has_video_count: 0,
          target_folder_name: targetFolder,
          scope: scope,
          sample_candidate_dirs: [],
          sample_video_blocked_dirs: [],
        },
      });
      payload.ok = payload.ok !== false;
      return payload;
    }

    function undoPreviewFor(runId){
      const rid = resolveRunId(runId);
      const payload = clone(store.undoPreviewByRunId[rid] || {
        ok: true,
        run_id: rid,
        batch_id: "preview-none",
        can_undo: false,
        undo_available: false,
        counts: {
          total: 0,
          reversible: 0,
          irreversible: 0,
          conflicts_predicted: 0,
        },
        categories: {
          empty_folder_dirs: 0,
          cleanup_residual_dirs: 0,
        },
        message: "Aucun undo disponible pour ce scenario.",
      });
      payload.ok = payload.ok !== false;
      payload.run_id = String(payload.run_id || rid);
      return payload;
    }

    function qualityReportFor(runId, rowId){
      const rid = resolveRunId(runId);
      const rowKey = String(rowId || "").trim();
      const existing = store.qualityReportsByRunId[rid] && store.qualityReportsByRunId[rid][rowKey];
      if(existing){
        return clone(existing);
      }
      const rows = planFor(rid).rows;
      const row = rows.find((entry) => String(entry && entry.row_id || "") === rowKey) || {};
      return {
        ok: true,
        status: "analyzed",
        score: 64,
        tier: "bon",
        profile_id: String(store.qualityProfile.id || "CinemaLux_v1"),
        profile_version: Number(store.qualityProfile.version || 1),
        probe_quality: "preview",
        cache_hit_probe: true,
        confidence: {
          label: "moyenne",
          value: 70,
        },
        explanation: {
          narrative: "Rapport preview genere a partir des mocks du scenario.",
          top_positive: [{ label: "Scenario stable" }],
          top_negative: [],
          factors: [
            { category: "global", label: String(row.proposed_title || row.video || row.folder || rowKey || "Film"), delta: 4 },
          ],
        },
        reasons: [
          "Donnees mockees deterministes",
          "Rapport reutilisable pour le travail UI",
        ],
      };
    }

    function upsertRunHistory(runId, patch){
      const rid = String(runId || "").trim();
      if(!rid){
        return;
      }
      const next = Object.assign({
        run_id: rid,
        run_dir: resolveRunDir(rid),
        started_ts: 1773027000,
        duration_s: 180,
        total_rows: planFor(rid).rows.length,
        applied_rows: 0,
        errors_count: 0,
        anomalies_count: 0,
      }, patch || {});
      const index = store.runsHistory.findIndex((entry) => String(entry && entry.run_id || "") === rid);
      if(index >= 0){
        store.runsHistory[index] = Object.assign({}, store.runsHistory[index], next);
      } else {
        store.runsHistory.unshift(next);
      }
      Object.keys(store.dashboardsByRunId).forEach((key) => {
        const dash = store.dashboardsByRunId[key];
        if(dash && typeof dash === "object"){
          dash.runs_history = clone(store.runsHistory);
        }
      });
    }

    function simulatePlanRun(settings){
      const rid = String(store.simulatedPlanRunId || "preview-run-live");
      const runDir = resolveRunDir(rid);
      const rows = planFor(store.activeRunId).rows.length
        ? clone(planFor(store.activeRunId).rows)
        : [];
      store.plansByRunId[rid] = { ok: true, rows: rows };
      store.validationsByRunId[rid] = { ok: true, decisions: {} };
      store.cleanupPreviewByRunId[rid] = cleanupPreviewFor(store.activeRunId || rid);
      store.undoPreviewByRunId[rid] = {
        ok: true,
        run_id: rid,
        batch_id: "preview-none",
        can_undo: false,
        undo_available: false,
        counts: {
          total: 0,
          reversible: 0,
          irreversible: 0,
          conflicts_predicted: 0,
        },
        categories: {
          empty_folder_dirs: 0,
          cleanup_residual_dirs: 0,
        },
        message: "Pas encore d'apply reel pour ce nouveau run.",
      };
      const dashboard = dashboardFor(store.activeRunId || "latest");
      dashboard.run_id = rid;
      dashboard.run_dir = runDir;
      dashboard.runs_history = clone(store.runsHistory);
      store.dashboardsByRunId[rid] = dashboard;
      store.activeRunId = rid;
      upsertRunHistory(rid, {
        run_dir: runDir,
        total_rows: rows.length,
        applied_rows: 0,
        anomalies_count: Array.isArray(dashboard.anomalies_top) ? dashboard.anomalies_top.length : 0,
      });
      store.simulatedStatusByRunId[rid] = {
        idx: rows.length,
        total: rows.length,
        speed: 3.24,
        eta_s: 0,
        current: settings && settings.root ? String(settings.root) : String(store.settings.root || ""),
        done: true,
        next_log_index: 0,
        logs: clone(store.simulatedPlanLogs),
      };
      return {
        ok: true,
        run_id: rid,
        run_dir: runDir,
      };
    }

    const api = {
      async get_settings(){
        return Object.assign({ ok: true }, clone(store.settings));
      },

      async save_settings(settings){
        store.settings = Object.assign({}, store.settings, clone(settings || {}));
        return {
          ok: true,
          state_dir: String(store.settings.state_dir || ""),
          tmdb_key_persisted: !!store.settings.remember_key,
        };
      },

      async test_tmdb_key(key){
        const ok = !!String(key || store.settings.tmdb_api_key || "").trim();
        return {
          ok: ok,
          message: ok ? "Cle TMDb acceptee en preview." : "Aucune cle TMDb fournie.",
        };
      },

      async get_quality_presets(){
        return {
          ok: true,
          presets: clone(store.qualityPresets),
        };
      },

      async apply_quality_preset(presetId){
        const pid = String(presetId || "").trim();
        const preset = store.qualityPresets.find((entry) => String(entry && entry.preset_id || "") === pid);
        if(!preset){
          return { ok: false, message: "Preset introuvable en preview." };
        }
        store.qualityProfile = clone(preset.profile_json || {});
        return {
          ok: true,
          profile_json: clone(store.qualityProfile),
        };
      },

      async get_quality_profile(){
        return {
          ok: true,
          profile_json: clone(store.qualityProfile),
        };
      },

      async save_quality_profile(profile){
        store.qualityProfile = clone(profile || {});
        return {
          ok: true,
          profile_id: String(store.qualityProfile.id || "CinemaLux_v1"),
          profile_version: Number(store.qualityProfile.version || 1),
        };
      },

      async reset_quality_profile(){
        store.qualityProfile = clone(store.initialQualityProfile || {});
        return {
          ok: true,
          profile_json: clone(store.qualityProfile),
        };
      },

      async export_quality_profile(){
        return {
          ok: true,
          json: JSON.stringify(store.qualityProfile, null, 2),
        };
      },

      async import_quality_profile(text){
        try {
          const parsed = JSON.parse(String(text || ""));
          store.qualityProfile = clone(parsed || {});
          return {
            ok: true,
            profile_json: clone(store.qualityProfile),
          };
        } catch(err){
          return {
            ok: false,
            message: "JSON invalide.",
            errors: [String(err || "parse error")],
          };
        }
      },

      async get_probe_tools_status(){
        return Object.assign({ ok: true }, clone(store.probeToolsStatus));
      },

      async recheck_probe_tools(){
        const payload = clone(store.probeToolsStatus);
        payload.ok = true;
        payload.message = "Diagnostic preview relu sans shell desktop.";
        return payload;
      },

      async set_probe_tool_paths(payload){
        const patch = clone(payload || {});
        store.settings.ffprobe_path = String(patch.ffprobe_path || "");
        store.settings.mediainfo_path = String(patch.mediainfo_path || "");
        store.settings.probe_backend = String(patch.probe_backend || "auto");
        if(store.probeToolsStatus.tools && typeof store.probeToolsStatus.tools === "object"){
          if(store.probeToolsStatus.tools.ffprobe){
            store.probeToolsStatus.tools.ffprobe.available = !!store.settings.ffprobe_path;
            store.probeToolsStatus.tools.ffprobe.status = store.settings.ffprobe_path ? "ok" : "missing";
            store.probeToolsStatus.tools.ffprobe.source = store.settings.ffprobe_path ? "manual" : "none";
          }
          if(store.probeToolsStatus.tools.mediainfo){
            store.probeToolsStatus.tools.mediainfo.available = !!store.settings.mediainfo_path;
            store.probeToolsStatus.tools.mediainfo.status = store.settings.mediainfo_path ? "ok" : "missing";
            store.probeToolsStatus.tools.mediainfo.source = store.settings.mediainfo_path ? "manual" : "none";
          }
        }
        store.probeToolsStatus.hybrid_ready = !!store.settings.ffprobe_path && !!store.settings.mediainfo_path;
        return Object.assign({ ok: true }, clone(store.probeToolsStatus));
      },

      async install_probe_tools(){
        return {
          ok: true,
          status: Object.assign({ ok: true }, clone(store.probeToolsStatus), {
            message: "Installation preview simulee.",
          }),
        };
      },

      async update_probe_tools(){
        return {
          ok: true,
          status: Object.assign({ ok: true }, clone(store.probeToolsStatus), {
            message: "Mise a jour preview simulee.",
          }),
        };
      },

      async get_dashboard(requested){
        return dashboardFor(requested);
      },

      async get_global_stats(limit_runs){
        return {
          ok: true,
          summary: {
            total_runs: 4,
            total_films: 48,
            avg_score: 72.5,
            premium_pct: 15.3,
            trend: "\u2191",
            unscored_films: 3,
          },
          timeline: [
            { run_id: "run-01", start_ts: 1741100000, score_avg: 68.2, scored_movies: 10, total_rows: 12, errors: 0, anomalies: 1 },
            { run_id: "run-02", start_ts: 1741200000, score_avg: 71.4, scored_movies: 14, total_rows: 15, errors: 0, anomalies: 0 },
            { run_id: "run-03", start_ts: 1741300000, score_avg: 74.1, scored_movies: 12, total_rows: 12, errors: 1, anomalies: 2 },
            { run_id: "run-04", start_ts: 1741400000, score_avg: 76.3, scored_movies: 9, total_rows: 9, errors: 0, anomalies: 0 },
          ],
          tier_distribution: { Premium: 7, Bon: 22, Moyen: 13, Mauvais: 6 },
          total_scored: 48,
          top_anomalies: [
            { code: "low_bitrate", count: 5, last_run_id: "run-04" },
            { code: "missing_audio", count: 3, last_run_id: "run-03" },
          ],
          activity: [
            { run_id: "run-04", start_ts: 1741400000, duration_s: 42, total_rows: 9, score_avg: 76.3, status: "DONE", applied: true, errors: 0, anomalies: 0 },
            { run_id: "run-03", start_ts: 1741300000, duration_s: 38, total_rows: 12, score_avg: 74.1, status: "DONE", applied: true, errors: 1, anomalies: 2 },
            { run_id: "run-02", start_ts: 1741200000, duration_s: 55, total_rows: 15, score_avg: 71.4, status: "DONE", applied: false, errors: 0, anomalies: 0 },
            { run_id: "run-01", start_ts: 1741100000, duration_s: 30, total_rows: 12, score_avg: 68.2, status: "DONE", applied: true, errors: 0, anomalies: 1 },
          ],
        };
      },

      async undo_last_apply_preview(runId){
        return undoPreviewFor(runId);
      },

      async get_cleanup_residual_preview(runId){
        return cleanupPreviewFor(runId);
      },

      async get_plan(runId){
        return planFor(runId);
      },

      async load_validation(runId){
        return validationFor(runId);
      },

      async save_validation(runId, decisions){
        const rid = resolveRunId(runId);
        store.validationsByRunId[rid] = {
          ok: true,
          decisions: clone(decisions || {}),
        };
        return {
          ok: true,
          saved_count: Object.keys(decisions || {}).length,
        };
      },

      async check_duplicates(runId){
        return duplicatesFor(runId);
      },

      async apply(runId, decisions, dryRun){
        const rid = resolveRunId(runId);
        const appliedCount = Object.values(decisions || {}).filter((entry) => entry && entry.ok).length;
        if(!dryRun){
          upsertRunHistory(rid, {
            applied_rows: appliedCount,
          });
          store.undoPreviewByRunId[rid] = {
            ok: true,
            run_id: rid,
            batch_id: "preview-apply-live",
            can_undo: true,
            undo_available: true,
            counts: {
              total: Math.max(1, appliedCount),
              reversible: Math.max(1, appliedCount),
              irreversible: 0,
              conflicts_predicted: 0,
            },
            categories: {
              empty_folder_dirs: 1,
              cleanup_residual_dirs: 1,
            },
            message: "Apply preview memorise pour undo.",
          };
        }
        return {
          ok: true,
          result: {
            renames: appliedCount,
            moves: appliedCount,
            mkdirs: appliedCount > 0 ? 2 : 0,
            collection_moves: 1,
            quarantined: 0,
            skipped: Math.max(0, planFor(rid).rows.length - appliedCount),
            errors: 0,
            skip_reasons: {
              skip_non_valide: Math.max(0, planFor(rid).rows.length - appliedCount),
            },
            cleanup_residual_diagnostic: cleanupPreviewFor(rid).preview,
          },
        };
      },

      async undo_last_apply(runId, dryRun){
        const rid = resolveRunId(runId);
        const preview = undoPreviewFor(rid);
        if(!dryRun && preview.can_undo){
          upsertRunHistory(rid, {
            applied_rows: 0,
          });
          store.undoPreviewByRunId[rid] = Object.assign({}, preview, {
            can_undo: false,
            undo_available: false,
            message: "Undo reel deja consomme dans ce scenario.",
          });
        }
        return {
          ok: true,
          run_id: rid,
          batch_id: String(preview.batch_id || "preview-apply-live"),
          status: dryRun ? "DRY_RUN" : "UNDONE",
          counts: {
            done: Number(preview.counts && preview.counts.reversible || 0),
            skipped: 0,
            failed: 0,
            irreversible: Number(preview.counts && preview.counts.irreversible || 0),
          },
          categories: Object.assign({}, preview.categories || {}, {
            empty_folder_dirs_reversed: Number(preview.categories && preview.categories.empty_folder_dirs || 0),
            cleanup_residual_dirs_reversed: Number(preview.categories && preview.categories.cleanup_residual_dirs || 0),
          }),
          message: dryRun ? "Undo teste en preview." : "Undo simule termine.",
        };
      },

      async export_run_report(runId, format){
        const rid = resolveRunId(runId);
        const ext = String(format || "json").toLowerCase() === "csv" ? "csv" : "json";
        return {
          ok: true,
          path: "D:\\Media\\CineSortState\\exports\\" + rid + "." + ext,
          rows_total: planFor(rid).rows.length,
        };
      },

      async open_path(path){
        return {
          ok: true,
          path: String(path || ""),
          message: "Mode preview: ouverture de dossier desactivee.",
        };
      },

      async start_plan(settings){
        return simulatePlanRun(settings || {});
      },

      async get_status(runId, logIndex){
        const rid = resolveRunId(runId);
        const status = clone(store.simulatedStatusByRunId[rid] || {
          idx: planFor(rid).rows.length,
          total: planFor(rid).rows.length,
          speed: 3.24,
          eta_s: 0,
          current: String(store.settings.root || ""),
          done: true,
          next_log_index: 0,
          logs: clone(store.simulatedPlanLogs),
        });
        const start = Number(logIndex || 0);
        const logs = Array.isArray(status.logs) ? status.logs.slice(start) : [];
        status.ok = true;
        status.logs = logs;
        status.next_log_index = start + logs.length;
        return status;
      },

      async get_tmdb_posters(ids){
        const posters = {};
        (Array.isArray(ids) ? ids : []).forEach((id) => {
          posters[String(id)] = "";
        });
        return {
          ok: true,
          posters: posters,
        };
      },

      async get_quality_report(runId, rowId){
        const rid = resolveRunId(runId);
        const rowKey = String(rowId || "").trim();
        const report = qualityReportFor(rid, rowKey);
        store.qualityReportsByRunId[rid] = store.qualityReportsByRunId[rid] || {};
        store.qualityReportsByRunId[rid][rowKey] = clone(report);
        return Object.assign({ ok: true }, clone(report));
      },

      async analyze_quality_batch(runId, rowIds){
        const rid = resolveRunId(runId);
        const ids = Array.isArray(rowIds) ? rowIds.map((value) => String(value || "").trim()).filter(Boolean) : [];
        const results = ids.map((rowId) => {
          const report = qualityReportFor(rid, rowId);
          store.qualityReportsByRunId[rid] = store.qualityReportsByRunId[rid] || {};
          store.qualityReportsByRunId[rid][rowId] = clone(report);
          return {
            row_id: rowId,
            status: String(report.status || "analyzed"),
            score: Number(report.score || 0),
            tier: String(report.tier || ""),
          };
        });
        return {
          ok: true,
          analyzed: results.length,
          ignored: 0,
          errors: 0,
          results: results,
        };
      },
    };

    return {
      scenarioId: store.scenarioId,
      store: store,
      api: api,
      scenarios: scenarioList(),
      reset(){
        return createRuntime({ scenarioId: store.scenarioId });
      },
    };
  }

  window.CineSortPreviewApi = {
    createRuntime: createRuntime,
  };
})();
