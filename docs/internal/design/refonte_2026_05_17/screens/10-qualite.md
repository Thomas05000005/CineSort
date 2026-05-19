# Spec — Vue Qualité (audit transverse collection, ex-QIJ/quality)


Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 10 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## Pourquoi cette spec

Ex-QIJ/quality, séparée maintenant en entrée sidebar dédiée (cf spec 04 Shell — décision Thomas : split QIJ en Qualité + Historique + Intégrations dans Paramètres).

Vue d'**audit transverse de la collection complète** (pas d'un run unique). Permet à Thomas de comprendre la santé globale de ses 853 films classés et d'identifier les priorités d'action (films Reject à remplacer, sagas incomplètes, décennies sous-représentées, etc.).

## 1. Layout (6 sections — décision Thomas : on garde les 6)

```
┌────────────────────────────────────────────────────────────────────────┐
│  Qualité — Audit de la bibliothèque                                  │
│  853 films classés · Score moyen 64/100 · Santé globale 38%          │
│  [▾ Filtrer par décennie / genre / source]   [↻ Re-calculer scores] │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  📊 DISTRIBUTION QUALITÉ                            853 films         │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Platinum  ▏                       0  (0%)                      │ │
│  │  Gold      ▏                       0  (0%)                      │ │
│  │  Silver    ▓▓▓▓▓                  273  (32%)                    │ │
│  │  Bronze    ▓▓▓▓▓▓▓▓▓▓▓            525  (62%)                    │ │
│  │  Reject    ▓                       55  (6%)                     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  🔴 À REMPLACER EN PRIORITÉ                       55 films Reject     │
│  [grille de 8 mini-posters cliquables + lien "Voir tous"]             │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ⚠️  SAGAS INCOMPLÈTES                            8 sagas             │
│  [liste avec barre progression + bouton "Voir sur TMDb"]              │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  💬 SUBS FR MANQUANTS                              901 films          │
│  [bouton "Configurer recherche auto" + lien "Voir liste"]            │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  📅 DÉCENNIES                                                         │
│  [histogramme horizontal du nombre de films par décennie]             │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  📈 ÉVOLUTION (30 derniers jours)                                     │
│  [graphique line + KPIs delta : score moyen, films, Reject]          │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                          + INSPECTEUR DROIT (contextuel par section)
```

## 2. Détail des 6 sections

### 2.1 Distribution qualité

Bargraph 5 tiers identique à la section Santé de l'Accueil mais en plus grand.

- Compteurs absolus + pourcentages
- Clic sur une barre → filtre Bibliothèque sur ce tier
- Couleur par tier (cf design tokens)

### 2.2 À remplacer en priorité (Reject)

```
┌────┐┌────┐┌────┐┌────┐┌────┐┌────┐┌────┐┌────┐
│post││post││post││post││post││post││post││post│  [→ Voir tous]
│ er ││ er ││ er ││ er ││ er ││ er ││ er ││ er │
└────┘└────┘└────┘└────┘└────┘└────┘└────┘└────┘
 Hibernatus  Mafia Blues 2  Le Jeu de la mort  ...
```

- Top 8 films tier Reject (triés par score V2 ascendant — les pires d'abord)
- Clic sur poster → inspecteur droit affiche Modal Détail Film mode A (cf spec 06)
- Bouton "Voir tous" → navigue vers Bibliothèque filtrée `tier=reject`

### 2.3 Sagas incomplètes

```
Astérix et Obélix    [████████░░] 8/12 (4 manquants)  [→ TMDb]
Die Hard             [█████░░░░░] 3/6  (3 manquants)  [→ TMDb]
L'Arme Fatale        [███████░░░] 3/4  (1 manquant)   [→ TMDb]
S.O.S. Fantômes      [█████░░░░░] 2/4  (2 manquants)  [→ TMDb]
...
[→ Voir toutes les sagas]
```

- Liste des sagas TMDb dont au moins 1 film est dans la bibliothèque
- Barre de progression (films présents / total saga TMDb)
- Bouton "→ TMDb" : ouvre la page TMDb de la saga dans le navigateur externe (pour voir les films manquants)
- Clic sur le nom de la saga → inspecteur droit avec liste films présents + liste films manquants

### 2.4 Subs FR manquants

```
┌──────────────────────────────────────────────────────────────────┐
│  C'est presque toute la bibliothèque qui n'a pas de subs FR.    │
│  [⚙ Configurer la recherche automatique de subs]                │
│  [→ Voir la liste complète]                                     │
└──────────────────────────────────────────────────────────────────┘
```

Section banner simple. Bouton "Configurer" navigue vers Paramètres > Analyse > Sous-titres. Bouton "Voir liste" navigue vers Bibliothèque filtrée.

### 2.5 Décennies

Histogramme horizontal du nombre de films par décennie de sortie (1930s → 2020s). Clic sur une barre → inspecteur droit avec top 10 et bottom 10 par score pour cette décennie.

### 2.6 Évolution 30j

```
Score moyen :  60 → 64    (+4)   📈
Films classifiés : 800 → 853 (+53)
Tier Reject : 78 → 55     (-23)  ✓

[graphique évolution sur 30j]
```

- Graphique line/area sur 30 derniers jours
- KPIs delta en haut (avant → maintenant)
- Période ajustable via filtre global (Aujourd'hui / 7j / 30j / 90j / Tout)

## 3. Filtres globaux

Header : `[▾ Filtrer par décennie / genre / source]`. Tous les filtres scopent toutes les sections simultanément :
- Décennie (1930s → 2020s)
- Genre TMDb (Action, Comédie, Drame, etc.)
- Source (BluRay, WEB-DL, DVD, autre)
- Audio language (FR, EN, multi)
- Période (pour la section Évolution)

Combinables (AND). Si filtre actif → tous les compteurs et graphes sont recalculés sur le sous-ensemble.

## 4. Action "Re-calculer tous les scores" (décision Thomas : oui utile)

Bouton dans le header de la vue. Utile quand le profil de qualité change (poids/seuils modifiés dans Paramètres > Profils Qualité).

**Action dangereuse car longue** (5-10 min sur 853 films) → modale de confirmation :

```
┌──────────────────────────────────────────────────────────────────┐
│  ↻ Re-calculer tous les scores ?                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Cette opération va re-scorer les 853 films classés à partir   │
│  du profil de qualité actuel. Durée estimée : 5-10 minutes.    │
│                                                                  │
│  Aucune modification sur les fichiers du disque.                │
│  Réversible : lance Re-calculer à nouveau avec l'ancien profil.│
│                                                                  │
│  [Annuler]                       [↻ Lancer le re-calcul]        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

- Pas de countdown 3s (action non destructive, juste longue)
- Lance via JobRunner. Pendant le re-calcul : toast en bas à droite avec progression "Re-calcul 234/853..."

## 5. Inspecteur droit (contextuel selon section sélectionnée)

| Section | Contenu inspecteur |
|---|---|
| Distribution tiers | Détail par tier sélectionné : composantes du score V2 qui définissent ce tier |
| À remplacer | Modal Détail Film mode A du film cliqué (cf spec 06) |
| Sagas incomplètes | Liste films présents + liste films manquants depuis TMDb + lien direct vers chaque film TMDb |
| Subs FR | Liens vers Bibliothèque filtrée + Paramètres > Subs |
| Décennies | Films de la décennie : top 10 (meilleurs scores) + bottom 10 (à remplacer) |
| Évolution | Détail de l'évolution : runs qui ont contribué aux changements + dates clés |

## 6. Source backend

| Donnée | Endpoint | Statut |
|---|---|---|
| Distribution tiers filtrée | `quality/get_distribution(filters)` | Existant à enrichir |
| Films tier Reject | `quality/get_films_by_tier("reject", limit=8)` | NOUVEAU |
| Sagas incomplètes | `library/get_incomplete_sagas()` | NOUVEAU |
| Histogramme décennies | `library/get_films_by_decade(filters)` | NOUVEAU |
| Évolution 30j | `quality/get_history(period=30d)` | NOUVEAU |
| Re-calcul scores | `quality/recompute_all_scores()` (lance JobRunner) | NOUVEAU |
| Subs FR manquants count | `library/get_library_counters({subtitle_missing_fr})` | Existant |

## 7. Effort

| Tâche | Effort |
|---|---|
| Backend 5 nouveaux endpoints | 1.5 j |
| Frontend layout général + filtres globaux | 0.5 j |
| Frontend section Distribution (réutilise composant Accueil) | 0.2 j |
| Frontend section À remplacer (grille mini-posters) | 0.4 j |
| Frontend section Sagas (barres + lien TMDb externe) | 0.5 j |
| Frontend section Subs FR (banner simple) | 0.1 j |
| Frontend section Décennies (histogramme horizontal) | 0.4 j |
| Frontend section Évolution (graphique line + KPIs delta) | 0.5 j |
| Frontend inspecteur droit contextuel par section | 0.5 j |
| Confirmation modale Re-calcul + intégration JobRunner + toast progression | 0.3 j |
| Tests E2E | 0.3 j |
| **Total Qualité** | **~5.2 jours** |

## 8. Hors scope v1

- ❌ Export rapport (PDF/CSV) — décidé hors scope par Thomas
- ❌ Recommandations IA "Tu devrais remplacer X par Y"
- ❌ Comparaison qualité vs autre bibliothèque (benchmarking)
- ❌ Mode "Goal" (objectif santé)
- ❌ Recommandations TMDb de films "à ajouter" (futur, demande backend lourd)
- ❌ Édition des profils de qualité (seuils, poids) → dans Paramètres > Profils (écran 11)
