/* views/traitement.js — Phase 5 (spec 08-traitement.md, refonte complete).
 *
 * Workflow Traitement natif : header run actif + breadcrumb 5 etapes +
 * etapes Analyse/Verification/Validation/Doublons/Apply portees nativement
 * (sans renvoi vers la vue Bibliotheque legacy).
 *
 * Spec §1 breadcrumb : Analyse → Verification → Validation → Doublons → Apply
 *
 * Endpoints consommes :
 *   - get_dashboard          : KPIs, run_id, runs_history (started_ts)
 *   - run/get_status         : statut, progress (idx/total), eta_s, logs
 *   - run/start_plan         : demarre un nouveau scan
 *   - run/cancel_run         : annule un run en cours
 *   - run/pause_run          : (optionnel, fallback si endpoint absent)
 *   - run/resume_run         : (optionnel, fallback si endpoint absent)
 *   - run/save_for_later     : (optionnel, fallback si endpoint absent)
 *   - check_duplicates       : groupes de doublons + comparison
 *   - save_validation        : persiste les decisions de validation
 *   - apply                  : execute apply (dry-run ou reel)
 *   - get_plan               : recharge plan.jsonl
 *
 * Route : /traitement (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost, fetchConfidenceThresholds, getConfidenceThresholdsSync } from "../core/api.js";
import { navigateTo } from "../core/router.js";
import { dangerConfirmModal, showModal, closeModal } from "../components/modal.js";
import { showToast } from "../components/toast.js";
import { formatRelative, formatDuration } from "../core/format.js";
import { initDoublons, unmountDoublons } from "./doublons.js";
// Fix audit 2026-05-24 : import renderFilmDetail pour brancher les actions
// "rename" (Vérification) et "inspect" (Validation) qui étaient inertes.
import { renderFilmDetail } from "../components/film-detail.js";

const STEPS = [
  { id: "analyse", label: "Analyse", desc: "Scan des dossiers racines" },
  { id: "verification", label: "Vérification", desc: "Cas à vérifier (priorités)" },
  { id: "validation", label: "Validation", desc: "Approuver / rejeter les films" },
  { id: "doublons", label: "Doublons", desc: "Choisir le film à conserver pour chaque groupe" },
  { id: "apply", label: "Application", desc: "Renommer / déplacer sur disque" },
];

const STATUS_COLORS = {
  RUNNING: { cls: "is-running", icon: "●", label: "En cours" },
  PENDING: { cls: "is-running", icon: "●", label: "En attente" },
  PAUSED: { cls: "is-paused", icon: "⏸", label: "En pause" },
  SAVED: { cls: "is-paused", icon: "💾", label: "Sauvegardé" },
  AWAITING_VALIDATION: { cls: "is-paused", icon: "⏳", label: "En attente de validation" },
  DONE: { cls: "is-done", icon: "✓", label: "Terminé" },
  CANCELLED: { cls: "is-error", icon: "✗", label: "Annulé" },
  FAILED: { cls: "is-error", icon: "✗", label: "Erreur" },
  ERROR: { cls: "is-error", icon: "✗", label: "Erreur" },
};

const POLL_INTERVAL_RUNNING = 5000; // 5s pendant RUNNING (header)
const POLL_INTERVAL_ANALYSE = 2000; // 2s pendant scan en cours (etape 1)
// Fix APPLY-2 (2026-05-30) : polling rapide pendant apply en cours (etape 5).
const POLL_INTERVAL_APPLY = 1500;
const UNDO_COUNTDOWN_INTERVAL_MS = 60_000; // Spec 08 §3.5 : refresh carte undo / 60s

// Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : backoff exponentiel cote UI sur
// erreur reseau / payload anormal (ex: ok=false, _runStatus=null apres tentative).
// Avant : setInterval fixe (2-5s) qui martelait /api/run/get_status meme quand le
// backend etait DEGRADED (probe hang ~35s, cf BILAN_ITER13 section 2 "Polling UI
// sans backoff sur degradation"). Maintenant : on degrade en sequence 1s/2s/4s/8s
// jusqu'au plafond, on remet a 0 sur premier succes. Affichage "Reconnexion dans Xs"
// visible dans le header pour informer l'utilisateur.
const POLL_BACKOFF_SEQUENCE_MS = [1000, 2000, 4000, 8000]; // plafond 8s
const POLL_BACKOFF_MAX_ATTEMPTS = 8; // borne souple : passe au plafond apres le 4eme

/**
 * mega-hotfix frontend_ui_polish (#5) : countdown gradue lineaire pour
 * dangerConfirmModal. Avant : cliff effect a 50/51 (0s a 50 elements, 3s
 * direct a 51 elements). Maintenant : transition lineaire entre 30 et 100.
 *   - <= 30 : 0s
 *   - 30 < n <= 50 : interpolation arrondie (0..3s)
 *   - > 50 : 3s (regle utilisateur "actions dangereuses : countdown 3s si >50")
 *
 * Fix regression UI-OVERLAYS-02-COUNTDOWN-RULE-VIOLATION-TRAITEMENT :
 * la version precedente (>= 100 : 3s, sinon interpolation) pouvait retourner
 * 1s ou 2s pour n entre 51 et 99, violant la regle utilisateur obligatoire.
 * Clamp ajoute : > 50 -> 3s pour garantir conformite.
 */
function _gradedCountdownSeconds(count) {
  const n = Number(count) || 0;
  if (n <= 30) return 0;
  if (n > 50) return 3;
  const linear = ((n - 30) / (100 - 30)) * 3;
  return Math.max(0, Math.min(3, Math.round(linear)));
}

// M14 (audit ultra 2026-07-13) : collation FRANCAISE partagee, meme instance
// d'Intl.Collator que la Bibliotheque (À classé avec A, Ç avec C, ellipse/
// ponctuation initiale ignorée, "Chapitre 2" avant "Chapitre 10"). Reutilisee
// par l'etape Verification (_renderVerificationStep) ET le tri de l'etape
// Validation (_sortValidationRows) pour une collation coherente entre ecrans.
const _FR_COLLATOR = new Intl.Collator("fr", { sensitivity: "base", numeric: true, ignorePunctuation: true });

let _currentStep = "analyse";
let _runInfo = null;
let _runStatus = null; // { status, idx, total, eta_s, speed, logs }
// R8-064 (F5) : résumé d'auto-approbation (run/get_auto_approved_summary), surfacé une
// fois le plan prêt. _autoApproveForRun = runId pour lequel le résumé a déjà été obtenu.
let _autoApprove = null; // { autoApproved, manualReview, threshold }
let _autoApproveForRun = null;
let _loading = false;
let _targetRunId = null; // Phase 5 spec §2 : fragment #run-XXX = run cible à afficher.
let _pollTimer = null;
// Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : state du backoff exponentiel.
// _pollErrorStreak : nombre d'echecs consecutifs (>=1 : on est en backoff).
// _pollNextRetryAt : timestamp (ms epoch) du prochain tick de polling, sert au
//   countdown affiche dans le header (mis a jour par _renderInPlace au render).
// _pollLastError : derniere cause d'echec (texte court), affichee a cote du
//   countdown pour donner un signal honnete (vs disparition silencieuse).
let _pollErrorStreak = 0;
let _pollNextRetryAt = 0;
let _pollLastError = null;
let _undoCountdownTimer = null; // Spec 08 §3.5 : refresh carte annulation post-apply.
let _logsState = { items: [], nextIndex: 0 };
let _scanOptions = {
  perceptual: true,
  subtitles: true,
  omdb: false,
  nfo: false,
  parallelism: 4,
};
let _activeContainer = null;
let _doublonsMounted = false;
// Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : flag d'idempotence du binding.
// Avant : _bindEvents() rattachait addEventListener() à chaque _renderInPlace()
// (polling 2-5s + chaque action UI) -> N listeners accumulés sur les MÊMES
// boutons (Pause, Cancel, Apply…) -> 1 clic = N appels API -> doubles annulations,
// doubles toasts, race conditions sur les state setters. Avec event delegation
// (un seul listener sur _container qui dispatch via event.target.closest),
// _renderInPlace() peut innerHTML= toute la vue sans risque : le listener vit
// sur le container parent, pas sur les enfants recrées.
let _eventsBound = false;
let _verifFilter = "all";
let _validationPlan = null; // { rows: [...] }
// Fix VAL-3 (2026-05-30) : state module-level pour filtre / tri / expanded rows
// de l'etape Validation. Reset au unmount pour eviter de garder un etat surprenant
// si l'utilisateur revient plus tard sur l'etape Validation.
let _validationFilter = "all"; // all | high | mid | low | none
let _validationSort = { key: "confidence", dir: "desc" };
let _validationExpanded = new Set();
// VN-C.2 (Vague N batch 2) : etat JS unique source de verite des decisions de
// validation (ok/year). Remplace l'ancien DOM-as-source-of-truth de
// _buildDecisions() qui ne lisait que les checkboxes presentes dans le DOM
// (i.e. apres filtre). Resultat avant fix : un filtre "high" actif + Save
// reinjectait silencieusement REJECT pour toutes les lignes hors viewport.
// rowId -> { ok: bool, year: int|null, decided_at: ts }
let _decisionsState = new Map();
// Fix APPLY-2 (2026-05-30) : intervalle polling pendant l'apply (idem scan)
// et state apply pour les progressions live.
let _applyStatus = null;
// Vague P / VP-A : `apply_atomic` opt-in (default OFF). Si actif et qu'une
// erreur interrompt le batch en cours d'apply reel, le backend declenche un
// rollback FS+DB forward (cf cinesort/app/apply_rollback.py).
let _applyOptions = {
  dry_run: true,
  export_csv: false,
  sync_jellyfin: false,
  quarantine: false,
  apply_atomic: false,
};
// AUDIT 2026-06-13 (R5-P2) : aperçu + résumé de l'Étape 5 alimentés par le VRAI
// plan backend (run/build_apply_preview), au lieu d'estimations client-side
// mensongères. Avant : `renames = approved.length`, `moves = 0`, et l'aperçu
// affichait "Dossier renommé : <racine> -> <titre>" pour les films posés à la
// racine alors que l'apply CRÉE un sous-dossier et y DÉPLACE le fichier (cf
// summary.txt du run + plan_support_core.py:674). _applyPreviewSig invalide le
// cache quand les décisions changent (approve/reject).
let _applyPreview = null;
let _applyPreviewLoading = false;
let _applyPreviewSig = "";
// Fix audit 2026-05-24 : AbortController scope module pour annuler tous les
// apiPost en vol au unmount (navigation, fermeture vue). Sans ça les fetch
// continuent et appellent _renderInPlace/_loadXxx après remise à null du
// container -> NPE silencieux dans la console + fuite mémoire.
let _abortController = null;

function _signal() {
  return _abortController ? _abortController.signal : undefined;
}

/** Relecture adversaire de la PR #873 (point 1) — l'abort de `unmountTraitement`
 *  n'est PAS un echec de l'operation.
 *
 *  `unmountTraitement()` appelle `_abortController.abort()` : toute requete en
 *  vol emise avec `_signal()` rejette alors un `AbortError`. Ce rejet ne dit
 *  RIEN du sort de l'operation cote serveur — le POST est deja parti et le
 *  backend continue son travail. Sur un chemin destructif (apply, undo), le
 *  presenter comme « Erreur lors de l'apply. » est le pire message possible :
 *  l'utilisateur croit son apply mort pendant que les fichiers bougent, et il
 *  relance.
 *
 *  Le declencheur reel est l'auditeur `cinesort:refresh` (`_refreshCurrentView`,
 *  core/keyboard.js) : F5 — ou l'entree « Rafraichir la vue » de Ctrl+K —
 *  re-monte la route courante, ce qui passe par le cleanup de la vue, donc par
 *  cet abort. (Fusion main <- PR #873 : ce lot avait pose cet auditeur dans
 *  app.js, main dans core/keyboard.js ; un seul a ete conserve, cf. app.js.)
 *
 *  Choix assume : on GARDE `_signal()` sur ces requetes (plutot que de les
 *  detacher comme `_handleSaveValidation({detached:true})`) et on filtre
 *  l'AbortError. Detacher ferait survivre la CONTINUATION (toast, puis
 *  `_loadRunInfo()` + `_renderInPlace()`) a la destruction de la vue —
 *  exactement le NPE + « state set sur ancien run » que l'abort a ete
 *  introduit pour empecher (cf. le commentaire de `_abortController`).
 *  `_handleSaveValidation` peut se detacher parce que son resultat est
 *  volontairement ignore (`if (detached) return;`) : il n'a pas de
 *  continuation. Ici il y en a une. Apres remount, `initTraitement()` refait
 *  `_loadRunInfo()` et relance le polling : l'utilisateur retrouve l'apply
 *  reel en cours, ce qui est l'information juste. */
function _abortedByViewTeardown(err) {
  return err?.name === "AbortError";
}

/* --- Step nav helpers --- */

function _readStep() {
  const hash = window.location.hash || "";
  const m = hash.match(/#step-([a-z]+)/);
  if (m && STEPS.some((s) => s.id === m[1])) return m[1];
  return "analyse";
}

/** Phase 5 (spec 05 §2 "Reprendre la validation") : extrait le run_id si
 *  fragment "/traitement#run-XXXX" présent. Stocké dans _targetRunId pour
 *  forcer le focus sur ce run au lieu du dernier en date.
 */
function _readTargetRunId() {
  const hash = window.location.hash || "";
  const m = hash.match(/#run-([^#&?\s]+)/);
  if (m) {
    try { return decodeURIComponent(m[1]); }
    catch (_e) { return m[1]; }
  }
  return null;
}

function _writeStep(stepId) {
  if (window.location.hash.includes(`#step-${stepId}`)) return;
  window.location.hash = `#/traitement#step-${stepId}`;
}

/* --- Data fetchers --- */

async function _loadRunInfo() {
  _loading = true;
  // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : on retourne un boolean
  // succes/echec consomme par la boucle de polling pour ajuster le backoff.
  let _ok = false;
  try {
    // Phase 5 : si fragment #run-XXX présent, charge ce run précis.
    const targetId = _targetRunId;
    // Fix audit 2026-05-24 : avant `run_id_or` (n'existe pas dans la facade)
    // -> get_dashboard renvoyait 400 -> _runInfo restait null -> polling
    // get_status jamais armé -> barre de progress + logs scan invisibles
    // dans l'UI alors que le scan tourne en backend.
    const params = targetId ? { run_id: targetId } : { run_id: "latest" };
    const res = await apiPost("run/get_dashboard", params, { signal: _signal() });
    if (!res || res.data?.ok === false) {
      _runInfo = null;
      _pollLastError = "Reponse get_dashboard invalide";
      _loading = false;
      return false;
    }
    const data = res.data || res;
    // Fix audit 2026-05-24 : si le run actif change (nouveau scan lancé,
    // navigation #run-XXX), les logs accumulés du run précédent restaient
    // dans _logsState et étaient injectés en haut du log live du nouveau run
    // -> confusion utilisateur + nextIndex pointait dans la timeline du run
    // précédent -> get_status renvoyait des logs déjà vus (ou rien).
    if (data.run_id && _runInfo && _runInfo.runId && data.run_id !== _runInfo.runId) {
      _logsState = { items: [], nextIndex: 0 };
    }
    const k = data.kpis || {};
    const history = Array.isArray(data.runs_history) ? data.runs_history : [];
    const current = history.find((r) => r.run_id === data.run_id) || history[0] || {};
    const pendingUndoRaw = data.pending_undo && typeof data.pending_undo === "object" ? data.pending_undo : null;
    _runInfo = {
      runId: data.run_id,
      total: Number(k.total_movies || k.total_rows || 0),
      validated: Number(k.validated_count || k.approved_count || 0),
      rejected: Number(k.rejected_count || 0),
      conflicts: Number(k.conflicts_count || 0),
      duplicatesGroups: Number(k.duplicates_groups || 0),
      applied: Number(k.applied_rows || current.applied_rows || 0),
      reviewQueue: Number(k.review_queue_count || 0),
      score: Number(k.score_avg || 0),
      startedTs: Number(current.started_ts || 0),
      endedTs: Number(current.ended_ts || 0),
      duration: Number(current.duration_s || 0),
      errorsCount: Number(current.errors_count || 0),
      // Spec 08 §3.5 : carte annulation post-apply (24h).
      pendingUndo: pendingUndoRaw
        ? {
            batchId: String(pendingUndoRaw.batch_id || ""),
            applyTs: Number(pendingUndoRaw.apply_ts || 0),
            deadlineTs: Number(pendingUndoRaw.deadline_ts || 0),
            reversibleCount: Number(pendingUndoRaw.reversible_count || 0),
            expired: Boolean(pendingUndoRaw.expired),
          }
        : null,
    };
    // R8-064 (F5) : surface le résumé d'auto-approbation (combien de films la confiance
    // élevée + 0 warning critique rendrait auto-approuvables). Endpoint run/get_auto_approved_summary
    // jamais consommé avant. Fetch une fois le plan prêt (retry tant que « plan pas prêt »),
    // puis figé pour ce run. enabled:true => on montre le POTENTIEL d'auto-approbation.
    if (_runInfo.runId && _autoApproveForRun !== _runInfo.runId) {
      try {
        const ar = await apiPost("run/get_auto_approved_summary",
          { run_id: _runInfo.runId, enabled: true }, { signal: _signal() });
        const ad = (ar && ar.data) || ar || {};
        if (ad.ok !== false) {
          _autoApprove = {
            autoApproved: Number(ad.auto_approved || 0),
            manualReview: Number(ad.manual_review || 0),
            threshold: Number(ad.threshold || 85),
          };
          _autoApproveForRun = _runInfo.runId; // figé seulement en cas de succès
        }
      } catch (_e) {
        /* plan pas encore prêt ou abort -> nouvel essai au prochain poll */
      }
    }
    _ok = true;
  } catch (err) {
    _runInfo = null;
    // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : capture la cause pour
    // l'affichage user (transparence non silencieuse).
    _pollLastError = err && err.name === "AbortError"
      ? null // unmount en cours, pas un vrai echec
      : `Erreur reseau get_dashboard${err && err.message ? ` : ${String(err.message).slice(0, 80)}` : ""}`;
  }
  _loading = false;
  return _ok;
}

async function _loadRunStatus() {
  if (!_runInfo || !_runInfo.runId) return true;
  // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : retourne un boolean pour
  // alimenter le backoff (idem _loadRunInfo).
  try {
    const res = await apiPost("run/get_status", {
      run_id: _runInfo.runId,
      last_log_index: _logsState.nextIndex || 0,
    }, { signal: _signal() });
    const data = res?.data || res;
    if (!data || data.ok === false) {
      _runStatus = null;
      _pollLastError = "Reponse get_status invalide";
      return false;
    }
    _runStatus = {
      status: String(data.status || "UNKNOWN"),
      running: Boolean(data.running),
      done: Boolean(data.done),
      idx: Number(data.idx || 0),
      total: Number(data.total || 0),
      eta_s: Number(data.eta_s || 0),
      speed: Number(data.speed || 0),
      current: String(data.current || ""),
      error: data.error || null,
      cancelRequested: Boolean(data.cancel_requested),
    };
    // Fix APPLY-2 (2026-05-30) : capter le sous-objet apply pour le rendu
    // de la barre de progression de l'etape 5. Backward-compat : si le backend
    // ne renvoie pas encore data.apply, on garde _applyStatus tel quel (peut
    // etre seede par _handleApplyNow en local).
    if (data.apply) {
      _applyStatus = {
        running: Boolean(data.apply.running),
        done: Boolean(data.apply.done),
        idx: Number(data.apply.idx || 0),
        total: Number(data.apply.total || 0),
        current: String(data.apply.current || ""),
        phase: String(data.apply.phase || ""),
        eta_s: Number(data.apply.eta_s || 0),
        speed: Number(data.apply.speed || 0),
        dryRun: Boolean(data.apply.dry_run),
      };
    } else if (!_applyStatus?.running) {
      _applyStatus = null;
    }
    const newLogs = Array.isArray(data.logs) ? data.logs : [];
    if (newLogs.length) {
      _logsState.items = (_logsState.items || []).concat(newLogs).slice(-30);
    }
    _logsState.nextIndex = Number(data.next_log_index || _logsState.nextIndex);
    return true;
  } catch (err) {
    /* on garde l'ancien _runStatus */
    _pollLastError = err && err.name === "AbortError"
      ? null
      : `Erreur reseau get_status${err && err.message ? ` : ${String(err.message).slice(0, 80)}` : ""}`;
    return false;
  }
}

/* --- Polling lifecycle --- */

function _stopPolling() {
  if (_pollTimer) {
    // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : on est passe d'un setInterval
    // a un setTimeout recursif (chaque tick programme le suivant en fonction du
    // backoff). clearTimeout suffit donc, mais on garde clearInterval pour la
    // backward-compat avec un eventuel hot-reload qui aurait deja installe un
    // ancien timer setInterval. clearTimeout/clearInterval acceptent le meme id.
    clearTimeout(_pollTimer);
    _pollTimer = null;
  }
  _pollNextRetryAt = 0;
}

function _computePollInterval() {
  // Fix audit 2026-06-08 medium : centralise la decision pour pouvoir la
  // re-evaluer a chaque tick (cf _startPolling). Avant : capture figee au
  // moment de _startPolling, donc le polling restait a l'ancien intervalle
  // apres une transition (ex: analyse 2s -> verification 5s, ou apply.running
  // qui passe a true).
  if (_currentStep === "analyse") return POLL_INTERVAL_ANALYSE;
  if (_currentStep === "apply" && _applyStatus?.running) return POLL_INTERVAL_APPLY;
  return POLL_INTERVAL_RUNNING;
}

// Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : interval effectif a appliquer
// au prochain tick. En mode degrade (_pollErrorStreak >= 1) on bascule sur la
// sequence exponentielle (1s -> 2s -> 4s -> 8s plafond), sinon on retombe sur
// l'interval contextuel calcule par _computePollInterval.
function _effectivePollInterval() {
  if (_pollErrorStreak >= 1) {
    const idx = Math.min(_pollErrorStreak - 1, POLL_BACKOFF_SEQUENCE_MS.length - 1);
    return POLL_BACKOFF_SEQUENCE_MS[idx];
  }
  return _computePollInterval();
}

// Helper : remaining ms avant prochain tick, expose pour le rendu du header
// ("Reconnexion dans Xs"). Plafonne a 0 pour ne pas afficher de duree negative
// si setTimeout a deja firé mais que l'UI n'a pas encore reflete le reset.
function _pollNextRetryRemainingMs() {
  if (!_pollNextRetryAt) return 0;
  return Math.max(0, _pollNextRetryAt - Date.now());
}

async function _pollTick() {
  // Fix audit 2026-05-24 : avant on poll-ait infiniment meme apres run done
  // -> 1 call/2-5s a vie tant que vue montee. Arret propre quand run termine.
  // Un refresh manuel ou un nouveau scan re-arme via _startPolling().
  // Fix APPLY-2 (2026-05-30) : ne PAS stopper le polling tant qu'un apply
  // est en cours, meme si le scan top-level est done.
  if (_runStatus && _runStatus.done && (!_applyStatus || _applyStatus.done || !_applyStatus.running)) {
    _stopPolling();
    if (_currentStep === "analyse") {
      _currentStep = "verification";
      _writeStep("verification");
      await _loadPlan();
    }
    _renderInPlace();
    return;
  }
  const okStatus = await _loadRunStatus();
  const okInfo = await _loadRunInfo();
  // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : un seul des deux echoue
  // suffit a degrader. Sur succes, reset complet du streak ET de l'erreur
  // affichee (signal visible que la connexion est revenue).
  if (okStatus && okInfo) {
    if (_pollErrorStreak > 0) {
      _pollErrorStreak = 0;
      _pollLastError = null;
    }
  } else {
    _pollErrorStreak = Math.min(_pollErrorStreak + 1, POLL_BACKOFF_MAX_ATTEMPTS);
    // log console minimal (debug) : visible en F12 pour traquer la source.
    try {
      // eslint-disable-next-line no-console
      console.warn(
        `[traitement] polling backoff attempt ${_pollErrorStreak}/${POLL_BACKOFF_MAX_ATTEMPTS}`,
        _pollLastError || "(no error message)",
      );
    } catch { /* console indispo */ }
  }
  _renderInPlace();
  // Re-arme le prochain tick avec l'interval effectif (contextuel ou backoff).
  _scheduleNextPoll();
}

function _scheduleNextPoll() {
  // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : ordonnancement recursif
  // setTimeout (vs ancien setInterval) pour reposer chaque delai sur le
  // resultat du tick precedent. _pollNextRetryAt est consomme par
  // _renderHeaderRun pour afficher "Reconnexion dans Xs" en cas de backoff.
  if (_pollTimer) {
    clearTimeout(_pollTimer);
    _pollTimer = null;
  }
  const interval = _effectivePollInterval();
  _pollNextRetryAt = Date.now() + interval;
  _pollTimer = setTimeout(_pollTick, interval);
}

function _startPolling() {
  _stopPolling();
  // Fix APPLY-2 (2026-05-30) : polling rapide pendant un apply en cours sur
  // l'etape 5, pour que la barre de progression et le fichier en cours
  // refletent la realite serveur sans attendre 5s.
  // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : reset du streak + erreur
  // a l'armement pour ne pas heriter d'un etat degrade laisse par une
  // session de polling precedente.
  // NB merge v1.5.2 : l'auto-transition Analyse->Verification (fix v1.5.2) est
  // préservée dans le handler de _scheduleNextPoll (cf bloc _runStatus.done plus haut),
  // avec une condition plus fine (tient compte de _applyStatus).
  _pollErrorStreak = 0;
  _pollLastError = null;
  _scheduleNextPoll();
}

/* --- Header run actif (spec §2) --- */

function _shortRunId(rid) {
  if (!rid) return "—";
  // Format usuel : 20260517_15123abc-xxxx
  return String(rid).slice(0, 16);
}

function _renderHeaderRun() {
  if (!_runInfo || !_runInfo.runId) {
    // Fix audit 2026-06-08 UX high : un seul CTA "Lancer un scan" sur l'ecran
    // vide (l'autre est dans _renderStepPanel placeholder ci-dessous). Avant :
    // doublon visible quand _runInfo=null car _renderTraitement concatene les
    // deux blocs. On garde seulement la mention textuelle ici, le CTA est dans
    // le panel step (qui demarre nativement via data-traitement-action).
    return `
      <header class="traitement-header-run traitement-header-run--empty">
        <p class="traitement-header-empty">Aucun run actif détecté.</p>
      </header>
    `;
  }

  const status = _runStatus?.status || "UNKNOWN";
  const meta = STATUS_COLORS[status] || { cls: "is-unknown", icon: "?", label: status };
  const isRunning = status === "RUNNING" || status === "PENDING";
  const isPaused = status === "PAUSED" || status === "SAVED";
  const idx = _runStatus?.idx || 0;
  // Fix audit 2026-06-08 high : pendant un run actif (RUNNING/PENDING/PAUSED),
  // n'utiliser QUE _runStatus.total (total cible decouvert par le scanner).
  // _runInfo.total (kpis.total_movies = rows persistees) diverge tant que
  // _runStatus n'est pas converge, ce qui causait des sauts ETA (12min -> 2h).
  const total = (isRunning || isPaused)
    ? (_runStatus?.total || 0)
    : (_runStatus?.total || _runInfo.total || 0);
  const etaSeconds = _runStatus?.eta_s || 0;
  // ETA derive : si pas d'eta_s, calcule depuis progress + elapsed
  let etaLabel = "—";
  // Fix audit 2026-06-08 high : ne JAMAIS afficher "X restant" quand le run
  // est termine/annule/echoue (DONE/CANCELLED/FAILED). Sans ce gate, la branche
  // etaSeconds>0 affichait "Termine - 29min restant" (incoherence signalee).
  if (etaSeconds > 0 && (isRunning || isPaused)) {
    etaLabel = `${formatDuration(etaSeconds)} restant`;
  } else if (isRunning && idx > 0 && total > 0 && _runInfo.startedTs > 0) {
    const elapsed = Date.now() / 1000 - _runInfo.startedTs;
    const estTotal = (elapsed / idx) * total;
    const remaining = Math.max(0, Math.round(estTotal - elapsed));
    etaLabel = remaining > 0 ? `${formatDuration(remaining)} restant` : "—";
  }

  const startedLabel = _runInfo.startedTs > 0
    ? `Démarré ${formatRelative(_runInfo.startedTs)}`
    : "";

  // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : badge "Reconnexion dans Xs"
  // quand le polling est en mode degrade. Donne un signal honnete a l'utilisateur
  // (vs "Polling silencieux qui reessaie toutes les 2s sans rien afficher").
  // Memoire violee avant : "degradation JAMAIS silencieuse - qualite indisponible
  // visible PAS score invente PAS ligne disparue PAS 0 trompeur". Le label retry
  // rend la latence backend visible cote UI.
  let backoffBadge = "";
  if (_pollErrorStreak > 0) {
    const remaining = Math.ceil(_pollNextRetryRemainingMs() / 1000);
    const retryLbl = remaining > 0
      ? `Reconnexion dans ${remaining}s`
      : "Reconnexion en cours…";
    const errLbl = _pollLastError
      ? ` (${escapeHtml(_pollLastError)})`
      : "";
    backoffBadge = `
      <div class="traitement-run-backoff" role="status" aria-live="polite"
           title="Connexion serveur degradee. Backoff exponentiel en cours.">
        <span class="traitement-run-backoff-dot" aria-hidden="true">⚠</span>
        <span class="traitement-run-backoff-label">${escapeHtml(retryLbl)}</span>
        <span class="traitement-run-backoff-detail">${errLbl}</span>
      </div>
    `;
  }

  return `
    <header class="traitement-header-run ${escapeHtml(meta.cls)}">
      <div class="traitement-header-run-top">
        <div class="traitement-header-run-id">
          <button type="button" class="traitement-runchip" data-traitement-copy-runid title="Copier le run ID">
            run ${escapeHtml(_shortRunId(_runInfo.runId))}…
          </button>
        </div>
        <div class="traitement-run-status ${escapeHtml(meta.cls)}">
          <span class="traitement-run-status-dot" aria-hidden="true">${escapeHtml(meta.icon)}</span>
          <span class="traitement-run-status-label">${escapeHtml(meta.label)}</span>
        </div>
        <div class="traitement-run-meta">
          <span>${escapeHtml(String(total))} films</span>
          ${startedLabel ? `<span>·</span><span>${escapeHtml(startedLabel)}</span>` : ""}
          ${etaLabel !== "—" ? `<span>·</span><span class="traitement-run-eta">${escapeHtml(etaLabel)}</span>` : ""}
        </div>
      </div>
      ${backoffBadge}
      <div class="traitement-header-actions">
        ${isRunning ? `<button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="pause">⏸ Pause</button>` : ""}
        ${isPaused ? `<button type="button" class="v5-btn v5-btn--primary" data-traitement-action="resume">▶ Reprendre</button>` : ""}
        ${(isRunning || isPaused) ? `<button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="save">💾 Enregistrer le run</button>` : ""}<!-- Fix audit 2026-06-07 UX high : harmonisation "Enregistrer + objet" sur les 3 sites (header / validation / dirty-state). Tooltip retire car libelle desormais explicite. -->
        ${(isRunning || isPaused) ? `<button type="button" class="v5-btn v5-btn--danger" data-traitement-action="cancel">⏹ Annuler</button>` : ""}
      </div>
    </header>
  `;
}

/* --- Breadcrumb --- */

function _renderBreadcrumb(currentStep) {
  const items = STEPS.map((s, i) => {
    const isCurrent = s.id === currentStep;
    const currentIndex = STEPS.findIndex((x) => x.id === currentStep);
    const isPast = i < currentIndex;
    const cls = isCurrent ? "is-current" : (isPast ? "is-past" : "is-future");
    return `
      <button type="button" class="traitement-step ${cls}"
              data-traitement-step="${escapeHtml(s.id)}"
              aria-current="${isCurrent ? "step" : "false"}"
              ${isPast || isCurrent ? "" : "disabled"}>
        <span class="traitement-step-num">${i + 1}</span>
        <span class="traitement-step-content">
          <span class="traitement-step-label">${escapeHtml(s.label)}</span>
          <span class="traitement-step-desc">${escapeHtml(s.desc)}</span>
        </span>
      </button>
      ${i < STEPS.length - 1 ? '<span class="traitement-step-sep" aria-hidden="true">→</span>' : ""}
    `;
  }).join("");
  return `
    <nav class="traitement-breadcrumb" role="navigation" aria-label="Étapes du workflow Traitement">
      ${items}
    </nav>
  `;
}

function _renderStat(label, value, suffix) {
  return `
    <div class="traitement-stat">
      <div class="traitement-stat-value">${escapeHtml(String(value))}${suffix ? ` <span class="traitement-stat-suffix">${escapeHtml(suffix)}</span>` : ""}</div>
      <div class="traitement-stat-label">${escapeHtml(label)}</div>
    </div>
  `;
}

function _renderStepStats(stepId) {
  if (!_runInfo) return "";
  switch (stepId) {
    case "analyse": {
      // Fix audit 2026-06-08 high : pendant un scan en cours, "Films scannes"
      // doit refleter le progres reel (_runStatus.idx) et non _runInfo.total
      // (total cible / final), sinon desync visible avec la barre "167/856".
      const _isRunning = _runStatus?.running;
      const scanned = _isRunning
        ? `${Number(_runStatus?.idx || 0)} / ${Number(_runStatus?.total || _runInfo.total || 0)}`
        : _runInfo.total;
      return `
        <div class="traitement-stats">
          ${_renderStat("Films scannés", scanned)}
          ${_renderStat("Score moyen", _runInfo.score ? _runInfo.score.toFixed(0) : "—", "/100")}
        </div>
      `;
    }
    case "verification":
      return `
        <div class="traitement-stats">
          ${_renderStat("Cas à vérifier", _runInfo.reviewQueue)}
          ${_renderStat("Conflits", _runInfo.conflicts)}
          ${_autoApprove ? _renderStat(`Auto-approuvables (confiance ≥ ${_autoApprove.threshold})`, _autoApprove.autoApproved) : ""}
        </div>
      `;
    case "validation": {
      // Fix VAL-1 (2026-05-30) : fallback defensif si le backend ne renvoie
      // pas encore validated_count / rejected_count dans kpis (compat ascendante
      // pendant rollout du patch backend dashboard_support.py).
      const validated = Number(_runInfo.validated ?? 0);
      const rejected = Number(_runInfo.rejected ?? 0);
      const total = Number(_runInfo.total ?? 0);
      return `
        <div class="traitement-stats">
          ${_renderStat("Validés", validated)}
          ${_renderStat("Rejetés", rejected)}
          ${_renderStat("En attente", Math.max(0, total - validated - rejected))}
        </div>
      `;
    }
    case "doublons":
      return `
        <div class="traitement-stats">
          ${_renderStat("Groupes de doublons", _runInfo.duplicatesGroups)}
        </div>
      `;
    case "apply":
      return `
        <div class="traitement-stats">
          ${_renderStat("Appliqués", _runInfo.applied)}
          ${_renderStat("Restant", Math.max(0, _runInfo.total - _runInfo.applied))}
        </div>
      `;
    default:
      return "";
  }
}

/* --- Etape 1 : Analyse (spec §3.1) --- */

function _renderAnalyseStep() {
  const isRunning = _runStatus?.running;
  const idx = _runStatus?.idx || 0;
  // Fix audit 2026-06-08 medium : utiliser strictement _runStatus.total
  // pour le calcul de la barre de progression pendant le scan. Le fallback
  // _runInfo.total (kpis.total_movies = rows persistees) divergeait souvent
  // de la cible reelle du scanner, ce qui faisait sauter la barre a >100%
  // ou bondir d'un coup quand _runStatus arrivait.
  const total = isRunning ? Number(_runStatus?.total || 0) : (_runStatus?.total || _runInfo?.total || 0);
  const progressPct = total > 0 ? Math.round((idx * 100) / total) : 0;
  // Mode indeterminate tant que _runStatus.total n'est pas converge.
  const isDiscovering = isRunning && total === 0;
  const logs = _logsState.items || [];

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 1 — Analyse</h2>
      <p class="traitement-panel-desc">Scan filesystem (probe ffprobe + MediaInfo)</p>
      ${_renderStepStats("analyse")}

      <details class="traitement-scan-drawer" ${isRunning ? "" : "open"}>
        <summary>Options de scan</summary>
        <fieldset class="traitement-scan-options" ${isRunning ? "disabled" : ""}>
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="perceptual" ${_scanOptions.perceptual ? "checked" : ""} ${isRunning ? "disabled" : ""}>
            Analyse perceptuelle (LPIPS V2)
          </label>
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="subtitles" ${_scanOptions.subtitles ? "checked" : ""} ${isRunning ? "disabled" : ""}>
            Détection sous-titres manquants (FR/EN)
          </label>
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="omdb" ${_scanOptions.omdb ? "checked" : ""} ${isRunning ? "disabled" : ""}>
            OMDb cross-check (rating + IMDb id)
          </label>
          <label class="checkbox-row">
            <input type="checkbox" data-scan-opt="nfo" ${_scanOptions.nfo ? "checked" : ""} ${isRunning ? "disabled" : ""}>
            Vérification cohérence NFO/Kodi
          </label>
          <label class="traitement-scan-slider-row">
            Parallélisme : <strong data-scan-parallelism-label>${_scanOptions.parallelism}</strong>
            <input type="range" min="1" max="8" value="${_scanOptions.parallelism}" data-scan-opt="parallelism" class="traitement-scan-slider" ${isRunning ? "disabled" : ""}>
          </label>
        </fieldset>
      </details>

      ${isRunning ? `
        <div class="traitement-scan-progress" role="status" aria-live="polite">
          <div class="traitement-scan-progress-bar">
            <div class="traitement-scan-progress-fill" style="--progress: ${progressPct / 100}"></div>
          </div>
          <div class="traitement-scan-progress-meta">
            ${isDiscovering
              ? `<span>Découverte en cours…</span>`
              : `<span>${escapeHtml(String(idx))}/${escapeHtml(String(total))} films</span>
                 <span>${progressPct}%</span>
                 ${_runStatus?.eta_s ? `<span>~${escapeHtml(formatDuration(_runStatus.eta_s))} restant</span>` : ""}`}
          </div>
        </div>
        <div class="traitement-scan-current">
          ${_runStatus?.current ? `Fichier en cours : <code>${escapeHtml(_runStatus.current)}</code>` : ""}
        </div>
      ` : ""}

      <div class="traitement-actions">
        ${!isRunning ? `<button type="button" class="v5-btn v5-btn--primary" data-traitement-action="start-scan">▶ Lancer le scan</button>` : ""}
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="view-logs">📋 Voir log complet</button>
      </div>

      ${logs.length > 0 ? `
        <div class="traitement-scan-live-log" aria-label="Journal live">
          <div class="traitement-scan-live-log-title">Journal live (10 dernières lignes)</div>
          <pre class="traitement-scan-live-log-pre">${escapeHtml(logs.slice(-10).map((l) => typeof l === "string" ? l : JSON.stringify(l)).join("\n"))}</pre>
        </div>
      ` : ""}
    </section>
  `;
}

/* --- Etape 2 : Verification (spec §3.2) --- */

function _renderVerificationStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  // Fix audit 2026-06-08 medium : warning_flags est un List[str] cote backend
  // (cinesort/domain/core.py PlanRow). Travailler directement sur le tableau
  // et matcher par prefixe pour eviter qu'un futur flag 'subtitle_ok' pollue
  // le filtre subs (.includes('subtitle') matchait par sous-chaine).
  const _readFlags = (r) => Array.isArray(r.warning_flags)
    ? r.warning_flags
    : String(r.warning_flags || "").split(",").filter(Boolean);
  // Liste = SEULEMENT les cas nécessitant une revue humaine = NON auto-approuvables
  // (confiance < seuil OU flag bloquant : conflit / NFO / intégrité). Les auto-approuvables
  // (pré-approuvés par le backend) et les faux subtitle_missing_fr (FR embarqué) ne
  // polluent plus l'écran. `auto_approvable` vient du backend
  // (history_support._enrich_plan_payload) -> source unique cohérente avec les compteurs.
  // Fallback défensif : si l'enrichissement est absent (bool non fourni), on retombe sur
  // "a des alertes" pour ne pas masquer de lignes.
  const flagged = rows.filter((r) =>
    (typeof r.auto_approvable === "boolean") ? !r.auto_approvable : _readFlags(r).length > 0
  );
  // "Tous problèmes" = la liste de REVUE (non auto-approuvables). Les puces de CATÉGORIE
  // (Subs FR / Doublons / NFO) sont des LENTILLES sur TOUTE la bibliothèque : un film bien
  // identifié à qui il ne manque qu'un sous-titre FR est auto-approuvable (donc hors revue)
  // mais doit rester visible/compté via sa puce dédiée — sinon "Subs FR manquants" tombe à ~0.
  const _matchCat = (r, cat) => {
    const flags = _readFlags(r);
    // F12 (2026-08-03) : la lentille « Subs FR » couvre aussi les films dont le
    // seul sous-titre FR est FORCÉ (subtitle_forced_only_fr). Sans eux, l'écran
    // n'exposerait nulle part le film qui n'a que ses incrustations traduites :
    // il est auto-approuvable, donc absent de la liste de revue « Tous problèmes ».
    if (cat === "subs") {
      return flags.some((f) => {
        const s = String(f);
        return s.startsWith("subtitle_missing_fr") || s.startsWith("subtitle_forced_only_fr");
      });
    }
    if (cat === "dups") return flags.some((f) => String(f).startsWith("duplicate"));
    if (cat === "nfo") return flags.some((f) => String(f).startsWith("nfo"));
    return false;
  };
  const filtered = (_verifFilter === "all")
    ? flagged.slice()
    : rows.filter((r) => _matchCat(r, _verifFilter));
  // Tri alphabétique FRANÇAIS (À avec A, Ç avec C, ponctuation/ellipse initiale ignorée,
  // "Chapitre 2" avant "Chapitre 10"). La table n'était triée par rien -> elle héritait de
  // l'ordre du scan (comparaison par point de code : "À…"/"Ç…"/"…" classés après Z).
  filtered.sort((a, b) => _FR_COLLATOR.compare(
    String(a.display_title || a.proposed_title || ""),
    String(b.display_title || b.proposed_title || "")
  ));
  // Compteurs de puces : chaque catégorie compte sur TOUTE la biblio (lentille), pas seulement la revue.
  const _nSubs = rows.filter((r) => _matchCat(r, "subs")).length;
  const _nDups = rows.filter((r) => _matchCat(r, "dups")).length;
  const _nNfo = rows.filter((r) => _matchCat(r, "nfo")).length;

  // Fix VAL-2 (2026-05-30) : suppression du slice(0,50) qui tronquait
  // silencieusement la liste. Si > 500 lignes, un info banner est affiche
  // pour suggerer l'usage des filtres de confiance.
  const tableRows = filtered.map((r) => {
    const flags = _readFlags(r);
    return `
      <tr data-row-id="${escapeHtml(r.row_id || "")}">
        <td class="traitement-verif-title">${escapeHtml(r.display_title || r.proposed_title || "—")}</td>
        <td class="traitement-verif-year">${escapeHtml(String(r.proposed_year || ""))}</td>
        <td class="traitement-verif-alerts">
          ${flags.length === 0 ? `<span class="traitement-verif-alert">confiance faible</span>` : ""}
          ${flags.slice(0, 3).map((f) => `<span class="traitement-verif-alert">${escapeHtml(f)}</span>`).join(" ")}
          ${flags.length > 3 ? `<span class="traitement-verif-alert-more">+${flags.length - 3}</span>` : ""}
        </td>
        <td class="traitement-verif-confidence">${escapeHtml(String(r.confidence || 0))}</td>
        <td class="traitement-verif-actions">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary" data-traitement-verif-action="rescan" data-row-id="${escapeHtml(r.row_id || "")}">↻ Re-scanner</button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary" data-traitement-verif-action="rename" data-row-id="${escapeHtml(r.row_id || "")}">✎ Renommer</button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary" data-traitement-verif-action="ignore" data-row-id="${escapeHtml(r.row_id || "")}">Ignorer</button>
        </td>
      </tr>
    `;
  }).join("");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 2 — Vérification</h2>
      <p class="traitement-panel-desc">Films problématiques à examiner avant validation</p>
      ${_renderStepStats("verification")}

      <div class="traitement-verif-filters" role="tablist" aria-label="Filtres vérification">
        <button type="button" class="traitement-verif-filter ${_verifFilter === "all" ? "is-active" : ""}" data-traitement-verif-filter="all">Tous problèmes (${flagged.length})</button>
        <button type="button" class="traitement-verif-filter ${_verifFilter === "subs" ? "is-active" : ""}" data-traitement-verif-filter="subs">Subs FR manquants (${_nSubs})</button>
        <button type="button" class="traitement-verif-filter ${_verifFilter === "dups" ? "is-active" : ""}" data-traitement-verif-filter="dups">Doublons cross-root (${_nDups})</button>
        <button type="button" class="traitement-verif-filter ${_verifFilter === "nfo" ? "is-active" : ""}" data-traitement-verif-filter="nfo">NFO incohérent (${_nNfo})</button>
      </div>

      ${filtered.length === 0 ? `
        <p class="traitement-placeholder">${_verifFilter === "all"
          ? "✅ Tous les fichiers passent les contrôles. Continuez vers Validation."
          : "Aucun film dans cette catégorie."}</p>
      ` : `
        <table class="traitement-verif-table" role="grid">
          <thead>
            <tr>
              <th>Titre</th>
              <th>Année</th>
              <th>Alertes</th>
              <th>Confiance</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
        ${filtered.length > 500 ? `
          <p class="traitement-verif-info v5u-text-muted v5u-text-center">
            Affichage de ${filtered.length} films. Utilisez les filtres ci-dessus pour reduire la liste si besoin.
          </p>
        ` : ""}
      `}

      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="go-validation">→ Continuer vers Validation</button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="reload-plan">↻ Re-vérifier</button>
      </div>
    </section>
  `;
}

/* --- Etape 3 : Validation (spec §3.3) --- */

// Fix VAL-3 (2026-05-30) : helpers de tri et bucketization.
// VN-C.1 (batch 2) : seuils 85/60 -> getConfidenceThresholdsSync()
// (source unique : cinesort/domain/confidence_thresholds.py).
function _confidenceBucket(conf) {
  const c = Number(conf || 0);
  const t = getConfidenceThresholdsSync();
  if (c >= t.high) return "high";
  if (c >= t.medium) return "mid";
  if (c > 0) return "low";
  return "none";
}

function _sortValidationRows(rows, sort) {
  const dirMult = sort.dir === "asc" ? 1 : -1;
  const key = sort.key;
  const copy = rows.slice();
  copy.sort((a, b) => {
    let va;
    let vb;
    if (key === "titre" || key === "proposed_title") {
      // M14 : collation FRANCAISE (meme Intl.Collator que la Bibliotheque et
      // l'etape Verification) au lieu de toLocaleLowerCase()+localeCompare() SANS
      // options — l'ancien tri ignorait numeric ("Film 10" avant "Film 2") et
      // ignorePunctuation ("…Titre"/"À…" mal classes). Cle de tri alignee sur la
      // cle AFFICHEE (display_title || proposed_title) et non proposed_title seul,
      // sinon l'ordre divergeait visiblement du libelle rendu dans la colonne.
      va = String(a.display_title || a.proposed_title || "");
      vb = String(b.display_title || b.proposed_title || "");
      return _FR_COLLATOR.compare(va, vb) * dirMult;
    }
    if (key === "annee" || key === "proposed_year") {
      va = Number(a.proposed_year) || 0;
      vb = Number(b.proposed_year) || 0;
    } else if (key === "score") {
      // Fix audit 2026-06-08 medium : PlanRow backend n'expose pas de champ
      // 'score' (cf cinesort/domain/core.py PlanRow + run_data_support._parse_basic_fields).
      // Le sort score etait donc un no-op (tous a 0, ordre instable). Fallback
      // sur confidence (signal de qualite disponible) pour eviter l'UX
      // "header cliquable sans effet". Voir aussi _renderValidationStep ou
      // la colonne Score n'est plus rendue.
      va = Number(a.confidence) || 0;
      vb = Number(b.confidence) || 0;
    } else {
      // confidence (defaut)
      va = Number(a.confidence) || 0;
      vb = Number(b.confidence) || 0;
    }
    if (va < vb) return -1 * dirMult;
    if (va > vb) return 1 * dirMult;
    return 0;
  });
  return copy;
}

// VN-C.2 : depuis l'introduction du state JS `_decisionsState`, le DOM est
// derive du state (pas l'inverse). _persistValidationDomState n'a donc plus a
// snapshoter le DOM avant re-render : le state survit deja a filter / tri /
// expand. On conserve toutefois un sync defensif (DOM -> state) pour le cas
// ou une frappe rapide dans le year input ne declencherait pas encore d'event
// "change" (ex. blur synthetique pendant un re-render).
function _persistValidationDomState() {
  if (!_activeContainer) return;
  _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
    const rowId = cb.dataset.rowId;
    if (rowId) _setDecisionOk(rowId, cb.checked);
  });
  _activeContainer.querySelectorAll(".traitement-validation-year-input").forEach((inp) => {
    const rowId = inp.dataset.rowId;
    if (rowId) _setDecisionYear(rowId, inp.value);
  });
}

function _renderValidationStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  const pending = rows.filter((r) => !r.decision || r.decision === "PENDING");
  // VN-C.3 (Vague N batch 2) : seuil bulk-approve "sûrs" aligne sur CONF_HIGH
  // (anciennement hardcode 90, desormais unifie via VN-C.1).
  const _sureThr = getConfidenceThresholdsSync().high;
  const sureCount = pending.filter((r) => Number(r.confidence || 0) >= _sureThr).length;

  // Fix VAL-3 : compteurs par bucket de confiance sur l'ensemble pending.
  const buckets = { high: 0, mid: 0, low: 0, none: 0 };
  pending.forEach((r) => { buckets[_confidenceBucket(r.confidence)] += 1; });

  // Application du filtre puis du tri (VAL-3).
  let filtered = pending;
  if (_validationFilter !== "all") {
    filtered = pending.filter((r) => _confidenceBucket(r.confidence) === _validationFilter);
  }
  filtered = _sortValidationRows(filtered, _validationSort);

  // Fix VAL-2 (2026-05-30) : suppression du slice(0,100). On rend toutes les
  // lignes filtrees/triees ; un info banner s'affiche au-dela de 500.
  const sortKey = _validationSort.key;
  const sortDir = _validationSort.dir;
  const ariaSort = (col) => (sortKey === col ? (sortDir === "asc" ? "ascending" : "descending") : "none");
  const sortIndicator = (col) => {
    if (sortKey !== col) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  };

  // VN-C.1 (batch 2) : seuils unifies — 85/60 deviennent t.high / t.medium.
  const _thr = getConfidenceThresholdsSync();
  const tableRows = filtered.map((r) => {
    const conf = Number(r.confidence || 0);
    const confLabel = conf >= _thr.high ? "Haute" : (conf >= _thr.medium ? "Moyenne" : "Basse");
    const confCls = conf >= _thr.high ? "is-high" : (conf >= _thr.medium ? "is-mid" : "is-low");
    const rowId = String(r.row_id || "");
    const isExpanded = _validationExpanded.has(rowId);
    // VN-C.2 : state JS = source de verite. Si la row est connue du state on
    // lit ok/year depuis lui (preserve les clics user a travers un filtre / tri
    // / expand). Fallback sur la decision serveur puis sur le seuil high pour
    // les rows non encore touchees.
    const stState = _decisionsState.get(rowId);
    let defaultChecked;
    if (stState) {
      defaultChecked = !!stState.ok;
    } else if (r.decision === "OK" || r.decision === "APPROVED") defaultChecked = true;
    else if (r.decision === "REJECT" || r.decision === "REJECTED") defaultChecked = false;
    // H14 : defaut = verdict backend auto_approvable (source unique _defaultDecisionOk),
    // pas la confiance brute >= high (qui pre-cochait des rows a flag bloquant).
    else defaultChecked = _defaultDecisionOk(r);
    const yearForRender = stState && stState.year != null
      ? String(stState.year)
      : String(r.proposed_year || "");

    // Fix audit 2026-06-08 medium : warning_flags est un List[str] cote backend.
    const flags = Array.isArray(r.warning_flags)
      ? r.warning_flags
      : String(r.warning_flags || "").split(",").filter(Boolean);
    const candidates = Array.isArray(r.candidates) ? r.candidates.slice(0, 3) : [];

    const baseRow = `
      <tr data-row-id="${escapeHtml(rowId)}">
        <td class="traitement-validation-check">
          <input type="checkbox" data-traitement-validation-check data-row-id="${escapeHtml(rowId)}" ${defaultChecked ? "checked" : ""}>
        </td>
        <td class="traitement-validation-confidence ${confCls}">${escapeHtml(confLabel)} (${conf})</td>
        <td class="traitement-validation-title">${escapeHtml(r.display_title || r.proposed_title || "—")}</td>
        <td class="traitement-validation-year">
          <input type="number" min="1900" max="2099" value="${escapeHtml(yearForRender)}" class="traitement-validation-year-input" data-row-id="${escapeHtml(rowId)}">
        </td>
        <!-- Fix audit 2026-06-08 high : colonne 'Score' retiree (PlanRow backend
             n'expose pas de champ score, cf cinesort/domain/core.py PlanRow).
             Avant : affichait "—" pour TOUTES les lignes => UX morte / trompeuse.
             A reintroduire quand _parse_basic_fields propagera quality.score. -->
        <td class="traitement-validation-source">${escapeHtml(String(r.proposed_source || "—"))}</td>
        <td class="traitement-validation-actions">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost"
                  data-traitement-validation-action="toggle-reasons"
                  data-row-id="${escapeHtml(rowId)}"
                  aria-expanded="${isExpanded ? "true" : "false"}"
                  title="${isExpanded ? "Replier les details" : "Afficher les details"}">
            ${isExpanded ? "▾" : "▸"}
          </button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-traitement-validation-action="inspect" data-row-id="${escapeHtml(rowId)}" title="Voir le detail">👁</button>
        </td>
      </tr>
    `;

    if (!isExpanded) return baseRow;

    const flagsHtml = flags.length
      ? `<div class="traitement-validation-reasons-flags">${flags.map((f) => `<span class="traitement-verif-alert">${escapeHtml(f)}</span>`).join(" ")}</div>`
      : "";
    const yearReason = r.detected_year_reason
      ? `<div><strong>Annee detectee :</strong> ${escapeHtml(String(r.detected_year_reason))}</div>`
      : "";
    const notes = r.notes
      ? `<div><strong>Notes :</strong> ${escapeHtml(String(r.notes))}</div>`
      : "";
    const candidatesHtml = candidates.length
      ? `<div class="traitement-validation-reasons-candidates">
           <strong>Candidats (top ${candidates.length}) :</strong>
           <ul>
             ${candidates.map((c) => `<li>[${escapeHtml(String(c.source || "?"))}] ${escapeHtml(String(c.title || "—"))} (${escapeHtml(String(c.year || "—"))}) — score=${escapeHtml(String(c.score ?? "—"))}${c.note ? ` — ${escapeHtml(String(c.note))}` : ""}</li>`).join("")}
           </ul>
         </div>`
      : "";

    return `${baseRow}
      <tr class="traitement-validation-row-expand">
        <td colspan="6">
          <div class="traitement-validation-reasons">
            ${flagsHtml}
            ${yearReason}
            ${notes}
            ${candidatesHtml}
            ${!flagsHtml && !yearReason && !notes && !candidatesHtml ? '<p class="v5u-text-muted">Aucun detail supplementaire.</p>' : ""}
          </div>
        </td>
      </tr>
    `;
  }).join("");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 3 — Validation</h2>
      <p class="traitement-panel-desc">Approuver / rejeter les propositions de classification</p>
      ${_renderStepStats("validation")}

      <div class="traitement-validation-filters" role="tablist" aria-label="Filtres confiance validation">
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "all" ? "is-active" : ""}" data-traitement-validation-filter="all" aria-selected="${_validationFilter === "all" ? "true" : "false"}">Tous (${pending.length})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "high" ? "is-active" : ""}" data-traitement-validation-filter="high" aria-selected="${_validationFilter === "high" ? "true" : "false"}">Haute (${buckets.high})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "mid" ? "is-active" : ""}" data-traitement-validation-filter="mid" aria-selected="${_validationFilter === "mid" ? "true" : "false"}">Moyenne (${buckets.mid})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "low" ? "is-active" : ""}" data-traitement-validation-filter="low" aria-selected="${_validationFilter === "low" ? "true" : "false"}">Basse (${buckets.low})</button>
        <button type="button" role="tab" class="traitement-validation-filter ${_validationFilter === "none" ? "is-active" : ""}" data-traitement-validation-filter="none" aria-selected="${_validationFilter === "none" ? "true" : "false"}">Sans confiance (${buckets.none})</button>
      </div>

      <div class="traitement-validation-bulk">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="bulk-approve-sure">
          ✓ Tout approuver les sûrs (${sureCount})
        </button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="preset-no-alert">
          Approuver sans alerte
        </button>
        <!-- Fix audit 2026-05-24 : bouton "Rejeter tier Reject" supprimé.
             L'action n'était branchée que sur un showToast "non disponible"
             (cf _bindEvents preset-reject-reject) -> UI mensongère qui
             cassait la confiance utilisateur. À ré-ajouter quand bulk reject
             via run/save_validation sera spécifié. -->
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="preset-platinum-gold">
          Approuver Platinum + Gold
        </button>
      </div>

      ${pending.length === 0 ? `
        <p class="traitement-placeholder">✅ Toutes les décisions sont prises. Continuez vers Doublons.</p>
      ` : `
        <table class="traitement-validation-table" role="grid">
          <thead>
            <tr>
              <th>✓</th>
              <th class="is-sort ${sortKey === "confidence" ? "is-active is-" + sortDir : ""}"
                  data-traitement-validation-sort="confidence"
                  aria-sort="${ariaSort("confidence")}"
                  role="columnheader"
                  tabindex="0">Confiance${sortIndicator("confidence")}</th>
              <th class="is-sort ${sortKey === "titre" ? "is-active is-" + sortDir : ""}"
                  data-traitement-validation-sort="titre"
                  aria-sort="${ariaSort("titre")}"
                  role="columnheader"
                  tabindex="0">Titre${sortIndicator("titre")}</th>
              <th class="is-sort ${sortKey === "annee" ? "is-active is-" + sortDir : ""}"
                  data-traitement-validation-sort="annee"
                  aria-sort="${ariaSort("annee")}"
                  role="columnheader"
                  tabindex="0">Année${sortIndicator("annee")}</th>
              <!-- Fix audit 2026-06-08 high : header 'Score' retire (cf cellule plus haut)
                   pour eviter un tri cliquable sans donnees. -->
              <th>Source</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
        ${filtered.length > 500 ? `
          <p class="traitement-validation-info v5u-text-muted v5u-text-center">
            Affichage de ${filtered.length} films. Utilisez les presets "Approuver les surs" ou les filtres de confiance pour traiter par lots.
          </p>
        ` : ""}
      `}

      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="save-validation">💾 Enregistrer les décisions</button>
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="go-doublons">→ Passer aux Doublons</button>
      </div>
    </section>
  `;
}

/* --- Etape 4 : Doublons (spec §3.4, inline) --- */

function _renderDoublonsStep() {
  return `
    <section class="traitement-panel traitement-panel--doublons" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 4 — Doublons</h2>
      <p class="traitement-panel-desc">Choisir le film à conserver pour chaque groupe de doublons</p>
      <div id="traitement-doublons-mount" class="traitement-doublons-mount"></div>
      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="go-apply">→ Passer à l'application</button>
      </div>
    </section>
  `;
}

/* --- Spec 08 §3.5 : Carte "Annulation possible" post-apply --- */

function _formatUndoRemaining(remainingSeconds) {
  // Forme courte FR : "23h 12min", "45min", "30s". Pas de zero-pad pour rester court.
  const r = Math.max(0, Math.floor(Number(remainingSeconds) || 0));
  if (r <= 0) return "0s";
  const h = Math.floor(r / 3600);
  const m = Math.floor((r % 3600) / 60);
  const s = r % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}min`;
  if (m > 0) return `${m}min ${s.toString().padStart(2, "0")}s`;
  return `${s}s`;
}

function _renderUndoCard() {
  const undo = _runInfo?.pendingUndo;
  if (!undo || !undo.applyTs) return "";

  const now = Date.now() / 1000;
  const remaining = Math.max(0, Math.floor(undo.deadlineTs - now));
  const expired = undo.expired || remaining <= 0;
  const appliedAt = undo.applyTs > 0
    ? `Apply réalisé ${formatRelative(undo.applyTs)}`
    : "Apply récent";

  if (expired) {
    return `
      <aside class="traitement-undo-card traitement-undo-card--expired" data-traitement-undo-card>
        <header class="traitement-undo-card-head">
          <strong>Annulation post-apply</strong>
          <span class="traitement-undo-card-badge traitement-undo-card-badge--expired">Délai dépassé</span>
        </header>
        <p class="traitement-undo-card-body">
          Délai d'annulation dépassé (24h). ${escapeHtml(appliedAt)}.
        </p>
        <div class="traitement-undo-card-actions">
          <button type="button" class="v5-btn v5-btn--ghost" disabled title="Délai 24h dépassé">
            Prévisualiser annulation
          </button>
        </div>
      </aside>
    `;
  }

  return `
    <aside class="traitement-undo-card" data-traitement-undo-card>
      <header class="traitement-undo-card-head">
        <strong>Annulation possible</strong>
        <span class="traitement-undo-card-badge">
          ${escapeHtml(_formatUndoRemaining(remaining))} restant
        </span>
      </header>
      <p class="traitement-undo-card-body">
        ${escapeHtml(String(undo.reversibleCount))} opération${undo.reversibleCount > 1 ? "s" : ""} réversible${undo.reversibleCount > 1 ? "s" : ""}.
        ${escapeHtml(appliedAt)}. Tu peux encore restaurer l'état d'avant l'apply.
      </p>
      <div class="traitement-undo-card-actions">
        <button type="button" class="v5-btn v5-btn--secondary" data-traitement-action="undo-preview">
          Prévisualiser annulation
        </button>
      </div>
    </aside>
  `;
}

function _updateUndoCountdownLabels() {
  if (!_activeContainer) return;
  const undo = _runInfo?.pendingUndo;
  if (!undo || !undo.applyTs) return;
  const card = _activeContainer.querySelector("[data-traitement-undo-card]");
  if (!card) return;
  const now = Date.now() / 1000;
  const remaining = Math.max(0, Math.floor(undo.deadlineTs - now));
  if (remaining <= 0 && !card.classList.contains("traitement-undo-card--expired")) {
    // Bascule passive sur "Délai dépassé" : on re-rend tout l'étape Apply.
    _renderInPlace();
    return;
  }
  const badge = card.querySelector(".traitement-undo-card-badge");
  if (badge && !badge.classList.contains("traitement-undo-card-badge--expired")) {
    badge.textContent = `${_formatUndoRemaining(remaining)} restant`;
  }
}

// Fix audit 2026-05-25 (v1.5.3) Vague G Fix 1 : idempotence du countdown undo.
// Sans le _stopUndoCountdown() initial, un appel répété à _startUndoCountdown()
// (ex. remount, hashchange brutal, re-binding) lancerait un 2eme setInterval
// alors que le 1er continue de tourner -> double tick -> badge "X restant" se
// rafraichit 2 fois par cycle + leak. Le guard ci-dessous clear l'ancien
// timer avant d'en créer un nouveau. Le cleanup au unmount est déjà couvert
// dans unmountTraitement() ligne ~1510 via _stopUndoCountdown().
function _startUndoCountdown() {
  _stopUndoCountdown();
  _undoCountdownTimer = setInterval(_updateUndoCountdownLabels, UNDO_COUNTDOWN_INTERVAL_MS);
}

function _stopUndoCountdown() {
  if (_undoCountdownTimer) {
    clearInterval(_undoCountdownTimer);
    _undoCountdownTimer = null;
  }
}

function _renderUndoPreviewModalBody(preview) {
  const counts = preview?.counts || {};
  const reversible = Number(counts.reversible || 0);
  const irreversible = Number(counts.irreversible || 0);
  const conflicts = Number(counts.conflicts_predicted || 0);
  const samples = Array.isArray(preview?.samples) ? preview.samples : [];

  const summary = `
    <div class="traitement-undo-modal-summary">
      <ul>
        <li><strong>${escapeHtml(String(reversible))}</strong> opération${reversible > 1 ? "s" : ""} réversible${reversible > 1 ? "s" : ""}</li>
        <li><strong>${escapeHtml(String(irreversible))}</strong> non réversible${irreversible > 1 ? "s" : ""}</li>
        <li><strong>${escapeHtml(String(conflicts))}</strong> conflit${conflicts > 1 ? "s" : ""} prévu${conflicts > 1 ? "s" : ""}</li>
      </ul>
    </div>
  `;

  if (!samples.length) {
    return `${summary}<p class="traitement-undo-modal-empty">Aucun fichier réversible à afficher.</p>`;
  }

  const rows = samples.map((s) => `
    <li class="traitement-undo-modal-row">
      <code class="traitement-undo-modal-before">${escapeHtml(String(s.current_path || ""))}</code>
      <span class="traitement-undo-modal-arrow">↩</span>
      <code class="traitement-undo-modal-after">${escapeHtml(String(s.restore_path || ""))}</code>
    </li>
  `).join("");

  return `
    ${summary}
    <p class="traitement-undo-modal-note">Aperçu (${samples.length} première${samples.length > 1 ? "s" : ""} opération${samples.length > 1 ? "s" : ""}) :</p>
    <ul class="traitement-undo-modal-list">${rows}</ul>
  `;
}

async function _onUndoPreview() {
  if (!_runInfo?.runId) return;
  if (!_runInfo?.pendingUndo) return;
  try {
    const res = await apiPost("run/undo_last_apply_preview", { run_id: _runInfo.runId }, { signal: _signal() });
    const data = res?.data || res;
    if (!data || data.ok === false) {
      showToast({ type: "error", text: "Impossible de préparer l'annulation." });
      return;
    }
    if (!data.can_undo) {
      showToast({ type: "info", text: data.message || "Aucune opération réversible." });
      return;
    }
    // Fix audit 2026-05-24 (v1.5.2) : si le backend signale `expired`, on
    // retire l'action "Exécuter annulation" du modal — le call serait refuse
    // avec un 410 Gone. La preview reste consultable pour info.
    const expired = Boolean(data.expired);
    const actions = expired
      ? [
          { label: "Fermer", cls: "v5-btn v5-btn--ghost", onClick: () => {} },
        ]
      : [
          { label: "Fermer", cls: "v5-btn v5-btn--ghost", onClick: () => {} },
          {
            label: "Exécuter annulation",
            cls: "v5-btn v5-btn--danger",
            onClick: () => _onUndoExecute(),
          },
        ];
    showModal({
      title: expired
        ? "Prévisualisation de l'annulation (délai 24h dépassé)"
        : "Prévisualisation de l'annulation",
      body: _renderUndoPreviewModalBody(data),
      actions,
    });
  } catch {
    showToast({ type: "error", text: "Erreur lors de la prévisualisation." });
  }
}

/** Ultra-audit 2026-08-03 (N01) — signale un undo REUSSI au shell.
 *  app.js recharge les compteurs de sidebar sur cet evenement. Best-effort :
 *  un environnement sans CustomEvent ne doit jamais faire echouer l'undo. */
function _emitUndoDone() {
  try { window.dispatchEvent(new CustomEvent("cinesort:undo")); }
  catch (e) { console.warn("[traitement] dispatch cinesort:undo", e); }
}

function _onUndoExecute() {
  if (!_runInfo?.runId) return;
  const undo = _runInfo?.pendingUndo;
  if (!undo) return;

  // Spec 08 §3.5 : confirmation supplementaire + countdown 3s (memo
  // utilisateur "actions dangereuses CineSort").
  closeModal();
  dangerConfirmModal({
    title: "Confirmer l'annulation du dernier apply ?",
    items: [
      `${undo.reversibleCount} opération${undo.reversibleCount > 1 ? "s" : ""} sera${undo.reversibleCount > 1 ? "ont" : ""} annulée${undo.reversibleCount > 1 ? "s" : ""}`,
      `Batch ID : ${undo.batchId || "—"}`,
    ],
    consequence:
      "Les fichiers seront restaurés à leur emplacement et nom d'origine. Cette opération elle-même n'est PAS réversible automatiquement.",
    confirmLabel: "↩ Exécuter l'annulation",
    cancelLabel: "Annuler",
    countdownSeconds: 3,
    onConfirm: async () => {
      try {
        const res = await apiPost("run/undo_last_apply", { run_id: _runInfo.runId, dry_run: false }, { signal: _signal() });
        const data = res?.data || res;
        if (!data || data.ok === false) {
          // Fix audit 2026-05-24 (v1.5.2) : message dedie quand le backend
          // refuse pour delai 24h depasse (cas race ou client a un cache
          // d'`expired=false` perime). On rafraichit aussi le dashboard pour
          // synchroniser la carte.
          const msg = data?.message || data?.error || "Échec de l'annulation.";
          showToast({ type: "error", text: msg });
          await _loadRunInfo();
          _renderInPlace();
          return;
        }
        showToast({ type: "success", text: "Annulation appliquée. Restauration effectuée.", duration: 6000 });
        // Ultra-audit 2026-08-03 (N01) : app.js ecoute `cinesort:undo` pour
        // rafraichir immediatement les compteurs de la sidebar (#92 quick
        // win #2). Personne n'emettait plus cet evenement depuis la migration
        // ESM : les badges restaient stales jusqu'au tick 30 s.
        _emitUndoDone();
        await _loadRunInfo();
        _renderInPlace();
      } catch (err) {
        // Relecture adversaire PR #873 (point 1), meme cause et meme gravite :
        // un F5 pendant l'undo aborte la requete alors que le backend RESTAURE
        // les fichiers. Un toast rouge inviterait a relancer une restauration.
        if (_abortedByViewTeardown(err)) return;
        showToast({ type: "error", text: "Erreur lors de l'annulation." });
      }
    },
  });
}

/* --- Etape 5 : Apply (spec §3.5) --- */

// Fix audit 2026-05-25 (v1.5.3) Vague F : formattage explicite des entries
// preview apply. apply_core.py ne renomme JAMAIS les fichiers video : il
// renomme uniquement le dossier parent. Affichage src->dst brut suggerait
// a tort un renommage du fichier.
function _formatPreviewEntry(entry) {
  const action = String(entry?.action_summary || "");
  const folderOld = escapeHtml(String(entry?.folder_old_name || ""));
  const folderNew = escapeHtml(String(entry?.folder_new_name || ""));
  const videoName = escapeHtml(String(entry?.video_filename || ""));
  if (action === "folder_rename") {
    return `<div class="apply-preview-entry">
      <span>Dossier renomme :</span>
      <code>${folderOld}</code> -> <code>${folderNew}</code>
      <div class="apply-preview-note">Fichier conserve : <code>${videoName}</code></div>
    </div>`;
  }
  if (action === "video_move" || action === "folder_rename_and_video_move") {
    return `<div class="apply-preview-entry">
      <span>Video deplacee :</span>
      <code>${folderOld}/${videoName}</code> -> <code>${folderNew}/${videoName}</code>
      <div class="apply-preview-note">Nom du fichier conserve.</div>
    </div>`;
  }
  if (action === "video_rename_tv") {
    return `<div class="apply-preview-entry">
      <span>Episode TV renomme :</span>
      <code>${folderOld}/${videoName}</code> -> <code>${folderNew}/${escapeHtml(String(entry?.dst_filename || ""))}</code>
    </div>`;
  }
  // Retro-compat : si l'entry n'a pas d'action_summary (ex. row simple),
  // on affiche le titre/annee comme fallback prudent en signalant que le
  // fichier video conserve son nom.
  const src = escapeHtml(String(entry?.src_path || entry?.video || ""));
  const dst = escapeHtml(String(entry?.dst_path || ""));
  if (src && dst) {
    return `<div class="apply-preview-entry">
      <code>${src}</code> -> <code>${dst}</code>
    </div>`;
  }
  return `<div class="apply-preview-entry">${src || dst || "&mdash;"}</div>`;
}

// F23 (revue post-merge 2026-07-18) : hash DJB2-xor 32 bits, stable et sans
// dépendance. Sert uniquement à compacter la signature de décisions.
function _hash32(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) h = (((h << 5) + h) ^ s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

// AUDIT 2026-06-13 (R5-P2) : signature légère des décisions pour invalider
// l'aperçu backend quand l'utilisateur approuve/rejette des films.
//
// F23 : `size` est CONSTANT (toutes les rows sont pré-seedées par
// _initDecisionsState) et `approved` ne bouge pas sur une édition d'année ni
// sur un swap approuvé/rejeté 1-pour-1. L'aperçu backend restait donc affiché
// tel quel — non étiqueté « estimation » — alors que l'apply réel poste
// _buildDecisions() frais, dont `year` prime pour le dossier cible côté
// backend. La signature dérive maintenant du CONTENU réellement posté.
function _applyDecisionsSignature() {
  let approved = 0;
  const parts = [];
  for (const [rowId, st] of _decisionsState.entries()) {
    const ok = !!(st && st.ok);
    if (ok) approved += 1;
    // Normalisation IDENTIQUE à _buildDecisions (sinon 2019 et "2019"
    // produiraient deux signatures pour un payload identique).
    const yearNorm = (st && st.year != null) ? (Number(st.year) || "") : "";
    parts.push(`${rowId}:${ok ? 1 : 0}:${yearNorm}`);
  }
  // L'ordre d'insertion de la Map n'est pas stable (delete+set dans les
  // bulk-actions) : on trie pour que seule la VALEUR des décisions compte.
  parts.sort();
  // `size|approved` reste en clair : une collision de hash 32 bits ne peut pas
  // à elle seule ramener le bug.
  return `${_runInfo?.runId || ""}|${_decisionsState.size}|${approved}|${_hash32(parts.join(","))}`;
}

// Charge le VRAI plan d'apply (build_apply_preview) une fois par signature de
// décisions. Idempotent : ne refetch pas tant que la signature est inchangée
// (évite toute boucle de re-render). En échec, on retombe sur l'estimation
// client clairement étiquetée.
async function _ensureApplyPreview() {
  if (!_runInfo?.runId) return;
  // Ne pas solliciter build_apply_preview pendant un apply réel : il acquiert
  // le même slot (409) et la vue montre déjà la progression live.
  if (_applyStatus?.running) return;
  const sig = _applyDecisionsSignature();
  if (_applyPreviewLoading || _applyPreviewSig === sig) return;
  _applyPreviewLoading = true;
  _applyPreviewSig = sig;
  // F23 (revue adversaire R1) : invalider AUSSI le plan deja en memoire.
  // `_renderApplyStep` appelle _ensureApplyPreview() SANS l'attendre puis lit
  // `_applyPreview` dans la foulee : tant que le refetch n'avait pas repondu,
  // l'ancien plan restait affiche comme VRAI plan backend (totals non nul ->
  // previewIsEstimate=false), non etiquete « (estimation) », alors que l'apply
  // reel poste des decisions fraiches (dec['year'] prime cote backend).
  // A null, l'etape retombe sur l'estimation client EXPLICITEMENT etiquetee
  // pendant l'aller-retour (comportement documente plus bas).
  _applyPreview = null;
  try {
    const res = await apiPost(
      "run/build_apply_preview",
      { run_id: _runInfo.runId, decisions: _buildDecisions() },
      { signal: _signal() },
    );
    const data = res?.data || res;
    _applyPreview = (data && data.ok !== false) ? data : null;
  } catch (err) {
    if (err && err.name === "AbortError") {
      _applyPreviewLoading = false;
      _applyPreviewSig = "";  // permet un refetch après annulation
      return;
    }
    _applyPreview = null;
  } finally {
    _applyPreviewLoading = false;
    if (_currentStep === "apply") _renderInPlace();
  }
}

// Aplatit les ops effectives (hors no-op) des films du plan backend, limité à N.
function _applyPreviewOps(limit) {
  const out = [];
  const films = (_applyPreview && Array.isArray(_applyPreview.films)) ? _applyPreview.films : [];
  for (const film of films) {
    if (film.change_type === "noop") continue;
    for (const op of (film.ops || [])) {
      if (op.action_summary === "noop_equivalent_fs") continue;
      out.push(op);
      if (out.length >= limit) return out;
    }
  }
  return out;
}

function _renderApplyStep() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  // H14 + revue R2 : le compteur DOIT lire _decisionsState (la SOURCE DE VERITE
  // des decisions, cf. _applyDecisionsToRows L1889), pas la chaine r.decision.
  // L'ancien `r.decision === "approved"` (minuscule) ne matchait jamais un
  // bulk-approve qui pose r.decision="APPROVED" (majuscule) -> sous-comptage des
  // rows approuvees en masse mais non auto-approvables. On compte l'etat REEL
  // (st.ok), avec repli sur le defaut backend pour une row pas encore seedee.
  const approved = rows.filter((r) => {
    const st = _decisionsState.get(String(r.row_id || ""));
    return st ? st.ok : _defaultDecisionOk(r);
  });

  // AUDIT 2026-06-13 (R5-P2) : déclenche le chargement du vrai plan backend.
  _ensureApplyPreview();
  const totals = _applyPreview?.totals || null;
  // Compteurs : vrais totaux backend si dispo, sinon estimation client étiquetée.
  // apply ne SUPPRIME jamais (un reject -> quarantaine), donc suppressions=0.
  const renames = totals ? Number(totals.renames || 0) : approved.length;
  const moves = totals ? Number(totals.moves || 0) : ((_runInfo?.duplicatesGroups || 0) * 2);
  const deletions = 0;
  const quarantined = totals ? Number(totals.quarantined || 0) : 0;
  const previewIsEstimate = !totals;

  // AUDIT 2026-06-13 (R5-P2) : aperçu issu du VRAI plan backend (build_apply_preview)
  // via _formatPreviewEntry, qui connaît le type d'op exact (création de
  // sous-dossier + déplacement pour les films à la racine, vs renommage de
  // dossier). Fallback estimation client clairement étiquetée si le plan n'a pas
  // (encore) pu être calculé.
  let preview;
  if (totals) {
    const ops = _applyPreviewOps(3);
    preview = ops.length
      ? ops.map((op) => `<li>${_formatPreviewEntry(op)}</li>`).join("")
      : `<li><div class="apply-preview-entry v5u-text-muted">Aucune opération sur disque (films déjà conformes).</div></li>`;
  } else if (_applyPreviewLoading) {
    preview = `<li><div class="apply-preview-entry v5u-text-muted">Calcul du plan réel…</div></li>`;
  } else {
    // Estimation client (plan backend indisponible). On NE présente PAS un
    // renommage de dossier comme certain : libellé prudent.
    preview = approved.slice(0, 3).map((r) => {
      const videoName = String(r.video || "");
      const folderOld = String(r.folder || r.path || "");
      const proposedTitle = String(r.proposed_title || "");
      const proposedYear = String(r.proposed_year || "");
      const folderNew = proposedTitle ? `${proposedTitle}${proposedYear ? " (" + proposedYear + ")" : ""}` : folderOld;
      return `
    <li>
      <div class="apply-preview-entry">
        <span>Destination prévue :</span>
        <code class="traitement-apply-before">${escapeHtml(folderOld)}</code>
        <span class="traitement-apply-arrow">-></span>
        <code class="traitement-apply-after">${escapeHtml(folderNew)}</code>
        ${videoName ? `<div class="apply-preview-note">Fichier conservé : <code>${escapeHtml(videoName)}</code> (estimation — lancez le dry-run pour le détail exact)</div>` : ""}
      </div>
    </li>
  `;
    }).join("");
  }

  // Fix APPLY-2 (2026-05-30) : barre de progression live pendant un apply
  // en cours. Reutilise les classes CSS .traitement-scan-progress-* deja
  // stylees pour l'etape Analyse.
  const applyIdx = Number(_applyStatus?.idx || 0);
  const applyTotal = Number(_applyStatus?.total || 0);
  const applyPct = applyTotal > 0 ? Math.round((applyIdx * 100) / applyTotal) : 0;
  const applyEta = Number(_applyStatus?.eta_s || 0);
  const applyDryRun = Boolean(_applyStatus?.dryRun);
  const applyCurrent = String(_applyStatus?.current || "");
  const applyPhase = String(_applyStatus?.phase || "");

  return `
    <section class="traitement-panel" aria-labelledby="traitement-panel-title">
      <h2 id="traitement-panel-title" class="traitement-panel-title">Étape 5 — Application</h2>
      <p class="traitement-panel-desc">Renommage et déplacement sur disque</p>
      ${_renderStepStats("apply")}

      ${_applyStatus?.running ? `
        <div class="traitement-apply-progress traitement-scan-progress" role="status" aria-live="polite">
          <div class="traitement-scan-progress-bar">
            <div class="traitement-scan-progress-fill" style="--progress: ${applyPct / 100}"></div>
          </div>
          <div class="traitement-scan-progress-meta">
            <span>${escapeHtml(String(applyIdx))}/${escapeHtml(String(applyTotal))} ${applyDryRun ? "simules" : "appliques"}</span>
            <span>${applyPct}%</span>
            ${applyEta > 0 ? `<span>~${escapeHtml(formatDuration(applyEta))} restant</span>` : ""}
          </div>
          ${applyCurrent ? `<div class="traitement-scan-current">${applyDryRun ? "Simulation" : "Traitement"} : <code>${escapeHtml(applyCurrent)}</code></div>` : ""}
          ${applyPhase ? `<div class="traitement-apply-phase v5u-text-muted">Phase : ${escapeHtml(applyPhase)}</div>` : ""}
        </div>
      ` : ""}

      <div class="traitement-apply-summary">
        <h3>Résumé des opérations${previewIsEstimate ? ` <span class="v5u-text-muted">(estimation)</span>` : ""}</h3>
        <ul>
          <li><strong>${escapeHtml(String(renames))}</strong> renommage${renames > 1 ? "s" : ""} de dossier</li>
          <li><strong>${escapeHtml(String(moves))}</strong> déplacement${moves > 1 ? "s" : ""} de fichier</li>
          ${quarantined > 0 ? `<li><strong>${escapeHtml(String(quarantined))}</strong> mise${quarantined > 1 ? "s" : ""} en quarantaine</li>` : ""}
          <li><strong>${escapeHtml(String(deletions))}</strong> suppression${deletions > 1 ? "s" : ""}</li>
        </ul>
        ${previewIsEstimate ? `<p class="apply-preview-note v5u-text-muted">Comptes estimés tant que le plan exact n'est pas calculé. Lancez le dry-run pour le détail réel (les films à la racine sont rangés dans un sous-dossier «Titre (Année)/», ce qui compte comme un déplacement).</p>` : ""}
      </div>

      ${preview ? `
        <div class="traitement-apply-preview">
          <h4>Aperçu (3 premiers exemples)</h4>
          <ul class="traitement-apply-preview-list">${preview}</ul>
        </div>
      ` : ""}

      <div class="traitement-apply-options">
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="dry_run" ${_applyOptions.dry_run ? "checked" : ""}>
          Mode dry-run (recommandé pour le premier passage)
        </label>
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="export_csv" ${_applyOptions.export_csv ? "checked" : ""}>
          Exporter le rapport en CSV
        </label>
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="sync_jellyfin" ${_applyOptions.sync_jellyfin ? "checked" : ""}>
          Synchroniser Jellyfin après apply
        </label>
        <label class="checkbox-row">
          <input type="checkbox" data-apply-opt="quarantine" ${_applyOptions.quarantine ? "checked" : ""}>
          Quarantaine des non-approuvés
        </label>
        <label class="checkbox-row" title="Si une erreur interrompt le batch, tous les renommages deja effectues sont annules (rollback FS+DB).">
          <input type="checkbox" data-apply-opt="apply_atomic" ${_applyOptions.apply_atomic ? "checked" : ""}>
          Mode atomique (rollback en cas d'echec en cours de batch)
        </label>
      </div>

      <div class="traitement-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="apply-now">
          ${_applyOptions.dry_run ? "▶ Lancer le dry-run" : "✅ Appliquer maintenant"}
        </button>
      </div>

      ${_renderUndoCard()}
    </section>
  `;
}

/* --- Step panel routing --- */

function _renderStepPanel(stepId) {
  if (_loading) {
    // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 3 : loading visible avec skeleton.
    // Avant : "Chargement de l'état du run…" sur une ligne -> écran quasi-vide
    // pendant 3-5s -> utilisateur confus (vue cassée ? backend lent ?). Pattern
    // emprunté à doublons.js:393 qui combine header + skeletons + détail attente.
    // ITER11 fix(ui): aria-busy="true" + aria-live="polite" pour annoncer le
    // chargement aux lecteurs d'ecran. Le cycle de vie est: appear (skeleton) ->
    // remplace par _runInfo render ou par empty-state (jamais skeleton infini :
    // si fetch echoue, _loading repasse a false et l'empty-state s'affiche).
    return `
      <section class="traitement-panel" aria-busy="true" aria-live="polite">
        <div class="traitement-loading-header">⏳ Chargement de l'état du run…</div>
        ${[1, 2, 3].map(() => `<div class="v5-skeleton" style="height:48px;margin:8px 0;"></div>`).join("")}
      </section>
    `;
  }
  if (!_runInfo) {
    const stepIndex = Math.max(0, STEPS.findIndex((s) => s.id === stepId));
    const step = STEPS[stepIndex];
    // Le titre de panneau doit garder le MEME format que les cinq panneaux
    // reels (« Étape 1 — Analyse ») : cet etat vide n'affichait que le libelle
    // nu (« Analyse »), donc l'intitule changeait selon qu'un run existait ou
    // non. C'est le seul chemin rendu quand aucun run n'est actif — le cas par
    // defaut d'une installation neuve, et celui du runner CI.
    const stepTitle = `Étape ${stepIndex + 1} — ${step.label}`;
    // Fix audit 2026-06-08 UX high : 1 seul CTA "Lancer un scan" (le header
    // empty-state n'en rend plus). Bouton avec data-traitement-action="start-scan"
    // pour rester dans la vue Traitement plutot que de rediriger vers
    // une vue tierce (#/processing) inexistante ou redondante.
    return `
      <section class="traitement-panel" aria-labelledby="traitement-panel-title">
        <h2 id="traitement-panel-title" class="traitement-panel-title">${escapeHtml(stepTitle)}</h2>
        <p class="traitement-placeholder">
          Aucun run actif détecté. Lance un scan pour démarrer le workflow.
        </p>
        <div class="traitement-actions">
          <button type="button" class="v5-btn v5-btn--primary" data-traitement-action="start-scan">▶ Lancer un scan</button>
        </div>
      </section>
    `;
  }
  switch (stepId) {
    case "analyse": return _renderAnalyseStep();
    case "verification": return _renderVerificationStep();
    case "validation": return _renderValidationStep();
    case "doublons": return _renderDoublonsStep();
    case "apply": return _renderApplyStep();
    default: return _renderAnalyseStep();
  }
}

/* --- Main render --- */

function _renderTraitement() {
  // Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 4) : si aucun run actif, on
  // masque le breadcrumb pour eviter l'incoherence visuelle "etape 3 Validation
  // en violet active" + message "Aucun run actif detecte" simultanes
  // (capture 11 du rapport audit). Le breadcrumb reapparait des qu'un run est
  // detecte via _loadRunInfo(). Note : on garde le step panel qui affiche un
  // CTA "Lancer un scan" — l'utilisateur sait quoi faire ensuite.
  const showBreadcrumb = Boolean(_runInfo && _runInfo.runId);
  return `
    <section class="traitement-view">
      <header class="traitement-header">
        <div class="traitement-header-row">
          <h1 class="traitement-title">Traitement</h1>
        </div>
        <p class="traitement-subtitle">Workflow d'un scan : analyse → validation → application</p>
      </header>
      ${_renderHeaderRun()}
      ${showBreadcrumb ? _renderBreadcrumb(_currentStep) : ""}
      ${_renderStepPanel(_currentStep)}
    </section>
  `;
}

function _renderInPlace() {
  if (!_activeContainer) return;
  _activeContainer.innerHTML = _renderTraitement();
  _bindEvents(_activeContainer);
  // Si on est sur l'etape doublons, monte la vue Doublons dans son container
  if (_currentStep === "doublons") {
    const mount = _activeContainer.querySelector("#traitement-doublons-mount");
    // Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 1) : avant on ne re-montait
    // Doublons QUE si !_doublonsMounted. Mais _renderInPlace() est appele par
    // le polling toutes les 5s (POLL_INTERVAL_RUNNING) -> ecrase mount.innerHTML
    // -> Doublons reste mount=true mais le DOM est vide -> zone blanche entre
    // titre et bouton "Passer a l'application" (capture 8 du rapport audit).
    // Solution : detecter mount vide (re-mount necessaire) OU !_doublonsMounted
    // (1er passage). Le re-mount est idempotent (initDoublons reset son _state
    // et _filmCache, puis relance _loadGroups). Pas de double fetch en pratique
    // car le polling 5s laisse le temps au fetch precedent de finir.
    if (mount && (!_doublonsMounted || mount.children.length === 0)) {
      _doublonsMounted = true;
      initDoublons(mount);
    }
  } else if (_doublonsMounted) {
    unmountDoublons();
    _doublonsMounted = false;
  }
}

/* --- Actions (header + steps) --- */

async function _handleHeaderAction(action) {
  if (!_runInfo?.runId) return;
  const runId = _runInfo.runId;

  if (action === "pause") {
    try {
      const res = await apiPost("run/pause_run", { run_id: runId }, { signal: _signal() });
      if (res?.data?.ok) {
        showToast({ type: "info", text: "Run mis en pause." });
        await _loadRunStatus();
        _renderInPlace();
      } else {
        console.warn("Endpoint pause indisponible (PR backend en attente).");
        showToast({ type: "warn", text: "La mise en pause n'est pas disponible pour ce run." });
      }
    } catch {
      showToast({ type: "error", text: "Erreur lors de la pause." });
    }
  } else if (action === "resume") {
    try {
      const res = await apiPost("run/resume_run", { run_id: runId }, { signal: _signal() });
      if (res?.data?.ok) {
        showToast({ type: "success", text: "Run repris." });
        await _loadRunStatus();
        _renderInPlace();
      } else {
        console.warn("Endpoint resume indisponible (PR backend en attente).");
        showToast({ type: "warn", text: "La reprise du run n'est pas disponible." });
      }
    } catch {
      showToast({ type: "error", text: "Erreur lors de la reprise." });
    }
  } else if (action === "save") {
    try {
      const res = await apiPost("run/save_for_later", { run_id: runId }, { signal: _signal() });
      if (res?.data?.ok) {
        showToast({ type: "success", text: "Run sauvegardé. Retrouvez-le dans l'Historique." });
      } else {
        console.warn("Endpoint save_for_later indisponible (PR backend en attente).");
        showToast({ type: "warn", text: "La sauvegarde du run n'est pas encore disponible." });
      }
    } catch {
      showToast({ type: "error", text: "Erreur lors de la sauvegarde." });
    }
  } else if (action === "cancel") {
    dangerConfirmModal({
      title: "Annuler le run en cours ?",
      items: [`Run ${_shortRunId(runId)}`, `${_runInfo.total} films · ${_runInfo.validated} validés`],
      consequence: "Les décisions validées seront perdues. Aucune modification sur disque (le run n'a pas été appliqué). Run marqué CANCELLED dans l'Historique.",
      confirmLabel: "Annuler le run",
      cancelLabel: "Garder le run",
      countdownSeconds: 3,
      onConfirm: async () => {
        try {
          const res = await apiPost("run/cancel_run", { run_id: runId }, { signal: _signal() });
          if (res?.data?.ok) {
            showToast({ type: "success", text: "Run annulé." });
            await _loadRunInfo();
            await _loadRunStatus();
            _renderInPlace();
          } else {
            showToast({ type: "error", text: "Échec de l'annulation." });
          }
        } catch {
          showToast({ type: "error", text: "Erreur lors de l'annulation." });
        }
      },
    });
  }
}

async function _handleScanStart() {
  try {
    const settings = {
      perceptual: _scanOptions.perceptual,
      subtitles: _scanOptions.subtitles,
      omdb: _scanOptions.omdb,
      nfo: _scanOptions.nfo,
      parallelism: _scanOptions.parallelism,
    };
    const res = await apiPost("run/start_plan", { settings }, { signal: _signal() });
    if (res?.data?.ok) {
      showToast({ type: "success", text: "Scan démarré." });
      await _loadRunInfo();
      await _loadRunStatus();
      _startPolling();
      _renderInPlace();
    } else {
      showToast({ type: "error", text: "Impossible de démarrer le scan." });
    }
  } catch {
    showToast({ type: "error", text: "Erreur lors du démarrage." });
  }
}

async function _loadPlan() {
  if (!_runInfo?.runId) return;
  try {
    const res = await apiPost("run/get_plan", { run_id: _runInfo.runId }, { signal: _signal() });
    const data = res?.data || res;
    if (data?.ok !== false) {
      _validationPlan = { rows: Array.isArray(data.rows) ? data.rows : (Array.isArray(data) ? data : []) };
    }
  } catch {
    _validationPlan = { rows: [] };
  }
  // VN-C.2 : initialise (ou complete) _decisionsState pour chaque row du plan.
  // Toute row inconnue prend son etat par defaut (decision serveur si presente,
  // sinon confidence >= seuil high -> approuve par defaut). Rows deja en state
  // (ex. user a coche puis reload partiel) conservent leur valeur courante.
  _initDecisionsState();
}

// H14 (audit ultra 2026-07-13) : defaut d'approbation d'une row = verdict
// BACKEND `auto_approvable` (confiance >= seuil ET aucun flag bloquant
// _AUTO_BLOCKING : history_support._enrich_plan_payload / run_read_support).
// Un film confiance 92 + nfo_year_mismatch a auto_approvable=false et NE DOIT
// PAS etre pre-coche. Fallback sur confiance >= high uniquement si
// l'enrichissement backend est absent (bool non fourni), coherent avec le
// filtre "a examiner" (meme vue, ligne ~785). Source UNIQUE partagee par les 4
// sites (seed / rendu checkbox / compteur Application / dirty-check), sinon
// _hasUnsavedValidationDecisions produirait un faux "decisions non enregistrees".
function _defaultDecisionOk(r) {
  if (typeof r.auto_approvable === "boolean") return r.auto_approvable;
  return Number(r.confidence || 0) >= getConfidenceThresholdsSync().high;
}

// VN-C.2 : seed/refresh du state JS depuis _validationPlan. On ne touche jamais
// au DOM ici (pas de querySelectorAll). On ne supprime pas non plus d'entree
// existante en cas de re-load partiel — la suppression franche se fait au
// unmount (anti-leak inter-run).
function _initDecisionsState() {
  const rows = (_validationPlan && _validationPlan.rows) || [];
  if (rows.length === 0) return;
  const validIds = new Set();
  for (const r of rows) {
    const rowId = String(r.row_id || "");
    if (!rowId) continue;
    validIds.add(rowId);
    if (_decisionsState.has(rowId)) continue; // user-modified state preserved
    let ok;
    if (r.decision === "OK" || r.decision === "APPROVED") ok = true;
    else if (r.decision === "REJECT" || r.decision === "REJECTED") ok = false;
    else ok = _defaultDecisionOk(r);
    const year = Number(r.proposed_year) || null;
    _decisionsState.set(rowId, { ok, year, decided_at: Date.now() });
  }
  // Cleanup d'eventuelles entrees orphelines (rows disparues du plan, ex.
  // rescan). Garde le state focus sur les rows actuelles uniquement.
  for (const rid of Array.from(_decisionsState.keys())) {
    if (!validIds.has(rid)) _decisionsState.delete(rid);
  }
}

// VN-C.2 : source de verite des decisions = _decisionsState (Map JS), pas le
// DOM. Garantit que les rows hors viewport (filtre actif, virtualisation
// future) sont incluses dans le payload save_validation / apply.
function _buildDecisions() {
  const decisions = {};
  for (const [rowId, st] of _decisionsState.entries()) {
    decisions[rowId] = {
      ok: !!st.ok,
      year: st.year != null ? Number(st.year) || null : null,
    };
  }
  return decisions;
}

// VN-C.2 : helpers d'update du state appeles par les handlers d'evenements
// delegues. set/merge garantit qu'on ne perd jamais le champ year en mettant
// a jour le ok, et reciproquement.
function _setDecisionOk(rowId, ok) {
  if (!rowId) return;
  const id = String(rowId);
  const prev = _decisionsState.get(id) || { ok: false, year: null, decided_at: 0 };
  _decisionsState.set(id, { ...prev, ok: !!ok, decided_at: Date.now() });
}

function _setDecisionYear(rowId, yearValue) {
  if (!rowId) return;
  const id = String(rowId);
  const prev = _decisionsState.get(id) || { ok: false, year: null, decided_at: 0 };
  const y = yearValue === "" || yearValue == null ? null : Number(yearValue) || null;
  _decisionsState.set(id, { ...prev, year: y, decided_at: Date.now() });
}

// VN-C.3 (Vague N batch 2) : seuil bulk-approve "sûrs" = CONF_HIGH (85),
// charge dynamiquement via les thresholds unifies (VN-C.1). Plus aucun
// hardcode 90 dans le module. Le filtre "no-alert" et "platinum-gold"
// conservent leur semantique propre (sans seuil de confiance).
function _computeBulkApproveTargets(filter) {
  const targetIds = new Set();
  const targetRows = [];
  if (!_validationPlan?.rows) return { targetIds, targetRows };
  const sureThr = getConfidenceThresholdsSync().high;
  for (const r of _validationPlan.rows) {
    const conf = Number(r.confidence || 0);
    // Fix audit 2026-06-08 medium : warning_flags est un List[str] cote
    // backend (cinesort/domain/core.py PlanRow). On bossait par coincidence
    // sur String(arr) = 'a,b' mais .includes('subtitle') matchait par
    // sous-chaine (fragile : 'subtitle_ok' aurait pollue subs).
    const flags = Array.isArray(r.warning_flags)
      ? r.warning_flags
      : String(r.warning_flags || "").split(",").filter(Boolean);
    // Fix audit 2026-06-08 high : PlanRow n'a pas de champ 'tier'. Le preset
    // 'Platinum + Gold' etait donc silencieusement inerte (approvedCount = 0).
    // Alignement avec bibliotheque.js:166-172 : lecture display_tier puis
    // tier_v2 (single source of truth Vague N batch 2). On compare en
    // minuscules pour matcher les variantes serveur (platinum/Platinum/PLATINUM).
    const tierKey = String(r.display_tier || r.tier_v2 || r.tier || "").toLowerCase();
    let match = false;
    if (filter === "sure") match = conf >= sureThr;
    else if (filter === "no-alert") match = flags.length === 0;
    else if (filter === "platinum-gold") match = tierKey === "platinum" || tierKey === "gold";
    if (match) {
      targetIds.add(r.row_id);
      targetRows.push(r);
    }
  }
  return { targetIds, targetRows };
}

// VN-C.3 (Vague N batch 2) : libelle court pour la liste d'items affichee
// dans dangerConfirmModal (max 5 visibles). Privilegie proposed_title puis
// le nom du fichier video, en fallback le row_id.
function _formatBulkApproveItem(r) {
  const title = String(r?.proposed_title || "").trim();
  const year = String(r?.proposed_year || "").trim();
  if (title) return year ? `${title} (${year})` : title;
  const video = String(r?.video || "").trim();
  if (video) return video;
  return String(r?.row_id || "—");
}

async function _handleBulkApprove(filter) {
  if (!_validationPlan?.rows) return;
  if (!_runInfo?.runId) return;

  const { targetIds, targetRows } = _computeBulkApproveTargets(filter);
  const approvedCount = targetIds.size;
  if (approvedCount === 0) {
    // Fix audit 2026-06-08 high : feedback explicite quand le preset ne
    // matche aucune ligne (ex: aucun film Platinum/Gold dans ce run, ou
    // aucun film sans alerte). Avant : sortie silencieuse => UX trompeuse.
    let msg = "Aucun film ne correspond à ce preset.";
    if (filter === "platinum-gold") {
      msg = "Aucun film Platinum ou Gold dans ce run.";
    } else if (filter === "no-alert") {
      msg = "Aucun film sans alerte dans ce run.";
    } else if (filter === "sure") {
      msg = "Aucun film à confiance haute dans ce run.";
    }
    showToast({ type: "info", text: msg });
    return;
  }

  // VN-C.3 (Vague N batch 2) : seuil de protection "actions dangereuses".
  // Au-dela de 50 films impactes d'un coup, on impose dangerConfirmModal
  // (liste + countdown 3s) conformement a la regle UX. Sous le seuil, on
  // conserve l'UX-03 fix v166 (toast persistant 10s avec Annuler).
  const DANGER_THRESHOLD = 50;
  if (approvedCount > DANGER_THRESHOLD) {
    const items = targetRows.slice(0, 5).map(_formatBulkApproveItem);
    if (targetRows.length > 5) {
      items.push(`… et ${targetRows.length - 5} autre${targetRows.length - 5 > 1 ? "s" : ""}`);
    }
    dangerConfirmModal({
      title: `Confirmer l'approbation en masse de ${approvedCount} films ?`,
      items,
      consequence: `${approvedCount} films seront marqués comme approuvés. Vous pourrez encore les décocher individuellement avant Apply.`,
      confirmLabel: `✓ Approuver ${approvedCount} films`,
      cancelLabel: "Annuler",
      // mega-hotfix frontend_ui_polish (#5) : countdown gradue (0-3s entre 30-100).
      // approvedCount > 50 ici (gate DANGER_THRESHOLD ci-dessus), donc valeur ~1.5-3s.
      countdownSeconds: _gradedCountdownSeconds(approvedCount),
      onConfirm: async () => {
        await _applyBulkApprove(targetIds, approvedCount);
      },
    });
    return;
  }

  await _applyBulkApprove(targetIds, approvedCount);
}

// VN-C.3 (Vague N batch 2) : extraction du chemin "approbation effective"
// (snapshot -> mutation -> persistance backend -> toast/undo) pour le
// reutiliser entre le chemin direct (<= 50) et le callback dangerConfirmModal
// (> 50). UX-03 fix v166 preserve : toast 10s avec bouton "Annuler".
async function _applyBulkApprove(targetIds, approvedCount) {
  // VN-C.2 + Fix audit 2026-05-30 (v1.5.8) UX-03 : snapshot pre-modification
  // depuis _decisionsState (source de verite JS). Capture TOUTES les rows du
  // plan, pas seulement celles visibles dans le DOM apres filtre. Sans ca,
  // l'undo ne restaurait que les rows visibles -> perte silencieuse.
  // Fix race condition (2026-06-05) : on memorise aussi le timestamp du
  // snapshot. Au rollback (echec API ou undo), les decisions utilisateur
  // intervenues pendant l'await fetch (decided_at > snapshot_ts) sont
  // preservees au lieu d'etre ecrasees par un wipe-and-replace de la Map.
  const snapshot_ts = Date.now();
  const stateSnapshot = new Map();
  for (const [rid, st] of _decisionsState.entries()) {
    stateSnapshot.set(rid, { ...st });
  }

  // Mise a jour state JS (source de verite) + DOM visible.
  for (const rid of targetIds) {
    _setDecisionOk(rid, true);
  }
  if (_activeContainer) {
    _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
      if (targetIds.has(cb.dataset.rowId)) cb.checked = true;
    });
  }

  // Fix VAL-1 (2026-05-30) : persister les decisions cote serveur via
  // run/save_validation AVANT d'afficher le toast success. Sans ca, les KPI
  // cards (Valides / Rejetes / En attente) restaient figes a 0 puisque le
  // backend ne savait rien des approbations en masse. En cas d'echec API on
  // rollback le DOM via le snapshot et on n'affiche pas le toast success.
  const decisions = _buildDecisions();
  let saveOk = false;
  try {
    const res = await apiPost(
      "run/save_validation",
      { run_id: _runInfo.runId, decisions },
      { signal: _signal() },
    );
    saveOk = res?.data?.ok !== false;
  } catch (_err) {
    saveOk = false;
  }

  if (!saveOk) {
    // VN-C.2 : rollback du state JS (source de verite) + DOM visible. Le
    // snapshot couvre toutes les rows du plan (pas seulement les visibles).
    // Fix race condition (2026-06-05) : merge selectif au lieu de wipe.
    // Toute decision (clic checkbox / edit year) faite par l'utilisateur
    // pendant l'await save_validation a decided_at > snapshot_ts et doit
    // etre preservee. On rollback uniquement les rows qu'on a effectivement
    // mutees ci-dessus (targetIds) et dont l'utilisateur n'a pas retouche
    // la decision depuis.
    for (const rid of targetIds) {
      const current = _decisionsState.get(rid);
      const prev = stateSnapshot.get(rid);
      // Si l'utilisateur a re-modifie cette row apres notre snapshot,
      // on respecte son intent et on ne rollback pas.
      if (current && current.decided_at > snapshot_ts) continue;
      if (prev) {
        _decisionsState.set(rid, { ...prev });
      } else {
        _decisionsState.delete(rid);
      }
    }
    if (_activeContainer) {
      _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
        const prev = _decisionsState.get(cb.dataset.rowId);
        if (prev) cb.checked = !!prev.ok;
      });
    }
    showToast({
      type: "error",
      text: "Echec de la sauvegarde des decisions. Aucun changement applique.",
      duration: 8000,
    });
    return;
  }

  // Recharge les KPIs frais (validated_count / rejected_count) puis re-render.
  await _loadRunInfo();
  // Fix audit 2026-06-08 critical : mutation locale de row.decision pour
  // chaque rowId approuve apres save reussi. Sans ca, _hasUnsavedValidationDecisions()
  // comparait _decisionsState[rid].ok=true au defaultOk derive de l'ancien
  // row.decision (souvent PENDING), provoquant la modale "Decisions non
  // enregistrees" juste apres le toast "X films approuves" => contradiction
  // signalee. Plus rapide qu'un _loadPlan() complet (pas de round-trip).
  if (_validationPlan?.rows) {
    for (const row of _validationPlan.rows) {
      const rid = String(row.row_id || "");
      if (targetIds.has(rid)) row.decision = "APPROVED";
    }
  }
  _renderInPlace();

  // Fix TOAST-1 (2026-05-30) : remplacement de persistent: true par
  // duration: 10000. Le bouton Annuler reste cliquable 10s (UX standard,
  // cf Gmail Undo Send 5-30s) et le toast disparait tout seul ensuite.
  // Evite l'accumulation de toasts indemontables si l'utilisateur clique
  // plusieurs fois "Approuver les surs" (10+ toasts persistants signales).
  showToast({
    type: "success",
    text: `${approvedCount} films approuves.`,
    duration: 10000,
    action: {
      label: "Annuler",
      onClick: async () => {
        if (!_activeContainer) return;
        // VN-C.2 : restaurer le state JS au snapshot (toutes rows, pas seulement
        // visibles) puis refleter sur le DOM visible.
        // Fix race condition (2026-06-05) : merge selectif (cf rollback ci-dessus).
        // Les decisions utilisateur posterieures au snapshot sont preservees ;
        // on ne rollback que les rows qu'on a bulk-approuvees et qui n'ont pas
        // ete retouchees depuis.
        for (const rid of targetIds) {
          const current = _decisionsState.get(rid);
          const prev = stateSnapshot.get(rid);
          if (current && current.decided_at > snapshot_ts) continue;
          if (prev) {
            _decisionsState.set(rid, { ...prev });
          } else {
            _decisionsState.delete(rid);
          }
        }
        _activeContainer.querySelectorAll("[data-traitement-validation-check]").forEach((cb) => {
          const prev = _decisionsState.get(cb.dataset.rowId);
          if (prev) cb.checked = !!prev.ok;
        });
        // Re-persister les decisions originales pour que les KPI reflechissent
        // l'etat avant le bulk approve.
        if (!_runInfo?.runId) return;
        const originalDecisions = _buildDecisions();
        try {
          await apiPost(
            "run/save_validation",
            { run_id: _runInfo.runId, decisions: originalDecisions },
            { signal: _signal() },
          );
          await _loadRunInfo();
          _renderInPlace();
          showToast({ type: "info", text: "Approbation en masse annulee." });
        } catch (_err) {
          showToast({
            type: "error",
            text: "Annulation echouee : impossible de restaurer les decisions.",
            duration: 8000,
          });
        }
      },
    },
  });
}

/** Relecture adversaire de la PR #873 (point 2) — REGISTRE des operations disque
 *  annoncees par la modale de confirmation d'apply.
 *
 *  INVARIANT : toute operation que `run/apply` peut declencher sur le disque
 *  DOIT avoir une entree ici, sinon la derniere confirmation avant que des
 *  fichiers bougent SOUS-ANNONCE. Le test
 *  `test_invariant_aucune_operation_disque_prevue_ne_manque_a_la_modale`
 *  verrouille les trois maillons : cle du payload run/apply -> entree de ce
 *  registre -> texte effectivement rendu dans la modale.
 *
 *  `source` dit d'ou vient le compte :
 *   - "preview" : `_applyPreview.totals`, calcule par `build_apply_preview` ;
 *   - "client"  : le plan backend NE PEUT PAS le donner, il est calcule ici.
 *     C'est le cas de la quarantaine : `build_apply_preview` force
 *     `quarantine_unapproved=False` (apply_support.py:3133), donc ses totals
 *     n'en portent JAMAIS — alors que l'apply reel envoie
 *     `_applyOptions.quarantine` et que `apply_core.py:2009` deplace CHAQUE
 *     film non approuve vers `_review/` en incrementant `res.quarantined`,
 *     jamais `renames` ni `moves`.
 *
 *  Regle de direction (memo « actions dangereuses ») : sur cette modale,
 *  SUR-annoncer est tolerable, SOUS-annoncer ne l'est pas. Le compte client de
 *  quarantaine est donc un MAJORANT assume (toutes les rows non approuvees,
 *  y compris celles qu'apply_core pourrait ecarter avant le deplacement).
 */
const _APPLY_DISK_OPS = [
  { key: "renames", source: "preview", text: (n) => `${n} renommage${n > 1 ? "s" : ""} de dossier` },
  { key: "moves", source: "preview", text: (n) => `${n} déplacement${n > 1 ? "s" : ""} de fichier` },
  {
    key: "quarantined",
    source: "client",
    text: (n) => `${n} mise${n > 1 ? "s" : ""} en quarantaine (_review/)`,
  },
];

/** Compte, pour chaque entree du registre, le nombre d'operations prevues.
 *  @returns {{key: string, count: number, text: string}[]} */
function _plannedApplyOps({ totals, clientCounts }) {
  return _APPLY_DISK_OPS.map((op) => {
    const raw = op.source === "client" ? (clientCounts || {})[op.key] : (totals || {})[op.key];
    const count = Math.max(0, Number(raw) || 0);
    return { key: op.key, count, text: op.text(count) };
  });
}

/** Ultra-audit 2026-08-03 (N35) — nombre d'operations en ECHEC dans la reponse
 *  de run/apply.
 *
 *  apply_support.py retourne `{"ok": True, "result": ApplyResult.__dict__}`
 *  SANS aucune condition sur `result.errors` : un fichier verrouille (seeding
 *  torrent, VLC, indexeur Windows) donne ok=True avec errors>=1 et le film n'a
 *  pas bouge. Le front ne testait que `data.ok !== false` et affichait un toast
 *  VERT « Apply termine » — le seul canal ou l'echec etait visible etait
 *  ui_log.txt sur disque. On lit desormais le compteur reel.
 *
 *  @returns {{count: number, messages: string[]}}
 */
function _applyResultErrors(res) {
  const result = (res && res.data && res.data.result) || {};
  const count = Number(result.errors || 0);
  const messages = Array.isArray(result.error_messages) ? result.error_messages.map(String) : [];
  return { count: count > 0 ? count : 0, messages };
}

/** Toast de fin d'apply : vert si zero echec, orange (warning) sinon, avec le
 *  premier message d'erreur backend pour que l'utilisateur sache QUOI regarder. */
function _showApplyDoneToast(res, { dryRun }) {
  const { count, messages } = _applyResultErrors(res);
  if (count > 0) {
    const detail = messages.length ? ` — ${messages[0]}` : "";
    showToast({
      type: "warning",
      text: `${dryRun ? "Dry-run terminé" : "Apply terminé"} avec ${count} échec${count > 1 ? "s" : ""}${detail}`,
      duration: 12000,
    });
    return;
  }
  showToast({
    type: "success",
    text: dryRun ? "Dry-run terminé. Aucun fichier modifié." : "Apply terminé · Undo possible 24h",
    duration: dryRun ? 5000 : 7000,
  });
}

async function _handleApplyNow() {
  if (!_runInfo?.runId) return;
  // Ultra-audit 2026-08-03 (N13) : la modale danger se ferme maintenant AVANT
  // de lancer l'apply (pour laisser voir la barre de progression), ce qui
  // re-expose le bouton « Appliquer maintenant ». Sans cette garde, un second
  // clic partirait pendant l'apply en cours et se ferait rejeter en 409 par
  // le slot guard backend, avec un toast d'erreur trompeur.
  if (_applyStatus?.running) return;
  const decisions = _buildDecisions();
  const opCount = Object.values(decisions).filter((d) => d.ok).length;

  if (_applyOptions.dry_run) {
    // Dry-run direct sans confirmation
    // Fix APPLY-2 (2026-05-30) : seed l'etat optimiste pour la barre de
    // progression + relance le polling avec interval rapide (1.5s).
    _applyStatus = {
      running: true,
      done: false,
      idx: 0,
      total: opCount,
      current: "Demarrage...",
      phase: "starting",
      eta_s: 0,
      speed: 0,
      dryRun: true,
    };
    _renderInPlace();
    _startPolling();
    try {
      const res = await apiPost("run/apply", {
        run_id: _runInfo.runId,
        decisions,
        dry_run: true,
        quarantine_unapproved: _applyOptions.quarantine,
        // Vague P / VP-A : dry-run ne declenche pas de rollback mais on
        // propage le flag pour qu'un eventuel preview cote backend puisse
        // tracer "mode atomique demande" si besoin.
        apply_atomic: Boolean(_applyOptions.apply_atomic),
      }, { signal: _signal() });
      if (res?.data?.ok !== false) {
        if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
        _showApplyDoneToast(res, { dryRun: true });
        await _loadRunInfo();
        _renderInPlace();
      } else {
        if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
        // Fix audit 2026-05-25 (v1.5.5) Vague J : remonter le vrai message
        // backend (user_message Vague G / message _err_response) au lieu
        // d'un toast generique qui masque le diag. (res.data || res) car
        // certains endpoints renvoient le payload a plat, d'autres sous .data.
        const data = res?.data || res || {};
        const backendMsg = data.user_message || data.message || data.error;
        showToast({
          type: "error",
          text: backendMsg ? `Echec du dry-run : ${backendMsg}` : "Echec du dry-run.",
          duration: 8000,
        });
      }
    } catch (err) {
      // Relecture adversaire PR #873 (point 1) : un F5 pendant le dry-run
      // aborte la requete cote client ; ce n'est pas un echec (cf.
      // `_abortedByViewTeardown`). Retour silencieux.
      if (_abortedByViewTeardown(err)) return;
      // Fix audit 2026-05-25 (v1.5.5) Vague J : meme exception, on tente de
      // remonter le message si l'erreur porte un payload (apiPost levee).
      const exMsg = err?.data?.user_message || err?.data?.message || err?.message;
      showToast({
        type: "error",
        text: exMsg ? `Erreur lors du dry-run : ${exMsg}` : "Erreur lors du dry-run.",
        duration: 8000,
      });
    }
    return;
  }

  // Ultra-audit 2026-08-03 (N07) : la modale annoncait `${opCount} fichiers
  // renommés/déplacés`, or opCount est le nombre de FILMS APPROUVÉS, pas le
  // nombre d'opérations disque. Les deux divergent réellement : apply_core
  // marque `NOOP_DEJA_CONFORME` et sort AVANT d'incrémenter `res.renames`, donc
  // sur une bibliothèque déjà rangée la modale annonçait « 250 » quand 12
  // dossiers seulement allaient bouger — en contredisant le « Résumé des
  // opérations » affiché juste au-dessus, qui lit `_applyPreview.totals`.
  // Second mensonge corrigé : apply ne renomme JAMAIS le fichier vidéo (règle
  // projet, seeding torrent), uniquement le dossier parent.
  //
  // Relecture adversaire de la PR #873 (point 2) : ce libelle etait juste en
  // NATURE mais SOUS-annoncait. Bibliotheque deja rangee + quarantaine cochee
  // + 50 films refuses, il affichait « 0 renommage de dossier · 0 deplacement
  // de fichier » pour un apply qui allait deplacer 50 dossiers vers `_review/`.
  // Les operations annoncees viennent desormais du registre `_APPLY_DISK_OPS`,
  // qui inclut la quarantaine comptee cote client (le plan backend ne peut pas
  // la donner, cf. le commentaire du registre).
  const previewTotals = _applyPreview?.totals || null;
  // Majorant assume : toutes les rows non approuvees partent en `_review/`
  // quand l'option est cochee (apply_core.py:2009, branche `else`).
  const quarantineCount = _applyOptions.quarantine
    ? Math.max(0, Object.keys(decisions).length - opCount)
    : 0;
  const plannedOps = _plannedApplyOps({
    totals: previewTotals,
    clientCounts: { quarantined: quarantineCount },
  });
  const quarantineText = plannedOps.find((o) => o.key === "quarantined")?.text || "";
  const opsLine = previewTotals
    ? plannedOps.map((o) => o.text).join(" · ")
    // Repli sans plan backend : on annonce des FILMS approuves en le disant,
    // et on n'oublie pas la quarantaine (elle, est connue cote client).
    : `${opCount} film${opCount > 1 ? "s" : ""} approuvé${opCount > 1 ? "s" : ""} (plan exact non calculé) · ${quarantineText}`;

  // Apply reel : modale danger avec countdown 3s
  dangerConfirmModal({
    title: "Confirmer l'application sur le filesystem ?",
    // Ultra-audit 2026-08-03 (N13) : la modale se fermait dans le `finally` de
    // `await onConfirm()`. `apply_changes` étant synchrone côté backend, son
    // overlay (position fixed, z-index 10100, noir 65 % + blur) restait
    // plusieurs minutes au-dessus de la barre de progression que `onConfirm`
    // venait justement de démarrer : bouton grisé, aucun spinner, progression
    // floutée. La confirmation ayant déjà rempli son office au clic, on ferme
    // avant de lancer l'action.
    closeBeforeConfirm: true,
    items: [
      opsLine,
      // Relecture adversaire PR #873 (point 2) : « activée » tout court ne
      // disait pas COMBIEN de films allaient bouger, et le plan backend ne les
      // comptait pas non plus (quarantine_unapproved=False au preview).
      `Quarantaine : ${_applyOptions.quarantine
        ? `activée — ${quarantineCount} film${quarantineCount > 1 ? "s" : ""} non approuvé${quarantineCount > 1 ? "s" : ""} déplacé${quarantineCount > 1 ? "s" : ""} vers _review/`
        : "désactivée"}`,
      `CSV : ${_applyOptions.export_csv ? "exporté" : "non exporté"}`,
      // Vague P / VP-A : indicateur mode atomique dans le recap pre-apply
      `Mode atomique : ${_applyOptions.apply_atomic ? "activé (rollback en cas d'echec)" : "désactivé"}`,
    ],
    // Fix audit 2026-05-26 (v1.5.6) Vague L (undo-1) :
    // Le backend enforce un delai d'undo de 24h (cf cinesort/ui/api/apply_support.py:52,
    // _UNDO_DEADLINE_SECONDS = 24 * 3600). La modale danger pre-apply affichait
    // erronement "7 jours" (heritage du doc 08-traitement.md), ce qui creait une
    // attente utilisateur incoherente avec la realite serveur. On aligne sur 24h
    // pour matcher le toast post-apply (ligne ~1317) et la carte annulation expiree.
    consequence: "Les fichiers sur disque seront effectivement modifiés. Réversible via Undo pendant 24h après apply.",
    confirmLabel: "✗ Appliquer pour de vrai",
    cancelLabel: "Annuler",
    countdownSeconds: 3,
    onConfirm: async () => {
      // Fix APPLY-2 (2026-05-30) : seed apply progress optimiste + polling
      // rapide pour refleter en direct l'avancement cote backend.
      _applyStatus = {
        running: true,
        done: false,
        idx: 0,
        total: opCount,
        current: "Demarrage...",
        phase: "starting",
        eta_s: 0,
        speed: 0,
        dryRun: false,
      };
      _renderInPlace();
      _startPolling();
      try {
        const res = await apiPost("run/apply", {
          run_id: _runInfo.runId,
          decisions,
          dry_run: false,
          quarantine_unapproved: _applyOptions.quarantine,
          // Vague P / VP-A : flag opt-in pour rollback FS+DB forward.
          apply_atomic: Boolean(_applyOptions.apply_atomic),
        }, { signal: _signal() });
        if (res?.data?.ok !== false) {
          if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
          _showApplyDoneToast(res, { dryRun: false });
          await _loadRunInfo();
          _renderInPlace();
        } else {
          if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
          showToast({ type: "error", text: "Échec de l'apply." });
          _renderInPlace();
        }
      } catch (err) {
        // Relecture adversaire PR #873 (point 1) : F5 (ou « Rafraichir la vue »
        // de Ctrl+K) pendant l'apply -> `unmountTraitement()` -> abort. Le
        // backend, lui, CONTINUE de deplacer les fichiers : annoncer une erreur
        // ici pousse l'utilisateur a relancer un apply destructif.
        if (_abortedByViewTeardown(err)) return;
        if (_applyStatus) { _applyStatus.running = false; _applyStatus.done = true; }
        showToast({ type: "error", text: "Erreur lors de l'apply." });
        _renderInPlace();
      }
    },
  });
}

/* --- Step transition guard (Fix audit 2026-06-08 high) --- */

// Centralise le check des decisions de validation non enregistrees pour
// TOUTES les transitions hors-Validation (go-doublons, go-apply, breadcrumb,
// hashchange, unmount). Avant : la modale ne s'affichait QUE sur go-doublons,
// les autres chemins (clic apply-now, navigation URL, breadcrumb) faisaient
// perdre silencieusement les modifs JS de _decisionsState.
//
// Mode: "auto-save" pour les transitions internes silencieuses (hashchange,
// unmount) afin d'eviter de bloquer la navigation systeme avec une modale.
// Mode: "modal" pour les actions utilisateur explicites.
//
// Retourne true si la transition peut continuer immediatement, false si une
// modale est affichee (le callback onConfirm decidera).
function _guardStepTransition(onConfirm, opts) {
  const mode = opts?.mode || "modal";
  // Le guard ne s'applique que quand on quitte la step Validation.
  if (_currentStep !== "validation") {
    onConfirm();
    return true;
  }
  if (!_hasUnsavedValidationDecisions()) {
    onConfirm();
    return true;
  }
  if (mode === "auto-save") {
    // Hashchange / unmount : on tente un auto-save silencieux best-effort.
    _handleSaveValidation().finally(() => onConfirm());
    return false;
  }
  // Modal classique avec 3 choix.
  showModal({
    title: "Décisions non enregistrées",
    body: `<p>Vous avez modifié des décisions de validation sans cliquer sur <strong>"Enregistrer les décisions"</strong>.</p>
           <p>Si vous continuez maintenant, vos modifications seront perdues au prochain rechargement.</p>
           <p><strong>Enregistrer avant de continuer ?</strong></p>`,
    actions: [
      { label: "Annuler", cls: "", onClick: () => {} },
      { label: "Continuer sans enregistrer", cls: "v5-btn--secondary", onClick: () => onConfirm() },
      { label: "Enregistrer puis continuer", cls: "btn-primary v5-btn--primary", onClick: async () => {
        await _handleSaveValidation();
        onConfirm();
      } },
    ],
  });
  return false;
}

/* --- Event binding --- */

// Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : event delegation centralisée.
// Avant : 7 boucles forEach(addEventListener) à chaque _renderInPlace() ->
// listeners empilés sur les boutons recréés (innerHTML replace ne nettoie pas
// les anciens handlers de leurs ancêtres si on rattache à chaque tour).
// Maintenant : 2 listeners (click + change) attachés UNE seule fois au container
// parent. Le dispatch utilise event.target.closest() qui survit aux re-renders
// puisque le container lui-même n'est jamais détruit avant unmount.
function _onContainerClick(event) {
  const container = _activeContainer;
  if (!container) return;

  // Breadcrumb (étapes du workflow)
  const stepBtn = event.target.closest("[data-traitement-step]");
  if (stepBtn && container.contains(stepBtn)) {
    if (stepBtn.disabled) return;
    const stepId = stepBtn.dataset.traitementStep;
    // Fix audit 2026-06-08 high : guard sur transition breadcrumb si on quitte
    // Validation avec decisions non enregistrees.
    if (stepId === _currentStep) return;
    _guardStepTransition(() => {
      _currentStep = stepId;
      _writeStep(stepId);
      _renderInPlace();
    });
    return;
  }

  // Copy run ID
  const copyBtn = event.target.closest("[data-traitement-copy-runid]");
  if (copyBtn && container.contains(copyBtn)) {
    if (!_runInfo?.runId) return;
    navigator.clipboard.writeText(_runInfo.runId).then(
      () => showToast({ type: "info", text: "Run ID copié dans le presse-papier." }),
      () => { /* ignore */ },
    );
    return;
  }

  // Header + step generic actions (data-traitement-action)
  const actionBtn = event.target.closest("[data-traitement-action]");
  if (actionBtn && container.contains(actionBtn)) {
    const action = actionBtn.dataset.traitementAction;
    if (["pause", "resume", "save", "cancel"].includes(action)) {
      _handleHeaderAction(action);
    } else if (action === "start-scan") {
      _handleScanStart();
    } else if (action === "view-logs") {
      // Fix 2026-06-07 : pas de toast intermediaire, la navigation est instantanee
      // (le toast s'afficherait sur la vue Logs et serait du bruit UX).
      window.location.hash = "#/logs";
    } else if (action === "go-validation") {
      _currentStep = "validation";
      _writeStep("validation");
      _renderInPlace();
    } else if (action === "go-doublons") {
      // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-02 : avant la
      // transition Validation -> Doublons, detecter si l'utilisateur a modifie
      // des decisions (checkboxes / annees) sans cliquer "Sauver les decisions".
      // Avant : la transition etait silencieuse -> au retour sur Validation,
      // les decisions etaient perdues car save_validation n'avait jamais ete
      // appele. Maintenant : modal explicite "Sauvegarder avant de continuer ?"
      // avec 3 choix (Sauver puis continuer / Continuer sans sauver / Annuler).
      if (_hasUnsavedValidationDecisions()) {
        // Fix audit 2026-06-07 UX high : harmonisation verbe "Enregistrer" + complement
        // sur les 3 sites traitement.js (header / validation / dirty-state modal).
        showModal({
          title: "Décisions non enregistrées",
          body: `<p>Vous avez modifié des décisions de validation sans cliquer sur <strong>"Enregistrer les décisions"</strong>.</p>
                 <p>Si vous passez aux Doublons maintenant, vos modifications seront perdues au prochain rechargement.</p>
                 <p><strong>Enregistrer avant de continuer ?</strong></p>`,
          actions: [
            { label: "Annuler", cls: "", onClick: () => {} },
            { label: "Continuer sans enregistrer", cls: "v5-btn--secondary", onClick: () => {
              _currentStep = "doublons";
              _writeStep("doublons");
              _renderInPlace();
            } },
            { label: "Enregistrer puis continuer", cls: "btn-primary v5-btn--primary", onClick: async () => {
              await _handleSaveValidation();
              _currentStep = "doublons";
              _writeStep("doublons");
              _renderInPlace();
            } },
          ],
        });
        return;
      }
      _currentStep = "doublons";
      _writeStep("doublons");
      _renderInPlace();
    } else if (action === "go-apply") {
      // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 4 : confirmation si doublons
      // non décidés. Avant : transition Doublons->Apply silencieuse -> appliquait
      // les "défauts" (le 1er fichier de chaque groupe gagne par convention) sans
      // que l'utilisateur en soit informé -> suppressions non voulues sur des
      // groupes qu'il n'avait pas encore arbitrés.
      // L'état pendingCount est local au module doublons.js (non exporté), on
      // lit donc le DOM du mount : le badge ".doublons-decided-count" affiche
      // "X décidés / Y" => on calcule pending depuis le DOM si présent.
      const pendingDups = _readDoublonsPendingFromDom();
      if (pendingDups > 0) {
        // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace window.confirm()
        // natif par dangerConfirmModal (application defauts = potentiellement destructif sur
        // les groupes non arbitres). Memoire utilisateur exige countdown 3s si > 50 elements.
        dangerConfirmModal({
          title: `Passer à Apply avec ${pendingDups} doublon${pendingDups > 1 ? "s" : ""} non décidé${pendingDups > 1 ? "s" : ""} ?`,
          consequence: "Les choix par défaut (premier fichier de chaque groupe) seront appliqués. Les autres fichiers de doublons peuvent être supprimés/déplacés selon votre profil.",
          // mega-hotfix frontend_ui_polish (#5) : countdown gradue (au lieu de cliff a 50).
          countdownSeconds: _gradedCountdownSeconds(pendingDups),
          confirmLabel: "Continuer vers Apply",
          cancelLabel: "Retourner aux Doublons",
          onConfirm: () => {
            _currentStep = "apply";
            _writeStep("apply");
            _renderInPlace();
          },
        });
        return;
      }
      _currentStep = "apply";
      _writeStep("apply");
      _renderInPlace();
    } else if (action === "reload-plan") {
      _loadPlan().then(() => _renderInPlace());
    } else if (action === "save-validation") {
      _handleSaveValidation();
    } else if (action === "bulk-approve-sure") {
      _handleBulkApprove("sure");
    } else if (action === "preset-no-alert") {
      _handleBulkApprove("no-alert");
    } else if (action === "preset-platinum-gold") {
      _handleBulkApprove("platinum-gold");
    } else if (action === "apply-now") {
      _handleApplyNow();
    } else if (action === "undo-preview") {
      _onUndoPreview();
    }
    return;
  }

  // Verification filters
  const verifFilterBtn = event.target.closest("[data-traitement-verif-filter]");
  if (verifFilterBtn && container.contains(verifFilterBtn)) {
    _verifFilter = verifFilterBtn.dataset.traitementVerifFilter;
    _renderInPlace();
    return;
  }

  // Fix VAL-3 (2026-05-30) : filtre confiance validation (chips).
  const validationFilterBtn = event.target.closest("[data-traitement-validation-filter]");
  if (validationFilterBtn && container.contains(validationFilterBtn)) {
    // Persister l'etat DOM (checkboxes/years modifies a la main) avant re-render
    // pour ne pas perdre les changements utilisateur (regression UX-03).
    _persistValidationDomState();
    _validationFilter = validationFilterBtn.dataset.traitementValidationFilter || "all";
    _renderInPlace();
    return;
  }

  // Fix VAL-3 (2026-05-30) : tri colonne validation.
  const validationSortBtn = event.target.closest("[data-traitement-validation-sort]");
  if (validationSortBtn && container.contains(validationSortBtn)) {
    _persistValidationDomState();
    const newKey = validationSortBtn.dataset.traitementValidationSort;
    if (_validationSort.key === newKey) {
      _validationSort = { key: newKey, dir: _validationSort.dir === "asc" ? "desc" : "asc" };
    } else {
      _validationSort = { key: newKey, dir: "asc" };
    }
    _renderInPlace();
    return;
  }

  // Verification actions (rescan / rename / ignore)
  const verifActionBtn = event.target.closest("[data-traitement-verif-action]");
  if (verifActionBtn && container.contains(verifActionBtn)) {
    const action = verifActionBtn.dataset.traitementVerifAction;
    const rowId = verifActionBtn.dataset.rowId;
    const runId = _runInfo?.runId;
    if (!runId || !rowId) return;
    if (action === "rescan") {
      apiPost("run/rescan_row", { run_id: runId, row_id: rowId }, { signal: _signal() })
        .then((res) => {
          if (res?.data?.ok !== false) {
            showToast({ type: "success", text: "Ligne re-scannée." });
            return _loadPlan().then(() => _renderInPlace());
          }
          showToast({ type: "error", text: "Échec du re-scan." });
        })
        .catch(() => showToast({ type: "error", text: "Erreur lors du re-scan." }));
    } else if (action === "rename") {
      renderFilmDetail({ mode: "C", rowId, runId });
    } else if (action === "ignore") {
      // E2 (verif totale 2026-07) : run/mark_alert_ignored n'a jamais existe
      // (la methode vit sur la facade library, signature (row_id, alert_code))
      // -> 404 systematique. On ignore chaque warning_flag de la row (backend
      // idempotent par couple row/code), meme source que les badges affiches.
      const row = (_validationPlan?.rows || []).find((r) => String(r.row_id) === String(rowId));
      const codes = Array.isArray(row?.warning_flags)
        ? row.warning_flags
        : String(row?.warning_flags || "").split(",").filter(Boolean);
      if (!codes.length) {
        showToast({ type: "info", text: "Aucune alerte à ignorer sur cette ligne." });
        return;
      }
      Promise.all(
        codes.map((code) =>
          apiPost("library/mark_alert_ignored", { row_id: rowId, alert_code: code }, { signal: _signal() })
        )
      )
        .then((results) => {
          const failed = results.filter((res) => res?.data?.ok === false).length;
          if (!failed) {
            showToast({ type: "info", text: codes.length > 1 ? `${codes.length} alertes ignorées.` : "Alerte ignorée." });
            return _loadPlan().then(() => _renderInPlace());
          }
          showToast({ type: "error", text: `Échec : ${failed}/${codes.length} alertes non ignorées.` });
        })
        .catch(() => showToast({ type: "error", text: "Erreur lors de l'ignorance." }));
    }
    return;
  }

  // Validation inspect (œil) + toggle-reasons (VAL-3)
  const validationActionBtn = event.target.closest("[data-traitement-validation-action]");
  if (validationActionBtn && container.contains(validationActionBtn)) {
    const action = validationActionBtn.dataset.traitementValidationAction;
    const rowId = validationActionBtn.dataset.rowId;
    const runId = _runInfo?.runId;
    if (action === "inspect" && runId && rowId) {
      renderFilmDetail({ mode: "C", rowId, runId });
    } else if (action === "toggle-reasons" && rowId) {
      // Fix VAL-3 (2026-05-30) : ouvrir/fermer la ligne de details.
      _persistValidationDomState();
      if (_validationExpanded.has(rowId)) {
        _validationExpanded.delete(rowId);
      } else {
        _validationExpanded.add(rowId);
      }
      _renderInPlace();
    }
    return;
  }
}

function _onContainerChange(event) {
  const container = _activeContainer;
  if (!container) return;

  // VN-C.2 : capture des changements validation (checkbox + year input) vers
  // le state JS `_decisionsState`. Sans ca, un re-render declenche par un
  // filtre / tri / expand effacerait la modification utilisateur car le DOM
  // est desormais derive du state (et plus l'inverse).
  const valCheck = event.target.closest("[data-traitement-validation-check]");
  if (valCheck && container.contains(valCheck)) {
    _setDecisionOk(valCheck.dataset.rowId, valCheck.checked);
    return;
  }
  const valYear = event.target.closest(".traitement-validation-year-input");
  if (valYear && container.contains(valYear)) {
    _setDecisionYear(valYear.dataset.rowId, valYear.value);
    return;
  }

  // Scan options (checkbox + range)
  const scanInput = event.target.closest("[data-scan-opt]");
  if (scanInput && container.contains(scanInput)) {
    // Fix audit 2026-06-08 high : ne PAS muter _scanOptions pendant un scan
    // en cours. Sinon la modification (faite via un clic sur un input non
    // disabled si l'attribut sautait) faussait le prochain start_plan et
    // donnait l'illusion de modifier le scan courant. Defense en profondeur :
    // les inputs sont aussi disabled dans le HTML (cf _renderAnalyseStep).
    if (_runStatus?.running) return;
    const key = scanInput.dataset.scanOpt;
    if (scanInput.type === "checkbox") {
      _scanOptions[key] = scanInput.checked;
    } else if (scanInput.type === "range") {
      _scanOptions[key] = Number(scanInput.value);
      const lbl = container.querySelector("[data-scan-parallelism-label]");
      if (lbl) lbl.textContent = String(_scanOptions[key]);
    }
    return;
  }

  // Apply options
  const applyInput = event.target.closest("[data-apply-opt]");
  if (applyInput && container.contains(applyInput)) {
    const key = applyInput.dataset.applyOpt;
    // Vague P / VP-A : activation `apply_atomic` -> dangerConfirmModal
    // pour expliquer les consequences. Pas de countdown (memo
    // `feedback_cinesort_actions_dangereuses` autorise countdown OFF pour
    // actions non-destructives) — AC-4.
    if (key === "apply_atomic" && applyInput.checked && !_applyOptions.apply_atomic) {
      // On annule l'activation tant que l'utilisateur n'a pas confirme.
      applyInput.checked = false;
      dangerConfirmModal({
        title: "Activer le mode atomique pour l'apply ?",
        items: [
          "Si une operation echoue au milieu du batch, TOUTES les operations precedentes sont annulees (rollback).",
          "Les fichiers deja deplaces reviennent a leur emplacement d'origine.",
          "La base de donnees est mise a jour pour tracer le rollback.",
          "Le mode standard laisse l'apply s'arreter sur l'erreur sans annuler les operations reussies.",
        ],
        consequence: "L'apply prendra legerement plus de temps a cause du journal write-ahead et du rollback potentiel. Recommande pour les batches critiques (>50 films).",
        confirmLabel: "Activer le mode atomique",
        cancelLabel: "Annuler",
        countdownSeconds: 0,
        onConfirm: () => {
          _applyOptions.apply_atomic = true;
          _renderInPlace();
        },
      });
      return;
    }
    _applyOptions[key] = applyInput.checked;
    _renderInPlace();
    return;
  }
}

// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-02 : detecte si l'etat
// des decisions diverge du `decision` cote serveur (_validationPlan).
// VN-C.2 : compare desormais _decisionsState (source de verite JS) contre les
// rows serveur, ce qui inclut TOUTES les rows (visible ou masquees par filtre).
// L'ancienne version iterait sur les checkboxes DOM et ratait les divergences
// hors viewport (faux negatifs).
function _hasUnsavedValidationDecisions() {
  if (!_activeContainer) return false;
  const rows = (_validationPlan && _validationPlan.rows) || [];
  if (rows.length === 0) return false;
  if (_decisionsState.size === 0) return false;
  for (const row of rows) {
    const rowId = String(row.row_id || "");
    const st = _decisionsState.get(rowId);
    if (!st) continue;
    let defaultOk;
    if (row.decision === "OK" || row.decision === "APPROVED") defaultOk = true;
    else if (row.decision === "REJECT" || row.decision === "REJECTED") defaultOk = false;
    // H14 : meme defaut que le seed (_defaultDecisionOk), sinon une row jamais
    // touchee par l'user apparaitrait faussement "non enregistree".
    else defaultOk = _defaultDecisionOk(row);
    if (!!st.ok !== defaultOk) return true;
    const originalYear = Number(row.proposed_year) || null;
    const currentYear = st.year != null ? Number(st.year) || null : null;
    if (currentYear !== originalYear) return true;
  }
  return false;
}

// Fix Vague G Fix 4 helper : lit le nombre de doublons en attente depuis le DOM
// du mount doublons (état interne du module non exporté). Fallback à 0 si la
// vue Doublons n'a jamais été montée ou si le selector n'est pas trouvé.
function _readDoublonsPendingFromDom() {
  if (!_activeContainer) return 0;
  const mount = _activeContainer.querySelector("#traitement-doublons-mount");
  if (!mount) return 0;
  // doublons.js rend "<strong>${pendingCount}</strong> en attente" dans le header.
  const candidates = mount.querySelectorAll("strong");
  for (const el of candidates) {
    const next = (el.nextSibling && el.nextSibling.textContent) || "";
    if (next.includes("en attente")) {
      const n = Number((el.textContent || "0").replace(/[^\d]/g, ""));
      if (Number.isFinite(n)) return n;
    }
  }
  return 0;
}

function _bindEvents(container) {
  // Idempotent : un seul jeu de listeners par mount, attachés au container parent.
  // _renderInPlace() peut réécrire innerHTML sans recréer les listeners car ils
  // vivent sur le container, pas sur les boutons enfants.
  if (_eventsBound) return;
  if (!container) return;
  container.addEventListener("click", _onContainerClick);
  container.addEventListener("change", _onContainerChange);
  _eventsBound = true;
}

async function _handleSaveValidation({ detached = false } = {}) {
  if (!_runInfo?.runId) return;
  const decisions = _buildDecisions();
  try {
    // AUDIT 2026-06-10 (REAL 2/2) : en mode detache (auto-save sur unmount), on
    // n'utilise PAS _signal() — sinon l'_abortController.abort() de unmount
    // annule la requete et les decisions sont perdues. On saute aussi le
    // render/toast post-save (le container est en cours de detachement).
    const res = await apiPost("run/save_validation", {
      run_id: _runInfo.runId,
      decisions,
    }, detached ? {} : { signal: _signal() });
    if (detached) return;
    if (res?.data?.ok !== false) {
      showToast({ type: "success", text: "Décisions sauvegardées." });
      await _loadRunInfo();
      // Fix audit 2026-06-08 critical : mutation locale de row.decision pour
      // chaque rowId du payload save. Sans ca, _hasUnsavedValidationDecisions()
      // continuait de detecter des "divergences" apres sauvegarde reussie car
      // row.decision restait fige a PENDING. Mapping ok=true -> APPROVED,
      // ok=false -> REJECTED (aligne sur le contrat backend save_validation).
      if (_validationPlan?.rows) {
        for (const row of _validationPlan.rows) {
          const rid = String(row.row_id || "");
          const d = decisions[rid];
          if (d) row.decision = d.ok ? "APPROVED" : "REJECTED";
        }
      }
      _renderInPlace();
    } else {
      showToast({ type: "error", text: "Échec de la sauvegarde." });
    }
  } catch {
    if (!detached) showToast({ type: "error", text: "Erreur lors de la sauvegarde." });
  }
}

/* --- Hash change handling --- */

function _onHashChange() {
  const next = _readStep();
  const nextRun = _readTargetRunId();
  let changed = false;
  if (next !== _currentStep) {
    // Fix audit 2026-06-08 high : transition via URL hash (back/forward navigateur
    // ou clic externe sur lien #step-xxx). Auto-save silencieux best-effort si
    // on quitte Validation avec decisions non enregistrees -> evite la perte
    // silencieuse non-couverte par les guards de boutons internes.
    if (_currentStep === "validation" && _hasUnsavedValidationDecisions()) {
      // Best effort, on n'attend pas la promesse (le hashchange est synchrone).
      _handleSaveValidation();
    }
    _currentStep = next;
    changed = true;
  }
  if (nextRun !== _targetRunId) {
    _targetRunId = nextRun;
    changed = true;
    // Recharge les données du nouveau run cible.
    if (_activeContainer) {
      // Fix audit 2026-05-24 : _rerender n'existe pas (ReferenceError silencieux
      // a chaque hashchange -> back/forward navigateur cassé). Utiliser
      // _renderInPlace() qui re-rend a partir du container actif.
      _loadRunInfo().then(() => {
        if (_activeContainer) _renderInPlace();
      });
      return;
    }
  }
  if (changed && _activeContainer) {
    _renderInPlace();
  }
}

/* --- Lifecycle --- */

export async function initTraitement(container) {
  if (!container) return;
  _activeContainer = container;
  _currentStep = _readStep();
  _targetRunId = _readTargetRunId();
  // Phase 5 : si fragment #run-XXX présent sans step, aller direct à "validation".
  if (_targetRunId && _currentStep === "analyse") {
    _currentStep = "validation";
  }
  _logsState = { items: [], nextIndex: 0 };
  // Fix audit 2026-05-24 : nouveau AbortController par mount, abort au
  // unmount pour interrompre tous les apiPost en vol (cf _signal()).
  _abortController = new AbortController();
  // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : reset flag binding au mount
  // pour qu'un re-mount (navigation back/forward) attache à nouveau les
  // listeners sur le nouveau container.
  _eventsBound = false;
  // VN-C.1 (batch 2) : prefetch des seuils confidence (cache module-level
  // dans core/api.js). Lance en // — pas critique de l'attendre, le
  // fallback sync renvoie les DEFAULTS si pas encore arrive.
  fetchConfidenceThresholds().catch(() => { /* fallback DEFAULTS */ });
  container.innerHTML = _renderTraitement();
  window.addEventListener("hashchange", _onHashChange);
  await _loadRunInfo();
  await _loadRunStatus();
  await _loadPlan();
  _renderInPlace();
  // Demarre le polling si on a un run actif
  if (_runInfo?.runId) {
    _startPolling();
    _startUndoCountdown();
  }
}

export function unmountTraitement() {
  // Fix audit 2026-06-08 high : auto-save silencieux best-effort sur unmount
  // si on quitte Validation avec decisions non enregistrees. Sans ca, fermer
  // la vue ou changer d'onglet perdait silencieusement les modifs JS.
  if (_currentStep === "validation" && _hasUnsavedValidationDecisions()) {
    // Mode detache : sans signal -> survit a l'abort ci-dessous (AUDIT 2026-06-10).
    _handleSaveValidation({ detached: true });
  }
  _stopPolling();
  _stopUndoCountdown();
  // Fix audit 2026-05-24 : abort tous les apiPost en vol avant remise à null
  // du container (sinon le .then() qui suit appelle _renderInPlace sur un
  // _activeContainer null -> NPE silencieux + state set sur ancien run).
  if (_abortController) {
    try { _abortController.abort(); } catch { /* noop */ }
    _abortController = null;
  }
  if (_doublonsMounted) {
    unmountDoublons();
    _doublonsMounted = false;
  }
  // Fix audit 2026-05-25 (v1.5.3) Vague G Fix 2 : retirer les listeners délégués
  // du container avant de le détacher. removeEventListener avec la même référence
  // de fonction module-level fonctionne car les handlers sont stables.
  if (_activeContainer && _eventsBound) {
    _activeContainer.removeEventListener("click", _onContainerClick);
    _activeContainer.removeEventListener("change", _onContainerChange);
  }
  _eventsBound = false;
  window.removeEventListener("hashchange", _onHashChange);
  _currentStep = "analyse";
  _runInfo = null;
  _targetRunId = null;
  _runStatus = null;
  _activeContainer = null;
  _validationPlan = null;
  // AUDIT 2026-06-13 (R5-P2) : reset du cache d'aperçu apply au unmount pour ne
  // pas réafficher le plan d'un run précédent.
  _applyPreview = null;
  _applyPreviewLoading = false;
  _applyPreviewSig = "";
  // VN-C.2 : reset du state JS des decisions au unmount. Aucune persistence
  // hors session run (par design — la spec interdit localStorage long-terme,
  // les decisions vivent uniquement le temps de la session de validation).
  _decisionsState = new Map();
  // Fix VAL-3 (2026-05-30) : reset filtre/tri/expand au unmount pour eviter
  // qu'un etat "filtre=high" persiste si l'utilisateur revient plus tard.
  _validationFilter = "all";
  _validationSort = { key: "confidence", dir: "desc" };
  _validationExpanded = new Set();
  // Fix APPLY-2 (2026-05-30) : reset etat apply.
  _applyStatus = null;
  // Fix iter13 POLLING_UI_BACKOFF (2026-06-10) : reset du state backoff au
  // unmount pour qu'un futur remount reparte sain (pas de fantome "Reconnexion
  // dans Xs" sur une vue qui vient juste d'etre remontée).
  _pollErrorStreak = 0;
  _pollNextRetryAt = 0;
  _pollLastError = null;
  _logsState = { items: [], nextIndex: 0 };
  void navigateTo;
}
