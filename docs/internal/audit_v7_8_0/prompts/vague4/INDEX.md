# Index Vague 4 — 8 missions validation finale (public release)

**Date** : 1er mai 2026 (après merge V3 réussi)
**Pré-requis** : Vague 3 mergée sur `audit_qa_v7_6_0_dev_20260428` ✅ (3643 tests OK, coverage 82.2%)
**Objectif** : valider et préparer le **public release GitHub** pour 2000 users francophones Windows en attente.

---

## ⚠️ LIRE EN PREMIER

- `audit/prompts/_WORKTREE_SETUP.md` — procédure worktree (chaque instance crée son worktree)
- Note architecture critique : pywebview affiche `web/dashboard/index.html` (PAS `web/index.html`). Toute modif UI doit cibler `web/dashboard/`.

---

## 📁 Comment utiliser

### Pour les missions 🟢 parallèles (5 missions)

1. Ouvre **5 instances** Claude Code (1 par mission)
2. Dans chaque instance : **"Lis et exécute le fichier `audit/prompts/vague4/<NUM>-XXX.md`"**
3. Chaque instance crée son worktree (étape 0 obligatoire)
4. Quand toutes mergées → passer aux hybrides + solo

### Pour les missions 🟡 hybrides (2 missions)

1. Lance l'instance Claude Code → elle prépare l'outil/script/guide
2. **Toi** exécutes le test physique (devices ou NVDA) en suivant le guide
3. Reporter résultats dans `audit/results/v4-XX-resultats.md`

### Pour la mission 🟠 solo+prep (1 mission)

1. Lance l'instance Claude Code → elle prépare le template annonce + canal feedback
2. **Toi** diffuses aux 20-50 early adopters
3. Suivre le feedback dans GitHub Discussions

---

## 🌊 8 missions Vague 4

### Catégorie A — Parallèles 🟢 (5 missions)

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V4-01 | [01-STRESS-TEST-10K-FILMS.md](01-STRESS-TEST-10K-FILMS.md) | `test/stress-10k-films` | `test-stress-10k-films` | 4-6h |
| V4-02 | [02-CONTRASTE-4-THEMES-WCAG.md](02-CONTRASTE-4-THEMES-WCAG.md) | `test/contrast-themes-wcag` | `test-contrast-themes-wcag` | 3-4h |
| V4-03 | [03-TEMPLATES-GITHUB-COMMUNITY.md](03-TEMPLATES-GITHUB-COMMUNITY.md) | `docs/github-community-templates` | `docs-github-community-templates` | 2-3h |
| V4-04 | [04-README-SCREENSHOTS-DEMO.md](04-README-SCREENSHOTS-DEMO.md) | `docs/readme-enriched-screenshots` | `docs-readme-enriched-screenshots` | 4-6h |
| V4-05 | [05-LIGHTHOUSE-SCORE.md](05-LIGHTHOUSE-SCORE.md) | `test/lighthouse-score` | `test-lighthouse-score` | 2-3h |

### Catégorie B — Hybrides 🟡 (2 missions, instance prépare + toi exécutes)

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V4-06 | [06-TEST-DEVICES-VIEWPORTS.md](06-TEST-DEVICES-VIEWPORTS.md) | `test/devices-multi-viewports` | `test-devices-multi-viewports` | 2h instance + 2-4h toi |
| V4-07 | [07-AUDIT-A11Y-NVDA.md](07-AUDIT-A11Y-NVDA.md) | `test/a11y-nvda-guide` | `test-a11y-nvda-guide` | 1-2h instance + 1-2h toi |

### Catégorie C — Solo+prep 🟠 (1 mission, instance prépare + toi diffuses)

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V4-08 | [08-BETA-PRIVEE-EARLY-ADOPTERS.md](08-BETA-PRIVEE-EARLY-ADOPTERS.md) | `docs/beta-private-onboarding` | `docs-beta-private-onboarding` | 2-3h instance + ton timing diffusion |

**Estimation parallèle (5 instances Catégorie A)** : ~1 jour
**Estimation Catégorie B (instances + toi)** : 1-2 jours
**Estimation Catégorie C (toi diffusion)** : 1-2 semaines (selon réactivité early adopters)

---

## 🎯 Statut V4

```
V4-01  [ ] Stress test 10 000 films (perf + crash + UI tient)
V4-02  [ ] Contraste 4 thèmes WCAG AA (4.5:1 chiffré)
V4-03  [ ] Templates GitHub Community (ISSUE/CONTRIBUTING/CODE_OF_CONDUCT)
V4-04  [ ] README enrichi + screenshots automatiques + démo GIF
V4-05  [ ] Lighthouse score dashboard
V4-06  [ ] Test devices multi-viewports (script + guide humain)
V4-07  [ ] Audit a11y NVDA (guide pas-à-pas pour test humain)
V4-08  [ ] Beta privée 20-50 early adopters (template + canal)
```

---

## 🚀 Quand toutes les V4 sont mergées + validées

Reviens vers l'orchestrateur avec :
- **« V4 done, on passe au public release »** → checklist final + tag v7.6.0 + création GitHub release

Ou en cas de findings critiques pendant V4 :
- **« V4-XX a trouvé un bug bloquant »** → on diagnose et on corrige avant release

---

## 📌 Au-delà de la V4

Une fois V4 livrée et validée :
- Tag `v7.6.0` officiel
- Création du dépôt GitHub public (ou conversion privé → public)
- GitHub Release avec changelog + binaire `.exe`
- Annonce sur les canaux choisis (HackerNews, Reddit r/Plex, r/jellyfin, r/selfhosted, Twitter/X, Discord communautés home media)
- Monitoring : issues GitHub, métriques téléchargements, retours beta
