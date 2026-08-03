# SYNTHÈSE VAGUE LOT C-FIX — les 17 findings runtime corrigés — 2026-07-08

> Branche `verif/totale-2026-07`, 16 commits (`fb9a880..` + 2 R2). **GATE FINAL : les 6 sweeps
> en exécution GROUPÉE = 45/45 verts, 0 xfail, en 3 min 45** — tous les xfails dynamiques
> qui documentaient les findings sont devenus des PASS naturels.

## Vague initiale (8 commits)

| Fix | Commit | Contenu |
|---|---|---|
| **LOTC-F1 ★racine** | `fb9a880` | `_dedupExec` : fetch partagé sur controller dédié + refcount + vue par appelant — l'abort d'un appelant ne tue plus la vue d'un autre. Guérit : accueil vide au boot, historique squelette-pour-toujours (2 échecs baseline), qualité gelée, écran mort traitement→doublons, bannière paramètres |
| Z1/Z2/Z3/M4 | `005865c` | Modale danger 10100 (au sommet, était sous la fiche film), backdrop drawer sous le panneau, drawer aide 1500, rail 28px du panneau replié + échelle z-index documentée |
| B1 | `f417f2c` | `_resolve_run_id` skippe les runs utilitaires (bulk Re-scanner ne vide plus la bibliothèque) + 9 tests SQLite |
| C1+M3 | `830e7e5` | Handlers inline (CSP) → listeners délégués capture (fallbacks posters vivants) ; `_dominantTier` → '—' à 0 |
| R1/M2/B3/M5 | `b43a216` | Router : query strippée + `opts.query` ; filter_hint lisible ; reveal token = vrai Bearer ; bruit BOOT-DEBUG |
| B2/M1/T1 | `99a31a7` | Review /processing peuplée (rows via get_plan) ; version About ; tiers E2E canoniques |

## Revue adversaire ROUND 1 (15 findings → 8 confirmés / 5 réfutés / 2 nuancés → 6 commits)

- **F1-bis** `2ab9959` : court-circuit signal déjà aborté + détachement des listeners au settle.
- **B1-bis** `270dfcc` : les 2 résolveurs jumeaux (quality_audit, library_audit) délèguent au résolveur corrigé.
- **B2-bis** `2c421f1` : capture `reviewRunId` (TOCTOU qui pouvait neutraliser la garde R2).
- **R1-bis** `d0c6471` : `opts.query.filter` consommé (chips) au lieu d'être perdu silencieusement.
- **Z3-bis** `588ddb5` : toasts 1600 / palette 1700 (masqués par tout drawer ouvert à 800/900).
- **Isolation** `954ab4e` : `e2e_server` scope module (10 échecs groupés = mutations partagées).

## Revue adversaire ROUND 2 (3 findings → 2 confirmés/nuancés → 2 commits)

- **R2-filtres** : le mapping R1-bis ratait les liens de l'app elle-même (`tier_*`, `decade_*`,
  `low_confidence` émis par Qualité/accueil → toast « non applicable » sur des liens first-party !).
  → consommation native (tierFilter, advanced.year_min/max, confidence_max).
- **R2-conftest** : le scope module × `pytest_plugins` dotted (plugin GLOBAL) faisait booter un
  serveur REST à ~100 modules unitaires étrangers → résolution paresseuse via `request.fixturenames`.

**Score des revues sur cette vague : rounds 1+2 = 8 vrais défauts corrigés DANS les fixes,
dont 2 dans les fixes du round 1.** La règle des 2-3 rounds attrape du réel à chaque étage,
sur chaque vague, depuis le Lot E.

## État final

- Gate groupé : **45/45 verts, 0 xfail** (et l'exécution groupée des sweeps est à nouveau possible).
- Contrats CI : 25+9 tests verts ; ruff propre sur les fichiers touchés ; node --check ×12.
- Registre SYNTHESE_LOT_C.md : les 17 findings ont tous un fix commité ; restent en réserve
  documentée : `film_support.py:28` (copie du pattern resolveur, lot dédié), câblage complet
  `omdb_disagree`/`codec_obsolete` (chips backend à créer), et le point pré-existant toast
  (1600) < fiche film (10001).

## Prochaines étapes de la campagne (PLAN_VERIF_TOTALE.md)

Lot D (Phase 4 : chaînes métier bout-en-bout sur bibliothèque virtuelle — scan→plan→apply→undo,
doublons, exports) puis Phase 5 principale (R8-085, DPAPI-NG, rest_api_token, purge JS mort,
i18n, settings fantômes, wip/b4) et Phase 6 UX/a11y, Phase 7 clôture (CLAUDE.md, tag).
