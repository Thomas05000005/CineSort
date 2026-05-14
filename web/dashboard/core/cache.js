/* core/cache.js — Cache localStorage des dernieres reponses API (J14)
 *
 * Permet d'afficher les donnees cachees quand le serveur est injoignable
 * (5xx, timeout) au lieu d'un ecran vide. TTL 24 h, whitelist stricte.
 */

const _PREFIX = "cinesort.cache.";
const _TTL_MS = 24 * 3600 * 1000;
const _MAX_BYTES = 2 * 1024 * 1024; // ~2 MB cap par entree

const _CACHEABLE = new Set([
  // Methodes directes (legacy, conservees pour backward-compat jusqu'a PR 10)
  "get_dashboard",
  "get_global_stats",
  "get_settings",
  "get_probe_tools_status",
  "get_runs_summary",
  "get_jellyfin_libraries",
  "get_plex_libraries",
  "get_radarr_status",
  // Issue #84 PR 9 : memes methodes via le path facade prefixe
  "settings/get_settings",
  "integrations/get_jellyfin_libraries",
  "integrations/get_plex_libraries",
  "integrations/get_radarr_status",
]);

export function isCacheable(method) {
  return _CACHEABLE.has(String(method || ""));
}

export function saveSnapshot(method, data) {
  if (!isCacheable(method)) return;
  try {
    const payload = JSON.stringify({ ts: Date.now(), data });
    if (payload.length > _MAX_BYTES) return; // skip si trop gros
    localStorage.setItem(_PREFIX + method, payload);
  } catch (e) {
    /* quota exceeded — silencieux */
  }
}

export function loadSnapshot(method) {
  try {
    const raw = localStorage.getItem(_PREFIX + method);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    const ageMs = Date.now() - Number(obj.ts || 0);
    if (ageMs > _TTL_MS) {
      localStorage.removeItem(_PREFIX + method);
      return null;
    }
    return { data: obj.data, ageSeconds: Math.floor(ageMs / 1000), stale: ageMs > 10 * 60 * 1000 };
  } catch {
    return null;
  }
}

export function clearCache() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(_PREFIX)) keys.push(k);
    }
    keys.forEach((k) => localStorage.removeItem(k));
  } catch { /* ignore */ }
}

/** Retourne un message user-friendly de l'age du cache. */
export function formatStaleness(ageSeconds) {
  const age = Number(ageSeconds) || 0;
  if (age < 60) return "il y a quelques secondes";
  if (age < 3600) return `il y a ${Math.floor(age / 60)} min`;
  if (age < 86400) return `il y a ${Math.floor(age / 3600)} h`;
  return `il y a plus d'un jour`;
}
