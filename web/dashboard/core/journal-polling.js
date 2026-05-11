/* core/journal-polling.js — Singleton polling anti-leak pour live logs QIJ
 *
 * Pourquoi un singleton ?
 *   La vue QIJ a 3 tabs (Quality, Integrations, Journal). Quand l'utilisateur
 *   switche entre tabs ou change de route, sans cleanup strict on accumule
 *   plusieurs setInterval qui continuent a faire des fetchs en boucle =>
 *   memory leak + appels backend inutiles. Le singleton garantit qu'au plus
 *   UN polling tourne a la fois pour un run_id donne.
 *
 * Usage :
 *   import { journalPoller } from "../core/journal-polling.js";
 *   journalPoller.start(runId, {
 *     onProgress: (idx, total, etaS, current) => { ... },
 *     onLogsAppend: (logEntries[]) => { ... },
 *     onDone: () => { ... },
 *   });
 *   // au unmount du tab Journal :
 *   journalPoller.stop();
 */

import { apiPost } from "./api.js";

class JournalLivePoller {
  constructor() {
    this.runId = null;
    this.timer = null;
    this.lastLogIndex = 0;
    this.callbacks = {};
    this.intervalMs = 2000;
  }

  /**
   * Demarre le polling pour un run_id donne.
   * Si un polling tourne deja pour le meme runId, ne fait rien (dedup).
   * Si polling tourne pour un autre runId, l'arrete avant.
   */
  start(runId, callbacks = {}) {
    if (!runId) return;
    if (this.runId === runId && this.timer) return; // deja actif sur ce run
    this.stop(); // cleanup ancien polling si autre runId
    this.runId = runId;
    this.lastLogIndex = 0;
    this.callbacks = callbacks || {};
    // 1er tick immediat (sinon on attend 2s avant de voir quoi que ce soit)
    this._tick();
    this.timer = setInterval(() => this._tick(), this.intervalMs);
  }

  /** Arrete proprement le polling et libere les references. */
  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.runId = null;
    this.lastLogIndex = 0;
    this.callbacks = {};
  }

  /** Indique si un polling est actif. */
  isActive() {
    return !!(this.timer && this.runId);
  }

  /** Retourne le runId actuellement polled (ou null). */
  getRunId() {
    return this.runId;
  }

  async _tick() {
    if (!this.runId) return;
    try {
      // V2-C R4-MEM-3 : timeout 5s pour eviter accumulation de ticks pendants
      // si le backend pend (la prochaine intervalle se declenchera sans avoir
      // attendu le retour, donc fetchs zombie cumulent → memory leak).
      const res = await apiPost(
        "get_status",
        { run_id: this.runId, last_log_index: this.lastLogIndex },
        { timeoutMs: 5000 },
      );
      const d = (res && res.data) || {};

      // Progress callback
      if (typeof this.callbacks.onProgress === "function") {
        this.callbacks.onProgress(
          Number(d.idx) || 0,
          Number(d.total) || 0,
          Number(d.eta_s) || 0,
          d.current || ""
        );
      }

      // Logs callback (si nouveaux logs)
      if (Array.isArray(d.logs) && d.logs.length > 0) {
        if (typeof this.callbacks.onLogsAppend === "function") {
          this.callbacks.onLogsAppend(d.logs);
        }
        if (d.next_log_index) this.lastLogIndex = d.next_log_index;
      }

      // Done callback (run termine)
      const isDone = d.done || (!d.running && !d.error);
      if (isDone) {
        if (typeof this.callbacks.onDone === "function") {
          this.callbacks.onDone({ error: d.error, status: d.status });
        }
        this.stop();
      }
    } catch (e) {
      // V2-C R4-MEM-3 : AbortError (timeout 5s) est attendu, pas un vrai echec.
      // Polling silencieux : prochain tick reessaiera.
      const isAbort = e && (e.name === "AbortError" || e.name === "TimeoutError");
      if (!isAbort) console.debug("[journal-poller] tick error:", e);
    }
  }
}

export const journalPoller = new JournalLivePoller();
