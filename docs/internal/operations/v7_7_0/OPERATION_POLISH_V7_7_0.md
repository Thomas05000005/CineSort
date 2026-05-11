# Opération Polish Total v7.7.0 — Plan d'exécution

> Document opérationnel **lu obligatoirement par chaque agent** au démarrage d'une mission.
> Source des règles, du découpage en vagues, des critères de validation.
>
> **Démarrage** : 4 mai 2026 — **Cible** : v7.7.0 production-grade publique
> **Branche** : `polish_total_v7_7_0` (depuis `audit_qa_v7_6_0_dev_20260428`)
> **Source des findings** : `PLAN_RESTE_A_FAIRE.md` + `AUDIT_TRACKING.md`

---

## Décisions actées (NON négociables)

1. **i18n EN INCLUS** (Vague 6) — infrastructure complète + extraction strings + tests round-trip
2. **Composite Score V2 = coexistence + toggle** — V1 reste défaut, V2 activable via setting `composite_score_version` (1|2). Pas de cassure pour users existants. Migration opt-in.
3. **Branche unique `polish_total_v7_7_0`** — tag final `v7.7.0` à la fin. Tags backup intermédiaires `backup-before-vague-N` à chaque vague.
4. **Compatibilité 100%** — tout usage existant doit continuer à fonctionner. Si breaking change détecté, demander confirmation utilisateur AVANT de l'appliquer.
5. **Vérification continue** — pas de "fait" déclaré sans preuve (tests + build + smoke + relecture par agent validator).

---

## Règles cardinales pour chaque agent

### Avant de coder
- **Lire CLAUDE.md** (architecture, conventions, règles à ne pas enfreindre)
- **Lire le finding source** dans `PLAN_RESTE_A_FAIRE.md` ET `AUDIT_TRACKING.md`
- **Consulter context7** pour la doc à jour de la lib touchée (pywebview, requests, sqlite3, etc.)
- **Si web research nécessaire** : utiliser un agent secondaire WebSearch/WebFetch avant d'écrire du code

### Pendant le code
- **Refactor incrémental** — pas de big-bang rewrite
- **Préserver le comportement existant** — toute fonction publique garde sa signature sauf demande explicite
- **Tests ajoutés EN MÊME TEMPS** que le code — pas après
- **Constantes nommées** — zéro magic number
- **except spécifique** — jamais `except Exception`
- **Langue** : commentaires/messages FR, code EN, docstrings FR

### Avant de déclarer "fait"
- ✅ `python -m ruff check .` retourne 0 erreurs
- ✅ `python -m unittest discover -s tests -p "test_*.py"` passe (0 régression)
- ✅ Si modification frontend : smoke test Playwright (navigation 7 vues v5)
- ✅ Si modification backend critique : test ciblé reproduit le finding AVANT le fix puis confirme APRÈS
- ✅ Coverage reste ≥ 80%
- ✅ Build .exe testé en fin de vague (pas après chaque mission)

### Communication
- Rapport final concis : ce qui a changé, pourquoi, fichiers touchés, tests lancés, ce qui reste
- En cas de blocage : signaler immédiatement, ne pas insister
- En cas de breaking change détecté : STOP, demander confirmation utilisateur

---

## Pattern multi-agents par vague

```
                     ┌─────────────────────────┐
                     │  Vague N démarre        │
                     │  Tag backup-before-N    │
                     └────────────┬────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
   ┌──────────┐            ┌──────────┐               ┌──────────┐
   │ Agent 1  │            │ Agent N  │               │Validator │
   │ Mission A│   ...      │ Mission Z│ (en parallèle)│  agent   │
   │ worktree │            │ worktree │               │ relecture│
   └────┬─────┘            └────┬─────┘               │ tests    │
        │                       │                     │ smoke    │
        │ commit                │ commit              └─────┬────┘
        ▼                       ▼                           │
   tests + ruff           tests + ruff                      │
        │                       │                           │
        └───────────┬───────────┘                           │
                    ▼                                       │
              merge fast-forward ◄─────────────────────────┘
                    │            (validator OK requis)
                    ▼
            Build .exe + smoke test
                    │
                    ▼
            Tag end-vague-N
                    │
                    ▼
            Récap utilisateur — go vague N+1 ?
```

**Agents en parallèle** : isolation via `git worktree` (un sous-dossier par mission). Aucun conflit fichiers. Merge fast-forward si tous les tests passent.

**Agent validator continu** : relit chaque commit des autres agents, vérifie cohérence cross-mission, lance tests d'intégration. Stoppe la vague si régression détectée.

**Agent web-research** : sequence-thinking + context7 + WebSearch en background pour vérifier best practices avant chaque fix non trivial (CVE patches, API changes, deprecations).

---

## Découpage en 8 vagues

### VAGUE 0 — Préparation (1h, séquentiel)
- [ ] Créer branche `polish_total_v7_7_0` depuis `audit_qa_v7_6_0_dev_20260428`
- [ ] Snapshot baseline : `tests count`, `coverage %`, `bundle size`, `ruff status`
- [ ] Tag `backup-before-polish-total`
- [ ] Sanity check : `python -m unittest discover` passe à 100%
- [ ] Sanity check : build .exe actuel testé OK (50.07 MB)

**Livrable** : branche prête, baseline documentée dans `OPERATION_POLISH_V7_7_0_BASELINE.md`

---

### VAGUE 1 — Bloquants public release (~3j → ~1j parallèle)

**6 missions indépendantes + 1 validator + 1 web-research**

| ID | Mission | Effort | Fichiers |
|---|---|---|---|
| V1-01 | CVE bumps urllib3 + pyinstaller | 2h | requirements.txt, build test |
| V1-02 | Migration 021 ON DELETE CASCADE/RESTRICT | 1j | cinesort/infra/db/migrations/021_*.sql, sqlite_store, tests |
| V1-03 | FFmpeg subprocess cleanup atexit | 4h | cinesort/domain/perceptual/ffmpeg_runner.py, tests |
| V1-04 | LPIPS model absent fallback | 1h | cinesort/domain/perceptual/lpips_compare.py |
| V1-05 | Tests E2E sélecteurs cassés | 4h | tests/e2e/test_02_navigation.py, test_12_errors.py |
| V1-06 | PyInstaller hidden imports perceptual | 1h | CineSort.spec |

**Critère de validation Vague 1** :
- Tous tests Python passent
- Build .exe < 60 MB et démarre sans erreur
- Tests E2E Playwright dashboard passent (au moins 100/121)
- Aucune CVE critique restante (pip-audit clean)

---

### VAGUE 2 — UX/A11y polish (~1 sem → ~2j parallèle)

**11 missions indépendantes + 1 validator**

| ID | Mission | Effort | Fichiers |
|---|---|---|---|
| V2-01 | Race conditions UI qij.js (3 fixes) | 4h | web/dashboard/views/qij.js |
| V2-02 | XSS hardening (grep + escape) | 30min | qij.js + autres views |
| V2-03 | Régression table runs perd tri | 1j | qij.js Journal section |
| V2-04 | Cache get_settings boot | 4h | web/dashboard/app.js |
| V2-05 | Memory leaks (5 fixes) | 1j | notification-center.js, journal-polling.js, router |
| V2-06 | WCAG 2.2 AA (focus trap, aria-live, arrow keys) | 2j | modal.js, top-bar-v5.js, table.js |
| V2-07 | font-display:swap | 5min | dashboard/styles.css |
| V2-08 | CSP sans unsafe-inline | 1h | rest_server.py + tests E2E |
| V2-09 | OpenLogsFolder REST exposé | 5min | rest_server.py |
| V2-10 | PRAGMA optimize shutdown | 30min | sqlite_store.py |
| V2-11 | PRAGMA integrity_check boot | 1h | sqlite_store.py + UI notif |

**Critère de validation Vague 2** :
- Lighthouse a11y ≥ 95, BP = 100
- Test axe-core 0 violations
- Smoke test 4 thèmes × 7 vues (screenshots)
- Memory profiling : pas de leak > 1 MB sur 30 min de session

---

### VAGUE 3 — Polish micro + Documentation (~1 sem → ~3j parallèle)

**Polish (4 missions) + Doc (8 missions) = 12 agents en parallèle**

#### Polish
| ID | Mission | Effort |
|---|---|---|
| V3-01 | CSS legacy cleanup ~80 KB | 1j |
| V3-02 | Manrope font dédup | 1h |
| V3-03 | .clickable-row CSS | 5min |
| V3-04 | Logging run_id transversal + request_id | 2j |

#### Documentation
| ID | Mission | Effort |
|---|---|---|
| V3-05 | CLAUDE.md mise à jour (98 endpoints, 23 fichiers >500L, sections v7.7) | 4h |
| V3-06 | docs/api/ENDPOINTS.md (génération auto via inspect.signature) | 1.5j |
| V3-07 | docs/MANUAL.md user manual (tutoriel + glossaire + FAQ 40+) | 2j |
| V3-08 | docs/TROUBLESHOOTING.md (probe, APIs, perf, undo, network) | 1j |
| V3-09 | docs/architecture.mmd (Mermaid diagram modules + workflows) | 4h |
| V3-10 | .env.example + settings.json.example | 30min |
| V3-11 | BILAN_CORRECTIONS.md cleanup (archive R1-R2) | 1h |
| V3-12 | RELEASE.md process (version bump, tags, build, GitHub) | 30min |

**Critère de validation Vague 3** :
- CLAUDE.md cohérent avec réalité code (vérification automatique : grep nb endpoints, lignes, etc.)
- Doc lisible (relecture par agent dédié)
- Aucun lien mort dans la doc
- README.md liste tous les nouveaux docs

---

### VAGUE 4 — Refactor code (~1.5 sem → ~5j SÉQUENTIEL)

**⚠ NON parallélisable** — touche cœur métier, risque régression élevé. 1 mission à la fois avec tests intégration complets entre chaque.

| ID | Mission | Effort | Notes |
|---|---|---|---|
| V4-01 | Refactor `_plan_item` 565L → 12 helpers | 3j | plan_support.py, garder API publique |
| V4-02 | Refactor `compute_quality_score` 369L | 1.5j | quality_score.py, garder API |
| V4-03 | Refactor `plan_library` 347L | 1j | scan/filter/dedup en 3 fonctions |
| V4-04 | ~200 docstrings publiques | 4h | apply_audit, apply_core helpers |
| V4-05 | Composite Score V2 toggle | 3j | Setting `composite_score_version` (1\|2), UI toggle |

**Critère de validation Vague 4** :
- 100% tests existants passent (3550+)
- Coverage stable ou en hausse
- Smoke scan complet 100 films mock = résultat identique avant/après
- CLAUDE.md "0 fonction > 100L" devient vrai

---

### VAGUE 5 — Stress / scale (~1 sem → ~3j parallèle)

**4 missions indépendantes**

| ID | Mission | Effort |
|---|---|---|
| V5-01 | UI virtualisation library.js (windowing 30-50 rows) | 3j |
| V5-02 | Perceptual parallelism multiprocessing.Pool | 2j |
| V5-03 | TMDb cache TTL + purge auto boot | 1j |
| V5-04 | Probe parallélisation 10k (ThreadPoolExecutor) | 2j |

**Critère de validation Vague 5** :
- Test stress 10k films simulés : UI library scroll fluide (60fps)
- Probe 10k films < 2h (vs 7.6h actuel)
- Perceptual 10k films < 2j (vs 14j mono-thread)

---

### VAGUE 6 — i18n EN (~2 sem → ~1 sem parallèle)

**6 missions**

| ID | Mission | Effort |
|---|---|---|
| V6-01 | Infrastructure i18n.js + i18n_messages.py + locales/ | 2j |
| V6-02 | Extraction frontend ~250 strings → locales/fr.json | 4j |
| V6-03 | Extraction backend ~45 messages → locales/ | 2j |
| V6-04 | Date/number formatters (Intl.DateTimeFormat) | 1j |
| V6-05 | Glossaire + Help EN (30 termes + 15 FAQ) | 2j |
| V6-06 | Tests round-trip fr→en→fr | 1j |

**Critère de validation Vague 6** :
- Setting `locale` (fr|en) fonctionne, switch live
- Tests assertent sur clés `t("key")` pas strings FR
- Coverage round-trip 100%
- Aucune string FR oubliée (script de détection)

---

### VAGUE 7 — Validation finale + release (~1j)

- [ ] Build `.exe` final + test sur Windows 11 clean (machine vierge si possible)
- [ ] Suite tests complète (3550+ unit + 121 E2E + 28 a11y + perf benchmarks)
- [ ] Lighthouse score (perf >70, a11y >95, BP 100, SEO >90)
- [ ] Smoke test exhaustif : 4 thèmes × 7 vues v5 + 4 vues v4 = 44 captures
- [ ] Stress test 10k films de bout en bout (scan→review→apply→undo)
- [ ] Tag `v7.7.0` + GitHub Release notes
- [ ] Update CHANGELOG.md + CLAUDE.md note finale (9.9/10 → 10/10)
- [ ] Build artefact final dans `dist/CineSort.exe` + ZIP
- [ ] Mise à jour `BILAN_CORRECTIONS.md` section "Opération Polish Total v7.7.0"

**Critère de validation Vague 7** :
- 0 régression imputable
- Build .exe stable < 60 MB
- App utilisable de A à Z sans erreur (parcours utilisateur complet)

---

## Vérification croisée (continue, par agent validator)

À chaque commit :
- ✅ `git diff` analysé pour cohérence avec le finding source
- ✅ `python -m ruff check .` propre
- ✅ Tests ciblés du module touché passent
- ✅ Pas de régression sur tests intégration adjacent

À chaque fin de mission :
- ✅ Suite tests complète passe
- ✅ Coverage ne baisse pas
- ✅ CLAUDE.md cohérent (si touché)

À chaque fin de vague :
- ✅ Build .exe complet
- ✅ Smoke test Playwright dashboard
- ✅ Tag intermédiaire + récap utilisateur
- ✅ Question : "On continue Vague N+1 ?"

---

## Fichiers de tracking pendant l'opération

| Fichier | Usage |
|---|---|
| `OPERATION_POLISH_V7_7_0.md` | CE document — règles + plan |
| `OPERATION_POLISH_V7_7_0_BASELINE.md` | Snapshot état initial (créé Vague 0) |
| `OPERATION_POLISH_V7_7_0_PROGRESS.md` | État vivant : vagues complétées, missions en cours, blocages |
| `PLAN_RESTE_A_FAIRE.md` | Source findings (existant) |
| `AUDIT_TRACKING.md` | Registry findings par round (existant) |
| `BILAN_CORRECTIONS.md` | Historique fixes (à enrichir Vague 7) |

---

## En cas de blocage

1. **Signalement immédiat** dans `OPERATION_POLISH_V7_7_0_PROGRESS.md`
2. **Ne pas forcer** un fix qui casse autre chose
3. **Demander confirmation utilisateur** avant tout breaking change
4. **Rollback propre** via tag `backup-before-vague-N` si vague entière compromise
5. **Documenter le blocage** pour reprise ultérieure

---

## Estimation totale

- **Sans i18n** : ~12 jours en parallèle
- **Avec i18n (cas actuel)** : ~19 jours en parallèle
- **Séquentiel pur** : ~7 semaines (équivalent ~35 jours homme)

---

## Statut courant

- **Vague actuelle** : 0 (préparation)
- **Vagues complétées** : aucune
- **Build référence** : `dist/CineSort.exe` v7.6.0-dev 50.07 MB (4 mai 2026 00:23)
- **Note de départ** : 9.2/10
- **Note cible** : 9.9-10/10
