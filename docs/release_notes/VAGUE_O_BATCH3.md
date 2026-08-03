# Vague O batch 3 - VO-C waterfall UI

## Resume technique

Troisieme batch de la Vague O : ajout d'un inspecteur waterfall scoring inspire
Radarr Custom Formats, qui expose le detail additif du `quality_score` (baseline
profil + categories video/audio/extras + custom_rules + suggestions/narrative)
dans la dashboard. 4 phases : 1 backend (helper pur `compose_score_explanation`
+ payload row enrichi) + 3 frontend (composant `score-v2` etendu, panneaux
inspecteur `lib-validation` et `lib-verification`). Zero regression sur le
`perceptual_score` (memoire user respectee : `perceptual_reports !=
quality_reports`). Aucun bump VERSION, aucune nouvelle dependance.

## Changements par item

### VO-C-BACKEND : helper `_build_row_payload` waterfall

- **VO-C-BACKEND** (`78a7298`) - `feat(vo-c-backend)`: ajoute
  `compose_score_explanation(quality_report, custom_rules_result)` dans
  `cinesort/ui/api/dashboard_support.py`, helper PURE qui fusionne les sorties
  de `build_rich_explanation` et `apply_custom_rules` en une structure
  waterfall consommable par le frontend (cle `score_explanation_full` du row
  payload). Categories serialisees en `list[{name,label,...}]` (vs dict en
  entree), avec entree synthetique `custom_rules` ajoutee SI
  `applied_rule_ids` non vide. Baseline/suggestions/narrative/top_positive/
  top_negative en passthrough. Backward compat : `None` si pas d'explanation,
  le frontend gere l'absence. Pure function : ne mute aucune source (verifie
  par tests). N'affecte PAS `perceptual_reports` (memoire user respectee).

### VO-C-FRONTEND-3 : composant `score-v2` waterfall

- **VO-C-FRONTEND-3** (`86ead12`) - `feat(vo-c-frontend-3)`: etend
  `score-v2.js::renderScoreV2Container` avec les opts
  `scoreExplanationFull`/`profileRulesById`/`showWaterfall`. Nouveau module
  `web/dashboard/core/score-helpers.js` (~225 LOC, 5 helpers reutilisables :
  `renderScoreWaterfallHtml`, `renderCustomFormatsImpact`,
  `renderBaselineGauge`, `renderSuggestionsList`,
  `renderQualityWaterfallSection` wrapper). CSS prefix `.score-waterfall-*`
  EXCLUSIF (memoire `feedback_js_release_checks`) ajoute dans `styles.css`
  apres le bloc `.score-v2-compare-*`. Tier colors via `var(--tier-*)`
  INVARIANTES (memoire `feedback_cinesort_v76_ui`). Backward compat preservee :
  sans opt -> rien ne change.

### VO-C-FRONTEND-2 : inspecteur lib-verification

- **VO-C-FRONTEND-2** (`6dbacca`) - `feat(vo-c-frontend-2)`: ajoute le rendu du
  waterfall scoring dans la modale "Pourquoi ce cas ?" (`_showWhyModal`) de
  l'inspecteur lib-verification. Pattern identique a lib-validation
  (VO-C-FRONTEND-1) mais module distinct conformement aux memoires user (pas
  de classe CSS partagee entre composants DOM differents). Helpers
  `_renderScoreWaterfall(row)` + `_renderCustomFormatsImpact(row)` retournent
  `""` si `score_explanation_full` absent (backend renvoie `None` si pas
  d'explanation, pas de regression sur les rows existantes).

### VO-C-FRONTEND-1 : inspecteur lib-validation

- **VO-C-FRONTEND-1** (`7a93fe3`) - `feat(vo-c-frontend-1)`: ajoute un panneau
  "Breakdown du score" type Radarr dans l'inspecteur de film
  (`lib-validation _showInspector`) qui consomme la cle
  `score_explanation_full` fournie par VO-C-BACKEND. Seuils du profil
  (Platinum/Gold/Silver/Bronze) en baseline, une ligne par categorie
  (contribution coloree +vert/-rouge, subscore, poids, count bonus/penalites),
  categorie synthetique `custom_rules` avec badges des regles appliquees,
  ligne total (score final -> tier lu depuis `row.score`/`row.quality_tier`),
  distance au prochain tier si calculee. Backward compat : `""` si
  `score_explanation_full` absent.

## Tests

- 14 tests unitaires PASS sur `test_compose_score_explanation_v77.py`
  (backward compat None inputs, fusion correcte, override de priorite,
  absence/presence de `custom_rules`, purete).
- `node --check` OK sur `score-helpers.js` + `score-v2.js` + les vues
  `lib-validation.js` / `lib-verification.js`.
- Aucune regression sur `perceptual-modal._renderBreakdownSection` (memoire
  `feedback_cinesort_design` : PerceptualScore V2 reste isole, le waterfall
  concerne UNIQUEMENT le `quality_score`).
- Backward compat verifiee : rows sans `score_explanation_full` -> rendu
  identique a avant le batch.

## 🎁 Pour toi

Tu peux maintenant voir le detail du score de chaque film: les categories de
bonus/malus (video, audio, extras), les regles custom appliquees, et comment
on arrive au score final. Cliquer sur un film dans la bibliotheque ouvre
l'inspecteur enrichi (inspire Radarr Custom Formats).

## Notes

- Pas de bump VERSION (decision differee, coherent avec Vague N + VO batches
  1 et 2).
- Tag local uniquement : `vague-o-batch3` (pas de push remote).
- Commits inclus : `78a7298`, `86ead12`, `6dbacca`, `7a93fe3`.
- `perceptual_reports` INTOUCHE (memoire
  `feedback_cinesort_design` : separation stricte avec `quality_reports`).
