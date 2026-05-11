# V4-01 — Resultats stress test 10 000 films

**Date** : 2026-05-01
**Branche** : `test/stress-10k-films`
**Worktree** : `.claude/worktrees/test-stress-10k-films/`
**Machine de test** : Windows 11 (10.0.26200), 14 cores physiques / 20 logiques, 15.7 GB RAM
**Python** : 3.13 (`.venv313`)
**Schema DB** : user_version 20 (migrations 001 a 020 appliquees)

---

## Methodologie

Le test cible **la couche DB** (SQLiteStore + helpers `dashboard_support`), qui
est le seul facteur qui croit lineairement avec la taille de la bibliotheque.
Les endpoints UI (`get_dashboard`, `get_global_stats`, `get_library_filtered`)
agregent leurs donnees via ces operations DB ; ce sont donc les vrais goulots
d'etranglement reproductibles sans monter une `api` complete.

**Periphrastie ecartee** : on n'a PAS instancie le runner ni l'objet api
complet. Les endpoints UI ajoutent du JSON encoding et un peu de logique
Python par-dessus mais zero IO supplementaire.

**Perimetre genere** :
- 1 run (statut DONE, stats_json mock) ;
- 10 000 `quality_reports` (score v1 + tier + metrics realistes) ;
- 10 000 `perceptual_reports` (visual/audio + `global_score_v2` + `global_tier_v2` + warnings).

Distributions tier ponderees pour rester realistes (Premium 20%, Bon 40%,
Moyen 30%, Mauvais 10% cote v1 ; platinum 10% / gold 30% / silver 35% /
bronze 20% / reject 5% cote v2). Seed RNG fixee (`20260501`) -> reproductible.

---

## Generation donnees

| Metrique | Valeur |
|---|---|
| Films inseres | **10 000** |
| Duree generation | **311.6 s** (~32 ms/film, 2 inserts SQLite par film) |
| Taille DB SQLite finale | **17.74 MB** |

La generation utilise les vraies signatures (`upsert_quality_report`,
`upsert_perceptual_report`) sans batching. C'est lent par design, mais ca
garantit que la DB produite est strictement identique a celle d'un vrai run
de scoring sur 10k films. C'est de la donnee setup, pas un signal perf.

---

## Performance — operations DB cles (budget 2.0 s)

| Operation | Temps observe | Items retournes | Budget | Verdict |
|---|---:|---:|---:|:---:|
| `list_quality_reports(run_id)` | 181.7 ms | 10 000 | < 2 s | OK |
| `list_perceptual_reports(run_id)` | 216.8 ms | 10 000 | < 2 s | OK |
| `get_global_tier_distribution(limit_runs=20)` | 11.8 ms | 2 | < 2 s | OK |
| `get_global_tier_v2_distribution(run_ids)` | 10.5 ms | 6 | < 2 s | OK |
| `get_quality_counts_for_runs(run_ids)` | 14.2 ms | 1 | < 2 s | OK |
| `get_anomaly_counts_for_runs(run_ids)` | 5.2 ms | 0 (vide) | < 2 s | OK |
| `get_top_anomaly_codes(limit_runs=20, limit_codes=10)` | 5.1 ms | 0 (vide) | < 2 s | OK |
| `get_global_score_v2_trend(since_ts=0)` | 17.3 ms | 1 | < 2 s | OK |

## Performance — helpers `dashboard_support`

| Helper | Temps observe | Items | Budget | Verdict |
|---|---:|---:|---:|:---:|
| `_compute_v2_tier_distribution(store, run_ids)` | 14.9 ms | 4 | < 2 s | OK |
| `_compute_trend_30days(store)` | 14.8 ms | 31 (jours) | < 2 s | OK |
| `_compute_space_analysis(store, run_id)` | 196.4 ms | 9 (champs) | < 2 s | OK |

`_compute_space_analysis` parcourt les 10 000 quality_reports + decode
metrics_json par row : ~196 ms est attendu et confortable.

---

## RAM

Mesure : `tracemalloc` autour de **5 lectures consecutives** de
`list_quality_reports` + `list_perceptual_reports` (=> 100 000 dicts charges
au pic theorique).

| Metrique | Valeur | Budget | Verdict |
|---|---:|---:|:---:|
| Pic RAM trace | **94 MB** | < 1 GB | OK |

Ratio confortable : on est ~10x sous le budget. Une lecture unitaire pleine
(~30 MB de dicts decodes) reste largement absorbable cote UI.

---

## DB

| Metrique | Valeur | Budget | Verdict |
|---|---:|---:|:---:|
| Taille DB finale | **17.74 MB** | < 100 MB | OK |
| Ratio | **~1.8 KB / film** | — | OK |

Profile lineaire attendu : 1.8 KB/film -> 100k films = ~180 MB. Pas de
fragmentation visible (PRAGMA `journal_mode=WAL` actif via `connect_sqlite`).

---

## Resultats unittest

```
Ran 6 tests in 323.179s
OK
```

(323 s = 311 s de generation + 12 s de mesures). Aucun test n'echoue, aucun
budget n'est franchi.

---

## Verdict global

**READY POUR PUBLIC RELEASE sur la cible 10 000 films.**

Les marges sont confortables :
- Operations DB ~10x sous le budget perf (top : 217 ms vs 2 s) ;
- RAM ~10x sous le budget (94 MB vs 1 GB) ;
- DB ~5.6x sous le budget (17.7 MB vs 100 MB).

## Limites de ce test

1. **Pas d'IO disque metier** : on ne stresse pas `plan.jsonl` (souvent
   4-5 MB sur 10k films) ni le scan des dossiers. Les tests existants
   `tests/stress/large_volume_flow.py` couvrent deja le scan jusqu'a 5000
   dossiers synthetiques.
2. **Pas de mesure UI rendering** : le freeze potentiel cote pywebview /
   navigateur sur des tableaux de 10k rows reste a valider via test UI
   manuel ou Playwright. Cote backend, le payload est pret en < 220 ms.
3. **Anomalies tables vides** : `get_anomaly_counts_for_runs` et
   `get_top_anomaly_codes` retournent 0 car le generateur ne produit pas
   d'anomalies. A enrichir si on veut stresser le pipeline anomalies.
4. **Generation lente (311 s)** : on insere unitairement, sans transaction
   batchee. C'est volontaire (refleter les inserts unitaires du runner reel
   en mode worker), mais ca rend le test lourd a relancer (~5 min). Pour
   regenerer plus vite : passer a un INSERT batche / WAL bulk. Pas
   prioritaire — le test est opt-in (`CINESORT_STRESS=1`).

## Recommandations suite

- **Pas de blocage release.**
- Programmer un test UI Playwright qui charge le dashboard avec une DB pre-generee
  (reutilise `generate_demo_library.py`) pour valider la fluidite cote rendu.
- Si support futur 100k films devient un objectif : prevoir pagination cote
  `list_quality_reports` / `list_perceptual_reports` (actuellement tout-ou-rien).
