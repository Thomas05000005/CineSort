# Vague P batch 2 - VP-B Hierarchie qualite tier-trumps & scoring multi-axes (inspire TRaSH/Radarr)

## Resume technique

Deuxieme batch de la Vague P : implementation du sub-lot **VP-B** (item
`VP-2-QUALITY-TIER-HIERARCHY`) introduisant une hierarchie qualite "Quality
Trumps All" inspiree de **TRaSH-Guides / Radarr 2026**. Le scoring multi-axes
se greffe **AVANT** `_cap_tier` securite pour preserver l'autorite finale
FAILED/CAM, et est strictement **OPT-IN** (default OFF) pour eviter toute
redistribution silencieuse sur les 853 films de la biblio existante (memo fix
#4 ROADMAP_VAGUE_P). 5 dimensions canoniques reorderables : `resolution >
video_codec > hdr > audio > release_group`. Floors TRaSH 2026 par defaut :
2160p_probe -> Gold, Dolby Vision -> Gold, HDR10+ -> Silver, TrueHD Atmos ->
Gold. Ceilings : 720p -> Silver, SD -> Bronze.

## Changements par item

### VP-B : hierarchie qualite tier-trumps multi-axes

- **VP-B-2** (`01f239e`) - `feat(VP-B-2)`: implementation complete du tier
  hierarchy "Quality Trumps All".

  Backend (`cinesort/domain`) :
  - `tiers_helpers.apply_tier_hierarchy(tier_pondere, dimensions,
    hierarchy_config)` : nouvelle fonction qui applique floors/ceilings dans
    l'ordre user-configurable.
  - `tiers_helpers.default_hierarchy_config()` : config par defaut avec
    `enabled=False` (AC-1 strict).
  - `tiers_helpers.normalize_hierarchy_config()` : backward compat pour les
    profils legacy v1.5.7 sans cle `tier_hierarchy` -> default OFF normalise.
  - `quality_score` : `tier_hierarchy` ajoute a `default_quality_profile()` +
    `validate_quality_profile()` + appele dans `compute_quality_score` apres
    `custom_rules` et **AVANT** `_cap_tier` securite (AC-2).
  - 5 dimensions canoniques : `resolution`, `video_codec`, `hdr`, `audio`,
    `release_group` (reorderable par l'utilisateur).
  - Floors TRaSH 2026 par defaut : `2160p_probe -> Gold`,
    `Dolby Vision -> Gold`, `HDR10+ -> Silver`, `TrueHD Atmos -> Gold`.
  - Ceilings : `720p -> Silver`, `SD -> Bronze`.

  UI (`web/dashboard/views/parametres.js`) :
  - Section "Hierarchie qualite (TRaSH 2026)" sous "Profils Qualite" : toggle
    `enabled` + liste reordonnable des 5 dimensions (boutons haut/bas).
  - Avertissement explicite : "Activer peut redistribuer 30-40% de votre
    bibliotheque - utilisez la simulation avant d'activer".
  - `node --check parametres.js` OK.

  PAS de migration SQL (profile_json suffit, conforme brief). PAS d'ALTER.

## Tests

- `tests/test_tier_hierarchy_floors.py` : 25 tests unitaires couvrant
  floors/ceilings/order/legacy/unknown dimensions.
- `tests/test_quality_score_hierarchy_integration.py` : 9 tests d'integration
  validant les ACs (AC-1 default OFF, AC-2 cap_tier autorite finale, AC-3
  perceptual non touche, AC-4 labels canoniques pour CSS tokens).
- `tests/test_tier_hierarchy_profile_migration.py` : 16 tests backward compat
  pour profils legacy v1.5.7 sans cle `tier_hierarchy` -> default OFF
  normalise.
- **Total : 50 nouveaux tests, 0 regression.**

Acceptance criteria (5/5) :

- AC-1 OK : default OFF, scoring V1 inchange si toggle non active (memo fix #4
  ROADMAP_VAGUE_P respecte, 853 films biblio non redistribues silencieusement).
- AC-2 OK : `_cap_tier` securite (FAILED/CAM) reste autorite finale apres
  hierarchy.
- AC-3 OK : `composite_score_v2` perceptual NON modifie (memo
  `perceptual_reports != quality_reports` respecte).
- AC-4 OK : tier colors hex INVARIANTES (`tokens.css` NON touche, memo
  `feedback_cinesort_v76_ui` "tier colors invariantes" respecte).
- AC-5 OK : import-linter green sur les nouvelles fonctions domain (aucune
  dependance ajoutee vers app/infra/ui).

## 🎁 Pour toi

CineSort sait maintenant noter tes films comme le font **TRaSH-Guides et
Radarr** : avec une vraie hierarchie qualite ou certains criteres "ecrasent"
les autres. Concretement, un film en **4K HDR10+ Dolby Vision** ne pourra
plus se faire releguer au rang Bronze juste parce que le release group est
inconnu, et un fichier en 720p ne pourra plus grimper accidentellement
au-dessus du tier Silver. Tu choisis l'ordre d'importance des criteres
(resolution > codec > HDR > audio > equipe de release) et CineSort fait le
reste.

**Important** : par defaut, c'est **OFF** - rien ne change pour les 853 films
deja dans ta biblio. Tu actives le toggle dans Parametres > Profils Qualite
seulement quand tu veux essayer. Et comme indique dans l'avertissement,
l'activer peut redistribuer 30 a 40% de ta biblio : passe d'abord par la
simulation pour voir ce que ca donne avant de valider. Les films en
**FAILED/CAM** restent toujours au plus bas, peu importe les autres criteres :
la securite reste prioritaire.

## Notes

- Pas de bump VERSION (decision differee, coherent avec les batches Vague
  N/O/P-1).
- Tag local uniquement : `vague-p-batch2` (pas de push remote).
- Commits inclus : `01f239e`.
- Suite Vague P : sub-lots VP-C+ (verrous, mini-recovery) a venir.
