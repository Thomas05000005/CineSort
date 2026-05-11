/* core/time-groups.js — Groupement temporel de runs (I13)
 *
 * Regroupe une liste de runs (avec started_at timestamp Unix) en 4 buckets :
 *   - "Aujourd'hui"   : < 24 h
 *   - "Cette semaine" : 1-7 jours
 *   - "Ce mois"       : 8-30 jours
 *   - "Plus ancien"   : > 30 jours
 *
 * Buckets vides omis.
 */

const _BUCKETS = [
  { id: "today", label: "Aujourd'hui", maxSeconds: 24 * 3600 },
  { id: "week", label: "Cette semaine", maxSeconds: 7 * 24 * 3600 },
  { id: "month", label: "Ce mois", maxSeconds: 30 * 24 * 3600 },
  { id: "older", label: "Plus ancien", maxSeconds: Infinity },
];

/**
 * @param {Array<{started_at:number}>} runs - runs avec champ timestamp (secondes).
 * @param {number} [nowSec] - pivot (defaut: Date.now()/1000).
 * @returns {Array<{id, label, runs: Array}>}
 */
function groupRunsByDate(runs, nowSec) {
  const now = nowSec ?? Date.now() / 1000;
  const groups = _BUCKETS.map((b) => ({ id: b.id, label: b.label, runs: [] }));

  for (const run of runs || []) {
    const ts = Number(run.started_at || run.start_ts || run.ts || 0);
    if (!ts) {
      groups[groups.length - 1].runs.push(run); // fallback dans Plus ancien
      continue;
    }
    const age = now - ts;
    for (let i = 0; i < _BUCKETS.length; i++) {
      if (age < _BUCKETS[i].maxSeconds) {
        groups[i].runs.push(run);
        break;
      }
    }
  }

  return groups.filter((g) => g.runs.length > 0);
}

if (typeof window !== "undefined") {
  window.groupRunsByDate = groupRunsByDate;
}
