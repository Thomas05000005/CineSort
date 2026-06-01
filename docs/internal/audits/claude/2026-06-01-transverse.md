# Audit Claude — 2026-06-01 — Couche transverse (hebdomadaire)

**Modele** : Opus 4.7 (thinking max)
**Persona dominant** : FRONTEND + ARCHITECT
**Modules audites** : cinesort/domain/ + cinesort/infra/ + cinesort/ui/api/ + web/dashboard/ + invariants architecture
**Categories couvertes** : 8 (i18n), 10 (dette technique), 14 (error handling), 17 (invariants)
**Issues creees** : 5 nouvelles (#489, #491, #492, #493, #494)
**PRs creees** : cette PR (rapport + JSONL)

## Resume executif

Audit transverse hebdomadaire post-livraison **v1.5.2-beta** (PR #403 "5 vagues post-audit + tools UI + update flow", commit 0882c50). Focus principal sur les fichiers tout-juste-merges pour detecter les regressions introduites par cette vague de fonctionnalites.

**Sante architecturale stable** (verification manuelle, `lint-imports` non installe sur l'environnement) :

| Invariant | Etat | Verification |
|---|:-:|---|
| Contract 1 (domain pure) | OK | `grep -rnE "from cinesort\.(app\|infra\|ui)" cinesort/domain/` : 1 hit autorise (TYPE_CHECKING cinesort.domain.core -> tmdb_client), 1 hit dans une **docstring** (_runners.py:67) |
| Contract 2 (infra borne) | OK | 0 hit `cinesort.app` ou `cinesort.ui` depuis cinesort/infra/ |
| Contract 3 (app borne) | OK | 0 hit `cinesort.ui` depuis cinesort/app/ |
| Repository pattern (SQLiteStore) | OK | Pas de nouveau mixin dans le diff v1.5.2, 7+ repositories dans cinesort/infra/db/repositories/ |
| Facade pattern (CineSortApi) | DEGRADE | 5 methodes publiques residuelles documentees dans #483 (audit precedent) ; PR #403 a ajoute `force_refresh` a `get_update_info` via la facade `runtime_facade` (correct) |

**Cycle domain -> app** : aucune regression (issue #83 reste close).

## Findings detailes

### Categorie 14 — Error handling (2 findings, severite HAUT/MOYEN)

#### Finding ui01 — #489 — **HAUT** — check_updates_now masque les erreurs HTTP

`web/dashboard/views/parametres.js:1862-1899` — handler du nouveau bouton "Vérifier les mises à jour" (Vague E, PR #403). Le code teste `res.ok !== false` alors qu'`apiPost` retourne `{status, data}` (jamais de `ok` a la racine — `res.ok` est toujours `undefined`).

```javascript
const ok = !!(res && res.ok !== false);   // toujours truthy
if (!ok) { /* DEAD CODE */ }
if (data.update_available && data.latest_version) { /* ... */ }
else { resultEl.textContent = `✓ À jour (v${current_version})`; }   // execute meme en 401/500/timeout
```

UX cassee : un 401 ou 500 affiche "✓ À jour (v)" au lieu du message d'erreur reel. Pattern correct deja utilise plus haut dans le meme fichier (ligne 1832 : `res?.data?.ok`) — il suffit de l'aligner. Fix trivial, 5 lignes.

#### Finding ui03 — #492 — **MOYEN** — testConnection() fetch sans try/catch

`web/dashboard/core/api.js:282-313` — la fonction de login fait 2 `await fetch()` sans `try/catch`. Le `.catch()` ligne 310 ne couvre **que** `.json()`, pas `fetch()` lui-meme. Si le reseau coupe entre le POST auth (reussit) et le GET /api/health (echoue), `TypeError: Failed to fetch` propage tel quel au login flow, qui affiche un message d'erreur generique alors que **le token est valide**.

Existe depuis le refactor #84 (PR 10) — pas une regression v1.5.2 mais une fragilite ancienne mise en lumiere par la review focalisee sur le login flow.

### Categorie 10 — Dette technique (1 finding, severite MOYEN)

#### Finding ui02 — #491 — **MOYEN** — _UNDO_DEADLINE_SECONDS dupliquee

`cinesort/ui/api/apply_support.py:50` ET `cinesort/ui/api/dashboard_support.py:440` definissent la meme constante `24 * 3600`. Le commentaire dans apply_support l'explicite : "Constante en miroir... pour eviter une dependance circulaire entre modules ui.api."

Risque concret : si la policy passe a 12h ou 48h (compliance / beta extension), un seul site mis a jour cree une desynchronisation invisible (UI affiche countdown 24h pendant que backend rejette en 410 a 12h, ou inverse). 4 sites de consommation (2 dans chaque module). 

Fix propose : extraire dans `cinesort/domain/run_models.py` (couche domain, importable par app+ui sans violer les contracts) + test invariant qui assert l'egalite.

### Categorie 10 — Documentation (1 finding, severite FAIBLE)

#### Finding dom01 — #493 — **FAIBLE** — docstring detect_title_ambiguity ment

`cinesort/domain/title_ambiguity.py:68-91` — la docstring dit "Les candidats nfo et name sont ignores" mais le code accepte `nfo_tmdb` et `nfo_imdb` (sources NFO mais enrichies d'un ID TMDb/IMDb authoritative). Le code est **correct** ; la doc est obsolete ou inexacte depuis l'origine.

Risque : un auditeur futur applique "la doc" et casse la detection d'ambiguite. Coherent avec l'incident 2026-05-17 (#217) qui rappelle que code et doc divergents egarent les audits.

### Categorie 8 — i18n (1 finding, severite FAIBLE)

#### Finding i18n01 — #494 — **FAIBLE** — 8 messages JSON hardcodes en FR cote backend

Issue #405 couvre les ~35 strings v152 cote JS. Complement : 8 occurrences cote Python dans `cinesort/ui/api/*_support.py` qui renvoient des champs `message` en FR dur dans le payload JSON (dashboard_support.py:115,912 / perceptual_support.py:99,809,977 / reset_support.py:444 / cinesort_api.py:2014 / apply_support.py:1486). Le REST server peut etre consomme par un client non-fr ; passage par `t()` requis.

Pas urgent isolement ; peut etre groupe avec #405 dans un "sprint i18n" unique.

## Verification regle #217 (suppression code mort)

Aucune proposition de suppression dans ce run. Les 5 findings sont tous des modifications **non-destructives** : ajout de try/catch, refactor de check booleen, extraction de constante, reecriture de docstring, migration vers `t()`.

## Categories non couvertes ce run

Categories 1 (bugs Python latents), 2 (bugs domaine), 3 (perf), 4 (secu), 5 (concurrence), 6 (UI XSS/leaks), 7 (a11y), 9 (migrations DB), 11 (code mort), 12 (patterns Python), 13 (typing), 15 (logging), 16 (tests) : couvertes en surface par les 3 agents Explore (rapports inclus dans la conversation), mais aucun finding nouveau retenu apres dedup contre les ~50 issues ouvertes (#404-#485).

Les findings remontes par les agents qui doublonnent un issue existant :
- Agent domain "_is_scene_title est mort" -> deja #463
- Agent domain "lru_cache normalize_title" -> deja #480
- Agent domain "pick_best_candidate mute note" -> deja #450
- Agent infra "circuit breaker 5xx" -> deja #458
- Agent infra "isolation_level pas explicite" -> deja #428
- Agent infra "migration record commit transactionalite" -> intentionnel (cf docstring _record_migration), pas un bug

## Test plan

- Pas de code Python touche (uniquement docs et JSONL)
- Fichiers respectent la nomenclature existante (`YYYY-MM-DD-transverse.{md,jsonl}`)
- JSONL : chaque ligne est un JSON valide
- Branche `docs/audit-rapport-2026-06-01-transverse` cree, PR a ouvrir

## Suite

5 issues a trier par le mainteneur (#489 a #494). Fix le plus prioritaire : **#489** (UX cassee sur le bouton "Vérifier les mises à jour" introduit hier dans v1.5.2, regression a fix avant un eventuel v1.5.3).
