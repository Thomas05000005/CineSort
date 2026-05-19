# Spec — Vue Aide

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 12 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## 1. Layout (5 sections + recherche)

```
┌────────────────────────────────────────────────────────────────────────┐
│  Aide                                                                 │
│  [🔍 Rechercher dans la doc...]                                      │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  📚 DOCUMENTATION                                                     │
│  ─────────────────                                                    │
│  • Premiers pas (guide quickstart)                                   │
│  • Comment lancer un scan                                            │
│  • Comment résoudre des doublons                                     │
│  • Comprendre les scores Bronze/Silver/Gold/Platinum                 │
│  • Configurer OMDb et TMDb                                           │
│  • Apply réel vs dry-run : différences                               │
│  • Undo : comment annuler                                            │
│  • Sécurité torrents : pourquoi on ne modifie pas les titres        │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ⌨️  RACCOURCIS CLAVIER                                                │
│  Ctrl+K   Command palette / Recherche globale                        │
│  Ctrl+S   Lancer un nouveau scan                                     │
│  Ctrl+B   Toggle sidebar                                             │
│  Ctrl+I   Toggle inspecteur droit                                    │
│  Ctrl+,   Paramètres                                                 │
│  Esc      Fermer modal / palette                                     │
│  ?        Aide contextuelle                                          │
│  ↑/↓     Navigation dans listes                                      │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ⚙ DIAGNOSTIC                                                         │
│  Version    : v1.2.0-beta                                             │
│  Python     : 3.13.13                                                 │
│  DB schema  : v21                                                     │
│  ffprobe    : 8.1.1   ✓                                              │
│  MediaInfo  : 23.07   ✓                                              │
│  Roots      : 2 actifs (4.7 To)                                      │
│  Lib total  : 901 films · 853 classés                               │
│  [📋 Copier le diagnostic]   [🐛 Signaler un bug]                    │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  📝 LOGS                                                              │
│  [📂 Ouvrir le dossier des logs]                                     │
│  [📋 Copier les 100 dernières lignes]                                │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ℹ️  À PROPOS                                                          │
│  CineSort — Tri et normalisation de bibliothèque films               │
│  Licence : MIT                                                        │
│  [Site web]  [Repo GitHub]  [Changelog]  [Contributeurs]             │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

Pas d'inspecteur droit (vue de synthèse, replié par défaut).

## 2. Source documentation (décision Thomas : nouveau guide)

**Action requise** : écrire un **nouveau guide utilisateur dédié refonte** dans `docs/USER_GUIDE_v2.md` qui :
- S'appuie sur les grandes lignes de `docs/MANUAL.md` existant (370+ lignes)
- Mais réécrit selon la nouvelle UX (3 zones, Workflow Traitement, Bibliothèque grille de posters, etc.)
- Cible un utilisateur final (pas un dev) : moins de jargon, plus de captures d'écran, plus d'exemples
- Section dédiée pour les concepts clés (tier qualité, score V2, OMDb cross-check, doublons workflow)

Le `MANUAL.md` actuel devient une référence dev/power user, conservé en parallèle dans `docs/internal/MANUAL_legacy.md`.

**Effort rédaction** : ~2-3 jours (à inclure dans l'implémentation de la refonte).

## 3. Comportements

| Cas | Comportement |
|---|---|
| Recherche dans la doc | Full-text dans `docs/USER_GUIDE_v2.md`, retourne liens vers les sections avec highlight |
| Clic sur "Premiers pas" | Ouvre la section markdown dans une modal large ou un drawer (à décider à l'implémentation) |
| Clic "Copier le diagnostic" | Copie le bloc texte au presse-papier (utile pour bug reports) |
| Clic "Signaler un bug" | Ouvre `https://github.com/Thomas05000005/CineSort/issues/new` dans le navigateur externe avec template pré-rempli (diagnostic auto-inclus) |
| Clic "Ouvrir le dossier des logs" | Lance `os.startfile(logs_dir)` côté Python |
| Clic "Copier les 100 dernières lignes" | Lit les logs récents + copie au presse-papier |

## 4. Source backend

| Donnée | Endpoint | Statut |
|---|---|---|
| Diagnostic complet | `runtime/get_diagnostic()` | NOUVEAU |
| 100 dernières lignes log | `runtime/get_recent_logs(limit=100)` | NOUVEAU |
| Ouvrir dossier logs | `runtime/open_logs_folder()` | Existant |
| Contenu doc | `runtime/get_doc(file)` (lit + retourne markdown brut) | NOUVEAU |
| Recherche full-text | `runtime/search_docs(query)` (grep dans docs/) | NOUVEAU |

## 5. Effort

| Tâche | Effort |
|---|---|
| Backend 4 nouveaux endpoints (get_diagnostic, get_recent_logs, get_doc, search_docs) | 0.7 j |
| Frontend layout 5 sections | 0.4 j |
| Frontend rendu markdown (markdown-it ou marked.js) + TOC navigable | 0.5 j |
| Frontend recherche full-text avec highlight | 0.3 j |
| Frontend Diagnostic section (refresh à chaque ouverture) | 0.2 j |
| Frontend logs section + copy/open | 0.2 j |
| Frontend "Signaler un bug" avec template pré-rempli | 0.2 j |
| **Rédaction du nouveau guide `USER_GUIDE_v2.md` (décision Thomas)** | **2.5 j** |
| Tests E2E | 0.2 j |
| **Total Aide** | **~5.2 jours** |

## 6. Hors scope v1

- ❌ Tutoriel interactif intégré (onboarding au premier lancement)
- ❌ Vidéos d'explication intégrées
- ❌ Chat support intégré
- ❌ Édition des raccourcis personnalisés (les raccourcis restent statiques)
- ❌ Multi-langue (français only en v1)
