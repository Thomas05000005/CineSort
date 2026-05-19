# Spec — Vue Doublons + Comparateur

Statut : **VALIDÉE** par Thomas le 2026-05-17 (session refonte UI multi-agents).
Position dans la refonte : **Écran 1 / N**.
Inspirée de : `docs/internal/design/11-key-screen-mockups.md` (mais doublons absent — c'est un ajout).

## Pourquoi cette spec

Test perso 2026-05-17 sur EXE v1.2.0-beta : la vue Doublons actuelle (28 groupes dans la lib de Thomas) affiche `<titre> + "Doublon détecté"` sans aucune donnée pour décider. Les fonctions backend (qualité probe, comparaison perceptuelle frames lazy, analyse perceptuelle riche) **existent** mais l'UI ne les expose pas. Cf [[feedback-cinesort-ui-pacotille]].

---

## 1. Vue Doublons (liste principale)

### Layout

```
┌────────────────────────────────────────────────────────────────────────┐
│  Doublons                          28 groupes · 3.2 Go récupérables   │
│  [Actualiser]  [▾ Filtrer]  [▾ Analyser perceptuel sur N groupes]    │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ ┌──────┐  Fast & Furious 4 (2009)                  3 alertes ⚠ │ │
│  │ │poster│  2 fichiers · 2 sources · 14.2 Go au total              │ │
│  │ │ TMDb │  ┌─ A ─────────────────┐  ┌─ B ─────────────────┐      │ │
│  │ │      │  │ 1080p BluRay x264   │  │ 720p WEB-DL x264    │      │ │
│  │ │      │  │ 8.4 Go · DTS 5.1    │  │ 5.8 Go · AAC 2.0    │      │ │
│  │ │      │  │ Score 87  ✓ Reco    │  │ Score 64            │      │ │
│  │ └──────┘  └─────────────────────┘  └─────────────────────┘      │ │
│  │           [Comparer en détail]  [▾ Analyser perceptuel]          │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌── (groupe à 3+ fichiers : titre + N fichiers + meilleur reco) ──┐ │
│  │ ... même structure, juste compteur "3 fichiers · 3 sources"     │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

### Données affichées

| Élément | Source backend |
|---|---|
| Compteur "X groupes" | `check_duplicates().groups.length` |
| Compteur "Y Go récupérables" | `sum(groups.comparison.size_savings)` ← À AGRÉGER (nouveau) |
| Poster TMDb | `library/get_film_full(row_id).poster_url` |
| Titre + année | `groups[i].title` + `.year` |
| Compteur "N fichiers · M sources" | `groups[i].files.length` + sources uniques |
| Cartes A/B (codec / source / taille / score) | `groups[i].comparison.criteria[]` + `total_score_a/b` |
| Badge "✓ Reco" | `groups[i].comparison.winner === "a"` |
| Compteur alertes | `groups[i].files[].warning_flags[]` agrégés |

### Interactions

| Action | Effet |
|---|---|
| Ouverture vue | Auto-trigger `check_duplicates(run_id, decisions)` + render des cartes |
| **Clic carte (zone titre/poster)** | **Sélectionne le groupe → met à jour le panneau inspecteur droit (voir section 2)** |
| **Clic "Comparer en détail"** | **Ouvre modal Comparateur (voir section 3)** |
| Clic "Actualiser" | Relance `check_duplicates` |
| Clic "▾ Filtrer" | Dropdown : Tous / Plan_conflict only / Has 3+ files / À décider |
| Clic "▾ Analyser perceptuel sur N groupes" | Bulk : queue analyse pour tous groupes sans décision (`queue_perceptual_analyses` nouveau) |

→ **Distinction importante** : un clic simple sélectionne le groupe (l'inspecteur droit montre le détail rapide). Un clic explicite sur "Comparer en détail" ouvre le modal Comparateur (workflow complet avec frames + audio + boutons "Garder"). On peut ainsi parcourir les 28 groupes à l'inspecteur sans ouvrir/fermer le modal pour chaque.

---

## 2. Inspecteur droit (panneau persistant sur cette vue)

Conformément au [Shell 3 zones](./04-shell-3-zones.md), la vue Doublons est une **vue experte** : l'inspecteur droit est visible par défaut. Il affiche le détail du groupe actuellement sélectionné dans la liste, sans ouvrir le modal Comparateur.

### Layout du panneau inspecteur (largeur 360px)

```
┌──────────────────────────────┐
│  ▼ Inspecteur                │
├──────────────────────────────┤
│                              │
│  Contexte                    │
│  ──────────────              │
│  28 groupes au total         │
│  3.2 Go récupérables         │
│  12 décidés · 16 en attente  │
│                              │
├──────────────────────────────┤
│                              │
│  📌 Groupe sélectionné       │
│  ──────────────              │
│  ┌──────────────────────┐    │
│  │                      │    │
│  │   [POSTER TMDB       │    │
│  │    GRAND FORMAT]     │    │
│  │                      │    │
│  └──────────────────────┘    │
│                              │
│  Fast & Furious 4 (2009)     │
│  Action · 1h47               │
│                              │
│  ⚠ 3 alertes                 │
│  • Sous-titres FR manquants  │
│    sur la version B          │
│  • Source non identifiée     │
│    sur la version B          │
│  • Doublon cross-root        │
│                              │
│  🎬 Synopsis                 │
│  "Cinq ans après les         │
│   événements de The Fast..." │
│                              │
│  🏷  Candidats TMDb           │
│  • Fast & Furious 4 (2009)   │
│    Confiance 95%             │
│  • Fast Five (2011)          │
│    Confiance 12%  ← rejeté    │
│                              │
├──────────────────────────────┤
│                              │
│  Suite logique               │
│  ──────────────              │
│  [▶ Comparer en détail]      │
│  [▾ Analyser perceptuel]     │
│  [→ Skip ce groupe]          │
│                              │
└──────────────────────────────┘
```

### Données affichées

| Élément | Source backend |
|---|---|
| Compteur "28 groupes au total" | `check_duplicates().groups.length` |
| Compteur "3.2 Go récupérables" | `check_duplicates().size_savings_total` |
| Compteur "12 décidés · 16 en attente" | `groups.filter(g => g.winner_decided).length` vs reste |
| Poster TMDb grand format | `library/get_film_full(row_id).poster_url` (taille `w500` ou `original`) |
| Titre + année + genre + durée | `groups[i].title`, `.year`, candidats TMDb top → `.genres[0]`, `.runtime_min` |
| Liste alertes humanisées | `groups[i].files[].warning_flags[]` agrégés + mapping codes → langage (cf perceptual-labels.js style) |
| Synopsis | `library/get_film_full(row_id).overview` (TMDb) |
| Candidats TMDb avec confiance | `library/get_film_full(row_id).candidates[]` |
| Boutons "Comparer/Analyser/Skip" | Actions sur le groupe sélectionné |

### Comportement

- **Sélection automatique** : à l'ouverture de la vue, le premier groupe non décidé est sélectionné par défaut
- **Navigation clavier** : `↑` / `↓` pour changer de groupe sélectionné (l'inspecteur se met à jour live)
- **Persistance** : si l'utilisateur change de vue (Bibliothèque, Accueil, ...) et revient, le dernier groupe sélectionné est restauré
- **Cas 3+ fichiers** : l'inspecteur affiche le poster TMDb + alertes agrégées sur tous les fichiers + un mini-récap "3 fichiers · 14.2 Go". Pour comparer, on passe par le modal qui a les tabs A/B/C.

### Mapping codes alertes → langage humain

Nouveau fichier `web/dashboard/core/alert-labels.js` à créer (analogue à `perceptual-labels.js`) :

```javascript
export const ALERT_LABELS = {
  "subtitle_missing_fr": "Sous-titres FR manquants",
  "subtitle_missing_en": "Sous-titres EN manquants",
  "root_level_source": "Source non identifiée (renommé à la main ?)",
  "duplicate_cross_root": "Doublon présent dans 2 dossiers racines",
  "duplicate_same_root": "Doublon dans le même dossier racine",
  "year_conflict_folder_file": "Année incohérente (dossier vs fichier)",
  "nfo_title_mismatch": "Titre NFO ≠ titre fichier",
  "low_confidence_tmdb": "Match TMDb peu fiable (<70%)",
  "omdb_disagree": "OMDb conteste le match TMDb",
  "runtime_mismatch_likely_wrong_film": "Durée incohérente — probablement un autre film",
  // ... liste à compléter au fil de l'implémentation
};

export function humanizeAlert(code, fallback = code) {
  return ALERT_LABELS[code] || fallback;
}
```

### Effort additionnel pour l'inspecteur

| Tâche | Effort |
|---|---|
| Slot `getRightPanelContent` dans `lib-duplicates.js` | 0.3 j |
| Composants : carte poster + liste alertes + candidats + synopsis | 0.5 j |
| `alert-labels.js` avec mapping codes → langage | 0.3 j |
| Navigation clavier ↑↓ + persistance sélection | 0.2 j |
| **Total inspecteur Doublons** | **+1.3 j** ajoutés à l'estimation initiale |

---

## 3. Modal Comparateur (au clic sur "Comparer en détail")

### Cas 2 fichiers

```
┌────────────────────────────────────────────────────────────────────────┐
│  ✕  Fast & Furious 4 (2009) — Comparaison détaillée                   │
├────────────────────────────────────────┬───────────────────────────────┤
│  Fichier A                              │  Fichier B                   │
│  📁 \\NAS\Media\Films\F&F4              │  📁 \\NAS\Media\downloads     │
│  📦 Fast.Furious.4.1080p.BR.mkv         │  📦 F&F4.720p.WEBDL.mkv      │
│                                         │                              │
│  🏆 Score global    87  ✓ Recommandé   │  🏆 Score global    64       │
│  🎬 1080p · x264 10b · 8.5 Mbps        │  🎬 720p · x264 8b · 4.2 Mbps│
│  🔊 FR DTS 5.1 · EN AC3 1.5 Mbps       │  🔊 FR AAC 2.0 · 192 kbps    │
│  💬 FR forced ✓  FR full ✓  EN ✓       │  💬 FR forced ✓  FR full ✗   │
│  📦 8.4 Go · 📅 14/03/2024              │  📦 5.8 Go · 📅 02/08/2023   │
├────────────────────────────────────────┴───────────────────────────────┤
│                                                                        │
│  📋 Critères techniques détaillés                       [▼ Replier]    │
│  (DÉPLIÉ PAR DÉFAUT — décision Thomas)                                │
│  ┌──────────────────┬─────────────┬─────────────┬────────┐            │
│  │ Critère          │     A       │      B      │ Winner │            │
│  ├──────────────────┼─────────────┼─────────────┼────────┤            │
│  │ Résolution       │ 1920×1080   │ 1280×720    │   A    │            │
│  │ Bitrate vidéo    │ 8.5 Mbps    │ 4.2 Mbps    │   A    │            │
│  │ Codec depth      │ 10 bit      │ 8 bit       │   A    │            │
│  │ Audio pistes     │ DTS 5.1 + EN│ AAC 2.0 FR  │   A    │            │
│  │ Sous-titres FR   │ forced+full │ forced only │   A    │            │
│  │ Date d'ajout     │ 14/03/2024  │ 02/08/2023  │   B    │            │
│  └──────────────────┴─────────────┴─────────────┴────────┘            │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  🎬 Comparaison visuelle (frames)            [▶ Extraire les frames]   │
│      ↑ BOUTON MANUEL (décision Thomas — pas d'auto-trigger)           │
│                                                                        │
│  [Quand calculé : 3 paires d'images PNG côte à côte sur 3 timestamps  │
│   représentatifs, avec annotation "Δ moyen 12.3 / 255" par paire.     │
│   Détection upscale automatique si A est un faux 1080p.]              │
│                                                                        │
│  Verdict : Vidéo A authentique 1080p natif vs Vidéo B 720p natif.     │
│            Grain comparable. Pas d'upscale détecté.                   │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  🔊 Comparaison audio (waveform + extraits)  [▶ Extraire l'audio]      │
│                                                                        │
│   Timestamp 1: Scène 12 (action)                                       │
│   ┌─────── A : DTS 5.1 ──────────┐  ┌─────── B : AAC 2.0 ──────┐      │
│   │ [waveform stéréo 5 canaux]   │  │ [waveform stéréo 2 ch]   │      │
│   │ Dynamique 18 dB              │  │ Dynamique 8 dB           │      │
│   │ [▶ Écouter 5s] (HTML5 <audio>)│  │ [▶ Écouter 5s]           │      │
│   └─────────────────────────────┘  └─────────────────────────┘      │
│                                                                        │
│   Timestamp 2: Scène 47 (dialogue)                                     │
│   [...similaire...]                                                    │
│                                                                        │
│   Timestamp 3: Scène 89 (musique)                                      │
│   [...similaire...]                                                    │
│                                                                        │
│  Verdict : A = 5.1 surround dynamique. B = stéréo compressé low.      │
│            Empreinte Chromaprint identique (même mastering source).   │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  💡 Recommandation                                                     │
│  Garder A : meilleure source, audio supérieur, sous-titres complets.  │
│  Économie disque : 5.8 Go si tu jettes B.                             │
│                                                                        │
│  [✓ Garder A]            [✓ Garder B]            [Skip ce groupe]     │
│                                                                        │
│   La suppression effective sera faite à l'étape Apply (sécurité       │
│   torrents : on ne touche aux fichiers qu'après ta validation finale).│
│   Destination : `\\NAS\Media\_review\_duplicates_user_decided\`       │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Cas 3+ fichiers (TABS — décision Thomas)

```
┌────────────────────────────────────────────────────────────────────────┐
│  ✕  Captain America: Civil War (2016) — 3 fichiers                    │
│  ┌───────────┬───────────┬───────────┐                                │
│  │ A vs B  ⚡ │ A vs C    │ B vs C    │  ← Tabs (A vs B actif)        │
│  └───────────┴───────────┴───────────┘                                │
├────────────────────────────────────────────────────────────────────────┤
│ ... layout identique au cas 2 fichiers, avec A et B au-dessus         │
│     Boutons en bas : [✓ Garder A] [✓ Garder B] [Skip ce groupe]       │
└────────────────────────────────────────────────────────────────────────┘

Quand l'utilisateur clique "✓ Garder A" dans la tab "A vs B" :
  → A marqué winner du groupe
  → Modal se met à jour : tab "A vs C" devient prioritaire pour valider que A reste winner
  → Quand A confirmé > B et > C → groupe DÉCIDÉ, modal fermé
```

### Workflow décision

L'utilisateur a validé : **bouton clair "Garder celui-là"** sur chaque fichier (pas swipe, pas toggle).

- 1 clic sur "✓ Garder A" → marque winner via `mark_duplicate_winner(group_id, row_id_a)` 
- Modal se ferme, carte du groupe dans la liste passe en état "Décidé : Garder A · 5.8 Go récupérables"
- À l'Apply, les fichiers non-winner sont déplacés vers `<root>/_review/_duplicates_user_decided/`

---

## 4. Décomposition backend

### ✅ Déjà existant (à câbler seulement)

| Endpoint | Statut |
|---|---|
| `check_duplicates(run_id, decisions)` | OK — retourne groups + comparison criteria + winner |
| `compare_perceptual(run_id, row_a, row_b)` | OK — scores + winner_label + recommandation |
| `get_perceptual_compare_frames(run_id, row_a, row_b)` | OK — frames PNG base64 lazy |
| `library/get_film_full(row_id)` | OK — poster TMDb |
| Quarantaine `_review/_duplicates_identical/` + undo | OK — `apply_core.py` (atomic_move + record_op) |

### 🔨 À ajouter côté Python

**1. Agrégation `size_savings_total`** dans la réponse `check_duplicates`
```python
# run_flow_support.py:check_duplicates
total_savings = sum(g.get("comparison", {}).get("size_savings", 0) for g in groups)
return {"ok": True, "data": {"groups": groups, "size_savings_total": total_savings}}
```

**2. Extraction audio côte à côte** (nouveau)
```python
# perceptual_support.py
def get_perceptual_compare_audio(run_id, row_id_a, row_id_b, options={}):
    """
    Extrait 3 timestamps représentatifs et retourne pour chaque :
    - Waveform PNG base64 (ffmpeg showwavespic=s=400x80)
    - Spectrogramme PNG base64 optionnel (ffmpeg showspectrumpic)
    - Extrait MP3 base64 court (5s, 96 kbps via ffmpeg -c:a libmp3lame)
    + métadonnées : dynamic_range_db, channels, codec, bitrate, chromaprint_match
    """
    return {
        "ok": True,
        "data": {
            "timestamps": [
                {
                    "ts": 720,  # secondes
                    "label": "Scène 12 (action)",
                    "waveform_a_b64": "...", "waveform_b_b64": "...",
                    "audio_a_b64": "...", "audio_b_b64": "...",
                    "audio_a_mime": "audio/mpeg", "audio_b_mime": "audio/mpeg",
                },
                # ... 2 autres timestamps
            ],
            "dynamic_range_a_db": 18.0, "dynamic_range_b_db": 8.0,
            "chromaprint_match": True,
            "verdict_a": "5.1 surround dynamique",
            "verdict_b": "stéréo compressé low",
        }
    }
```

**3. Marquage winner** (nouveau)
```python
# run_flow_support.py
def mark_duplicate_winner(run_id, group_id, winner_row_id):
    """Stocke en DB la décision utilisateur pour ce groupe de doublons.
    À l'apply, les autres fichiers du groupe seront déplacés vers
    <root>/_review/_duplicates_user_decided/.
    """
    return {"ok": True, "data": {"group_id": group_id, "winner": winner_row_id}}
```

**4. Queue d'analyses perceptuelles** (utilise JobRunner existant)
```python
# perceptual_support.py
def queue_perceptual_analyses(run_id, pairs, options={}):
    """
    pairs = [{"row_id_a": "X", "row_id_b": "Y"}, ...]
    Lance les analyses en background via JobRunner.
    Retourne job_id. Polling via get_job_status(job_id).
    """
    return {"ok": True, "data": {"job_id": "perceptual_batch_XXX"}}
```

**5. Apply : nouveau bucket** `_review/_duplicates_user_decided/`
```python
# apply_core.py — build_apply_context
duplicates_user_decided_root = merge_review_root / "_duplicates_user_decided"
if not dry_run:
    duplicates_user_decided_root.mkdir(parents=True, exist_ok=True)
```

Et une nouvelle logique dans la boucle apply : si le row appartient à un groupe avec winner ≠ self → déplacer vers ce bucket via `atomic_move + record_op` (réversible par l'undo).

### 💻 Côté frontend (`web/dashboard/views/library/lib-duplicates.js`)

Refonte de ~217 lignes à ~500 lignes :
- Refactor `_render` : cartes avec poster + 2 sous-cartes côte-à-côte
- Refactor modal Comparateur : header A/B + tableau critères déplié + section Vidéo + section Audio + zone décision
- Composant tabs (cas 3+ fichiers)
- Composant lecteur audio HTML5 inline (`<audio>` + base64)
- Boutons "Garder A/B" qui appellent `mark_duplicate_winner` puis ferment et passent au groupe suivant
- Boutons "Extraire frames" / "Extraire audio" manuels (pas auto-trigger)

---

## 5. Estimation effort

| Tâche | Effort |
|---|---|
| Backend `get_perceptual_compare_audio` (ffmpeg waveform + extrait MP3) | 1 j |
| Backend `mark_duplicate_winner` + intégration apply (bucket `_duplicates_user_decided`) | 0.5 j |
| Backend `queue_perceptual_analyses` (utilise JobRunner) | 0.5 j |
| Backend agrégation `size_savings_total` | 0.1 j |
| Frontend refonte vue Doublons (cartes côte à côte + tabs) | 1.5 j |
| **Frontend inspecteur droit + `alert-labels.js` + navigation clavier** | **1.3 j** |
| Frontend modal comparateur (4 sections + lecteur audio + winner) | 1.5 j |
| Tests unitaires + E2E sur ce flow | 0.5 j |
| **Total Doublons** | **~6.9 jours** (était 5.5 j sans inspecteur) |

## 6. Hors scope pour cette spec v1

Reportés à v2 si besoin :
- ❌ Filtre par type d'alerte
- ❌ Tri par taille récupérable / par ancienneté
- ❌ Bulk select + actions groupées
- ❌ Suppression automatique du perdant (toujours via Apply manuel — sécurité torrent + contrainte memory "ne JAMAIS modifier le titre des films")
- ❌ Configurable bucket destination dans Paramètres (par défaut : `_duplicates_user_decided/`, pas d'option pour l'instant)
- ❌ Comparaison spectrogramme (juste waveform + extrait audio pour v1)
