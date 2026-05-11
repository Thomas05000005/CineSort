/* core/time-groups.js — Groupement temporel (dashboard, ES module). */

const _BUCKETS = [
  { id: "today", label: "Aujourd'hui", maxSeconds: 24 * 3600 },
  { id: "week", label: "Cette semaine", maxSeconds: 7 * 24 * 3600 },
  { id: "month", label: "Ce mois", maxSeconds: 30 * 24 * 3600 },
  { id: "older", label: "Plus ancien", maxSeconds: Infinity },
];

export function groupRunsByDate(runs, nowSec) {
  const now = nowSec ?? Date.now() / 1000;
  const groups = _BUCKETS.map((b) => ({ id: b.id, label: b.label, runs: [] }));

  for (const run of runs || []) {
    const ts = Number(run.started_at || run.start_ts || run.ts || 0);
    if (!ts) {
      groups[groups.length - 1].runs.push(run);
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
