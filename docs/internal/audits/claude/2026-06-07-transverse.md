# Audit Claude - 2026-06-07 - Couche transverse

**Modele** : Opus 4.7 (thinking max)
**Persona dominant** : ARCHITECT (+ secondaire RELIABILITY)
**Couche** : transverse
**Niveau** : modere
**Open PRs** : true

## Resume executif

Bilan : **architecture en tres bonne sante**. Les 3 grands chantiers transverses
historiques (cycle `domain -> app`, mixins SQLite, duplication
desktop/dashboard) sont **resolus**. Reste un reliquat de dette technique
sur les fonctions > 100L, deja inventorie dans l'issue ouverte
**#215** et enrichi le 2026-05-31. Ce re-audit valide les chiffres
et complete l'inventaire avec trois fonctions non listees.

Aucune nouvelle issue critique ouverte (CAS B enrichissement de #215
plutot que CAS D doublon).

### Verifications cles

| Invariant | Etat | Source |
|---|---|---|
| Cycle `domain -> app` casse | ✅ | `.importlinter` + CI `lint-imports` (ci.yml:66) |
| Mixins SQLite migres -> Repositories | ✅ | 0 classe `_XxxMixin` (issue #85 close 2026-05-17) |
| Dashboard unifie (plus de duplication desktop/dashboard) | ✅ | `web/dashboard/` seul ; `web/components/` supprime (PR #217) |
| Facades pattern installe | ✅ | 6 facades / 147 methodes publiques |
| Methodes publiques residuelles sur CineSortApi | 5 (#483 ouvert) | `grep -nE "^    def [a-zA-Z]" cinesort_api.py` |

## Par categorie (focus transverse)

### Cat. 10 - Dette technique : fonctions > 100L

**Total actuel** : ~20 fonctions > 100L dans `cinesort/` (vs 14 le 2026-05-17
et ~18 au 2026-05-31). Stable +/- 2.

**Comparaison avec inventaire enrichi #215 (commentaire 2026-05-31)** :

| Fonction | Etat 2026-05-31 | Etat 2026-06-07 | Delta |
|---|---:|---:|---|
| `_execute_undo_ops` (apply_support:335) | 209L | 209L | stable |
| `_execute_apply` (apply_support:1101) | 244L | 244L | stable |
| `_cleanup_apply` (apply_support:1345) | 194L | **91L** | ⬇ **sorti du seuil** ✅ |
| `apply_changes` (apply_support:1774) | 155L | 153L | stable |
| `undo_selected_rows` (apply_support:670) | 138L | 138L | stable |
| `_summarize_apply` (apply_support:1436) | non liste | **145L** | ⬆ nouveau |
| `_build_dashboard_section` (dashboard_support:186) | 219L | 219L | stable |
| `get_global_stats` (dashboard_support:1241) | 175L | 175L | stable |
| `_compute_active_insights` (dashboard_support:1126) | non liste | **115L** | ⬆ nouveau |
| `apply_rows` (apply_core:887) | 114L | **324L** | ⬆ **croissance massive** ⚠ |
| `apply_single` (apply_core:1211) | 132L | 132L | stable |
| `apply_collection_item` (apply_core:1343) | 110L | 110L | stable |
| `move_file_with_collision_policy` (apply_core:470) | 154L | 154L | stable |
| `move_duplicate_losers_to_user_decided` (apply_core:723) | 121L | 121L | stable |
| `_classify_and_plan_folder` (plan_support:555) | 104L | 104L | stable |
| `_build_resolved_row` (plan_support:1359) | 122L | 122L | stable |

**Highlights** :
- ✅ **`_cleanup_apply`** : 194 -> 91L (-103L). Decoupage en cours, sorti du seuil.
- ⚠ **`apply_rows`** : 114 -> 324L (+210L). Croissance massive depuis V152
  (PR #403). A surveiller en priorite -- candidat tier 1 du plan multi-PR
  (split entre orchestration, batch processing, journal, finalize).
- ⬆ Deux fonctions nouvelles au-dessus du seuil : `_summarize_apply` (145L)
  et `_compute_active_insights` (115L). A integrer au plan #215.

**Action** : commentaire CAS B sur #215 (enrichissement, pas nouvelle issue).

### Cat. 10 - Imports lazy : reliquat 76 (vs 162 historique)

Compte actuel : **76 imports lazy** dans `cinesort/` (vs 162 au 2026-05-12,
45 au 2026-05-17, 30 implicite apres #238 close 2026-05-22).

Top 5 fichiers :

| # | Fichier | Nature des imports |
|---:|---|---|
| 7 | `cinesort/ui/api/perceptual_support.py` | `base64`, `io`, `PIL.Image`, `subprocess` (stdlib + lib optionnelle) |
| 6 | `cinesort/ui/api/cinesort_api.py` | `io`, `segno`, `webbrowser`, `datetime`, `subprocess`, `sys` (stdlib + segno optionnel) |
| 5 | `cinesort/ui/api/library_actions_support.py` | stdlib only |
| 4 | `cinesort/infra/single_instance.py` | platform-specific |
| 4 | `cinesort/domain/perceptual/lpips_compare.py` | numpy heavy |

**Verdict** : tous les imports lazy residuels sont **legitimes**
(stdlib, libs optionnelles, isolation subprocess, platform-conditional).
Aucun import `cinesort.*` lazy qui violerait l'invariant architectural.
Le contract import-linter `domain_pure` est respecte.

**Action** : pas de nouvelle issue. Le reliquat n'est pas un finding,
c'est l'etat-cible. Issue historique #83 reste fermee.

### Cat. 20 - Feature parity desktop <-> dashboard

**Verdict** : **non applicable**. Le dossier `web/components/` (anciens
composants desktop) a ete supprime (PR #217). Le dashboard mobile
(`web/dashboard/`) est devenu le frontend unique. Plus de divergence
possible.

Le prompt d'audit historique mentionne "22 composants JS dupliques" --
ce chiffre etait **stale** : issue #91 (resolu par suppression desktop)
et issue #217 (suppression effective).

**Action** : pas d'issue. Documentation dans le rapport pour calibrage
des prochains audits.

### Cat. 47 - Invariants architecture

Verification rapide des contracts `.importlinter` (3 contracts) :

| Contract | Source | Forbidden | Etat |
|---|---|---|---|
| `domain_pure` | `cinesort.domain` | `cinesort.app`, `cinesort.infra`, `cinesort.ui` | ✅ (1 exception TYPE_CHECKING documentee) |
| `infra_bounded` | `cinesort.infra` | `cinesort.app`, `cinesort.ui` | ✅ |
| `app_bounded` | `cinesort.app` | `cinesort.ui` | ✅ |

CI `lint-imports` configure dans `.github/workflows/ci.yml:66`. Toute
regression future est bloquee par CI.

### Cat. 47 - Repository pattern + facades

- **Mixins SQLite** : `grep -rn "class.*Mixin" cinesort/infra/db/` = 0.
  Migration B8 (issue #85) terminee. SQLiteStore = `_StoreBase` (601L)
  + 7 Repositories pour 3380L total.
- **Facades** : 6 facades (run, settings, quality, integrations,
  library, runtime) totalisant 147 methodes publiques (vs "5 facades /
  50 methodes" dans le contexte projet -- chiffres a rafraichir).
- **Methodes directes residuelles sur CineSortApi** : 5 (log, progress,
  log_api_exception, test_reset, open_path). Issue #483 ouverte pour
  la facade-isation finale.

## Statistiques

- **Modules audites** : 4 (apply_support, apply_core, plan_support,
  dashboard_support en profondeur ; cinesort_api + facades + db
  en spot-check)
- **Findings nouveaux confirmes** : 3 (fonctions > 100L non listees +
  croissance `apply_rows`)
- **Findings deja connus (dedup)** : 4 (cycle domain->app casse,
  mixins migres, dashboard unifie, facades en place)
- **Issues creees** : 0 nouvelles -- CAS B enrichissement de #215
- **PRs ouvertes** : 1 (cette PR rapport)
- **Self-critique** : 0 finding supprime (analyse focalisee CAS B)

## Notes de calibrage pour audits futurs

Le prompt `audit-prompt.md:1407` mentionne "49 fonctions > 100L",
"22 composants JS dupliques", "161 imports lazy". Ces chiffres sont
**obsoletes** :

- Fonctions > 100L : 20 actuel (vs 49 prompt). Reduction 60% en
  6 mois grace aux chantiers facade-isation + decoupage.
- Composants JS dupliques : 0 (vs 22 prompt). Resolu par suppression
  de `web/components/` (#217).
- Imports lazy : 76 actuel (vs 161 prompt). Reduction 53% grace
  a #83/#216/#238. Le reliquat est **legitime** (stdlib + libs
  optionnelles).

Suggestion : mettre a jour `.github/audit-prompt.md:1407` pour eviter
que les prochains audits considerent ces chiffres comme une cible
a atteindre alors qu'ils sont deja largement depasses.
