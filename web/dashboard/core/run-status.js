/* core/run-status.js — derivation du statut affiche d'un run.
 *
 * SOURCE UNIQUE, partagee par /accueil (timeline « Activite recente ») et
 * /historique (liste, tableau, filtres, inspecteur). Les deux ecrans decrivent
 * le MEME objet : ils doivent en dire le meme mot.
 *
 * Pourquoi ce module existe (revue adversaire de la PR #855, 2026-08-03) :
 * les deux vues portaient chacune leur propre derivation, et la correction de
 * `historique.js` seule les avait mises en CONTRADICTION. Mesure faite en
 * executant les deux vraies fonctions sur le meme payload :
 *
 *   run                      | /accueil (avant)      | /historique (apres fix)
 *   -------------------------|-----------------------|------------------------
 *   FAILED, errors_count 0   | DONE (pastille grise) | ERROR
 *   RUNNING                  | DONE                  | RUNNING
 *   CANCELLED                | DONE                  | CANCELLED
 *   AWAITING_VALIDATION      | DONE                  | AWAITING_VALIDATION
 *   DONE, applied 10/10      | DONE                  | APPLIED
 *
 * La ligne `FAILED -> DONE` d'accueil.js portait EXACTEMENT le defaut que la PR
 * corrigeait ailleurs (« run plante invisible »), sur l'ecran le plus vu : la
 * liste blanche `APPLIED/DONE/PARTIAL/ERROR` ne contenait ni FAILED, ni
 * CANCELLED, ni les statuts transitoires, donc tout run non termine ou plante
 * sans ligne d'erreur retombait sur `return "DONE"` — pastille neutre et
 * infobulle « ... — DONE » sur un run en cours ou echoue.
 *
 * Convention retenue : le statut ECRIT EN BASE fait foi (c'est la seule source
 * qui sait si le run a plante, a ete annule, ou tourne encore) ; les compteurs
 * ne servent qu'a affiner les etats terminaux qui ne disent rien de l'apply.
 *
 * Fait d'ancrage : `run/get_dashboard` emet TOUJOURS un `status` non vide
 * (`str(run_row.get("status") or "PENDING")`, dashboard_support.py) — d'ou le
 * cas `""` qui n'arrive qu'avec un payload de test ou un futur endpoint.
 */

/** Statuts terminaux qui ne disent rien de l'apply : les compteurs les affinent. */
export const NEUTRAL_TERMINAL_STATUS = ["", "DONE", "SAVED"];

/** Les 8 valeurs de RunStatus (cinesort/domain/run_models.py). */
export const DB_RUN_STATUSES = [
  "PENDING",
  "RUNNING",
  "DONE",
  "FAILED",
  "CANCELLED",
  "PAUSED",
  "SAVED",
  "AWAITING_VALIDATION",
];

/**
 * Statut affiche d'un run, dans le vocabulaire de l'UI.
 *
 * @param {object} run  ligne de `runs_history` (payload run/get_dashboard).
 * @returns {string} ERROR | APPLIED | PARTIAL | DONE, ou le statut DB tel quel
 *                   (PENDING / RUNNING / PAUSED / CANCELLED / AWAITING_VALIDATION).
 */
export function deriveRunStatus(run) {
  const r = run || {};
  const raw = String(r.status || "").toUpperCase();
  // FAILED est le statut ecrit par le backend (repositories/run.py) ; ERROR est
  // le vocabulaire de l'UI (filtre, classe CSS, libelle).
  if (raw === "FAILED" || raw === "ERROR") return "ERROR";
  // PENDING / RUNNING / PAUSED / CANCELLED / AWAITING_VALIDATION : le statut DB
  // est plus informatif que n'importe quel compteur, on le garde tel quel.
  if (!NEUTRAL_TERMINAL_STATUS.includes(raw)) return raw;
  const errors = Number(r.errors_count || 0);
  const applied = Number(r.applied_rows || 0);
  const total = Number(r.total_rows || 0);
  if (errors > 0) return "ERROR";
  if (applied > 0 && applied >= total) return "APPLIED";
  if (applied > 0 && applied < total) return "PARTIAL";
  return raw || "DONE";
}
