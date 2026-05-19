# Spec — Détail Film (tri-mode : inspecteur / standalone / modal)

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 6 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## Pourquoi cette spec

Test perso 2026-05-17 sur EXE v1.2.0-beta : la modal "Détail Film" actuelle (screenshot "La Doublure (2006)") affiche les alertes en code brut (`subtitle_missing_fr, root_level_source, duplicate_cross_root`), les candidats TMDb sans poster (impossible de désambiguïser entre 2 candidats au même titre), et "Fichier vidéo —" alors que c'est un film. Cf [[feedback-cinesort-ui-pacotille]].

**Constat de l'existant** :
- Modal minimaliste dans `web/dashboard/views/library/lib-validation.js:345` (`_showInspector`)
- Page standalone riche dans `web/views/film-detail.js` (605 lignes, hero band + 4 onglets) — mais en legacy
- → Consolidation en **1 contenu, 3 modes d'affichage** selon le contexte d'invocation

## 1. Mode d'affichage adaptatif (tri-mode)

| Mode | Quand invoqué | Conteneur | Width |
|---|---|---|---|
| **A — Inspecteur élargi** | Vues expertes : Bibliothèque, Doublons, Qualité | Panneau inspecteur droit élargi | 360 → 600px max |
| **B — Page standalone** | Route `#film/<row_id>` (URL partageable, ouverture depuis Historique, etc.) | Pleine page (sidebar reste visible) | flexible |
| **C — Modal overlay** | Accueil, ou depuis "Voir fiche détaillée" du Modal Comparateur Doublons | Overlay centré classique | 80vw max |

Layout interne **identique** dans les 3 modes. Seul le conteneur change.

## 2. Layout du contenu film

```
┌──────────────────────────────────────────────────────────────────────┐
│  ✕  La Doublure (2006)                                              │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐  La Doublure                                          │
│  │          │  2006 · Comédie · 1h25 · Réalisé par Francis Veber   │
│  │  POSTER  │                                                       │
│  │   TMDb   │  Score V2 : ⬤ 64/100 (Bronze)                        │
│  │          │  Confiance match : 90%                                │
│  │          │  Source : NFO                                         │
│  │          │                                                       │
│  └──────────┘  📁 \\NAS\Media\downloads\La.Doublure.2006.1080p.../  │
│                📦 La.Doublure.2006.1080p.WEB.x264-fist.mkv (4.2 Go)│
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  ▼ Synopsis                                                          │
│  "François Pignon, voiturier dans un grand restaurant parisien...   │
│   ...se retrouve par hasard mêlé au scandale d'un milliardaire."    │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  ⚠️  3 alertes                                                       │
│                                                                      │
│   • 💬 Sous-titres FR manquants                                     │
│     [⚙ Configurer recherche subs]                                   │
│                                                                      │
│   • 📁 Source non identifiée (renommé à la main ?)                  │
│     Le dossier source n'est pas dans un format scene standard.      │
│     [✓ Ignorer]                                                     │
│                                                                      │
│   • 🔁 Doublon présent dans 2 dossiers racines                      │
│     Aussi présent dans : \\NAS\Media\Films\La Doublure (2006)\      │
│     [→ Voir les doublons]                                           │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  🏷  Candidats TMDb                                                  │
│                                                                      │
│   ┌──────┐  La Doublure (2006)              ✓ Choisi    90%        │
│   │poster│  Comédie · Francis Veber · 1h25                          │
│   └──────┘                                                          │
│                                                                      │
│   ┌──────┐  La Doublure (2006)                Choisir  72%         │
│   │poster│  Drame · Bertrand Tavernier · 2h05                       │
│   └──────┘  "Bertrand Tavernier signe ici un drame intime..."       │
│                                                                      │
│   ┌──────┐  The Valet (2006)                  Choisir  45%         │
│   │poster│  Remake US du film de Veber                              │
│   └──────┘                                                          │
│                                                                      │
│  [▾ Voir 4 autres candidats]                                        │
│  [🔍 Rechercher manuellement sur TMDb]                              │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  📜 Onglets (cliquer pour déplier)                                  │
│   [Aperçu]  [Analyse V2]  [Historique]  [Renommage proposé]         │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  Actions principales                                                 │
│                                                                      │
│  [✓ Valider]   [▶ Analyser perceptuel]   [📂 Ouvrir dossier]       │
│  [↻ Re-scanner ce fichier]   [🗑 Marquer pour suppression]         │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## 3. Détails par section

### 3.1 Hero (poster + métadonnées)

- **Poster TMDb** ~200×300 px (taille `w300` ou `w500`), avec fallback générique "Pas de poster" si TMDb pas configuré
- **Titre + année + genre + durée + réalisateur**
- **Score V2** : cercle visuel cliquable → ouvre l'onglet "Analyse V2"
- **Confiance match** + **Source** (NFO / Probe / Nom / Hash)
- **Chemin dossier + fichier vidéo** :
  - Si `video_filename` vide → "⚠ Fichier vidéo non détecté" + bouton "Re-scanner ce fichier"
  - Sinon → nom du fichier + taille en Go formatée

### 3.2 Synopsis

Repliable (▼/▶). Plié par défaut si > 200 caractères, déplié sinon.

### 3.3 Alertes humanisées

Réutilise `web/dashboard/core/alert-labels.js` (créé dans la spec 01 Doublons). Chaque alerte a :
- Icône thématique (💬 sous-titres, 📁 fichiers, 🔁 doublons, 🏷 metadata, etc.)
- Libellé humain
- Explication courte (1-2 lignes)
- Action contextuelle ("Ignorer", "Configurer", "Voir les doublons", etc.)

L'action "✓ Ignorer" appelle `library/mark_alert_ignored(row_id, alert_code)` (nouveau). L'alerte disparaît visuellement pour ce film mais reste loggée en DB pour les stats globales.

### 3.4 Candidats TMDb avec posters

- Mini-poster ~80×120 px par candidat (lazy load pour les > 3 candidats)
- Titre + année + genre + score + réalisateur + mini-synopsis (1 ligne tronquée)
- **Candidat choisi** : badge "✓ Choisi" (vert)
- **Autres candidats** : bouton "Choisir"
- **Action "Choisir"** (décision Thomas : direct, sans confirmation) :
  - Appelle `library/set_film_tmdb_candidate(run_id, row_id, tmdb_id)` (nouveau)
  - Met à jour la confidence + le renommage proposé automatiquement
  - Refresh de la vue + toast "Candidat changé. Renommage mis à jour."
  - Réversible tant que l'apply n'est pas faite
- Si > 3 candidats : bouton "▾ Voir N autres candidats" déplie le reste
- Bouton "🔍 Rechercher manuellement sur TMDb" → ouvre une modal de recherche libre

### 3.5 Onglets (sections détaillées)

| Onglet | Contenu |
|---|---|
| **Aperçu** | Récap condensé du hero + synopsis + alertes (déjà visible au-dessus) |
| **Analyse V2** | Score V2 complet inline (réutilise la Modal Perceptuelle, mode "inline") |
| **Historique** | Timeline des opérations passées (probes successifs, runs, scores évolutifs) — source : `library/get_film_history(film_id)` |
| **Renommage proposé** | Diff coloré avant/après : ancien nom de dossier → nom proposé + raison du renommage + impact (déplacement, conflit potentiel) |

### 3.6 Actions principales

| Bouton | Effet | Endpoint |
|---|---|---|
| **✓ Valider** | Marque la décision OK pour la prochaine apply | `save_validation(run_id, {row_id: {ok: true, ...}})` (existant) |
| **▶ Analyser perceptuel** | Ouvre Modal Perceptuelle dual-mode (cf spec 02) | `quality/get_perceptual_details(run_id, row_id)` |
| **📂 Ouvrir dossier** | Ouvre l'explorateur Windows sur le dossier du film | `runtime/open_folder(path)` (à vérifier si existant) |
| **↻ Re-scanner ce fichier** | Relance probe + analyse + match TMDb pour ce row | `run/rescan_row(run_id, row_id)` (NOUVEAU) |
| **🗑 Marquer pour suppression** | Marque le fichier pour déplacement vers `_user_marked_for_deletion/` au prochain apply | `library/mark_for_deletion(run_id, row_id)` (NOUVEAU) |

### 3.7 Marquage suppression (décision Thomas : oui, vers bucket)

- Pas de suppression dure
- Le fichier est **déplacé** vers `<root>/_user_marked_for_deletion/` au prochain apply
- Préfixe `_` pour qu'il apparaisse en haut du tri alphabétique
- Le déplacement est **réversible via l'undo** (même mécanisme que `_review/_duplicates_user_decided/`)
- L'utilisateur peut ensuite supprimer manuellement le dossier `_user_marked_for_deletion/` quand il est sûr (Corbeille Windows recommandée)

**⚠️  Confirmation obligatoire** (cf [[feedback-cinesort-actions-dangereuses]]) : clic sur "🗑 Marquer pour suppression" déclenche une modale :

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️  Confirmer le marquage suppression ?                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  La Doublure (2006)                                             │
│  📁 \\NAS\Media\downloads\La.Doublure.2006.1080p.WEB.x264.../   │
│                                                                  │
│  Conséquence :                                                  │
│  Le dossier sera déplacé vers `_user_marked_for_deletion/`     │
│  au prochain apply. Réversible via Undo.                       │
│                                                                  │
│  [Annuler]                       [✗ Confirmer le marquage]     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

- Bouton "Annuler" focus par défaut
- Bouton "Confirmer" variant `danger` (rouge)
- Esc/clic hors = Annuler

## 4. Source de chaque donnée

| Donnée | Endpoint |
|---|---|
| Hero data (titre, année, genre, durée, réalisateur, score) | `library/get_film_full(row_id)` — enrichir si poster_url/runtime/director manquants |
| Poster TMDb | URL depuis `library/get_film_full().tmdb_data.poster_url` (`https://image.tmdb.org/t/p/w500/<path>`) |
| Synopsis | `library/get_film_full(row_id).overview` (TMDb) |
| Alertes | `row.warning_flags[]` + mapping `alert-labels.js` |
| Candidats TMDb avec poster | `row.candidates[]` (enrichir avec `poster_url` si pas déjà inclus) |
| Historique du film | `library/get_film_history(film_id)` (existant) |
| Score V2 | `quality/get_perceptual_details(run_id, row_id)` |
| Renommage proposé | `row.proposed_path` vs `row.current_path` + diff calculé côté frontend |

## 5. Backend à ajouter (5 endpoints)

| Endpoint | Effort | But |
|---|---|---|
| `library/set_film_tmdb_candidate(run_id, row_id, tmdb_id)` | 0.5 j | Choisir un autre candidat TMDb + recalcul confidence + nouveau renommage |
| `library/mark_for_deletion(run_id, row_id)` | 0.4 j | Marquer fichier pour bucket `_user_marked_for_deletion/` à l'apply |
| `library/mark_alert_ignored(row_id, alert_code)` | 0.3 j | Persister "j'ai vu cette alerte, on continue" |
| `run/rescan_row(run_id, row_id)` | 0.4 j | Relance probe + analyse + match TMDb pour 1 row seul |
| Enrichir `library/get_film_full` avec poster_url + runtime + director | 0.2 j | Si pas déjà inclus |

## 6. Frontend (composant + 3 modes)

| Tâche | Effort |
|---|---|
| Composant `<FilmDetail>` ESM avec layout 6 sections | 1.5 j |
| Tri-mode renderer (inspecteur élargi / standalone / modal overlay) | 0.4 j |
| Onglets (Aperçu / Analyse V2 / Historique / Renommage) | 0.6 j |
| Posters candidats TMDb avec lazy load + click "Choisir" | 0.4 j |
| Modal recherche manuelle TMDb (input texte → liste résultats) | 0.5 j |
| Routing `#film/<row_id>` (mode B standalone) | 0.2 j |
| Diff renommage (avant/après coloré) | 0.3 j |
| Tests E2E | 0.4 j |

## 7. Effort total

| Composant | Effort |
|---|---|
| Backend (5 nouveaux endpoints) | 1.8 j |
| Frontend composant + modes + onglets | 4.3 j |
| **Total Détail Film** | **~6.1 jours** |

## 8. Comportements transverses

| Cas | Comportement |
|---|---|
| Ouverture depuis vue Bibliothèque (clic ligne) | Mode A : inspecteur élargi |
| Ouverture depuis vue Doublons | Mode A : inspecteur élargi (en plus du Modal Comparateur si ouvert) |
| Ouverture depuis Accueil (clic sur film dans suggestions) | Mode C : modal overlay |
| Ouverture depuis URL `#film/<row_id>` | Mode B : page standalone |
| Ouverture depuis Modal Comparateur "Voir fiche détaillée" | Mode C : modal overlay au-dessus de la modal Comparateur (stack) |
| `Esc` pour fermer | Mode C : ferme l'overlay. Mode A/B : pas d'effet (l'inspecteur n'est pas fermable par Esc) |
| Navigation entre films | Mode A : ↑/↓ navigue dans la liste à gauche. Mode B : pas de navigation directe (URL change). Mode C : pas de navigation (overlay isolé) |

## 9. Hors scope v1

- ❌ Édition manuelle du titre / année (contrainte mémoire : "ne JAMAIS modifier le titre des films au-delà du renommage configuré")
- ❌ Affichage des cast members (acteurs) avec photo TMDb
- ❌ Trailer YouTube embed
- ❌ Notation manuelle (5 étoiles) — c'est l'IA qui score, pas l'utilisateur
- ❌ Tags personnels / collections perso (futur, gros chantier)
- ❌ Édition manuelle des alertes (ajouter une alerte custom)
