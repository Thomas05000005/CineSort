# V5C-02 — Décision intégrations Jellyfin/Plex/Radarr/Logs

**Date** : 2026-05-03
**Branche** : `feat/v5c-integrations-v5`
**Effort réel** : ~30 min (audit + décision + alignement minimal)

## Audit

| Vue | LOC | Pattern actuel | Classes CSS | Features V1-V4 préservées |
|---|---|---|---|---|
| jellyfin.js | 267 | ESM + `apiPost` ✅ | v4 (`card`, `btn`, `btn-primary`, `kpi-grid`, `kpi-card`, `status-msg`, `jellyfin-lib-list`, `sync-ok/warn/error`) | Guard `jellyfin_enabled`, KPIs (statut/films/serveur/version), liste libraries, test connexion, refresh, validation croisée (matched/missing/ghost/mismatch), skeleton V2-08, `Promise.allSettled` V2-04 |
| plex.js | 77 | ESM + `apiPost` ✅ | v4 (`card`, `btn-primary`, `btn--compact`, `kpi-grid`, `kpi-card`) | Guard `plex_enabled`, KPI 3 cartes (statut/serveur/version), infos URL/refresh, test connexion, validation croisée, skeleton |
| radarr.js | 96 | ESM + `apiPost` ✅ | v4 (idem + `tbl`) | Guard `radarr_enabled`, KPI 3 cartes, test connexion, status report (matched/not_in_radarr/upgrade_candidates), table candidats avec bouton upgrade, skeleton |
| logs.js | 259 | ESM + `apiPost`/`apiGet` ✅ | v4 (`btn--compact`, `progress-bar`, `logs-box`, `log-line`, `log-error/warn/end`, `status-msg`) | Toggle live/historique, polling 2s, ETA, annuler run, table runs sortable, exports JSON/CSV/HTML/.nfo, `Promise.allSettled` V2-04 |

### Observations

1. **Aucun `window.pywebview.api`** — Toutes les 4 vues utilisent déjà `apiPost`/`apiGet` (pattern ESM moderne identique à V5bis-01..07).
2. **Aucun IIFE legacy** — Modules ES exportant `init*()` propres.
3. **Polish V1-V4 déjà présent** — skeletons, allSettled, KPIs colorés, badges, tables sortables.
4. **Bug mineur détecté** : la classe `.btn--compact` est utilisée dans `plex.js`, `radarr.js`, `logs.js` mais absente de `web/dashboard/styles.css` et `web/shared/components.css` (elle n'existe que dans `web/styles.css`, jamais chargé par le dashboard distant). Les boutons "Tester la connexion", "Validation croisée", etc. apparaissent donc sans le styling compact attendu. Bug pré-existant non imputable à V5C.

## Décision

**Choisi : Option B — Conservation v4 avec alignement minimal**

### Raison

L'audit révèle que les vues v4 dashboard sont déjà très propres :

1. **Pattern ESM moderne** déjà appliqué — pas de chantier technique à mener (contrairement à V5bis-01..07 qui partaient d'IIFE).
2. **Polish V1-V4 préservé à 100%** (skeleton V2-08, allSettled V2-04, KPIs, badges, sync reports, exports).
3. **Effort/bénéfice défavorable** : un port v5 complet (renommage `.btn` → `.v5-btn`, `.card` → `.v5-card`, etc., ajout de glossary tooltips ⓘ) coûterait 4-6h pour un gain visuel marginal. Les classes v4 (`.card`, `.btn`, `.kpi-grid`, `.status-msg`) sont définies dans `web/dashboard/styles.css` et fonctionnent correctement sous le shell v5.
4. **Cohérence avec le principe v7.6.0** — "coexistence v5+legacy via prefix `v5-*`" autorise explicitement les vues sans préfixe quand il n'y a pas de bénéfice à les migrer.
5. **Vues simples et stables** — KPIs + tables + boutons d'action. Aucune logique métier nouvelle n'est attendue.

### Plan d'exécution (Option B)

1. ✅ Audit des 4 vues — pas de pattern legacy à corriger.
2. ✅ Vérification compatibilité shell v5 — toutes les classes v4 utilisées sont présentes dans `web/dashboard/styles.css`, sauf `.btn--compact` (bug pré-existant).
3. 🔧 **Alignement minimal** : ajouter `.btn--compact` dans `web/dashboard/styles.css` pour que les boutons compacts de Plex/Radarr/Logs s'affichent correctement.
4. 📝 Documenter le choix architectural dans `CLAUDE.md` : "Jellyfin/Plex/Radarr/Logs restent en v4 par choix architectural — vues simples qui ne bénéficient pas d'une refonte v5".
5. 🧪 Tests structurels minimaux : vérifier que les 4 vues continuent d'exister, n'utilisent pas `window.pywebview.api`, et que la décision est documentée.

## Plan reporté à plus tard (V5C+)

Si un futur besoin émerge (ex. nouveau composant v5 partagé sur les vues intégrations), envisager un port à ce moment-là. Pour l'instant : **statu quo + alignement minimal**.
