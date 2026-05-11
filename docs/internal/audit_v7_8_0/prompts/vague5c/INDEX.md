# Index Vague 5C — Cleanup post-migration v5

**Date** : 3 mai 2026
**Pré-requis** : Vague 5B mergée ✅ (v5 active dans le dashboard)

---

## ⚠️ LIRE EN PREMIER

Maintenant que v5 est active (V5B), il reste du code v4 et legacy qui n'est plus utilisé. V5C nettoie tout ça pour avoir un repo propre.

⚠ **NE PAS lancer V5C avant d'avoir validé visuellement V5B** (au moins 1 jour de test).

---

## 🌊 3 missions Vague 5C

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V5C-01 | [01-CLEANUP-VUES-V4-DASHBOARD.md](01-CLEANUP-VUES-V4-DASHBOARD.md) | `chore/v5c-cleanup-v4-views` | `chore-v5c-cleanup-v4-views` | 3-4h |
| V5C-02 | [02-PORT-OU-CLEANUP-INTEGRATIONS-V5.md](02-PORT-OU-CLEANUP-INTEGRATIONS-V5.md) | `feat/v5c-integrations-v5` | `feat-v5c-integrations-v5` | 4-6h ou 30 min selon décision |
| V5C-03 | [03-ADAPT-LEGACY-TESTS.md](03-ADAPT-LEGACY-TESTS.md) | `chore/v5c-adapt-legacy-tests` | `chore-v5c-adapt-legacy-tests` | 3-4h |

---

## 🚀 Quand V5C mergée

**Repo final** : architecture cohérente 100% v5, plus de code mort.

Reviens avec : **« V5C done, on prépare le public release »** → checklist final + tag v7.6.0 + GitHub Release.
