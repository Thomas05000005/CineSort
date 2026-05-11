# Index Vague 5A — Port V1-V4 vers fichiers v5 dormants

**Date** : 2 mai 2026
**Pré-requis** : Vague 4 mergée sur `audit_qa_v7_6_0_dev_20260428` ✅
**Objectif** : enrichir les fichiers v5 dormants (sidebar-v5.js, settings-v5.js, etc.) avec les 19 features V1-V4 manquantes, **SANS encore activer la v5**.

---

## ⚠️ LIRE EN PREMIER

- `audit/prompts/_WORKTREE_SETUP.md` — procédure worktree
- **PHASE A UNIQUEMENT** : on porte les features dans les fichiers v5. La v4 reste l'UI active.
- **PHASE B (à venir)** : activation v5 dans `app.js` (swap sidebar/topbar)
- **PHASE C (à venir)** : cleanup v4 obsolète

---

## 🎯 Architecture cible

```
v4 actuelle (active) ──── on garde tout intact pendant Phase A
                             │
v5 dormante ─── enrichissement ─── tout ce qui manque (19 features V1-V4)
                                      │
                                      ▼
                          v5 prête à activer en Phase B
```

---

## 🌊 8 missions Phase A

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V5A-01 | [01-SIDEBAR-V5-ENRICHI.md](01-SIDEBAR-V5-ENRICHI.md) | `feat/v5a-sidebar-port` | `feat-v5a-sidebar-port` | 3-4h |
| V5A-02 | [02-TOP-BAR-V5-ENRICHI.md](02-TOP-BAR-V5-ENRICHI.md) | `feat/v5a-topbar-port` | `feat-v5a-topbar-port` | 2-3h |
| V5A-03 | [03-SETTINGS-V5-ENRICHI.md](03-SETTINGS-V5-ENRICHI.md) | `feat/v5a-settings-port` | `feat-v5a-settings-port` | 4-6h |
| V5A-04 | [04-HOME-V5-ENRICHI.md](04-HOME-V5-ENRICHI.md) | `feat/v5a-home-port` | `feat-v5a-home-port` | 4-6h |
| V5A-05 | [05-PROCESSING-V5-ENRICHI.md](05-PROCESSING-V5-ENRICHI.md) | `feat/v5a-processing-port` | `feat-v5a-processing-port` | 1 jour |
| V5A-06 | [06-QIJ-V5-ENRICHI.md](06-QIJ-V5-ENRICHI.md) | `feat/v5a-qij-port` | `feat-v5a-qij-port` | 4-6h |
| V5A-07 | [07-LIBRARY-FILM-V5-ENRICHI.md](07-LIBRARY-FILM-V5-ENRICHI.md) | `feat/v5a-library-film-port` | `feat-v5a-library-film-port` | 4-6h |
| V5A-08 | [08-HELP-V5-AUDIT.md](08-HELP-V5-AUDIT.md) | `feat/v5a-help-audit` | `feat-v5a-help-audit` | 2-3h |

**Estimation parallèle (8 instances)** : ~1 jour
**Estimation séquentielle** : ~4-5 jours

---

## ⚠ Règles globales V5A

1. **Préservation v5** : conserver le style v5 (`v5-*` prefix, schema déclaratif, design "data-first"), tier colors invariantes
2. **Ne pas activer** : NE PAS modifier `web/dashboard/app.js` (sauf si explicitement demandé pour câbler un util sans changer l'UI active)
3. **Référence v4** : lire les fichiers v4 actuels (`web/dashboard/views/*.js` et `web/dashboard/index.html`) pour comprendre comment la feature fonctionne, puis adapter au pattern v5
4. **Tests structurels** : chaque mission ajoute un test qui vérifie la présence des features portées dans le fichier v5

---

## 🎯 Statut V5A

```
V5A-01  [ ] Sidebar v5 enrichi (5 features V1-V4)
V5A-02  [ ] Top-bar v5 enrichi (2 features)
V5A-03  [ ] Settings-v5 enrichi (2 features)
V5A-04  [ ] Home v5 enrichi (5 features)
V5A-05  [ ] Processing v5 enrichi (5 features)
V5A-06  [ ] QIJ v5 enrichi (3 features)
V5A-07  [ ] Library + Film v5 enrichis (3 features)
V5A-08  [ ] Help v5 audit + port V3-13 si manquant
```

---

## 🚀 Quand toutes les V5A sont mergées

Reviens vers l'orchestrateur avec : **« V5A done, on lance V5B activation »**.

V5B contiendra ~3 missions :
- V5B-01 : Activer composants v5 dans app.js (sidebar + top-bar + breadcrumb)
- V5B-02 : Activer notification center + câbler endpoints
- V5B-03 : Migrer router vers structure v5 + supprimer sidebar HTML statique

V5C contiendra ~3 missions cleanup :
- Suppression vues v4 obsolètes (quality.js, review.js, library/, etc.)
- Mise à jour CLAUDE.md
- Tests E2E complets sur v5
