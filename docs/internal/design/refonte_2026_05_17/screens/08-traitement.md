# Spec — Vue Traitement (workflow run en cours)

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 8 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## Pourquoi cette spec

Vue conditionnelle qui apparaît dans le sidebar uniquement quand un run est actif (cf spec 04 Shell). Elle orchestre le workflow d'un run : Analyse → Vérification → Validation → Doublons → Apply. Aujourd'hui ces étapes existent en code (`lib-analyse.js`, `lib-verification.js`, `lib-validation.js`, `lib-duplicates.js`, `lib-apply.js`) mais sont sous le label "Bibliothèque" — ce qui crée la confusion sémantique entre "collection complète" et "workflow d'un run". On clarifie en séparant.

## 1. Layout général

```
┌────────────────────────────────────────────────────────────────────────┐
│  Traitement · Run 20260517_151                                        │
│  ● En cours · 40 films · Démarré il y a 18 min · ~5 min restant       │
│                                                                        │
│  [⏸ Pause]   [⏹ Annuler]   [💾 Sauvegarder pour plus tard]          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ━●━━━━━●━━━━━━●━━━━━━○━━━━━━○━━━━━━○━━━━━━                          │
│   1.Analyse  2.Vérif  3.Valid 4.Doubl 5.Apply                         │
│    ✓ Done    ✓ Done   ▶ ici   ⌛ next  ⌛                              │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  [contenu spécifique à l'étape active]                                │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                          + INSPECTEUR DROIT (cf spec 06 Détail Film mode A)
```

## 2. Header + breadcrumb 5 étapes

| Élément | Source | Comportement |
|---|---|---|
| Run ID | `run.run_id` | Clic → copy au presse-papier |
| Statut + couleur | `run.status` (RUNNING/PAUSED/DONE/ERROR/CANCELLED) | Vert RUNNING, jaune PAUSED, gris DONE, rouge ERROR/CANCELLED |
| Démarré il y a... | `formatRelative(run.started_at)` | |
| ETA | `run.eta_seconds` | "~5 min restant" calculé par backend |
| Breadcrumb | 5 étapes avec icône d'état | États : `⌛ pending`, `▶ ici`, `✓ done`, `⚠ warning`, `✗ error` |

### Navigation (décision Thomas : libre)

- L'utilisateur peut **revenir** sur n'importe quelle étape déjà passée pour vérifier ou corriger
- Une étape future (non encore atteinte par le worker) **n'est pas cliquable**
- Indicateur visuel clair : étape courante avec halo accent froid, étapes passées en gris foncé, étapes futures en gris clair

## 3. Contenu par étape

### Étape 1 — Analyse (lecture FS + probe)

```
┌────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 — ANALYSE                                                    │
│                                                                        │
│  Scan en cours sur :                                                  │
│   📂 \\NAS\Media\Films                                                │
│   📂 \\NAS\Media\downloads                                            │
│                                                                        │
│  Progression : ████████░░░░░░░░░░░░  450/901 fichiers (50%)          │
│                                                                        │
│  Découverts : 450 fichiers vidéo                                      │
│  Probés    : 380 (ffprobe + MediaInfo)                                │
│  Erreurs   : 2 (corrompus ou inaccessibles)                           │
│                                                                        │
│  Live log :                                                           │
│   12:31:42  PROBE  Inception.2010.1080p.mkv → ok                     │
│   12:31:43  PROBE  Avatar.2009.1080p.mkv    → ok                     │
│   12:31:44  ERR    Corrupted.file.mkv       → ffprobe failed         │
│   ...                                                                 │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

- **Polling auto** toutes les 2s pour mettre à jour progression et live log
- Live log = tail des 10 dernières opérations, scroll auto
- Bouton "Voir log complet" → ouvre le journal complet dans une modal

### Étape 2 — Vérification (sanity, parsing PTN, NFO)

```
┌────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 2 — VÉRIFICATION                                               │
│                                                                        │
│  ✓ 38/40 fichiers passent les contrôles                              │
│  ⚠ 2 fichiers problématiques :                                       │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Fichier              Problème                  Action           │ │
│  ├──────────────────────────────────────────────────────────────────┤ │
│  │  Corrupted.file.mkv   ⚠ Header vidéo invalide  [↻ Re-scanner]  │ │
│  │  Movie..mkv           ⚠ Nom illisible par PTN  [✎ Renommer]    │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  [→ Continuer vers Validation]   [↻ Re-vérifier]                     │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

- Si 0 problème : message "✅ Tous les fichiers passent les contrôles" + auto-transition vers étape 3 après 2s
- Si problèmes : table avec actions ciblées

### Étape 3 — Validation (table dense — décision Thomas)

```
┌────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 3 — VALIDATION                                                 │
│  35/40 décidés · 5 à revoir                                           │
│                                                                        │
│  [✓ Tout approuver les sûrs (28)]   [▼ Filtres]   [▼ Tri]            │
│  Filtres : [Tous] [À revoir] [Sensibles] [Faible qualité] [Sagas]    │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  ✓/✗  Confiance  Type    Titre proposé      Année   Score      │ │
│  ├──────────────────────────────────────────────────────────────────┤ │
│  │  ☑    Haute      Film    Inception          2010    87         │ │
│  │  ☑    Haute      Film    Avatar             2009    72         │ │
│  │  ⚠    Basse      Film    La Doublure ⚠ 3   2006    64    [👁]│ │
│  │  ☑    Haute      Film    Dune               2021    91         │ │
│  │  ☐    Moyenne    Saga    Captain America... 2016    79         │ │
│  │  ...                                                             │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  [→ Passer aux Doublons]                                              │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

- **Vue par défaut : table dense** (décision Thomas). Toggle grille dispo via icône en haut à droite.
- **Action "Tout approuver les sûrs"** (décision Thomas : pas de confirmation) :
  - Approuve d'un coup tous les films avec `confidence >= 85`
  - Affichage du compteur dans le label : "Tout approuver les sûrs (28)"
  - Toast après action : "28 films approuvés. [Annuler]" (5s)
- Clic sur ligne → inspecteur droit affiche Modal Détail Film mode A
- Bouton 👁 sur ligne → ouvre Modal Détail Film mode C overlay (focus profond)
- Cellule année éditable inline (input number)
- Presets : Tous / À revoir (confidence basse) / Sensibles (alertes critiques) / Faible qualité (tier Reject) / Sagas

### Étape 4 — Doublons

Reprend exactement la spec 01 Doublons (vue + inspecteur droit + Modal Comparateur). La spec 01 est complète, juste afficher ici.

### Étape 5 — Apply

```
┌────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 5 — APPLICATION                                                │
│                                                                        │
│  Résumé des opérations à exécuter :                                  │
│   • 40 fichiers à renommer/déplacer                                  │
│   • 22 doublons à déplacer vers _review/_duplicates_user_decided/    │
│   • 12 films marqués pour suppression vers _user_marked_for_deletion/│
│   • Espace récupéré estimé : 5.8 Go                                  │
│                                                                        │
│  ☑ Mode test (dry-run) — recommandé pour le premier passage          │
│  ☐ Sortir le rapport en CSV                                          │
│  ☐ Refresh Jellyfin après apply                                      │
│                                                                        │
│  [▶ Lancer le dry-run]    ou bien...                                 │
│  [▶ APPLIQUER POUR DE VRAI] (variant danger, confirmation requise)   │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Après apply : section "Annulation"                                   │
│   [↻ Prévisualiser l'annulation]   [Exécuter l'annulation]           │
│   ☑ Mode test                                                         │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

#### Apply réel — action dangereuse (cf [[feedback-cinesort-actions-dangereuses]])

Modale obligatoire avant exécution :

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️  Confirmer l'application sur le filesystem ?                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Opérations à exécuter :                                        │
│  • 40 fichiers renommés/déplacés                                │
│  • 22 doublons → `_review/_duplicates_user_decided/`            │
│  • 12 films → `_user_marked_for_deletion/`                      │
│                                                                  │
│  Conséquence :                                                  │
│  Les fichiers sur disque seront effectivement modifiés.         │
│  Réversible via Undo pendant 7 jours après apply.               │
│                                                                  │
│  [Annuler]                       [✗ Appliquer pour de vrai]    │
│                                                                  │
│  ⏱  Confirmer dans 3s...                                         │
└──────────────────────────────────────────────────────────────────┘
```

- Bouton "Annuler" focus par défaut
- Bouton "Appliquer" variant `danger`, désactivé pendant 3s (countdown visible)
- Esc/clic hors = Annuler

### Inspecteur droit par étape

| Étape | Contenu de l'inspecteur |
|---|---|
| 1 Analyse | Live log détaillé + statistiques de scan en temps réel |
| 2 Vérification | Détail du problème sélectionné dans la table |
| 3 Validation | Modal Détail Film mode A (cf spec 06) du film sélectionné |
| 4 Doublons | Inspecteur Doublons (cf spec 01) |
| 5 Apply | Prévisualisation des opérations : chemin avant/après, taille, conséquence |

## 4. Actions globales (header)

| Action | Comportement |
|---|---|
| ⏸ Pause | Suspend le run sans le détruire. Reprise possible via "Reprendre" |
| ⏹ Annuler | **Action dangereuse** : modale confirmation + bouton danger (décision Thomas) |
| 💾 Sauvegarder pour plus tard | Sauvegarde l'état + ferme la vue Traitement. Réouvrable depuis Historique. |

### Annuler le run — modale confirmation

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️  Annuler le run en cours ?                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Run 20260517_151 — 40 films · 35 déjà validés                  │
│                                                                  │
│  Conséquence :                                                  │
│  • Les décisions validées seront perdues                        │
│  • Aucune modification sur disque (le run n'a pas été appliqué) │
│  • Run marqué CANCELLED dans l'Historique                       │
│                                                                  │
│  [Annuler la décision]              [✗ Annuler le run]          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 5. Backend

| Endpoint | Statut |
|---|---|
| `run/get_run_status(run_id)` | Existant (phase + progress + ETA) |
| `run/pause_run(run_id)` | NOUVEAU |
| `run/resume_run(run_id)` | NOUVEAU |
| `run/cancel_run(run_id)` | NOUVEAU |
| `run/save_for_later(run_id)` | NOUVEAU |
| `run/list_pending_runs()` | NOUVEAU |
| `save_validation`, `apply`, `undo_last_apply` | Existants |

## 6. Effort estimé

| Tâche | Effort |
|---|---|
| Backend pause/resume/cancel/save_for_later/list_pending | 1 j |
| Frontend layout général + header + breadcrumb 5 étapes navigable libre | 1 j |
| Frontend étape 1 Analyse (progress + live log + polling 2s) | 0.5 j |
| Frontend étape 2 Vérification (table problèmes + actions ciblées) | 0.3 j |
| Frontend étape 3 Validation (table dense + filtres + presets + bulk approve) — réutilise lib-validation.js | 1.5 j |
| Frontend étape 4 Doublons — réutilise spec 01 | 0 j (déjà compté) |
| Frontend étape 5 Apply (résumé + dry-run + apply réel + Undo) | 1 j |
| Frontend confirmations dangereuses (apply réel + cancel run + countdown 3s) | 0.5 j |
| Inspecteur droit adapté par étape | 0.5 j |
| Toast d'annulation 5s sur bulk approve | 0.2 j |
| Tests E2E full workflow | 0.8 j |
| **Total Traitement** | **~7.3 jours** |

## 7. Hors scope v1

- ❌ Workflow parallèle (lancer 2 runs en même temps)
- ❌ Workflow custom (skip étape 3, faire étape 5 direct, etc.)
- ❌ Templates de validation pré-enregistrés
- ❌ Mode "auto-approuver tout" sans validation
- ❌ Diff visuel avant/après pour le renommage (déjà dans Modal Film onglet Renommage)
- ❌ Édition en masse des décisions (genre "tous ces 10 films → confiance Haute")
- ❌ Notifications push pendant les étapes longues (Analyse) — toast simple suffit
