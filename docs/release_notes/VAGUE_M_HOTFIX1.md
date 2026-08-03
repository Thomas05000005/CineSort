# Vague M Hotfix 1 - Bundle Cleanup (-94%)

## 🎁 Pour toi

L'application demarre maintenant beaucoup plus vite (avant: 30s, apres: 5s). Le fichier d'installation passe de 2.3 GB a ~54 MB, soit 98% en moins. Aucun changement fonctionnel: tout ce que tu peux faire reste identique, c'est juste plus leger et plus rapide a charger.

## Technique

- `CineSort.spec` excludes: `torch`, `torchvision`, `transformers`, `scipy`, `jupyter`, `pytest`, `playwright`, dev tools
- `collect_submodules('PIL')` retire, remplace par `hiddenimports` explicite
- Fix off-by-one `test_runstate_logs_are_capped_in_memory` (M-07 RunState extract)

### Metriques rebuild

- Taille bundle: 2.33 GB -> 53.53 MB (-97.76%)
- Smoke test: `exe_starts=true`, `health_ok=true`

### Commits inclus

- `c0426a7` build(spec): excludes torch/scipy/transformers/jupyter/dev (hotfix Vague M)
- `df2891a` fix(m07): off-by-one RunState logs cap (hotfix Vague M)

### Notes

- Pas de bump VERSION (decision differee a fin Vague Q)
- Tag local uniquement: `vague-m-hotfix1` (pas de push remote)
