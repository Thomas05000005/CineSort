# Spec — Vue Historique (ex-QIJ/journal)

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 9 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## 1. Layout (timeline groupée par jour — décision Thomas)

```
┌────────────────────────────────────────────────────────────────────────┐
│  Historique                                                           │
│  18 runs · 4 apply · 1 undo · sur les 30 derniers jours              │
│                                                                        │
│  [▾ Statut: Tous]  [▾ Période: 30j]  [▾ Type: Tous]  [🔍 Rechercher] │
│  [📅 Timeline] [≡ Tableau]                                           │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  📅 Aujourd'hui                                                       │
│  ─────────────                                                        │
│  ● 15:11   Run 20260517_151    Plan    40 films    Done    [...]    │
│                                                                        │
│  📅 Hier                                                              │
│  ─────────────                                                        │
│  ● 13:13   Run 20260515_131    Plan    855 films   Done    [...]    │
│  ● 11:12   Run 20260515_112    Plan    855 films   Cancel  [...]    │
│                                                                        │
│  📅 10 mai                                                            │
│  ─────────────                                                        │
│  ● 18:02   Apply on 20260510_18    855 films    Applied   [...]      │
│  ● 17:55   Run 20260510_18    Plan    855 films    Done    [...]     │
│                                                                        │
│  ... scroll infini par batch de 30 runs                              │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                              + INSPECTEUR DROIT (détail run sélectionné)
```

Toggle vers tableau dense disponible (icône `≡`), persisté dans settings.

## 2. Filtres

| Filtre | Options |
|---|---|
| Statut | Tous / Done / Cancel / Error / Applied / Undone |
| Période | Aujourd'hui / 7j / 30j / 90j / Tout / Custom (date picker) |
| Type | Tous / Plan (scan) / Apply / Undo |
| Recherche | Par run_id ou par nom de film concerné |

## 3. Inspecteur droit (détail run sélectionné)

```
┌──────────────────────────────┐
│  ▼ Inspecteur                │
├──────────────────────────────┤
│  Run 20260517_151            │
│  📅 Aujourd'hui 15:11        │
│  ⏱  Durée : 8 min            │
│  ✓ Statut : Done             │
│                              │
│  Films analysés : 40         │
│  Score moyen   : —           │
│  Apply effectué : Non        │
├──────────────────────────────┤
│  [Résumé][Films][Apply]      │
│  [Doublons][Log]             │
│                              │
│  [contenu de l'onglet]       │
├──────────────────────────────┤
│  Actions                     │
│   [Voir rapport complet]     │
│   [↻ Reprendre ce run]       │
│   [↺ Annuler l'apply]        │
│   [🗑 Supprimer]             │
└──────────────────────────────┘
```

### Onglets de l'inspecteur

| Onglet | Contenu |
|---|---|
| **Résumé** | Stats globales (films, score moyen, durée, root, étape atteinte) |
| **Films** | Liste des films traités avec leur statut individuel (approuvé/rejeté/doublon) — réutilise le composant Bibliothèque |
| **Apply** | Liste des opérations effectuées si applique (renames, moves, quarantaine, marquage suppression) |
| **Doublons** | Groupes de doublons décidés pour ce run, avec winner |
| **Log** | Log complet (scrollable, monospace) du run |

## 4. Actions sur un run

| Action | Comportement | Sécurité |
|---|---|---|
| **Voir rapport complet** | Ouvre page standalone `#run/<id>` (vue large avec tous les onglets dépliés) | Safe |
| **↻ Reprendre ce run** | Si statut PAUSED ou SAVED → ré-ouvre la vue Traitement à l'étape où il en était (décision Thomas : on garde uniquement Reprendre, pas Re-jouer) | Safe |
| **↺ Annuler l'apply** | Si run a un apply réel → lance undo via `undo_last_apply(run_id)` | **Dangereuse** : modale obligatoire (cf [[feedback-cinesort-actions-dangereuses]]) |
| **🗑 Supprimer ce run** | Supprime le run + son plan + son log de l'historique | **Dangereuse** : modale obligatoire |

### Modale "Annuler l'apply" (action dangereuse)

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️  Annuler l'apply du Run 20260510_18 ?                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Opérations à inverser :                                        │
│  • 855 fichiers renommés/déplacés (inverse)                     │
│  • 12 doublons sortis de `_review/` (réintégrés)                │
│                                                                  │
│  Conséquence :                                                  │
│  Les fichiers reviendront à l'état d'avant l'apply du 10 mai.   │
│  L'apply ne sera plus annulable après cette opération.          │
│                                                                  │
│  [Annuler la décision]              [✗ Annuler l'apply]         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Modale "Supprimer ce run" (action dangereuse)

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️  Supprimer le Run 20260515_112 de l'historique ?            │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Conséquence :                                                  │
│  • Le run + son plan + son log seront supprimés définitivement  │
│  • Aucune modification sur les fichiers du disque               │
│  • Action NON réversible                                        │
│                                                                  │
│  [Annuler]                       [✗ Supprimer le run]           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 5. Rétention automatique (décision Thomas : 90 j)

- **Par défaut** : les runs sont supprimés automatiquement après 90 jours
- **Configurable** dans Paramètres > Avancé > Rétention historique (slider 7-365 j, ou "Jamais")
- Indication visible : tout en bas de la timeline "Les runs antérieurs au [date - 90j] ont été supprimés automatiquement"
- Suppression auto = pas de notification (silencieuse), juste un cron job côté Python qui tourne au démarrage de l'app

## 6. Source backend

| Donnée | Endpoint |
|---|---|
| Liste runs filtrée | `run/list_runs(filters, limit, offset)` (existant) |
| Compteurs en haut | `run/get_history_stats(period)` (NOUVEAU) |
| Détail d'un run | `run/get_run_summary(run_id)` + `run/get_run_detail(run_id)` (existants) |
| Reprendre un run | `run/resume_run(run_id)` (cf spec 08 Traitement) |
| Annuler l'apply | `undo_last_apply(run_id)` (existant) |
| Supprimer run | `run/delete_run(run_id)` (NOUVEAU) |
| Cron rétention | `run/cleanup_old_runs()` (NOUVEAU, lancé au démarrage Python) |

## 7. Effort estimé

| Tâche | Effort |
|---|---|
| Backend `get_history_stats` + `delete_run` + `cleanup_old_runs` cron | 0.5 j |
| Frontend timeline groupée par jour (default) | 0.5 j |
| Frontend toggle tableau dense | 0.3 j |
| Frontend filtres (statut/période/type/recherche) | 0.4 j |
| Frontend inspecteur droit avec 5 onglets compactés | 0.6 j |
| Frontend actions (reprendre/undo/supprimer + 2 modales confirmation) | 0.5 j |
| Frontend page standalone `#run/<id>` | 0.3 j |
| Frontend scroll infini | 0.3 j |
| Tests E2E | 0.3 j |
| **Total Historique** | **~3.7 jours** |

## 8. Hors scope v1

- ❌ Comparer 2 runs côte à côte (diff)
- ❌ Export PDF d'un rapport de run
- ❌ Sélection multi-runs pour bulk delete (jugé trop dangereux)
- ❌ Re-jouer un run identique (décision Thomas : on garde uniquement Reprendre)
- ❌ Archivage automatique vers un dossier dédié (juste suppression silencieuse)
- ❌ Graphique d'évolution des scores entre runs (futur si demande)
