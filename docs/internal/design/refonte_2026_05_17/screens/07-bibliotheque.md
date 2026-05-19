# Spec — Vue Bibliothèque

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 7 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## Pourquoi cette spec

Test perso 2026-05-17 sur EXE v1.2.0-beta : Thomas a 901 films scannés. La vue Bibliothèque actuelle est confuse — le nom "Bibliothèque" est utilisé dans le code à la fois pour la collection complète ET pour le workflow d'un run (validation + vérification + doublons + apply).

**Séparation sémantique adoptée** (cohérente avec le Shell 3 zones) :
- **Bibliothèque** = vue de la **collection complète** (peu importe le run, tous les 901 films persistés)
- **Traitement** (autre vue, écran 8 à venir) = workflow d'un **run en cours** (40 films du dernier scan)

## 1. Layout cible

```
┌────────────────────────────────────────────────────────────────────────┐
│  Bibliothèque                              901 films · 4.7 To total   │
│                                                                        │
│  [🔍 Rechercher (Ctrl+F)]   [▾ Tri: A→Z]    [▾ Grille][≡ Tableau]    │
│                                                                        │
│  Filtres : [Tous] | Tier: [Bronze 525][Silver 273][Gold 0][Plat 0]   │
│            [Reject 55] | [Sans subs FR 901][Non id. 1][Modif récent] │
│            [Dans doublons 22][Sagas 30] [+ Avancé]                   │
│            853/901 résultats                                          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│  │POSTER  │ │POSTER  │ │POSTER  │ │POSTER  │ │POSTER  │ │POSTER  │   │
│  │ TMDb   │ │ TMDb   │ │ TMDb   │ │ TMDb   │ │ TMDb   │ │ TMDb   │   │
│  │        │ │        │ │        │ │        │ │        │ │        │   │
│  │        │ │  ⚠ 3   │ │  ⚠ 1   │ │        │ │   👥   │ │        │   │
│  │  □     │ │  □     │ │  □     │ │  □     │ │  □     │ │  □     │   │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘   │
│  Inception   La Doublure  Avatar     Dune      Captain    Hibernatus │
│  2010 · 87   2006 · 64⚠   2009 · 72  2021 · 91 America... 1969 · 58  │
│                                                                        │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│  │POSTER  │ │POSTER  │ │POSTER  │ │POSTER  │ │POSTER  │ │POSTER  │   │
│  │        │ │        │ │  REJECT│ │        │ │   👥   │ │        │   │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘   │
│  ... scroll infini : charge 60 films à la fois                       │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                          + INSPECTEUR DROIT (cf spec 06 Détail Film mode A)
```

### Toolbar contextuelle (visible quand sélection > 0)

```
┌────────────────────────────────────────────────────────────────────────┐
│  ✓ 12 films sélectionnés                                              │
│  [▶ Analyser perceptuel]   [🗑 Marquer pour suppression]              │
│  [↻ Re-scanner]   [📤 Exporter liste...]   [Annuler sélection]       │
└────────────────────────────────────────────────────────────────────────┘
```

## 2. Filtres chips (décision Thomas : tous visibles)

Trois groupes horizontaux séparés par un séparateur visuel léger :

### Groupe 1 — Tier qualité (mutuellement exclusifs)

`Tous` | `Bronze (525)` | `Silver (273)` | `Gold (0)` | `Platinum (0)` | `Reject (55)`

### Groupe 2 — Filtres problématiques (combinables)

`Sans sous-titres FR (901)` | `Non identifiés (1)` | `Modifiés récemment (?)`

### Groupe 3 — Filtres structurels (combinables)

`Dans doublons (22)` | `Sagas (30)`

### + Bouton "Avancé"

Ouvre un drawer latéral avec filtres détaillés :
- Année (slider 1900-2025)
- Durée (slider 0-300 min)
- Taille fichier (slider 0-100 Go)
- Résolution (480p / 720p / 1080p / 4K / autre)
- Codec vidéo (H264 / H265 / AV1 / autre)
- Source (BluRay / WEB / DVD / autre)
- Audio language (FR / EN / multi)
- Subtitle language (FR / EN / aucun)
- Confidence (slider 0-100%)
- Date d'ajout (date range picker)

Combinaisons : tous les filtres avancés sont AND. Le filtre chip choisi en groupe 1 (Tier) prend priorité, les groupes 2+3 sont AND avec le tier.

## 3. Tri (dropdown)

| Critère | asc/desc |
|---|---|
| Alphabétique (titre) | A→Z / Z→A |
| Année | ancien/récent |
| Score V2 | meilleur/pire |
| Date d'ajout | récent/ancien |
| Taille fichier | gros/petit |
| Durée | long/court |

Default : Alphabétique A→Z.

## 4. Vue alternative "Tableau dense" (toggle ≡)

```
┌────────────────────────────────────────────────────────────────────────┐
│  □ Titre              Année  Tier      Confiance  Taille   Source     │
├────────────────────────────────────────────────────────────────────────┤
│  □ Inception          2010   Gold      95%        18.4 Go  BluRay    │
│  ☑ La Doublure        2006   Bronze ⚠  90%        4.2 Go   WEB        │
│  □ Avatar             2009   Silver    72%        12.1 Go  BluRay    │
│  ...                                                                  │
└────────────────────────────────────────────────────────────────────────┘
```

- Colonnes triables (clic sur header → toggle asc/desc)
- Checkbox de sélection multi (idem grille)
- Hover sur ligne → highlight + inspecteur droit met à jour
- Densité élevée : ~30 lignes visibles d'un coup vs 12 en grille

Toggle persisté en `localStorage` + settings utilisateur (`library_view_mode: 'grid' | 'table'`).

## 5. Sélection multi + actions bulk (décision Thomas : OUI)

### Activation

- Checkboxes visibles au hover sur les posters (grille) ou toujours visibles (tableau)
- Toggle "Sélection multi" persistant en haut (sinon on coche par défaut un seul)
- Raccourci : `Espace` toggle la sélection de la carte focused
- Drag-select : maintenir clic gauche sur la grille pour sélectionner une zone rectangulaire

### Toolbar contextuelle

Apparaît au-dessus de la grille quand `selection.length > 0` :

| Action | Description | Endpoint |
|---|---|---|
| ▶ Analyser perceptuel sur N films | Queue analyses en background via JobRunner | `quality/queue_perceptual_analyses(pairs[])` (spec 01) |
| 🗑 Marquer pour suppression | Marque N films pour bucket `_user_marked_for_deletion/` | `library/mark_for_deletion_bulk(row_ids[])` (NOUVEAU bulk) |
| ↻ Re-scanner N films | Relance probe + analyse + match TMDb pour les N rows | `run/rescan_rows_bulk(row_ids[])` (NOUVEAU bulk) |
| 📤 Exporter liste... | Export CSV/JSON avec métadonnées (titre, année, score, chemin, etc.) | `library/export_films(row_ids[], format)` (NOUVEAU) |
| Annuler sélection | Désélectionne tout | (côté frontend) |

### Sécurité (règle transverse — actions dangereuses)

**Toute action dangereuse déclenche une modale de confirmation supplémentaire** (règle Thomas, cf [[feedback-cinesort-actions-dangereuses]]).

#### Actions qui nécessitent confirmation

| Action | Modale |
|---|---|
| 🗑 Marquer pour suppression (1 ou N films) | "Vraiment marquer N film(s) pour suppression ? Ils seront déplacés vers `_user_marked_for_deletion/` au prochain apply. Réversible via Undo." |
| Tous les bulks > 50 éléments | Délai 3s anti-clic réflexe avant que le bouton "Confirmer" soit cliquable |

#### Actions qui NE nécessitent PAS confirmation

- ▶ Analyser perceptuel (safe, juste compute)
- ↻ Re-scanner (safe, relit le fichier)
- 📤 Exporter liste (safe, juste lecture)
- Annuler sélection (juste cosmétique)

#### Format de la modale de confirmation

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️  Confirmer la suppression de 12 films ?                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Films concernés :                                              │
│  • La Doublure (2006)                                           │
│  • Avatar de feu et de cendres (2024)                           │
│  • Bienvenue chez les Ch'tis (2008)                             │
│  • Bons baisers de Bruges (2008)                                │
│  • Ennemi d'état (1998)                                         │
│  ... et 7 autres                                                 │
│                                                                  │
│  Conséquence :                                                  │
│  Les fichiers seront déplacés vers `_user_marked_for_deletion/`│
│  au prochain apply. Réversible via Undo dans la vue Traitement.│
│                                                                  │
│  [Annuler]                       [✗ Confirmer la suppression]  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

- Esc ou clic hors modale = Annuler
- Bouton "Annuler" en default focus (focus auto)
- Bouton "Confirmer" en variant `danger` (rouge)
- Si N > 50 : countdown 3s sur le bouton "Confirmer" avant qu'il devienne cliquable

#### Aucun renommage en bulk
Contrainte mémoire CLAUDE.md : "ne JAMAIS modifier le titre des films au-delà du renommage configuré". Aucun bouton de renommage massif dans cette toolbar.

## 6. Inspecteur droit

Réutilise la spec 06 Détail Film **mode A (inspecteur élargi)**. Au clic sur une carte/ligne, l'inspecteur affiche le détail complet du film sélectionné (poster grand + alertes + candidats TMDb + onglets).

Si **sélection multi** > 1 film : l'inspecteur affiche un récapitulatif "12 films sélectionnés" + suggestions d'actions bulk + agrégats (durée totale, taille totale, distribution tier).

## 7. Source de chaque donnée

| Donnée | Endpoint |
|---|---|
| Liste films (filtrée + paginée) | `library/get_library_filtered(filters, offset, limit)` (existant à enrichir avec scroll infini support) |
| Compteur total + compteurs par chip | `library/get_library_counters_by_chip(filters)` (NOUVEAU — retourne counts par chip pour afficher (525), (273), etc.) |
| Poster TMDb par film | `row.poster_url` (à enrichir dans `get_library_filtered` si manquant) |
| Recherche fuzzy | `library/get_library_filtered({query: $search, ...})` (existant) |
| Filtres avancés | `library/get_library_filtered({year_range, codec, source, ...})` (à enrichir avec nouveaux filtres) |

## 8. Performance — scroll infini (décision Thomas)

- Charge **60 films par batch** au scroll
- Threshold : quand l'utilisateur a scrollé à 80% de la liste actuelle, charge le suivant
- Indicateur "Chargement..." en bas pendant la requête
- Cache local des batchs déjà chargés (pas de re-fetch si scroll arrière)
- Lazy loading des posters (chargés seulement quand visibles dans le viewport)

Pour 901 films, scroll infini reste fluide. Si la lib monte > 10000, on basculera vers virtualisation (hors scope v1).

## 9. Comportements transverses

| Cas | Comportement |
|---|---|
| Premier ouverture | Grille 6 colonnes + filtre "Tous" + tri "A→Z" + scroll en haut |
| Bibliothèque vide (0 film) | Empty state : "Aucun film dans la bibliothèque. [▶ Lancer un scan]" |
| Filtre actif → 0 résultat | "Aucun film ne correspond à ces filtres. [Effacer les filtres]" |
| Hover sur poster | Petit badge "Cliquer pour détail" + halo léger |
| Clic simple sur poster | Sélectionne (toggle si sélection multi active) → inspecteur droit met à jour |
| Double-clic sur poster | Ouvre Modal Détail Film mode C (overlay) |
| Drag-select sur grille | Sélection rectangulaire pour bulk actions |
| Tri changé | Re-charge depuis le début avec nouveau tri |
| Filtre changé | Re-charge depuis le début avec filtre appliqué + maj compteur "X / 901 résultats" |
| Run terminé en background | Toast en bas à droite "Run terminé — 40 films ajoutés. [→ Voir]" — possible refresh manuel ou auto de la grille |

## 10. Effort estimé

| Tâche | Effort |
|---|---|
| Backend `library/get_library_counters_by_chip` (agrégation pour chips) | 0.4 j |
| Backend bulk : `library/mark_for_deletion_bulk` + `run/rescan_rows_bulk` + `library/export_films` | 0.8 j |
| Backend filtres avancés étendus (codec, source, audio_lang, date_range) | 0.4 j |
| Frontend grille posters responsive 4-6 colonnes + lazy load | 1 j |
| Frontend tableau dense (toggle, colonnes triables, checkbox) | 0.8 j |
| Frontend filtres chips (3 groupes + drawer avancé) | 0.7 j |
| Frontend tri + recherche fuzzy + autocomplete | 0.5 j |
| Frontend sélection multi (checkbox + drag-select + toolbar bulk) | 0.7 j |
| Frontend scroll infini avec cache | 0.5 j |
| Frontend inspecteur droit (réutilise spec 06) | 0.3 j |
| Frontend export CSV/JSON | 0.3 j |
| Tests E2E | 0.6 j |
| **Total Bibliothèque** | **~7 jours** |

## 11. Hors scope v1

- ❌ Vues "Stats" / "Podiums" détaillés (déplacés depuis l'Accueil — gardés en hors scope si valeur ajoutée faible)
- ❌ Tags utilisateur custom
- ❌ Listes/Playlists personnelles (Watchlists, "À voir", etc.)
- ❌ Notation manuelle 5 étoiles (l'IA score, pas l'utilisateur)
- ❌ Mode visuel "wall" 4K (futur)
- ❌ Animations 3D au scroll (overkill)
- ❌ Virtualisation pour > 10000 films (à implémenter quand la lib grossira)
- ❌ Filtres custom enregistrables (genre "Mes films Bronze à supprimer")
- ❌ Drag-and-drop entre vues (drag d'un poster vers Doublons pour forcer)
