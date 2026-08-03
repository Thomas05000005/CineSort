# SYNTHÈSE LOT A — Phase 0 (assainissement) + Phase 1 (8 matrices) — 2026-07-08

> Branche `verif/totale-2026-07` (base : `650d162` = origin/main). Go/No-Go Lot B : **GO proposé**.

## Phase 0 — faite intégralement, 0 régression

| Item | Commit | Résultat |
|---|---|---|
| 0.3 Purge artefacts | `f9da5aa` | 36 fichiers trackés supprimés, logs racine effacés, JSON de revue archivés (`docs/internal/archive/`), `.gitignore` renforcé (`*.err/*.pid/_iter*` + `/settings.json` ancré) |
| 0.4 Tests morts | `13c37e8` | 74 fichiers « Legacy frontend removed » supprimés (~15 k lignes), `[tool.pytest.ini_options]` déclaré (testpaths + marker runtime). Collecte : 6 029 tests, 0 erreur |
| 0.2 Locks | `a8947fc` | `uv.lock` + `requirements.lock` régénérés (**pydantic 2.13.4** présent), `requirements-dev.txt` aligné (+pytest-cov, +sqlparse) |
| 0.1 main local | — | Fast-forward sur `650d162`. **Découverte** : travail non commité dans le worktree B4 (+102/-25 : rate-limit 401 5→20, PAGE_SIZE 200, sentinel #82, format To) sauvé dans `wip/b4-main-uncommitted-2026-06` — à réconcilier en Phase 5 (une partie n'est PAS dans R8) |
| 0.5 Baseline | ce commit | **23 failed, 5 796 passed, 17 skipped, 50 errors** en 13 min 44 (venv 3.13, périmètre CI exact). Liste nominative : `baseline_tests.txt`. Les 5 échecs suspects (pyproject/hygiène/imports) rejoués sur `650d162` vierge : identiques → **préexistants, 0 régression Phase 0**. Les 50 errors = cluster `test_runtime_*` (Playwright/app réelle, environnement local — Phase 3) |

⚠️ Leçons d'exécution : lancer les tests avec `.venv/Scripts/python.exe` (3.13) — le `python` global est un 3.12 qui produit un mur de faux échecs ; le périmètre CI réel ignore aussi `e2e_dashboard/e2e_desktop/manual/live/stress` et n'utilise PAS `--timeout` (la commande « Vérifications rapides » de CLAUDE.md est fausse, à corriger en Phase 7).

## Phase 1 — les 8 matrices (commit `4c329c6`)

Scripts rejouables : `scripts_matrices/mX_*.py` (python -X utf8) → `matrices/mX_*.json`.

| M | Périmètre | STATS |
|---|---|---|
| M1 UI→API | 193 apiPost / 172 méthodes | OK 188 · **PAYLOAD_DESACCORDE 3** · **MAUVAISE_FACADE 1** · EXCLU 1 · reverse : ORPHELINE 50 (+3 incert.) |
| M2 Façades | 176 méthodes, 147 `_X_impl` | PROPRE 155 · DUPLIQUE 11 (wrapper-chain) · DOUBLE_CHEMIN 6 · ORPHELIN 4 (SimilarFilmsFacade) |
| M3 Settings | 160 clés canoniques | CABLEE 86 · READ_ONLY 38 · **FANTOME 21** · **WRITE_ONLY 15** |
| M4 Actions UI | 109 actions / 121 sites | OK 106 · **SANS_CONFIRMATION 3** (toutes vue /processing) |
| M5 CSS | 2 326 classes déf. / 1 499 utilisées | **DEFINIE_NON_UTILISEE 903** · **UTILISEE_NON_DEFINIE 212** · INCERTAIN 136 · HEX_HORS_TOKENS 488 |
| M6 i18n | 747 clés ×2 locales | référencées 157 · **ORPHELINE 519 (69 %)** · TEXTE_EN_DUR 20 (échant.) · 0 divergence fr/en |
| M7 DB | 24 tables | CABLEE 21 · READ_NEVER 1 (`anomalies`) · WRITE_ONLY 1 (schema_migrations, voulu) · MORTE 1 (vec_*, D3 voulu) |
| M8 Timers | 130 occurrences | PROPRE 117 · FUITE 1 (**R8-083 confirmé**) · RACE 4 · **R8-084 DÉJÀ CORRIGÉ** (registre mis à jour) |

## Top findings à corriger (alimentent Phase 5)

1. **3 nouveaux boutons cassés** (M1, en plus des 2 connus) : Apply de /processing (`processing.js:768`, payload `{run_id,dry_run,quarantine}` vs signature `decisions`+`quarantine_unapproved` → 400) ; upgrade Radarr (`radarr.js:94`, `movie_id` vs `radarr_movie_id`) ; refresh jaquette (`film-detail.js:922`, `force_refresh` inconnu).
2. **La vue /processing concentre le legacy dangereux** (M4+M8+M1) : apply sans confirmation, cancel muet (le `apiPost` de `_v5_helpers` ne throw jamais → catch morts), poll R8-083 (`unmountProcessing` existe mais jamais câblé au router), bouton Apply cassé. Route toujours atteignable (`app.js:287`). → chantier « /processing » unique.
3. **i18n débranchée** (M6) : les 9 vues principales font 0 appel `t()` ; 519 clés entretenues pour rien ; glossaire avec dict FR en dur. → décision : câbler ou assumer FR-only et tailler.
4. **Settings menteurs** (M3) : `auto_approve_enabled/threshold` affichés dans l'UI mais lus par PERSONNE ; `notifications_enabled` sans lecteur depuis R8-069 ; `onboarding_completed` décoratif ; 6 flags `_has_*` générés jamais affichés (l'UI ne peut pas dire si un secret est déjà enregistré) ; 17 clés `perceptual_*` réglables uniquement à la main.
5. **Table `anomalies` structurellement vide** (M7) : 4 SELECT, 0 INSERT — le dashboard vit sur le fallback `anomalies_light`.
6. **CSS : familles entières mortes** (M5) : v5-film-* (59), v5-settings-* (34), v5-qij-* (28), v5-palette-* (14) + 15 classes `traitement-undo-*` et 15 `about-*` posées dans le DOM sans aucun style ; `:root` secondaire `--tier-*` sans `-solid` (styles.css:2044) toujours présent.
7. **4 races timers mineures** (M8) + modale reset qui survit à la navigation si ouverte.

## Reclassements vs plan initial

- R8-084 (course reset↔autosave) : **corrigé dans R8**, retiré du reste-à-faire.
- M4 bien meilleur qu'attendu : le flux principal (traitement) confirme correctement apply/undo/cancel via dangerConfirmModal + countdown.
- M2 : les 11 « homonymes » sont des wrapper-chains sans logique dupliquée (nommage piégeux, pas de bug).

## Suite — Lot B (Phase 2) : tests de contrat permanents

Transformer M1/M3/M6/M5-statique/M2 en tests CI (test_contract_ui_api en premier — il aurait attrapé les 5 boutons cassés). Puis Lot C (Phase 3 runtime Playwright, 13 vues) où les 50 errors `test_runtime_*` de la baseline seront réhabilités.
