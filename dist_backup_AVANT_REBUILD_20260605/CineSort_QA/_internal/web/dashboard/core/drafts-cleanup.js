/* core/drafts-cleanup.js — Purge drafts review localStorage (V2-C R4-MEM-5)
 *
 * Pourquoi ?
 *   review.js sauvegarde les decisions in-memory dans localStorage par run :
 *   cle val_draft_<run_id>. Sans purge, les drafts de runs anciens (termines,
 *   rejetes, supprimes) restent indefiniment et grossissent localStorage au
 *   fil du temps.
 *
 *   Cette fonction est appelee au boot du dashboard (app.js) — elle scanne
 *   toutes les cles val_draft_* et supprime celles dont le timestamp depasse
 *   le TTL (30 jours par defaut, aligne avec review.js).
 *
 *   Note : la constante VAL_DRAFT_KEY_PREFIX et VAL_DRAFT_TTL_MS sont
 *   dupliquees ici pour ne pas creer de dependance entre core/ et views/
 *   (interdit par test_v5c_cleanup : app.js ne peut pas importer review.js
 *   directement). Si le format change un jour, mettre a jour les 2 endroits.
 */

const VAL_DRAFT_KEY_PREFIX = "val_draft_";
const VAL_DRAFT_TTL_MS = 30 * 24 * 60 * 60 * 1000;  // 30 jours

/**
 * Purge tous les drafts review.js expires (TTL 30j) dans localStorage.
 * Appelee une fois au boot du dashboard. Idempotent et silencieux.
 */
export function cleanupExpiredDrafts() {
  try {
    const now = Date.now();
    const toRemove = [];
    // Snapshot des cles d'abord (on ne mute pas localStorage en iteration).
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(VAL_DRAFT_KEY_PREFIX)) continue;
      try {
        const raw = localStorage.getItem(key);
        if (!raw) { toRemove.push(key); continue; }
        const draft = JSON.parse(raw);
        const ts = (draft && Number(draft.ts)) || 0;
        if (!ts || (now - ts) > VAL_DRAFT_TTL_MS) toRemove.push(key);
      } catch {
        // Draft corrompu : on le supprime aussi.
        toRemove.push(key);
      }
    }
    for (const key of toRemove) {
      try { localStorage.removeItem(key); } catch { /* noop */ }
    }
    if (toRemove.length > 0) {
      console.debug("[drafts-cleanup] removed %d expired entries", toRemove.length);
    }
  } catch (e) {
    console.warn("[drafts-cleanup] failed", e);
  }
}
