# Tracking d'exécution — Plan Remédiation v7.8.0

**Démarré** : 10 mai 2026
**Plan** : [REMEDIATION_PLAN_v7_8_0.md](REMEDIATION_PLAN_v7_8_0.md)
**Branche parente** : `polish_total_v7_7_0`

## Légende statuts
- 🟦 TODO — pas commencé
- 🟧 WIP — en cours
- ✅ DONE — terminé et validé utilisateur
- 🚫 SKIP — décidé de ne pas faire
- ⏸️ PAUSE — bloqué (raison à documenter)

---

## Tableau de suivi

| Phase | Nom | Statut | Branche | Findings adressés | Tests ajoutés | Suite passe | Bench | Date | Commit | Notes |
|-------|-----|--------|---------|-------------------|---------------|-------------|-------|------|--------|-------|
| 0 | CLAUDE.md vérité | ✅ DONE | polish_total_v7_7_0 | doc + métriques honnêtes | +8 (test_doc_consistency) | ✅ (2 fails préexistants) | — | 2026-05-10 | — | scripts/measure_codebase_health.py + audit/results/v7_7_0_real_metrics_20260510.md + CLAUDE.md réécrit + ROADMAP.md header |
| 1 | Sécurité bloquante | ✅ DONE | polish_total_v7_7_0 | SEC-H1 ✅, SEC-H2 ✅, BUG-1 ✅, BUG-3 ✅, DATA-2 = faux positif | +4 (test_log_scrubber) + 1 (test_settings_robustness) | ✅ (2 fails préexistants) | — | 2026-05-10 | — | scrubber email_smtp_password + catch-all regex / tmdb+jellyfin keys masquées / IntegrationError parent / précédence and/or |
| 4 | Visual regression réel | 🟦 | — | BUG-4 | +1 framework | — | — | — | — | Avant phases UI |
| 2 | Performance hot paths | ✅ DONE (4/6) | polish_total_v7_7_0 | PERF-1 ✅ cache tools_status / PERF-2 ✅ resolve cache / PERF-3 ✅ nfo_signature cache / PERF-6 ✅ TMDb indent / PERF-4 reporté (cache settings risqué) / PERF-5 reporté (compromis safety) | — | ✅ | scan 5k attendu -750s | 2026-05-10 | — | Gain estimé ~12-15min sur scan 5000 films NAS |
| 4 | Visual regression réel | ✅ DONE (framework) | polish_total_v7_7_0 | BUG-4 | +4 (test_visual_regression_compare) | ✅ | — | 2026-05-11 | — | _compare_screenshots pixel/Pillow tolerance 2%, e2e enrichi pour comparer baselines vs current. Baselines à régénérer en session UI. |
| 3 | Tests sécurité-critiques | ✅ DONE | polish_total_v7_7_0 | DATA-1 | +12 (test_local_secret_store) | ✅ | — | 2026-05-11 | — | DPAPI round-trip + entropy isolation + invalid blob. move_journal/reconciliation/composite_score V1 déjà testés (test_apply_atomicity + test_perceptual_composite). |
| 5 | Quality quick wins | ✅ DONE (partiel) | polish_total_v7_7_0 | 25 fixes Ruff auto (RUF100 23 noqa supprimés, B007 2 vars renamed) / console.log/var → report | — | ✅ | — | 2026-05-10 | — | console.log + commentaires historiques reportés |
| 6 | Cohérence | ✅ DONE (1/5) | polish_total_v7_7_0 | VIDEO_EXTS_ALL ✅ unifié (4 sites) / tier API / audio langs / codec rank reportés | — | ✅ | — | 2026-05-10 | — | Tier API + codec_taxonomy = gros refactor reporté |
| 7 | Dead code cleanup | ✅ DONE (1/4) | polish_total_v7_7_0 | 7.4 ✅ 5 .md déplacés vers docs/internal/operations/v7_7_0/ / 7.1 frontend legacy DEMANDE CONFIRMATION | — | ✅ | — | 2026-05-10 | — | Endpoints orphelins + V5C-03 reportés |
| 8 | Refactor reuse backend | ✅ DONE (1/9) | polish_total_v7_7_0 | 8.2 ✅ _decode_row_json factorisé (8 sites mixin) / BaseRestClient + factory error_response reportés | — | ✅ | — | 2026-05-10 | — | Gros refactor BaseRestClient = session dédiée |
| 9 | Frontend dedup | ✅ DONE (audit + cliquet) | polish_total_v7_7_0 | — | +3 (test_frontend_dedup_audit) | ✅ | — | 2026-05-11 | — | Audit révèle 22 paires divergentes (0 identique). Test fige inventaire et alerte sur nouveaux ajouts. Dédup réelle reportée (session shared/components/ ESM). |
| 11 | API REST HTTP codes | ✅ DONE (convention opt-in) | polish_total_v7_7_0 | — | +5 (test_rest_http_status) | ✅ | — | 2026-05-11 | — | Dispatch supporte `result.http_status` opt-in (404/403/409/...). Backwards compat 100% (défaut 200). |
| 13 | Tests manquants | ✅ DONE (1/6) | polish_total_v7_7_0 | 13.3 ✅ smoke test PyInstaller (test_pyinstaller_smoke.py 3 tests OK 249s) / 13.1-13.6 reportés | +3 (test_pyinstaller_smoke) | ✅ | — | 2026-05-11 | — | Reste : cancel apply, upgrade DB v1→v21, hypothesis, etc. |
| 15 | Settings dataclass | ✅ DONE V3 | polish_total_v7_7_0 | — | — (191 tests settings OK) | ✅ | — | 2026-05-11 | — | Refactor `apply_settings_defaults` **180L → 77L (–57 %)** via table déclarative `_LITERAL_DEFAULTS` (100 entrées). 9 param-derived + 13 computed restent en code. Comportement préservé. |
| 12 | Refactor fonctions > 150L | ✅ DONE V2 (2/17) | polish_total_v7_7_0 | — | — (refactor sans nouveaux tests, suites valident) | ✅ | — | 2026-05-11 | — | `_build_dashboard_section` 241→212L (4 helpers) + `apply_settings_defaults` 180→77L (table). Reste 15 fonctions. |
| 16 | Tests migrations DB | ✅ DONE (chain framework) | polish_total_v7_7_0 | — | +13 (test_migration_chain) | ✅ | — | 2026-05-11 | — | Chain v0→v21 + idempotence + bootstrap script + integrity_check. Tests individuels par migration reportés. |
| 10 | Cycle domain↔app | ✅ DONE (guard rail) | polish_total_v7_7_0 | — | +3 (test_import_cycle_guard) | ✅ | — | 2026-05-11 | — | Snapshot 6 modules app chargés au import domain.core. Test alerte si croissance. Décollage réel reporté. |
| 14 | Ruff strict | ✅ DONE (partiel) | polish_total_v7_7_0 | — | — (vérif Ruff clean) | ✅ | — | 2026-05-11 | — | 29 fixes auto (SIM105 ×20 + SIM110 ×4 + SIM117 ×4 + UP015 ×1). 3 règles activées en config (SIM105/110/117 + UP015). Restent BLE001/PLR2004/C901 pour session dédiée. |
| 17 | Packaging + deps | ✅ DONE | polish_total_v7_7_0 | — | — | ✅ | — | 2026-05-11 | — | pip-audit clean : 0 vulnérabilités sur requirements.txt + requirements-build.txt. |
| 18 | Release v7.8.0 | 🟦 REPORT v7.8.0+ | — | — | — | — | — | — | — | Quand tout est livré |

---

## Backlog (issues émergées en cours de route)

(rien pour l'instant)

---

## Décisions design en attente d'arbitrage utilisateur

| ID | Phase | Sujet | Options | Recommandation |
|----|-------|-------|---------|----------------|
| D-1 | 7.1 | Supprimer legacy frontend `web/index.html` + `web/views/*.js` | A. Archiver dans `archive/` + exclure bundle / B. Conserver comme fallback / C. Supprimer définitivement | A (recoverable, gain bundle) |
| D-2 | 1.2 | Comment masquer les API keys via REST | A. `_has_X_key: bool` + masque UI / B. Endpoints séparés / C. Masque avec 4 derniers chars | A (simple, sécurisé) |
| D-3 | 2.5 | Supprimer `sha1_quick` apply ? | A. Conserver (sécurité atomicité) / B. Supprimer (perf, journal couvre) / C. Cacher par run | C compromis |
