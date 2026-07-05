# Audit complet par modules via Claude Code Action

## Objectif

Auditer progressivement chaque module de CineSort avec Claude. Pour chaque item, mentionner `@claude` avec la mission specifique. Cocher la case quand la PR est mergee.

## Mode de fonctionnement

**Niveau d'agressivite par defaut : MODERE.**
- Claude propose les fixes evidents (bugs latents, simplifications mineures)
- Si Claude juge qu'un refactor profond est necessaire, il ouvre une PR distincte
- Vous validez ou rejetez chaque PR
- Reviews et commentaires en francais

**Pour chaque mention `@claude`** : 
> Analyse ce module en mode MODERE. Cherche les bugs latents (try/except trop larges, comparaisons douteuses, None.method, races condition), les simplifications mineures, et les patterns dangereux. Si tu vois un besoin de refactor profond, ouvre une PR distincte clairement etiquetee `refactor:`. Reponds en francais.

## Domain (logique metier)

- [ ] `@claude` audit cinesort/domain/core.py (1480L)
- [ ] `@claude` audit cinesort/domain/quality_score.py (1439L, fonction 181L)
- [ ] `@claude` audit cinesort/domain/title_helpers.py
- [ ] `@claude` audit cinesort/domain/scan_helpers.py
- [ ] `@claude` audit cinesort/domain/duplicate_compare.py
- [ ] `@claude` audit cinesort/domain/librarian.py (fonction 178L)
- [ ] `@claude` audit cinesort/domain/naming.py
- [ ] `@claude` audit cinesort/domain/edition_helpers.py

## Perceptual engine

- [ ] `@claude` audit cinesort/domain/perceptual/composite_score.py
- [ ] `@claude` audit cinesort/domain/perceptual/composite_score_v2.py (761L)
- [ ] `@claude` audit cinesort/domain/perceptual/video_analysis.py (618L)
- [ ] `@claude` audit cinesort/domain/perceptual/audio_perceptual.py (700L, fonction 169L)
- [ ] `@claude` audit cinesort/domain/perceptual/grain_analysis.py (537L)
- [ ] `@claude` audit cinesort/domain/perceptual/hdr_analysis.py (655L)
- [ ] `@claude` audit cinesort/domain/perceptual/lpips_compare.py

## App (orchestration)

- [ ] `@claude` audit cinesort/app/plan_support.py (2050L)
- [ ] `@claude` audit ci