# Index des prompts d'orchestration parallèle

**Date** : 1er mai 2026

---

## ⚠️ LIRE EN PREMIER : `audit/prompts/_WORKTREE_SETUP.md`

Chaque instance DOIT créer son worktree avant tout travail (zéro collision git).

---

## 🌊 Vague 1 — TERMINÉE ✅

15 missions livrées + mergées sur `audit_qa_v7_6_0_dev_20260428` (3310 tests OK,
coverage 80.4%, ruff clean, 4 runs successifs sans flake).

📁 Fichiers : `audit/prompts/vague1/01-XXX.md` à `14-XXX.md` (gardés en archive)

---

## 🌊 Vague 2 — TERMINÉE ✅

12 missions livrées + mergées sur `audit_qa_v7_6_0_dev_20260428` (3525 tests OK,
coverage 82.4%, ruff clean, V2-07 EmptyState validé manuellement).

📁 Fichiers : `audit/prompts/vague2/01-XXX.md` à `12-XXX.md` (gardés en archive)

---

## 🌊 Vague 3 — TERMINÉE ✅

13 missions polish livrées + mergées sur `audit_qa_v7_6_0_dev_20260428` (3643 tests OK,
coverage 82.2%, ruff clean, V3-09 + V3-12 post-fix portés vers le bon dashboard settings).

📁 Fichiers : `audit/prompts/vague3/01-XXX.md` à `13-XXX.md` (gardés en archive)

---

## 🌊 Vague 4 — TERMINÉE ✅

7/8 missions livrées + mergées sur `audit_qa_v7_6_0_dev_20260428` (3665 tests OK,
coverage 82.3%, Lighthouse a11y 96 / BP 100). V4-08 (beta privée) non lancée — utilisable
plus tard quand prêt à diffuser.

📁 Fichiers : `audit/prompts/vague4/01-XXX.md` à `08-XXX.md` (gardés en archive)

---

## 🌊 Vague 5A — TERMINÉE ✅

8 missions livrées + mergées sur `audit_qa_v7_6_0_dev_20260428` (3705 tests OK,
coverage 82.5%, 19 features V1-V4 portées dans 9 fichiers v5 dormants).

📁 Fichiers : `audit/prompts/vague5a/01-XXX.md` à `08-XXX.md`

---

## 🌊 Vague 5-bis — TERMINÉE ✅

8 missions livrées + mergées (3784 tests OK, coverage 82.5%, ~6900 lignes refactorées).

📁 Fichiers : `audit/prompts/vague5bis/00-XXX.md` à `07-XXX.md`

---

## 🌊 Vague 5B — À LANCER MAINTENANT (1 mission, activation v5)

**Pré-requis** : Vague 5-bis mergée ✅

📁 **Index Vague 5B** : [`vague5b/INDEX.md`](vague5b/INDEX.md)

**1 mission monolithique** : refonte `index.html` + `app.js` pour activer le shell v5
et utiliser les vues v5 maintenant ESM-compatibles. Smoke test visuel impératif.

Effort : ~1 jour.

---

## 🌊 Vague 5B — TERMINÉE ✅

V5B-01 livrée + mergée (smoke test Playwright OK, 21 tests structurels V5B passent).
26 tests legacy à adapter en V5C (prévu).

---

## 🌊 Vague 5C — À LANCER MAINTENANT (3 missions parallèles)

**Pré-requis** : V5B mergée ✅

📁 **Index Vague 5C** : [`vague5c/INDEX.md`](vague5c/INDEX.md)

- V5C-01 : Cleanup vues v4 dashboard obsolètes (~3-4h)
- V5C-02 : Décision Jellyfin/Plex/Radarr/Logs : port v5 ou conservation v4 (~30min à 6h)
- V5C-03 : Adapter 26 tests legacy + supprimer `_legacy_globals.js` (~3-4h)

**Pré-requis** : Vague 3 mergée ✅

📁 **Index Vague 4** : [`vague4/INDEX.md`](vague4/INDEX.md)

8 missions de validation finale. Mix de modes selon nature de la tâche :
- **5 parallèles** 🟢 (V4-01 à V4-05) — pure code/scripts → 5 instances Claude Code
- **2 hybrides** 🟡 (V4-06, V4-07) — instance prépare + toi exécutes (devices physiques, NVDA)
- **1 solo+prep** 🟠 (V4-08) — instance prépare canal beta + template, toi diffuses

**Estimation** : ~1 jour parallèles + 1-2 jours hybrides + ton timing diffusion beta

---

## 🛡 Fichiers de référence

- [`_WORKTREE_SETUP.md`](_WORKTREE_SETUP.md) — procédure worktree obligatoire
- [`_RULES_GLOBALES.md`](_RULES_GLOBALES.md) — règles communes (incluses dans chaque prompt)
- [`_CLEANUP_AFTER_INCIDENT.md`](_CLEANUP_AFTER_INCIDENT.md) — historique cleanup post-incident V1

---

## 📊 Tableau de bord global

```
VAGUE 1 (15 missions) : ✅ TERMINÉE et MERGÉE
VAGUE 2 (12 missions) : ✅ TERMINÉE et MERGÉE
VAGUE 3 (13 missions) : ✅ TERMINÉE et MERGÉE
VAGUE 4 (8 missions)  : ✅ TERMINÉE (7/8 mergées, V4-08 différée)
VAGUE 5A (8 missions) : ✅ TERMINÉE (port V1-V4 vers v5 dormante)
VAGUE 5-bis (8 miss.) : ✅ TERMINÉE (port IIFE → ES modules)
VAGUE 5B (1 mission)  : ✅ TERMINÉE (v5 active, smoke test OK)
VAGUE 5C (3 missions) : 🚀 À LANCER MAINTENANT (cleanup + tests + decision integrations)
```

---

## ⚠️ Quand revenir vers l'orchestrateur principal

- "Vague 2 mergée, génère V3"
- "L'instance V2-XX bloque sur ABC, aide"
- "Conflit git entre V2-XX et V2-YY, comment résoudre"
- "Une instance a touché un fichier hors scope, dois-je rollback ?"
