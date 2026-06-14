/* views/accueil.js — Phase 3.1 (spec 05-accueil.md) — Accueil refondu.
 *
 * Vue de synthese editoriale. 3 PRs incrementales :
 * - PR 3.1-A : Hero + Dernier run + Activite recente (sections 2 + 6).
 * - PR 3.1-B : CTA Scan + Sante biblio + Suggestions (sections 3 + 4 + 5).
 * - PR 3.1-C (cette version) : Environment bar (section 1) + Inspecteur
 *   droit content (rappels operateur + raccourcis) + etat "scan en cours".
 *
 * Toutes les sections de la spec 05 sont desormais couvertes.
 *
 * Source backend : get_dashboard("latest") + get_global_stats() + settings.
 * Route cible : /accueil (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";
import * as rightPanel from "../components/right-panel.js";

/* --- Format dates relatives -------------------------------------------- */

const _ONE_DAY_MS = 86400000;

/** "Aujourd'hui 15:11", "Hier 13:13", "Il y a 3 jours", "12/05 14:30" sinon. */
export function formatRelativeTime(isoOrEpoch) {
  if (!isoOrEpoch) return "—";
  const d = isoOrEpoch instanceof Date ? isoOrEpoch : new Date(isoOrEpoch);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dayOfTarget = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((today.getTime() - dayOfTarget.getTime()) / _ONE_DAY_MS);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  if (diffDays === 0) return `Aujourd'hui ${hh}:${mm}`;
  if (diffDays === 1) return `Hier ${hh}:${mm}`;
  if (diffDays > 1 && diffDays < 7) return `Il y a ${diffDays} jours`;
  const dd = String(d.getDate()).padStart(2, "0");
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mo} ${hh}:${mm}`;
}

/* --- Resume dynamique du Hero (spec 05 §2 Hero) ------------------------ */

/** Determine la phrase de resume selon l'etat agrege.
 *  Retourne { greeting, summary } pour le hero editorial.
 */
export function computeHeroSummary(state) {
  const hasActiveRun = !!state.active_run_id;
  const hasAnyRun = !!state.latest_run;
  const errorCritical = !!state.error_critical;
  const alertCount = Number(state.alert_count || 0);
  const alertSeverity = String(state.alert_severity || "info");

  if (errorCritical) {
    return { summary: "Problème : la base de données n'est pas accessible." };
  }
  if (hasActiveRun) {
    const total = state.active_total || 0;
    const eta = state.active_eta_min;
    const etaTxt = eta != null ? ` ~${eta} min restant.` : "";
    return { summary: `Scan en cours sur ${total} films.${etaTxt}` };
  }
  if (!hasAnyRun) {
    return { summary: "Bienvenue. Lance ton premier scan pour commencer." };
  }
  if (alertCount === 0) {
    return { summary: "Ta bibliothèque va bien." };
  }
  if (alertCount <= 3 && alertSeverity !== "danger") {
    return { summary: "Ta bibliothèque va bien, quelques points à voir." };
  }
  return { summary: "Ta bibliothèque demande ton attention." };
}

/* --- HTML rendering ---------------------------------------------------- */

function _renderSkeleton() {
  return `
    <section class="accueil-view accueil-view--loading" aria-busy="true">
      <div class="accueil-hero">
        <div class="v5-skeleton accueil-hero-greeting-skel"></div>
        <div class="v5-skeleton accueil-hero-summary-skel"></div>
      </div>
      <div class="accueil-section v5-skeleton accueil-section-skel"></div>
      <div class="accueil-section v5-skeleton accueil-section-skel"></div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="accueil-view accueil-view--error" role="alert">
      <h2 class="accueil-error-title">L'accueil n'a pas pu se charger.</h2>
      <p class="accueil-error-message">${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-accueil-retry>Réessayer</button>
    </section>
  `;
}

function _renderHero(heroState) {
  const { summary } = computeHeroSummary(heroState);
  return `
    <header class="accueil-hero">
      <h1 class="accueil-hero-greeting">Bonjour Thomas</h1>
      <p class="accueil-hero-summary">${escapeHtml(summary)}</p>
    </header>
  `;
}

function _renderLastRunCard(latestRun, kpis) {
  if (!latestRun || !latestRun.run_id) {
    return `
      <section class="accueil-section accueil-last-run accueil-last-run--empty" aria-label="Dernier run">
        <h2 class="accueil-section-title">Dernier run</h2>
        <p class="accueil-empty-msg">Aucun run encore. Lance ton premier scan pour commencer.</p>
        <div class="accueil-actions">
          <button type="button" class="v5-btn v5-btn--primary" data-accueil-action="start-scan">▶ Démarrer un scan</button>
        </div>
      </section>
    `;
  }
  // Source backend get_dashboard : runs_history[i] expose started_ts (float epoch),
  // total_rows, applied_rows, errors_count, anomalies_count. Pas de avg_score
  // par run dans runs_history -> on lit le score moyen du run actif via payload.kpis.
  const startedTs = latestRun.started_ts || latestRun.started_at;
  const startedDate = typeof startedTs === "number" ? new Date(startedTs * 1000) : startedTs;
  const date = formatRelativeTime(startedDate);
  const total = latestRun.total_rows != null ? Number(latestRun.total_rows) : null;
  const avgScore = kpis && kpis.score_avg != null ? Number(kpis.score_avg) : (latestRun.avg_score_v2 != null ? Number(latestRun.avg_score_v2) : null);
  // R6-I : la confiance moyenne vient de kpis.confidence_avg (runs_history n'a
  // pas avg_confidence_pct -> affichait toujours "—").
  const avgConfidence = kpis && kpis.confidence_avg != null ? Number(kpis.confidence_avg) : latestRun.avg_confidence_pct;
  const scoreTxt = avgScore != null && avgScore > 0 ? `${Math.round(avgScore)}/100` : "— (pas calculé)";
  const confTxt = avgConfidence != null ? `${Math.round(avgConfidence)}%` : "—";
  const totalTxt = total != null ? `${total} films analysés` : "— films";
  const showResume = String(latestRun.status || "").toUpperCase() === "AWAITING_VALIDATION";
  return `
    <section class="accueil-section accueil-last-run" aria-labelledby="accueil-last-run-title">
      <h2 id="accueil-last-run-title" class="accueil-section-title">Dernier run</h2>
      <div class="accueil-last-run-meta">
        <span class="accueil-last-run-id">${escapeHtml(latestRun.run_id)}</span>
        <span class="accueil-last-run-sep">·</span>
        <time class="accueil-last-run-date" datetime="${escapeHtml(String(startedTs || ""))}">${escapeHtml(date)}</time>
      </div>
      <dl class="accueil-last-run-stats">
        <div><dt>Films</dt><dd>${escapeHtml(totalTxt)}</dd></div>
        <div><dt>Score moyen</dt><dd>${escapeHtml(scoreTxt)}</dd></div>
        <div><dt>Confiance moyenne</dt><dd>${escapeHtml(confTxt)}</dd></div>
      </dl>
      <div class="accueil-actions">
        ${showResume ? '<button type="button" class="v5-btn v5-btn--primary" data-accueil-action="resume-validation" data-run-id="' + escapeHtml(latestRun.run_id) + '">▶ Reprendre la validation</button>' : ""}
        <button type="button" class="v5-btn v5-btn--secondary" data-accueil-action="view-run-detail" data-run-id="${escapeHtml(latestRun.run_id)}">📊 Voir le détail</button>
      </div>
    </section>
  `;
}

/* Phase 3.1-C : Environment bar (section 1 spec 05).
 * Slim 32px, affiche les roots actifs (max 3) + 5 pastilles integrations.
 * Une integration peut etre : configuree+OK ☑, non configuree ☐, ou
 * configuree mais hors ligne ⚠.
 */
const _INTEGRATIONS = [
  // settingKeys[] : on considere l'integration "configuree" si AU MOINS UNE
  // des clefs est renseignee (string non vide) OU le flag *_enabled === true.
  // Fix bug #1 : avant on ne regardait que *_enabled, donc un Jellyfin/Plex/
  // Radarr/OMDb avec url+api_key mais sans flag enabled passait "Non configuré".
  { key: "tmdb", label: "TMDb", settingKeys: ["tmdb_api_key"] },
  { key: "jellyfin", label: "Jellyfin", settingKeys: ["jellyfin_enabled", "jellyfin_url", "jellyfin_api_key"] },
  { key: "plex", label: "Plex", settingKeys: ["plex_enabled", "plex_url", "plex_token"] },
  { key: "radarr", label: "Radarr", settingKeys: ["radarr_enabled", "radarr_url", "radarr_api_key"] },
  { key: "omdb", label: "OMDb", settingKeys: ["omdb_enabled", "omdb_api_key"] },
];

/** Retourne true si AU MOINS UNE des settingKeys de l'integration est renseignee
 *  (string non vide) OU egale à true (flag *_enabled).
 */
function _isIntegrationConfigured(integration, settings) {
  const settingsObj = settings || {};
  // Backward compat : tolere l'ancien champ settingKey (singulier).
  const keys = Array.isArray(integration.settingKeys)
    ? integration.settingKeys
    : (integration.settingKey ? [integration.settingKey] : []);
  for (const k of keys) {
    const val = settingsObj[k];
    if ((typeof val === "string" && val.trim() !== "") || val === true) return true;
  }
  return false;
}

/** Etat de chaque integration : "ok" (configuré + ping OK),
 *  "off" (non configuré) ou "offline" (configuré mais ping fail).
 *  Phase 5 spec §1 : la pastille passe à ⚠ orange si hors ligne.
 */
function _integrationState(integration, settings, pingResults) {
  const configured = _isIntegrationConfigured(integration, settings);
  if (!configured) return "off";
  const pr = pingResults && pingResults[integration.key];
  if (pr === false) return "offline";
  // Si pas encore pingé ou ping OK : "ok".
  return "ok";
}

function _renderEnvironmentBar(roots, settings, pingResults) {
  const rootsList = Array.isArray(roots) ? roots : [];
  const rootsTxt = rootsList.length === 0
    ? "<em class=\"accueil-env-empty\">Aucun root configuré</em>"
    : rootsList.slice(0, 2).map((r) => escapeHtml(String(r))).join(", ") + (rootsList.length > 2 ? `, <span class="accueil-env-more">+${rootsList.length - 2}</span>` : "");
  const pastilles = _INTEGRATIONS.map((it) => {
    const state = _integrationState(it, settings, pingResults);
    let symbol;
    let stateClass;
    let title;
    if (state === "ok") {
      symbol = "☑";
      stateClass = "is-ok";
      title = `${it.label} configuré`;
    } else if (state === "offline") {
      symbol = "⚠";
      stateClass = "is-offline";
      title = `${it.label} configuré mais hors ligne — clique pour diagnostiquer`;
    } else {
      symbol = "☐";
      stateClass = "is-off";
      title = `${it.label} non configuré — clique pour le configurer`;
    }
    return `<button type="button" class="accueil-env-pill ${stateClass}" data-integration="${escapeHtml(it.key)}" data-integration-state="${escapeHtml(state)}" title="${escapeHtml(title)}">
      <span class="accueil-env-pill-sym" aria-hidden="true">${symbol}</span>${escapeHtml(it.label)}
    </button>`;
  }).join("");
  return `
    <div class="accueil-env-bar" role="status" aria-label="Environment et integrations" data-accueil-env-bar>
      <span class="accueil-env-roots" aria-label="Dossiers racines actifs">📂 ${rootsTxt}</span>
      <span class="accueil-env-pills">${pastilles}</span>
    </div>
  `;
}

/* Cache des résultats de ping (5 min). Module-level pour persister entre
 * (re-)renders et navigations de la même session de boot.
 */
const _PING_CACHE_TTL_MS = 5 * 60 * 1000;
const _pingCache = {
  // { key: { ok: bool, ts: ms } }
};

function _pingCacheGet(key) {
  const entry = _pingCache[key];
  if (!entry) return undefined;
  if (Date.now() - entry.ts > _PING_CACHE_TTL_MS) {
    delete _pingCache[key];
    return undefined;
  }
  return entry.ok;
}

function _pingCacheSet(key, ok) {
  _pingCache[key] = { ok: !!ok, ts: Date.now() };
}

/** Ping une seule intégration. Retourne true (ok) / false (offline) ou null
 *  si on ne peut pas la tester (ex : pas d'endpoint dispo, ou pas configurée).
 */
async function _pingIntegration(key, settings, signal) {
  const cached = _pingCacheGet(key);
  if (cached !== undefined) return cached;
  // Fix audit 2026-05-25 (v1.5.3) Vague F : si la vue est deja detached avant
  // de meme lancer la requete, on annule (evite fetch inutile + DOM detached).
  if (signal && signal.aborted) return null;
  // Fix audit 2026-05-24 : avant, les pings Jellyfin/Plex/Radarr passaient un
  // objet vide {} aux facades integrations/test_*_connection. Or ces facades
  // attendent { url, api_key, timeout_s } et retournent generalement une
  // erreur "missing parameters" -> pastille bloquee sur "offline" meme quand
  // l'integration etait OK. On lit maintenant les settings (url + api_key) et
  // on les transmet explicitement. Si une cle attendue manque dans settings
  // (ex: ancien install), on garde {} et le backend doit alors fallback sur
  // ses propres settings persistes (cf doc facades).
  const s = settings || {};
  try {
    // Fix audit 2026-05-25 (v1.5.3) Vague F : signal abort propage a apiPost
    // pour annuler les pings en cours si la vue est demontee pendant l'attente.
    const _opts = signal ? { signal } : {};
    let res = null;
    if (key === "tmdb") {
      const apiKey = String(s.tmdb_api_key || "");
      if (!apiKey) return null;
      res = await apiPost("integrations/test_tmdb_key", { api_key: apiKey, state_dir: "", timeout_s: 5 }, _opts);
    } else if (key === "jellyfin") {
      const url = String(s.jellyfin_url || "");
      const apiKey = String(s.jellyfin_api_key || "");
      const payload = (url || apiKey)
        ? { url, api_key: apiKey, timeout_s: 5 }
        : {}; // settings vides : backend doit lire ses propres settings persistes
      res = await apiPost("integrations/test_jellyfin_connection", payload, _opts);
    } else if (key === "plex") {
      const url = String(s.plex_url || "");
      const token = String(s.plex_token || "");
      const payload = (url || token)
        ? { url, api_key: token, timeout_s: 5 }
        : {};
      res = await apiPost("integrations/test_plex_connection", payload, _opts);
    } else if (key === "radarr") {
      const url = String(s.radarr_url || "");
      const apiKey = String(s.radarr_api_key || "");
      const payload = (url || apiKey)
        ? { url, api_key: apiKey, timeout_s: 5 }
        : {};
      res = await apiPost("integrations/test_radarr_connection", payload, _opts);
    } else if (key === "omdb") {
      const apiKey = String(s.omdb_api_key || "");
      res = await apiPost("integrations/test_omdb_connection", { api_key: apiKey, timeout_s: 5 }, _opts);
    }
    // Fix audit 2026-05-25 (v1.5.3) Vague F : pattern standardise res.data.ok.
    // apiPost retourne { ok, status, data: {...payload backend...} }. Le ok du
    // payload backend est dans res.data.ok ; res.ok est le ok HTTP de l'enveloppe.
    const _payload = (res && res.data) || res || {};
    const ok = !!(_payload.ok === true || _payload.connected === true);
    _pingCacheSet(key, ok);
    return ok;
  } catch (_err) {
    _pingCacheSet(key, false);
    return false;
  }
}

/** Lance les pings en arrière-plan, met à jour le DOM au fil des résultats.
 *  N'attend pas que les pings se terminent (fire-and-forget).
 */
function _runEnvironmentPingsBackground(container, settings, signal) {
  for (const it of _INTEGRATIONS) {
    // Fix bug #1 : utilise _isIntegrationConfigured (multi-keys) au lieu de
    // tester uniquement *_enabled, sinon on ne ping pas un Jellyfin/Plex/etc.
    // configure via url+api_key sans flag enabled.
    if (!_isIntegrationConfigured(it, settings)) continue;
    // Cache hit ? Applique direct sans refetch.
    const cached = _pingCacheGet(it.key);
    if (cached !== undefined) {
      _applyPingResultToDom(container, it.key, cached);
      continue;
    }
    // Fix audit 2026-05-25 (v1.5.3) Vague F : fire-and-forget AVEC signal abort.
    // Si l'utilisateur navigue avant la fin du ping, _abortController.abort()
    // annule la requete ; _applyPingResultToDom verifie isConnected en plus.
    _pingIntegration(it.key, settings, signal).then((ok) => {
      if (ok === null) return;
      if (signal && signal.aborted) return;
      _applyPingResultToDom(container, it.key, ok);
    }).catch(() => { /* deja cache a false, ou abort */ });
  }
}

function _applyPingResultToDom(container, key, ok) {
  // Fix audit 2026-05-25 (v1.5.3) Vague F : guard DOM detache. Sans ce check,
  // un ping fire-and-forget qui revient apres navigation manipulerait un
  // conteneur orphelin (querySelector OK mais aucun effet visible + warnings).
  if (!container || !container.isConnected) return;
  const pill = container.querySelector(`[data-accueil-env-bar] [data-integration="${key}"]`);
  if (!pill) return;
  pill.classList.remove("is-ok", "is-offline", "is-off");
  const sym = pill.querySelector(".accueil-env-pill-sym");
  if (ok) {
    pill.classList.add("is-ok");
    if (sym) sym.textContent = "☑";
    pill.dataset.integrationState = "ok";
    pill.title = pill.title.replace(/configuré mais hors ligne.*$/, "configuré");
  } else {
    pill.classList.add("is-offline");
    if (sym) sym.textContent = "⚠";
    pill.dataset.integrationState = "offline";
    // Fix bug #3 : textContent inclut le symbole ☑/⚠/☐ du <span> (DOM concat
    // tout le sous-arbre). Au lieu de pill.textContent.trim() on lit le label
    // canonique depuis _INTEGRATIONS via data-integration -> evite "TMDb⚠" colle.
    const intKey = pill.dataset.integration || "";
    const intMeta = _INTEGRATIONS.find((i) => i.key === intKey);
    const label = (intMeta && intMeta.label) || intKey || "Integration";
    pill.title = `${label} configuré mais hors ligne — clique pour diagnostiquer`;
  }
}

/* Phase 3.1-C : Etat "scan en cours" — section CTA Scan transformee en
 * compteur de progression. Le polling de mise a jour sera dans initAccueil.
 */
function _renderScanInProgress(progress) {
  const total = progress.total != null ? Number(progress.total) : 0;
  const current = progress.current != null ? Number(progress.current) : 0;
  const phase = String(progress.phase || "");
  const phaseLabel = progress.phase_label || phase || "Scan en cours";
  const etaMin = progress.eta_min;
  const pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  const etaTxt = etaMin != null ? `~${etaMin} min restant` : "";
  return `
    <section class="accueil-section accueil-cta-scan accueil-cta-scan--running" aria-labelledby="accueil-cta-title">
      <h2 id="accueil-cta-title" class="accueil-cta-scan-title">🔄 Scan en cours sur ${escapeHtml(String(total))} films</h2>
      <p class="accueil-cta-scan-phase">${escapeHtml(phaseLabel)} (${escapeHtml(String(current))}/${escapeHtml(String(total))})</p>
      <div class="accueil-cta-scan-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
        <span class="accueil-cta-scan-fill" style="--progress: ${pct / 100}"></span>
      </div>
      ${etaTxt ? `<p class="accueil-cta-scan-eta">${escapeHtml(etaTxt)}</p>` : ""}
      <div class="accueil-actions">
        <button type="button" class="v5-btn v5-btn--secondary" data-accueil-action="open-traitement">→ Voir le détail</button>
      </div>
    </section>
  `;
}

function _renderCtaScan(roots, scanProgress) {
  if (scanProgress && scanProgress.active) {
    return _renderScanInProgress(scanProgress);
  }
  const rootsList = Array.isArray(roots) ? roots : [];
  const rootsLabel = rootsList.length > 0
    ? rootsList.slice(0, 3).map((r) => escapeHtml(String(r))).join(" + ")
    : "<em class=\"text-muted\">Aucun root configuré. Va dans Paramètres > Sources.</em>";
  // Phase 5 spec §3 : Démarrer = 1-clic (appel direct run/start_plan).
  return `
    <section class="accueil-section accueil-cta-scan" aria-labelledby="accueil-cta-title">
      <div class="accueil-cta-scan-content">
        <h2 id="accueil-cta-title" class="accueil-cta-scan-title">🚀 Lancer un nouveau scan</h2>
        <p class="accueil-cta-scan-targets">Sur ${rootsLabel}</p>
      </div>
      <div class="accueil-actions">
        <!-- Fix audit 2026-06-07 UX medium : harmoniser verbe "Lancer" (titre H2,
             raccourci aide.js, traitement.js) entre titre et CTA, eviter incoherence. -->
        <button type="button" class="v5-btn v5-btn--primary" data-accueil-action="start-scan-direct">▶ Lancer le scan</button>
        <button type="button" class="v5-btn v5-btn--secondary" data-accueil-action="open-scan-options">⚙ Options…</button>
      </div>
    </section>
  `;
}

const _TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject"];
const _TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
};

function _renderTierBar(tier, count, total) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  // Spec : barre proportionnelle. On garde la largeur en % CSS.
  return `
    <div class="accueil-health-row" data-tier="${escapeHtml(tier)}">
      <span class="accueil-health-label">${escapeHtml(_TIER_LABELS[tier] || tier)}</span>
      <div class="accueil-health-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="${escapeHtml(_TIER_LABELS[tier])} : ${count} films (${pct}%)">
        <span class="accueil-health-fill accueil-health-fill--${escapeHtml(tier)}" style="--progress: ${pct / 100}"></span>
      </div>
      <span class="accueil-health-count">${escapeHtml(String(count))}</span>
      <span class="accueil-health-pct">${pct}%</span>
    </div>
  `;
}

function _normalizeTierDist(rawDist) {
  // Le backend peut renvoyer des keys Capitalisees (legacy : "Bronze", "Gold", ...)
  // ou lowercase (v2_tier_distribution.counts). On normalise tout en lowercase.
  const out = {};
  for (const [k, v] of Object.entries(rawDist || {})) {
    out[String(k).toLowerCase()] = Number(v) || 0;
  }
  return out;
}

function _renderHealth(stats) {
  // Priorite a v2_tier_distribution.counts (lowercase garantis, structure v7.6.0).
  // Fallback sur tier_distribution legacy si v2 vide (cas frequent : films
  // anciens sans global_tier_v2 calcule -> counts tous a 0).
  let dist = {};
  if (stats && stats.v2_tier_distribution && stats.v2_tier_distribution.counts) {
    const v2 = _normalizeTierDist(stats.v2_tier_distribution.counts);
    const v2sum = _TIER_ORDER.reduce((s, t) => s + (v2[t] || 0), 0);
    if (v2sum > 0) {
      dist = v2;
    } else if (stats.tier_distribution) {
      // v2 vide -> on retombe sur le tier classique (legacy quality_reports).
      dist = _normalizeTierDist(stats.tier_distribution);
    }
  } else if (stats && stats.tier_distribution) {
    dist = _normalizeTierDist(stats.tier_distribution);
  }
  // Total des films effectivement classes (somme des 5 tiers, sans "unknown").
  const sumTiers = _TIER_ORDER.reduce((sum, t) => sum + (Number(dist[t]) || 0), 0);
  const total = sumTiers;
  if (total === 0) {
    return `
      <section class="accueil-section accueil-health accueil-health--empty" aria-labelledby="accueil-health-title">
        <h2 id="accueil-health-title" class="accueil-section-title">Santé bibliothèque</h2>
        <p class="accueil-empty-msg">Lance ton premier scan pour voir la distribution qualité.</p>
      </section>
    `;
  }
  const rows = _TIER_ORDER.map((t) => _renderTierBar(t, Number(dist[t]) || 0, total)).join("");
  return `
    <section class="accueil-section accueil-health" aria-labelledby="accueil-health-title">
      <h2 id="accueil-health-title" class="accueil-section-title">Santé bibliothèque <span class="accueil-health-total">(${escapeHtml(String(total))} films classés)</span></h2>
      <div class="accueil-health-bars">${rows}</div>
      <div class="accueil-actions">
        <button type="button" class="v5-btn v5-btn--ghost" data-accueil-action="view-qualite">→ Audit qualité complet</button>
      </div>
    </section>
  `;
}

const _INSIGHT_ROUTE_BY_TYPE = {
  duplicates_probable: "/bibliotheque?filter=duplicates",
  films_not_identified: "/bibliotheque?filter=not_identified",
  films_low_confidence: "/bibliotheque?filter=low_confidence",
  subs_missing_fr: "/bibliotheque?filter=subs_missing_fr",
  omdb_disagreements: "/bibliotheque?filter=omdb_disagree",
  quality_reject: "/qualite",
  health_low: "/qualite",
  sagas_incomplete: "/bibliotheque?filter=sagas_incomplete",
};

function _routeFromInsight(insight) {
  if (!insight) return "/accueil";
  if (insight.action_url && typeof insight.action_url === "string") {
    // L'URL backend peut etre un hash (#doublons) — on normalise.
    return insight.action_url.replace(/^#/, "/").replace(/^\/?/, "/");
  }
  return _INSIGHT_ROUTE_BY_TYPE[insight.type || insight.code] || "/bibliotheque";
}

function _librarianPriorityToSeverity(prio) {
  // Mapping priority librarian (1=Haute / 2=Moyenne / 3=Basse / 4=Info) -> severity.
  const p = Number(prio);
  if (p === 1) return "danger";
  if (p === 2) return "warning";
  return "info";
}

function _librarianIdToRoute(id) {
  // Maps id librarian (codec_obsolete, duplicates, subs_missing, etc.) vers routes FR.
  switch (String(id || "")) {
    case "duplicates":
    case "doublons":
      return "/bibliotheque?filter=duplicates";
    case "subs_missing":
    case "subs_missing_fr":
      return "/bibliotheque?filter=subs_missing_fr";
    case "not_identified":
    case "films_not_identified":
      return "/bibliotheque?filter=not_identified";
    case "codec_obsolete":
      return "/bibliotheque?filter=codec_obsolete";
    case "low_confidence":
      return "/bibliotheque?filter=low_confidence";
    case "sagas_incomplete":
    case "sagas":
      return "/bibliotheque?filter=sagas_incomplete";
    case "quality_reject":
      return "/qualite";
    default:
      return "/bibliotheque";
  }
}

function _extractAccueilSuggestions(stats) {
  // Priorite 1 : insights v7.6.0 Vague 2 (format { type, severity, count, label, ... }).
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  if (insights.length > 0) {
    return insights.map((it) => ({
      code: String(it.type || it.code || "info"),
      severity: String(it.severity || "info"),
      label: String(it.label || it.title || "Point à traiter"),
      count: it.count != null ? Number(it.count) : null,
      route: _routeFromInsight(it),
      filter_hint: it.filter_hint || null,
    }));
  }
  // Priorite 2 : librarian.suggestions (format legacy { id, priority, message, count, details }).
  const librarian = stats && stats.librarian;
  const lsugs = Array.isArray(librarian && librarian.suggestions) ? librarian.suggestions : [];
  if (lsugs.length > 0) {
    return lsugs.map((s) => ({
      code: String(s.id || "info"),
      severity: _librarianPriorityToSeverity(s.priority),
      label: String(s.message || "Point à traiter"),
      count: s.count != null ? Number(s.count) : null,
      route: _librarianIdToRoute(s.id),
      filter_hint: null,
    }));
  }
  return [];
}

function _renderSuggestions(stats) {
  const items = _extractAccueilSuggestions(stats);
  if (items.length === 0) {
    return `
      <section class="accueil-section accueil-suggestions accueil-suggestions--empty" aria-labelledby="accueil-suggestions-title">
        <h2 id="accueil-suggestions-title" class="accueil-section-title">Points à traiter</h2>
        <p class="accueil-empty-msg">✅ Aucun point à traiter. Tout va bien.</p>
      </section>
    `;
  }
  // Phase 5 spec §4 : 3 suggestions max (top sévérité), lien "Voir toutes" si >3.
  const _MAX_SUGGESTIONS = 3;
  const totalItems = items.length;
  const rows = items.slice(0, _MAX_SUGGESTIONS).map((it) => {
    const sev = it.severity;
    const sevClass = sev === "danger" ? "is-danger" : sev === "warning" ? "is-warning" : "is-info";
    const sevDot = sev === "danger" ? "🔴" : sev === "warning" ? "🟡" : "🔵";
    // Si le message contient deja le count en prefixe ("22 film(s) ..."), on ne l'ajoute pas.
    const labelStr = it.label;
    const messageStartsWithCount = it.count != null && /^\d/.test(labelStr.trim());
    const prefix = it.count != null && !messageStartsWithCount ? `${it.count} ` : "";
    const filterHint = it.filter_hint ? `<span class="accueil-suggestion-hint">${escapeHtml(String(it.filter_hint))}</span>` : "";
    return `
      <li class="accueil-suggestion-row ${sevClass}" data-target-route="${escapeHtml(it.route)}">
        <span class="accueil-suggestion-dot" aria-hidden="true">${sevDot}</span>
        <span class="accueil-suggestion-text"><strong>${escapeHtml(prefix + labelStr)}</strong>${filterHint}</span>
        <button type="button" class="v5-btn v5-btn--ghost accueil-suggestion-action" data-accueil-action="open-insight" data-target-route="${escapeHtml(it.route)}" aria-label="Ouvrir cette suggestion">→</button>
      </li>
    `;
  }).join("");
  const moreLink = totalItems > _MAX_SUGGESTIONS
    ? `<div class="accueil-actions"><button type="button" class="v5-btn v5-btn--ghost" data-accueil-action="view-all-suggestions">→ Voir toutes (${totalItems})</button></div>`
    : "";
  return `
    <section class="accueil-section accueil-suggestions" aria-labelledby="accueil-suggestions-title">
      <h2 id="accueil-suggestions-title" class="accueil-section-title">⚠️ ${totalItems} Points à traiter</h2>
      <ul class="accueil-suggestion-list">${rows}</ul>
      ${moreLink}
    </section>
  `;
}

/* Phase 5 (spec 05 §6 Activité récente) — Timeline visuelle 7 jours.
 * Affiche une bande horizontale avec 7 colonnes (J-6 à J) ; chaque run est
 * une "bullet" colorée selon son statut, empilée verticalement dans sa
 * colonne. Le hover affiche un tooltip natif (title) avec les détails.
 */
const _TIMELINE_DAYS = 7;
const _WEEKDAY_SHORT_FR = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];

/** Retourne le statut derive (APPLIED/PARTIAL/ERROR/DONE) pour un run. */
function _deriveRunStatus(r) {
  const errors = Number(r.errors_count || 0);
  const applied = Number(r.applied_rows || 0);
  const total = Number(r.total_rows || 0);
  const explicit = String(r.status || "").toUpperCase();
  if (explicit) {
    if (explicit === "APPLIED" || explicit === "DONE" || explicit === "PARTIAL" || explicit === "ERROR") {
      return explicit;
    }
  }
  if (errors > 0) return "ERROR";
  if (applied > 0 && total > 0 && applied >= total) return "APPLIED";
  if (applied > 0 && total > 0 && applied < total) return "PARTIAL";
  return "DONE";
}

function _statusBulletClass(status) {
  const s = String(status || "").toUpperCase();
  if (s === "APPLIED") return "accueil-timeline-bullet--applied";
  if (s === "PARTIAL") return "accueil-timeline-bullet--partial";
  if (s === "ERROR") return "accueil-timeline-bullet--error";
  return "accueil-timeline-bullet--done";
}

/** Construit les 7 colonnes (J-6 → J) avec les runs groupes par jour calendaire. */
function _bucketRunsByDay(runs, now) {
  const ref = now || new Date();
  const todayStart = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate());
  const cols = [];
  for (let i = _TIMELINE_DAYS - 1; i >= 0; i -= 1) {
    const day = new Date(todayStart.getTime() - i * _ONE_DAY_MS);
    cols.push({
      date: day,
      label: i === 0 ? "Auj." : (i === 1 ? "Hier" : _WEEKDAY_SHORT_FR[day.getDay()]),
      dayNum: day.getDate(),
      runs: [],
    });
  }
  const list = Array.isArray(runs) ? runs : [];
  for (const r of list) {
    const tsSrc = r.started_ts != null ? new Date(Number(r.started_ts) * 1000) : (r.started_at ? new Date(r.started_at) : null);
    if (!tsSrc || Number.isNaN(tsSrc.getTime())) continue;
    const rDay = new Date(tsSrc.getFullYear(), tsSrc.getMonth(), tsSrc.getDate());
    const diff = Math.round((todayStart.getTime() - rDay.getTime()) / _ONE_DAY_MS);
    if (diff < 0 || diff >= _TIMELINE_DAYS) continue;
    const colIdx = _TIMELINE_DAYS - 1 - diff;
    cols[colIdx].runs.push({ ...r, _ts: tsSrc });
  }
  // Trie les runs intra-colonne par heure croissante (le plus ancien en bas).
  for (const c of cols) c.runs.sort((a, b) => a._ts.getTime() - b._ts.getTime());
  return cols;
}

function _renderRecentActivity(runs) {
  const list = Array.isArray(runs) ? runs : [];
  if (list.length === 0) {
    return `
      <section class="accueil-section accueil-activity accueil-activity--empty" aria-labelledby="accueil-activity-title">
        <h2 id="accueil-activity-title" class="accueil-section-title">Activité récente</h2>
        <p class="accueil-empty-msg">Aucune activité pour l'instant.</p>
      </section>
    `;
  }
  const cols = _bucketRunsByDay(list, new Date());
  const colsHtml = cols.map((c) => {
    const bullets = c.runs.map((r) => {
      const status = _deriveRunStatus(r);
      const cls = _statusBulletClass(status);
      const hh = String(r._ts.getHours()).padStart(2, "0");
      const mm = String(r._ts.getMinutes()).padStart(2, "0");
      const total = Number(r.total_rows || 0);
      const tooltip = `${hh}:${mm} — Run ${r.run_id} — ${total} films — ${status}`;
      return `<button type="button" class="accueil-timeline-bullet ${cls}"
                 data-run-id="${escapeHtml(r.run_id)}"
                 title="${escapeHtml(tooltip)}"
                 aria-label="${escapeHtml(tooltip)}"></button>`;
    }).join("");
    const isToday = c.label === "Auj.";
    // Fix bug #4 : c.date est construit en heure locale (minuit local). Un
    // toISOString() le convertit en UTC -> sur fuseau negatif (ou proche de
    // minuit positif) data-day-iso renvoie le jour calendaire precedent et
    // casse les selecteurs e2e. On construit l'ISO YYYY-MM-DD localement.
    const _y = c.date.getFullYear();
    const _mm = String(c.date.getMonth() + 1).padStart(2, "0");
    const _dd = String(c.date.getDate()).padStart(2, "0");
    const _dayIsoLocal = `${_y}-${_mm}-${_dd}`;
    return `
      <div class="accueil-timeline-day ${isToday ? "is-today" : ""}" data-day-iso="${escapeHtml(_dayIsoLocal)}">
        <div class="accueil-timeline-bullets">${bullets}</div>
        <div class="accueil-timeline-day-label">
          <span class="accueil-timeline-day-name">${escapeHtml(c.label)}</span>
          <span class="accueil-timeline-day-num">${escapeHtml(String(c.dayNum))}</span>
        </div>
      </div>
    `;
  }).join("");
  // Legende des couleurs (3 statuts principaux pour la timeline).
  const legend = `
    <ul class="accueil-timeline-legend" aria-label="Légende des statuts">
      <li><span class="accueil-timeline-bullet accueil-timeline-bullet--applied" aria-hidden="true"></span>Appliqué</li>
      <li><span class="accueil-timeline-bullet accueil-timeline-bullet--partial" aria-hidden="true"></span>Partiel</li>
      <li><span class="accueil-timeline-bullet accueil-timeline-bullet--error" aria-hidden="true"></span>Erreur</li>
      <li><span class="accueil-timeline-bullet accueil-timeline-bullet--done" aria-hidden="true"></span>Terminé</li>
    </ul>
  `;
  return `
    <section class="accueil-section accueil-activity" aria-labelledby="accueil-activity-title">
      <h2 id="accueil-activity-title" class="accueil-section-title">Activité récente (7 jours)</h2>
      <div class="accueil-timeline-7d" role="img" aria-label="Timeline des runs sur les 7 derniers jours">
        ${colsHtml}
      </div>
      ${legend}
      <div class="accueil-actions">
        <button type="button" class="v5-btn v5-btn--ghost" data-accueil-action="view-history">→ Voir l'historique complet</button>
      </div>
    </section>
  `;
}

function _extractScanProgress(payload) {
  // Le backend get_dashboard retourne active_run_id si un scan est en cours.
  // Pour cette PR 3.1-C, on se contente d'un check basique. Le polling
  // complet (re-fetch /run/get_status toutes les 2s) viendra Phase 3.1-D.
  if (!payload) return { active: false };
  const activeRunId = payload.active_run_id || (payload.run_info && payload.run_info.status === "running" ? payload.run_info.run_id : null);
  if (!activeRunId) return { active: false };
  const ri = payload.run_info || {};
  return {
    active: true,
    run_id: activeRunId,
    total: ri.total_rows || ri.total || 0,
    current: ri.current_index || 0,
    phase: ri.phase || "running",
    phase_label: ri.phase_label || null,
    eta_min: ri.eta_min != null ? ri.eta_min : null,
  };
}

function _resolveLatestRun(payload) {
  // get_dashboard ne retourne PAS un champ run_info dedie. Le dernier run est
  // identifie par payload.run_id (id du run resolu en mode "latest") et ses
  // donnees se trouvent dans payload.runs_history[]. On cherche d'abord par
  // run_id ; fallback sur runs_history[0].
  const runs = Array.isArray(payload && payload.runs_history) ? payload.runs_history : [];
  if (payload && payload.run_id) {
    const match = runs.find((r) => r && r.run_id === payload.run_id);
    if (match) return match;
  }
  return runs.length > 0 ? runs[0] : null;
}

// Fix audit 2026-05-24 (v1.5.2) : first-run setup incomplet — l'utilisateur ne
// sait pas pourquoi rien ne marche quand TMDb n'est pas configure. On ajoute
// une banniere jaune en tete d'Accueil pour TMDb (alert, bloquant) et une
// banniere info plus discrete listant les integrations secondaires non
// configurees (Jellyfin / Plex / Radarr). La pastille env-bar restait trop
// silencieuse pour un onboarding decouverte.
function _renderSetupBanner(settings) {
  const s = settings || {};
  // AUDIT 2026-06-14 (R6-G) : le GET masque les secrets -> `tmdb_api_key` revient
  // vide ("••••" ou ""), donc tester sa valeur donnait une FAUSSE alerte
  // "TMDb n'est pas configuré" alors que la clé est bien là (cf pastille ☑TMDb
  // verte + Paramètres "Configuré"). On lit le flag canonique `_has_tmdb_api_key`
  // (présence réelle de la clé), avec repli sur la valeur si elle n'est pas masquée.
  const tmdbKey = typeof s.tmdb_api_key === "string" ? s.tmdb_api_key.trim() : "";
  const hasTmdbKey = s._has_tmdb_api_key === true || tmdbKey !== "";
  const tmdbEnabled = s.tmdb_enabled !== false; // par defaut on suppose enabled
  const tmdbMissing = !tmdbEnabled || !hasTmdbKey;

  const secondaryMissing = [];
  if (!s.jellyfin_enabled && !(typeof s.jellyfin_api_key === "string" && s.jellyfin_api_key.trim())) {
    secondaryMissing.push("Jellyfin");
  }
  if (!s.plex_enabled && !(typeof s.plex_token === "string" && s.plex_token.trim())) {
    secondaryMissing.push("Plex");
  }
  if (!s.radarr_enabled && !(typeof s.radarr_api_key === "string" && s.radarr_api_key.trim())) {
    secondaryMissing.push("Radarr");
  }

  let html = "";
  if (tmdbMissing) {
    html += `
      <div class="accueil-setup-banner accueil-setup-banner--alert" role="alert">
        ⚠️ Configuration incomplète : TMDb n'est pas configuré.
        <a href="#/parametres#integrations">Configurer maintenant →</a>
      </div>
    `;
  }
  if (secondaryMissing.length > 0) {
    html += `
      <div class="accueil-setup-banner accueil-setup-banner--info" role="status">
        ℹ️ Intégrations optionnelles non configurées : ${escapeHtml(secondaryMissing.join(", "))}.
        <a href="#/parametres#integrations">Configurer →</a>
      </div>
    `;
  }
  return html;
}

// Fix audit 2026-05-24 (v1.5.2) : Vague E — carte discrete "Nouvelle version
// disponible" sous le hero, visible uniquement si update detectee. Le badge
// sidebar reste affiche en parallele (deja gere par app.js:_checkUpdateBadge).
// La donnee provient du cache backend (runtime/get_update_info) fetchee en
// parallele du dashboard au init.
function _renderUpdateCard(updateInfo) {
  if (!updateInfo || !updateInfo.update_available || !updateInfo.latest_version) {
    return "";
  }
  const version = escapeHtml(String(updateInfo.latest_version));
  const releaseUrl = updateInfo.release_url ? String(updateInfo.release_url) : "";
  const downloadUrl = updateInfo.download_url ? String(updateInfo.download_url) : releaseUrl;
  const viewAttr = releaseUrl ? `data-accueil-update-url="${escapeHtml(releaseUrl)}"` : "";
  const dlAttr = downloadUrl && downloadUrl !== releaseUrl
    ? `data-accueil-update-url="${escapeHtml(downloadUrl)}"`
    : "";
  const dlBtn = dlAttr
    ? `<button type="button" class="v5-btn v5-btn--sm v5-btn--primary" ${dlAttr}>Télécharger</button>`
    : "";
  return `
    <div class="accueil-update-card" role="status" aria-label="Mise à jour disponible">
      <span class="accueil-update-card-msg">⬆ Nouvelle version v${version} disponible.</span>
      <span class="accueil-update-card-actions">
        ${releaseUrl ? `<button type="button" class="v5-btn v5-btn--sm" ${viewAttr}>Voir</button>` : ""}
        ${dlBtn}
      </span>
    </div>
  `;
}

function _renderAccueil(payload, stats, settings, updateInfo) {
  const latestRun = _resolveLatestRun(payload);
  const recentRuns = Array.isArray(payload && payload.runs_history) ? payload.runs_history : [];
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  const alertCount = insights.length;
  const alertSeverity = insights.some((i) => i.severity === "danger") ? "danger" : "info";
  const roots = settings && Array.isArray(settings.roots) ? settings.roots : [];
  const scanProgress = _extractScanProgress(payload);
  const heroState = {
    active_run_id: scanProgress.active ? scanProgress.run_id : null,
    active_total: scanProgress.total,
    active_eta_min: scanProgress.eta_min,
    latest_run: latestRun,
    error_critical: payload.error_critical || false,
    alert_count: alertCount,
    alert_severity: alertSeverity,
  };
  // Snapshot des pings synchrones (utilise le cache si dispo).
  const pingSnapshot = {};
  for (const it of _INTEGRATIONS) {
    const cached = _pingCacheGet(it.key);
    if (cached !== undefined) pingSnapshot[it.key] = cached;
  }
  return `
    <section class="accueil-view">
      ${_renderSetupBanner(settings)}
      ${_renderEnvironmentBar(roots, settings, pingSnapshot)}
      ${_renderHero(heroState)}
      ${_renderUpdateCard(updateInfo)}
      ${_renderLastRunCard(latestRun, payload && payload.kpis)}
      ${_renderCtaScan(roots, scanProgress)}
      ${_renderSuggestions(stats || {})}
      ${_renderHealth(stats || {})}
      ${_renderRecentActivity(recentRuns)}
    </section>
  `;
}

/* Phase 3.1-C : alimente l'Inspecteur droit avec 3 sections : Contexte,
 * Rappels operateur, Raccourcis (spec 05 §3 Inspecteur droit sur Accueil).
 */
function _buildInspectorSections(payload, stats, settings) {
  const total = (stats && stats.summary && stats.summary.total_films)
    || (stats && stats.v2_tier_distribution && stats.v2_tier_distribution.total)
    || (stats && stats.total_scored)
    || null;
  const activeRun = payload && payload.active_run_id;
  const latestRun = _resolveLatestRun(payload);
  const lastScanTs = latestRun && latestRun.started_ts != null
    ? new Date(Number(latestRun.started_ts) * 1000)
    : (latestRun && latestRun.started_at) || null;
  const lastScanLabel = lastScanTs ? formatRelativeTime(lastScanTs) : "—";
  const omdbEnabled = settings && (settings.omdb_enabled === true || (typeof settings.omdb_api_key === "string" && settings.omdb_api_key.trim() !== ""));
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  const reminders = [];
  if (latestRun && String(latestRun.status || "").toUpperCase() === "AWAITING_VALIDATION") {
    reminders.push("Pense à valider la run de ce matin");
  }
  if (!omdbEnabled) {
    reminders.push("OMDb non configuré — pas de validation croisée sur les matchs douteux");
  }
  insights.slice(0, 3).forEach((i) => {
    if (i.label && i.severity === "warning") reminders.push(`${i.count || ""} ${i.label}`.trim());
  });
  return [
    {
      title: "Contexte",
      html: `
        <dl class="accueil-inspector-dl">
          <div><dt>Bibliothèque</dt><dd>${escapeHtml(total != null ? String(total) : "—")}</dd></div>
          <div><dt>Run actif</dt><dd>${escapeHtml(activeRun || "aucun")}</dd></div>
          <div><dt>Dernier scan</dt><dd>${escapeHtml(lastScanLabel)}</dd></div>
        </dl>
      `,
    },
    {
      title: "Rappels opérateur",
      html: reminders.length === 0
        ? `<p class="accueil-empty-msg">Rien à signaler.</p>`
        : `<ul class="accueil-inspector-list">${reminders.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`,
    },
    {
      title: "Raccourcis",
      // Fix bug #2 : raccourcis alignes sur la vraie table de core/keyboard.js.
      // Ctrl+S = save-request (PAS "Nouveau scan"). Les vrais raccourcis utiles
      // pour la navigation depuis l'Accueil sont Alt+1..7, plus Ctrl+B/I/K/, et ?.
      html: `
        <dl class="accueil-inspector-shortcuts">
          <div><dt><kbd>Alt</kbd>+<kbd>1</kbd>..<kbd>7</kbd></dt><dd>Navigation directe (Accueil → Aide)</dd></div>
          <div><dt><kbd>Ctrl</kbd>+<kbd>K</kbd></dt><dd>Recherche / palette de commandes</dd></div>
          <div><dt><kbd>Ctrl</kbd>+<kbd>B</kbd></dt><dd>Replier / déplier la sidebar</dd></div>
          <div><dt><kbd>Ctrl</kbd>+<kbd>I</kbd></dt><dd>Afficher / masquer l'inspecteur</dd></div>
          <div><dt><kbd>Ctrl</kbd>+<kbd>,</kbd></dt><dd>Paramètres</dd></div>
          <div><dt><kbd>?</kbd></dt><dd>Aide</dd></div>
        </dl>
      `,
    },
  ];
}

/* --- Démarrage 1-clic + drawer Options + polling ----------------------- */

/* Stocke les settings courants pour pouvoir appeler start_plan sans refetch. */
let _currentSettings = null;
let _pollScanTimer = null;
let _pollContainer = null;

/** Lance run/start_plan avec les settings courants. UI : bouton désactivé +
 *  toast bref. Au succès, démarre le polling 2s sur get_dashboard pour
 *  remplacer la card CTA par la progress bar.
 */
async function _triggerStartPlan(container, btn) {
  if (!_currentSettings) {
    // Pas de settings -> fallback sécurisé vers /traitement.
    navigateTo("/traitement");
    return;
  }
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Démarrage…";
  }
  try {
    const res = await apiPost("run/start_plan", { settings: _currentSettings });
    // Fix audit 2026-05-25 (v1.5.3) Vague F : pattern standardise res.data.ok.
    // L'enveloppe apiPost a un res.ok HTTP (toujours true sur 2xx) ; le ok
    // metier du backend est dans res.data.ok. Avant, on confondait les deux
    // et un start_plan en erreur metier (res.data.ok=false) passait silencieux.
    const _payload = (res && res.data) || res || {};
    if (_payload.ok === false) {
      // Fix audit 2026-06-07 UX : ne plus exposer le message brut du backend
      // (souvent jargon technique anglais). Log technique + message UX clair.
      const technicalMsg = (_payload.message || _payload.error || "").toString();
      if (technicalMsg) console.error("[accueil] start_plan refused:", technicalMsg);
      _showErrorBanner(container, "Impossible de démarrer l'analyse. Réessayer ?");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "▶ Lancer le scan";
      }
      return;
    }
    const runId = _payload.run_id || _payload.runId;
    if (runId) {
      // Démarrer le polling pour transitionner la card vers "scan en cours".
      _startScanPolling(container);
    } else {
      // Fix audit 2026-06-07 UX high : retirer jargon "run_id"/"start_plan".
      _showErrorBanner(container, "Impossible de démarrer l'analyse. Réessayer ?");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "▶ Lancer le scan";
      }
    }
  } catch (err) {
    // Fix audit 2026-06-07 UX high : err.message brut expose du jargon (TypeError,
    // NetworkError…). Log technique en console, message UX clair a l'ecran.
    console.error("[accueil] start_plan failed:", err);
    _showErrorBanner(container, "Impossible de démarrer l'analyse. Réessayer ?");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "▶ Lancer le scan";
    }
  }
}

function _showErrorBanner(container, msg) {
  if (!container || !container.isConnected) return;
  try {
    let banner = container.querySelector(".accueil-scan-error-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "accueil-scan-error-banner";
      banner.setAttribute("role", "alert");
      const cta = container.querySelector(".accueil-cta-scan");
      if (cta) cta.parentElement.insertBefore(banner, cta);
      else container.prepend(banner);
    }
    banner.textContent = "⚠ " + msg;
    setTimeout(() => { if (banner && banner.isConnected) banner.remove(); }, 8000);
  } catch (_e) { /* noop */ }
}

/** Polling get_dashboard 2s pour réactualiser la section CTA Scan + suggestions.
 *  Phase 5 spec §3 : la card "CTA scan" transitionne en "Scan en cours" avec
 *  progress bar et ETA pendant qu'un run est actif.
 */
function _startScanPolling(container) {
  if (_pollScanTimer) clearInterval(_pollScanTimer);
  _pollContainer = container;
  const tick = async () => {
    if (!_pollContainer || !_pollContainer.isConnected) {
      _stopScanPolling();
      return;
    }
    try {
      const res = await apiPost("run/get_dashboard", { run_id: "latest" });
      // Fix audit 2026-05-25 (v1.5.3) Vague F : pattern standardise res.data.ok.
      // Le polling get_dashboard peut renvoyer ok=false metier (run perdu, db
      // inaccessible) alors que l'HTTP est 200. On lit le ok du payload.
      const payload = (res && res.data) || res || {};
      if (payload.ok === false) return;
      const scanProgress = _extractScanProgress(payload);
      const ctaSection = _pollContainer.querySelector(".accueil-cta-scan");
      if (!ctaSection) return;
      if (scanProgress.active) {
        // Remplace la section in-place avec la nouvelle progression.
        const wrapper = document.createElement("div");
        wrapper.innerHTML = _renderScanInProgress(scanProgress).trim();
        ctaSection.replaceWith(wrapper.firstElementChild);
        _rebindCtaScanEvents(_pollContainer);
      } else {
        // Run terminé : full re-render via initAccueil.
        // Fix audit 2026-05-25 (v1.5.3) Vague F : sauve reference DOM avant nullification
        const _savedContainer = _pollContainer;
        _stopScanPolling();
        if (_savedContainer && _savedContainer.isConnected) {
          initAccueil(_savedContainer);
        }
      }
    } catch (_err) { /* silencieux */ }
  };
  _pollScanTimer = setInterval(tick, 2000);
  // Premier tick immédiat pour transitionner sans attendre 2s.
  setTimeout(tick, 100);
}

function _stopScanPolling() {
  if (_pollScanTimer) {
    clearInterval(_pollScanTimer);
    _pollScanTimer = null;
  }
  _pollContainer = null;
}

function _rebindCtaScanEvents(container) {
  // Rebind les boutons de la section CTA après replace.
  container.querySelectorAll(".accueil-cta-scan [data-accueil-action]").forEach((btn) => {
    if (btn.dataset.accueilBound) return;
    btn.dataset.accueilBound = "1";
    btn.addEventListener("click", (ev) => {
      const action = btn.dataset.accueilAction;
      if (action === "open-traitement") navigateTo("/traitement");
      ev.preventDefault();
    });
  });
}

/** Mini-drawer 3 checkboxes (dry-run, profil, ignorer doublons). */
function _openScanOptionsDrawer(container) {
  // Si déjà ouvert, focus.
  const existing = container.querySelector("[data-accueil-scan-drawer]");
  if (existing) {
    const first = existing.querySelector("input,button");
    if (first) first.focus();
    return;
  }
  const drawer = document.createElement("div");
  drawer.className = "accueil-scan-drawer";
  drawer.setAttribute("data-accueil-scan-drawer", "");
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-label", "Options du scan");
  drawer.innerHTML = `
    <div class="accueil-scan-drawer-inner">
      <h3 class="accueil-scan-drawer-title">Options du scan</h3>
      <label class="accueil-scan-drawer-row">
        <input type="checkbox" data-opt="dry_run"> Dry-run (simulation seulement)
      </label>
      <label class="accueil-scan-drawer-row">
        <input type="checkbox" data-opt="skip_duplicates"> Ignorer la détection de doublons
      </label>
      <label class="accueil-scan-drawer-row">
        <input type="checkbox" data-opt="apply_after"> Appliquer automatiquement après validation
      </label>
      <div class="accueil-scan-drawer-actions">
        <button type="button" class="v5-btn v5-btn--ghost" data-accueil-scan-drawer-cancel>Annuler</button>
        <button type="button" class="v5-btn v5-btn--primary" data-accueil-scan-drawer-start>▶ Lancer le scan</button>
      </div>
    </div>
  `;
  const ctaSection = container.querySelector(".accueil-cta-scan");
  if (ctaSection) ctaSection.appendChild(drawer);
  else container.appendChild(drawer);
  drawer.querySelector("[data-accueil-scan-drawer-cancel]").addEventListener("click", () => drawer.remove());
  drawer.querySelector("[data-accueil-scan-drawer-start]").addEventListener("click", async () => {
    const opts = {};
    drawer.querySelectorAll("input[type=checkbox][data-opt]").forEach((cb) => {
      opts[cb.dataset.opt] = !!cb.checked;
    });
    drawer.remove();
    // Merge options dans settings courants pour l'appel start_plan.
    const merged = Object.assign({}, _currentSettings || {}, opts);
    const previousSettings = _currentSettings;
    _currentSettings = merged;
    try {
      await _triggerStartPlan(container, null);
    } finally {
      _currentSettings = previousSettings;
    }
  });
}

/* --- Event binding ----------------------------------------------------- */

function _bindEvents(container) {
  // Boutons d'action principaux (start scan / resume / view detail / view history /
  // open-insight / view-qualite / open-scan-options / start-scan-direct / view-all-suggestions)
  container.querySelectorAll("[data-accueil-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      const action = btn.dataset.accueilAction;
      const runId = btn.dataset.runId;
      const targetRoute = btn.dataset.targetRoute;
      switch (action) {
        case "start-scan":
          // Empty state (jamais de run) -> route vers Traitement pour onboarding.
          navigateTo("/traitement");
          break;
        case "start-scan-direct":
          // Phase 5 spec §3 : lancement 1-clic via run/start_plan.
          _triggerStartPlan(container, btn);
          break;
        case "view-all-suggestions":
          // Phase 5 spec §4 : "Voir toutes" => Qualité (audit complet).
          navigateTo("/qualite");
          break;
        case "resume-validation":
          if (runId) navigateTo(`/traitement#run-${encodeURIComponent(runId)}`);
          else navigateTo("/traitement");
          break;
        case "view-run-detail":
          if (runId) navigateTo(`/historique#run-${encodeURIComponent(runId)}`);
          else navigateTo("/historique");
          break;
        case "view-history":
          navigateTo("/historique");
          break;
        case "view-qualite":
          navigateTo("/qualite");
          break;
        case "open-insight":
          if (targetRoute) navigateTo(targetRoute);
          break;
        case "open-scan-options":
          // Phase 5 spec §3 : mini-drawer pour 3 options puis Démarrer.
          _openScanOptionsDrawer(container);
          break;
        case "open-traitement":
          navigateTo("/traitement");
          break;
        default:
          break;
      }
      ev.preventDefault();
    });
  });

  // Phase 3.1-C : pastilles integrations cliquables -> Parametres > Integrations.
  container.querySelectorAll("[data-integration]").forEach((pill) => {
    pill.addEventListener("click", (ev) => {
      const key = pill.dataset.integration || "";
      // Section "integrations" dans la sub-sidebar Parametres (Phase 3.1-D).
      // En attendant : fragment pour pre-selection.
      navigateTo(`/parametres#integrations-${encodeURIComponent(key)}`);
      ev.preventDefault();
    });
  });

  // Lignes d'activite cliquables -> historique > detail run (legacy)
  container.querySelectorAll(".accueil-activity-row").forEach((row) => {
    const open = () => {
      const runId = row.dataset.runId;
      if (runId) navigateTo(`/historique#run-${encodeURIComponent(runId)}`);
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });

  // Phase 5 : bullets de la timeline cliquables -> historique > detail run.
  container.querySelectorAll(".accueil-timeline-bullet[data-run-id]").forEach((bullet) => {
    bullet.addEventListener("click", (ev) => {
      const runId = bullet.dataset.runId;
      if (runId) navigateTo(`/historique#run-${encodeURIComponent(runId)}`);
      ev.preventDefault();
    });
  });

  // Retry button (cas erreur)
  const retryBtn = container.querySelector("[data-accueil-retry]");
  if (retryBtn) {
    retryBtn.addEventListener("click", () => initAccueil(container));
  }

  // Fix audit 2026-05-24 (v1.5.2) : Vague E — clic sur "Voir" / "Telecharger"
  // dans la carte update sous le hero -> ouvre l'URL externe via runtime
  // (WebView2 sans handler bloque window.open silencieusement).
  container.querySelectorAll("[data-accueil-update-url]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const url = btn.getAttribute("data-accueil-update-url") || "";
      if (!url) return;
      try { await apiPost("runtime/open_external_url", { url }); } catch { /* silencieux */ }
    });
  });
}

/* --- Entrypoint -------------------------------------------------------- */

// Phase 6 spec 05 100% : AbortController dédié à la vue Accueil pour pouvoir
// abort tous les fetchs en cours quand on quitte la vue (cleanup propre).
let _abortController = null;

/**
 * Cleanup callback de la vue Accueil. Appelé par le router à la navigation
 * sortante (return value de init dans registerRoute). Idempotent.
 * - Stoppe le polling de scan
 * - Abort les fetchs en cours via _abortController
 */
export function unmountAccueil() {
  _stopScanPolling();
  if (_abortController) {
    try { _abortController.abort(); } catch { /* no-op */ }
    _abortController = null;
  }
}

export async function initAccueil(container) {
  if (!container) return;
  // Re-entrance safety : si initAccueil est appelé alors qu'une vue précédente
  // est encore active, cleanup d'abord (évite le double polling + listeners).
  unmountAccueil();
  _abortController = new AbortController();
  const signal = _abortController.signal;

  // Phase 3.1-B : on charge en parallele les 3 sources (dashboard latest +
  // global stats + settings) pour avoir les donnees des 5 sections en un boot.
  // Fix audit 2026-05-24 (v1.5.2) Vague E : on ajoute un 4e fetch (update_info
  // cache uniquement, donc instantane) pour la carte "Nouvelle version
  // disponible" sous le hero. Pas d'appel reseau ici, juste lecture du cache
  // alimente au boot par le hook updater.
  let dashRes = null;
  let statsRes = null;
  let settingsRes = null;
  let updateRes = null;
  try {
    [dashRes, statsRes, settingsRes, updateRes] = await Promise.all([
      apiPost("run/get_dashboard", { run_id: "latest" }, { signal }),
      apiPost("run/get_global_stats", {}, { signal }).catch(() => null),
      apiPost("settings/get_settings", {}, { signal }).catch(() => null),
      apiPost("runtime/get_update_info", {}, { signal }).catch(() => null),
    ]);
  } catch (err) {
    if (err && err.name === "AbortError") return;
    container.innerHTML = _renderError(err ? String(err.message || err) : "Erreur réseau");
    _bindEvents(container);
    return;
  }

  // AUDIT 2026-06-10 (REAL 2/2) : le ok METIER est dans res.data.ok, pas au
  // top-level de l'enveloppe apiPost {status, data}. Avant, dashRes.ok===false
  // n'etait jamais vrai -> une erreur metier (DB inaccessible, 401, 429) etait
  // rendue comme un succes avec le payload d'erreur comme donnees. Meme pattern
  // que _triggerStartPlan / pings (res.data || res).
  const _dashPayload = (dashRes && dashRes.data) || dashRes || {};
  if (!dashRes || _dashPayload.ok === false) {
    const msg = (_dashPayload.message || _dashPayload.error) || "Erreur de chargement du dashboard.";
    container.innerHTML = _renderError(msg);
    _bindEvents(container);
    return;
  }

  const dashboardData = _dashPayload;
  const _statsP = (statsRes && statsRes.data) || statsRes || {};
  const stats = _statsP.ok !== false ? _statsP : {};
  const _setP = (settingsRes && settingsRes.data) || settingsRes || {};
  const settings = _setP.ok !== false ? _setP : {};
  const _updP = (updateRes && updateRes.data) || updateRes || null;
  const updateInfo = _updP && _updP.ok !== false ? _updP : null;
  _currentSettings = settings;

  container.innerHTML = _renderAccueil(dashboardData, stats, settings, updateInfo);
  _bindEvents(container);

  // Phase 5 : lance les pings en arrière-plan pour détecter les intégrations
  // hors-ligne. Les pastilles passent à ⚠ orange au fil des résultats.
  // Fix audit 2026-05-25 (v1.5.3) Vague F : on transmet signal pour cancel
  // propre en cas de navigation pendant l'attente d'un ping reseau.
  _runEnvironmentPingsBackground(container, settings, signal);

  // Phase 5 : si un scan est actif au boot, démarrer le polling pour refresh.
  const initialScan = _extractScanProgress(dashboardData);
  if (initialScan.active) {
    _startScanPolling(container);
  }

  // Phase 5 spec §3 : MAJ visibilité Traitement dans la sidebar selon run actif.
  try {
    _updateSidebarForActiveRun(initialScan.active);
  } catch (_e) { /* noop */ }

  // Phase 3.1-C : alimente l'Inspecteur droit avec contexte + rappels + raccourcis.
  try {
    rightPanel.setSections(_buildInspectorSections(dashboardData, stats, settings));
  } catch (err) {
    // Defensive : l'inspecteur n'est pas critique pour l'Accueil.
    console.warn("[accueil] setSections inspector failed:", err);
  }
}

/** Phase 5 spec §3 : dimmer/masquer l'entrée Traitement de la sidebar si
 *  aucun run actif (visible mais grisée). Si run actif, restaurer l'état.
 */
function _updateSidebarForActiveRun(hasActiveRun) {
  const el = document.querySelector('.v5-sidebar-item[data-route="processing"]');
  if (!el) return;
  el.classList.toggle("v5-sidebar-item--dimmed", !hasActiveRun);
  if (!hasActiveRun) {
    el.setAttribute("data-no-active-run", "1");
    el.setAttribute("title", "Aucun run actif — Traitement disponible quand un scan est lancé");
  } else {
    el.removeAttribute("data-no-active-run");
    el.removeAttribute("title");
  }
}
