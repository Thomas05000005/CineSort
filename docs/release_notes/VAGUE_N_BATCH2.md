# Vague N batch 2 - VN-B reconcile scoring + VN-C confidence & bulk

## Resume technique

Deuxieme batch de la Vague N : reconciliation du scoring composite (V1 -> V2 unique source de
verite), unification des tiers Platinum/Gold/Silver/Bronze entre backend et UI, alignement des
seuils de confiance (CONF_HIGH=85, CONF_MED=60) cote Python et JS, et durcissement des
approbations bulk via `dangerConfirmModal` au-dela de 50 elements. 5 commits, aucune nouvelle
dependance, aucun bump VERSION. Rattrapage des notes redigees apres pose manuelle du tag
`vague-n-batch2` par le parent (workflow precedent tronque avant l'etape notes).

## Changements par item

### VN-B : reconcile scoring composite + tiers

- **VN-B.1** (`75e6f5e`) - `refactor(vn-b1)`: bascule `composite_score` V1 -> V2 comme unique
  source de verite. Suppression de la divergence V1/V2 qui produisait des scores incoherents
  selon le chemin d'appel (`perceptual_support` vs `settings_support`).
- **VN-B.2** (`2de1f9b`) - `refactor(vn-b2)`: reconciliation des tiers V1/V2 dans
  `tiers_helpers.py` + ajout d'un champ `display_tier` explicite. Les composants UI
  (`perceptual-modal.js`, `bibliotheque.js`) consomment desormais `display_tier` au lieu de
  recalculer leur propre tier. Alias legacy preserve via tests dedies
  (`test_tiers_helpers_legacy_alias_v77.py`).

### VN-C : seuils de confiance + state JS + bulk

- **VN-C.1** (`603e27b`) - `refactor(vn-c1)`: creation de `confidence_thresholds.py` avec
  constantes `CONF_HIGH=85` / `CONF_MED=60` exposees cote backend (`facades/settings_facade.py`,
  `core.py`, `quality_score.py`) et cote frontend (`web/dashboard/core/api.js`,
  `views/traitement.js`, `views/library/lib-validation.js`). Fin du desalignement
  Python (85/60) vs JS (80/50).
- **VN-C.2** (`d0af577`) - `fix(vn-c2)`: remplace l'approche DOM-as-truth de `_buildDecisions`
  par une `Map` JS interne. Corrige la perte de decisions utilisateur quand un filtre cache
  les lignes correspondantes dans le tableau.
- **VN-C.3** (`333e2ea`) - `fix(vn-c3)`: bulk-approve restreint aux items `CONF_HIGH` par defaut,
  et passage obligatoire par `dangerConfirmModal` quand la selection depasse 50 elements
  (memoire feedback_cinesort_actions_dangereuses).

## Tests

- 5 commits avec suites de tests vertes (`test_composite_score_toggle.py`,
  `test_library_support_display_tier_vnb2.py`, `test_tiers_helpers_legacy_alias_v77.py`,
  `test_core_heuristics.py`).
- Verification manuelle des seuils CONF_HIGH/CONF_MED via le mock pywebview
  (`tests/manual/pywebview_api_mock.js`).
- Smoke test bulk-approve > 50 elements : modale `dangerConfirmModal` s'affiche avec liste +
  consequence + delai 3s, conforme aux regles d'actions dangereuses.

## 🎁 Pour toi

Le scoring est maintenant plus coherent : un seul algorithme (au lieu de 2 en parallele qui se
contredisaient), les tiers Platinum/Gold/Silver/Bronze affiches de maniere uniforme partout, et
les seuils de confiance alignes (85% = haute, 60% = moyenne). Les approbations groupees
protegees par confirmation au-dela de 50 films.

## Notes

- Pas de bump VERSION (decision differee a fin Vague Q, coherent avec batch 1).
- Tag local uniquement : `vague-n-batch2` (pose manuellement par le parent, pas de push remote).
- Commits inclus : `75e6f5e`, `2de1f9b`, `603e27b`, `d0af577`, `333e2ea`.
- Notes redigees en rattrapage : le workflow batch 2 precedent a ete tronque avant l'etape
  TagRelease/notes.
