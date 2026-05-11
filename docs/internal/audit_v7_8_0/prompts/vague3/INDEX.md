# Index Vague 3 — 13 missions polish à lancer en parallèle

**Date** : 1er mai 2026 (après merge V2 réussi)
**Pré-requis** : Vague 2 mergée sur `audit_qa_v7_6_0_dev_20260428` ✅ (3525 tests OK, coverage 82.4%)

---

## ⚠️ LIRE EN PREMIER

- `audit/prompts/_WORKTREE_SETUP.md` — procédure worktree (chaque instance crée son worktree)
- `audit/report.md` — contexte audit complet
- Note architecture critique : **pywebview charge `web/dashboard/index.html`** en mode normal (PAS `web/index.html`). Toute modif UI doit cibler `web/dashboard/`. Voir `app.py:89-90, 400`.

---

## 📁 Comment utiliser

1. Ouvre **13 instances** Claude Code (1 par mission)
2. Dans chaque instance : **"Lis et exécute le fichier `audit/prompts/vague3/<NUM>-XXX.md`"**
3. Chaque instance crée son worktree (étape 0 obligatoire)
4. Quand toutes mergées → demande la Vague 4

---

## 🌊 13 missions Vague 3

### Catégorie A — UX / Découvrabilité (5 missions)

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V3-01 | [01-DECOUVRABILITE-INTEGRATIONS.md](01-DECOUVRABILITE-INTEGRATIONS.md) | `feat/sidebar-integrations-discovery` | `feat-sidebar-integrations-discovery` | 2-3h |
| V3-02 | [02-MODE-DEBUTANT-EXPERT.md](02-MODE-DEBUTANT-EXPERT.md) | `feat/expert-mode-toggle` | `feat-expert-mode-toggle` | 1 jour |
| V3-03 | [03-TOOLTIPS-GLOSSAIRE.md](03-TOOLTIPS-GLOSSAIRE.md) | `feat/tooltips-glossaire` | `feat-tooltips-glossaire` | 1 jour |
| V3-04 | [04-COMPTEURS-SIDEBAR.md](04-COMPTEURS-SIDEBAR.md) | `feat/sidebar-counters` | `feat-sidebar-counters` | 1 jour |
| V3-05 | [05-MODE-DEMO-WIZARD.md](05-MODE-DEMO-WIZARD.md) | `feat/demo-mode-wizard` | `feat-demo-mode-wizard` | 1 jour |

### Catégorie B — UX / Polish (4 missions)

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V3-06 | [06-DRAWER-MOBILE-INSPECTOR.md](06-DRAWER-MOBILE-INSPECTOR.md) | `feat/drawer-mobile-inspector` | `feat-drawer-mobile-inspector` | 4-6h |
| V3-07 | [07-FIX-FOCUS-VISIBLE-STUDIO.md](07-FIX-FOCUS-VISIBLE-STUDIO.md) | `fix/focus-visible-studio` | `fix-focus-visible-studio` | 2-3h |
| V3-08 | [08-TOOLTIPS-RACCOURCIS-PALETTE.md](08-TOOLTIPS-RACCOURCIS-PALETTE.md) | `feat/keyboard-shortcuts-tooltips` | `feat-keyboard-shortcuts-tooltips` | 4-6h |
| V3-09 | [09-RESET-ALL-DATA-UI.md](09-RESET-ALL-DATA-UI.md) | `feat/reset-all-data-ui` | `feat-reset-all-data-ui` | 2-3h |

### Catégorie C — Qualité / Perf / Backend (4 missions)

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V3-10 | [10-HARDCODES-COLORS-TO-TOKENS.md](10-HARDCODES-COLORS-TO-TOKENS.md) | `refactor/hardcodes-to-css-tokens` | `refactor-hardcodes-to-css-tokens` | 4-6h |
| V3-11 | [11-PRAGMA-MMAP-SIZE.md](11-PRAGMA-MMAP-SIZE.md) | `perf/sqlite-mmap-size` | `perf-sqlite-mmap-size` | 1-2h |
| V3-12 | [12-UPDATER-BOOT-HOOK-UI.md](12-UPDATER-BOOT-HOOK-UI.md) | `feat/updater-boot-hook-ui` | `feat-updater-boot-hook-ui` | 4-6h |
| V3-13 | [13-OUVRIR-LOGS-AIDE.md](13-OUVRIR-LOGS-AIDE.md) | `feat/help-open-logs-button` | `feat-help-open-logs-button` | 1-2h |

**Estimation parallèle (13 instances)** : ~1 jour (la plus longue est 1 jour)
**Estimation séquentielle** : ~10-12 jours

---

## ⚠ Coordinations à connaître

| Fichier touché par plusieurs missions | Missions | Risque |
|---|---|---|
| `web/dashboard/index.html` (sidebar) | V3-01 + V3-04 | Sections différentes (V3-01 = groupe Intégrations, V3-04 = badges sur autres items) |
| `web/dashboard/styles.css` | V3-07 + V3-10 | V3-07 ajoute outline focus, V3-10 remplace couleurs — sections différentes |
| `web/dashboard/app.js` | V3-01 + V3-02 + V3-04 + V3-12 | Sections init différentes |
| `cinesort/ui/api/settings_support.py` | V3-02 + V3-09 + V3-12 | Endpoints distincts |
| `web/dashboard/views/help.js` | V3-08 + V3-13 | Sections différentes (raccourcis vs bouton logs) |

---

## 🎯 Statut V3

```
V3-01  [ ] Découvrabilité Intégrations (sidebar toujours visible avec état)
V3-02  [ ] Mode débutant `expert_mode` (cache options avancées)
V3-03  [ ] Tooltips ⓘ glossaire métier (~15 termes)
V3-04  [ ] Compteurs sidebar (badges)
V3-05  [ ] Mode démo wizard (1ère ouverture)
V3-06  [ ] Drawer mobile inspector Validation
V3-07  [ ] Fix focus visible thème Studio
V3-08  [ ] Tooltips raccourcis clavier + palette Cmd+K
V3-09  [ ] Reset all data UI (bouton Paramètres)
V3-10  [ ] 30 hardcodes couleurs → tokens CSS
V3-11  [ ] PRAGMA mmap_size SQLite
V3-12  [ ] Hook updater au boot + UI Settings
V3-13  [ ] Vue Aide : bouton "Ouvrir logs"
```

---

## 🚀 Quand toutes les V3 sont mergées

Reviens vers l'orchestrateur avec : **"Vague 3 mergée, génère V4"**.

Vague 4 contiendra (~8 missions validation finale) :
- Test devices Win10/11/4K/petit écran/mobile
- Audit a11y NVDA réel
- Stress 10 000 films
- Lighthouse score
- Contraste 4 thèmes
- Templates GitHub Issues / CONTRIBUTING / CODE_OF_CONDUCT
- README enrichi + screenshots + démo GIF
- Beta privée 20-50 early adopters
