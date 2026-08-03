# Vague N batch 3 - VN-D detection doublons multi-signal

## Resume technique

Troisieme batch de la Vague N : durcissement de la detection des doublons via 3 signaux
complementaires. Branchement effectif de Chromaprint (empreinte audio) + fuzzy matching titre
+ tolerance annee, exploitation des `alternative_titles` TMDb pour les cas cross-langue
(FR/EN), et ajout d'un filtre runtime HARD pour ecarter les candidats TMDb dont la duree
diverge de plus de 60 minutes sans flag "edition longue". 3 commits, aucune nouvelle dependance
externe (Chromaprint deja installe), aucun bump VERSION.

## Changements par item

### VN-D : detection doublons multi-signal

- **VN-D.1** (`7d532c3`) - `feat(vn-d1)`: nouveau module
  `cinesort/domain/duplicate_multi_signal.py` (642 lignes) branchant Chromaprint + fuzzy title
  matching + tolerance annee +/- 1. Resout les cas multi-rip (meme film, encodages differents)
  et cross-langue (Spirited Away vs Le Voyage de Chihiro) que la detection mono-signal
  precedente laissait passer. Suite de tests
  `test_duplicate_grouping_multisignal_v77.py` (462 lignes) couvre les scenarios reels.
- **VN-D.2** (`7016777`) - `feat(vn-d2)`: extension de `infra/tmdb_client.py` pour recuperer
  `alternative_titles` quand `sim_best < 0.85` lors du matching dans `app/plan_support.py`.
  Resout les noms de fichiers ambigus en utilisant les titres alternatifs TMDb (titre
  international, sortie regionale, etc.). Tests dedies
  `test_tmdb_alternative_titles_v77.py` (232 lignes).
- **VN-D.3** (`d42b768`) - `feat(vn-d3)`: nouveau module
  `cinesort/domain/runtime_hard_filter.py` (118 lignes) qui ecarte les candidats TMDb dont la
  duree differe de plus de 60 minutes du fichier scanne, sauf si un flag "edition longue" /
  "director's cut" est detecte. Integration dans `app/plan_support.py` (200 lignes
  modifiees). Tests `test_runtime_hard_filter_v77.py` (496 lignes) couvrent edge cases :
  edition longue, mini-series, films courts.

## Tests

- 3 nouvelles suites de tests vertes (1190 lignes de tests cumulees).
- Verification adversaire des cas cross-langue avec corpus reel (Studio Ghibli FR/EN/JP,
  trilogies majeures en VF/VOSTFR).
- Edge cases runtime HARD : "Director's Cut" / "Extended Edition" / "Theatrical" detectes
  correctement, pas de faux positifs sur les mini-series mal etiquetees.
- Pas de regression sur les suites existantes (composite_score, tiers_helpers,
  confidence_thresholds).

## 🎁 Pour toi

La detection des doublons est maintenant beaucoup plus intelligente : elle utilise les
empreintes audio (Chromaprint) en plus des metadonnees pour grouper les films multi-rip ou les
versions cross-langue (Spirited Away vs Le Voyage de Chihiro). Les noms de fichiers ambigus
sont resolus via les titres alternatifs TMDb. Enfin, un filtre de duree empeche d'identifier
un film de 90 minutes comme etant le meme qu'un film de 180 minutes (sauf edition longue).

## Notes

- Pas de bump VERSION (decision differee a fin Vague Q, coherent avec batches 1 et 2).
- Tag local uniquement : `vague-n-batch3` (pas de push remote).
- Commits inclus : `7d532c3`, `7016777`, `d42b768`.
