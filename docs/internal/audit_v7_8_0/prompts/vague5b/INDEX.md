# Index Vague 5B — Activation v5 dans le dashboard

**Date** : 3 mai 2026
**Pré-requis** : Vague 5-bis mergée ✅ (7 vues v5 portées vers ES modules + REST apiPost)

---

## ⚠️ LIRE EN PREMIER

V5bis a porté les 7 vues v5 vers ES modules. Maintenant V5B fait la **bascule effective** : on remplace la sidebar HTML statique par le shell v5 et on câble les routes vers les vues v5 maintenant ESM-compatibles.

C'est la phase **visible** : à la fin, l'utilisateur verra la nouvelle UI v5.

---

## 🌊 Mission unique V5B-01

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V5B-01 | [01-ACTIVATION-V5-COMPLETE.md](01-ACTIVATION-V5-COMPLETE.md) | `feat/v5b-activation` | `feat-v5b-activation` | 1 jour |

**Pourquoi 1 mission monolithique** : V5B touche `app.js` + `index.html` + `router.js` (fichiers partagés). Faire en parallèle créerait des conflits inévitables.

---

## 🚀 Quand V5B est mergée

**Test visuel impératif** :
- Sidebar v5 affichée correctement
- Top-bar Cmd+K + cloche notification + menu thèmes
- Navigation entre les 8 vues fonctionne
- Compteurs sidebar (V3-04) marchent
- Mode expert (V3-02), glossaire (V3-03), demo wizard (V3-05)
- Notification center s'ouvre via la cloche
- Aucune erreur F12 console

Reviens avec :
- **« V5B done, lance V5C cleanup »**
- **« Bug visuel sur X »** → on diagnose
