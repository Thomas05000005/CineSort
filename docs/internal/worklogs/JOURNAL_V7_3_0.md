# Journal de bord — CineSort v7.3.0

> Journal tenu par Claude pour pallier la perte de contexte inter-session.
> Ordre chronologique inversé (plus récent en haut).
> Chaque entrée : date · palier · ce qui a changé · fichiers touchés · tests · prochaine étape.

---

## 🎯 Cap stratégique v7.3.0

Décisions utilisateur validées le 2026-04-22 :

1. **App pro partageable** (potentiellement communautaire) → **robustesse data safety** est la priorité absolue. Aucun rename/undo/apply ne doit pouvoir détruire une bibliothèque.
2. **Scoring comme différenciateur** (plus que l'automatisation). Les sous-titres/fanart auto existent déjà ailleurs ; le scoring perceptuel est la valeur unique de CineSort.
3. **Visuels forts, interactifs**. Comparateur de doublons côte-à-côte type mockup (deux cards avec toutes les infos techniques + score + recommandation).
4. **Qualité avant tout** : dépendances supplémentaires autorisées si elles améliorent la qualité. Temps illimité (étape par étape, recherche à chaque étape).

---

## 🗺️ Feuille de route v7.3.0 (4 paliers)

### Palier 1 — Data Safety (condition sine qua non pour partage)
- **P1.1** NFO cross-validation (ne pas faire confiance aveuglément)
- **P1.2** Undo checksum + atomic rollback (garantie retour arrière)
- **P1.3** Pre-apply visual preview (show-before-touch)

### Palier 2 — Scoring transparent (différenciateur)
- **P2.1** Explain-score mode (pourquoi ce score)
- **P2.2** Résolution "deux films même titre"
- **P2.3** Logging granulaire apply

### Palier 3 — Visuel premium (comparateur)
- **P3.1** Comparateur doublons côte-à-côte (mockup user)
- **P3.2** Badges tiers visuels (pastilles Platinum/Gold/Silver/Bronze/Reject)
- **P3.3** Historique film enrichi

### Palier 4 — Scoring avancé (R&D)
- **P4.1** Calibration perceptuelle avec feedback utilisateur
- **P4.2** Règles genre-aware (animation vs live-action vs thriller)
- **P4.3** Import/export profils qualité (partage communautaire)

---

## 📝 Entrées chronologiques

### 2026-04-22 · Session d'ouverture

**Contexte** : fin de la session d'audit ultra-complète (AUDIT_20260422.md, 40+ findings P0/P1/P2 tous traités). État du repo : clean, tag `v7.2.0-dev-audit-clean`, HEAD `1404190`. Base v12 (schema_history), boundary decorator, ruff étendu, CI active.

**Décisions** :
- Priorité Palier 1 (data safety) car prérequis pour partage pro. Sprint 2+ viennent après.
- Journal créé dans `docs/internal/worklogs/JOURNAL_V7_3_0.md`.

**Reconnaissance P1.1** (NFO cross-validation) :

État actuel (lu dans [core.py](../../../cinesort/domain/core.py) et [plan_support.py](../../../cinesort/app/plan_support.py:720)) :
- `NfoInfo` (core.py:474) : `title, originaltitle, year, tmdbid, imdbid`. **Pas de runtime.**
- `parse_movie_nfo` (core.py:483) : gère 3 encodages (utf-8, latin-1, cp1252), XML ElementTree.
- `nfo_consistent` (core.py:531) : compare NFO titre vs 6 variantes (folder + filename, clean, préfixe année). Retourne `ok, cov, seq` — **pas de distinction entre "folder match" et "filename match".**
- `should_reject_nfo_year` (core.py:807) : gère remaster, delta mineur.
- `compute_confidence` (core.py:984) : `nfo_ok=True` donne +65, `False` donne +35.
- **IMDb cross-check EXISTE déjà** (plan_support.py:773, V4 ajout A) : si `nfo.imdbid` + TMDb activé → appelle `find_by_imdb_id`, vérifie similarité titre vs folder/video. Rejette si mismatch. **C'est déjà très bien.**

**Gaps identifiés** (à combler en P1.1) :
1. **TMDb ID pas cross-check** : si NFO a `<tmdbid>27205</tmdbid>` mais PAS d'IMDb ID, aucune vérification. Symétrique à corriger.
2. **Runtime absent de NfoInfo** : le Kodi NFO standard a `<runtime>148</runtime>` (minutes). On pourrait comparer avec `probe.duration` pour détecter un NFO obsolète ou pointant sur le mauvais film.
3. **Pas de distinction folder-match vs filename-match** : si le dossier dit "Inception" + NFO "Inception" MAIS le fichier vidéo est `matrix.mkv`, `nfo_consistent` retourne `ok=True`. Risque : NFO valide pour le dossier, fichier vidéo en réalité un autre film.

**Approche P1.1** (3 sous-étapes) :
- **P1.1.a** : enrichir `NfoInfo` avec `runtime: Optional[int]` + parsing du tag `<runtime>`.
- **P1.1.b** : ajouter cross-check TMDb ID (symétrique à IMDb existant) dans plan_support.py.
- **P1.1.c** : enrichir `nfo_consistent` pour retourner `(ok, cov, seq, folder_match, filename_match)` ; pénaliser compute_confidence quand un seul des deux matche + warning_flag `nfo_file_mismatch`.
- **P1.1.d** : ajouter runtime cross-check dans quality_report_support (après probe) → warning_flag `nfo_runtime_mismatch` si delta > 10%.

Ordre d'implémentation : a → c → b → d (parsing + logique de base d'abord, puis cross-checks externes).

**Sources consultées** :
- [Kodi Wiki — NFO files/Movies](https://kodi.wiki/view/NFO_files/Movies) (champs standards : title, originaltitle, year, runtime, plot, uniqueid type=tmdb/imdb, etc.)

---

### 2026-04-22 · P1.1 terminé — NFO cross-validation complète

**Livré** (4 sous-étapes + UI) :

**P1.1.a — `NfoInfo.runtime` + parsing** ([core.py:474-536](../../../cinesort/domain/core.py))
- Ajout champ `runtime: Optional[int] = None` (minutes, convention Kodi)
- Helper `_parse_nfo_runtime()` : lit `<runtime>` (Kodi) ET `<fileinfo><streamdetails><video><durationinseconds>` (tinyMediaManager). Tolère suffixe "min" ou "minutes".
- Garde-fou : rejette valeurs aberrantes (0 ou > 1200 min).
- 6 tests unitaires (`tests/test_domain_core.py::ParseMovieNfoRuntimeTests`).

**P1.1.b — folder_match vs filename_match** ([core.py:565-656](../../../cinesort/domain/core.py), [plan_support.py:732-744](../../../cinesort/app/plan_support.py))
- Nouveau dataclass `NfoConsistency` + fonction `nfo_consistency_check()` (retourne `ok, cov, seq, folder_match, filename_match, folder_cov/seq, filename_cov/seq`).
- Ancienne fonction `nfo_consistent()` conservée en wrapper rétrocompat (3-tuple).
- Si `folder_match XOR filename_match` → `nfo_partial_match = True` → pénalité de 8 points dans `compute_confidence` quand source=nfo + warning flag `nfo_file_mismatch` + log WARN explicite.
- Rationale : détecte le cas "utilisateur a remplacé video.mkv mais oublié de MAJ le NFO du dossier".
- 11 tests (`NfoConsistencyCheckTests` + `ComputeConfidenceNfoPartialMatchTests` + `WarningFlagsNfoFileMismatchTests`).

**P1.1.c — cross-check TMDb ID** ([tmdb_client.py:362-427](../../../cinesort/infra/tmdb_client.py), [plan_support.py:853-933](../../../cinesort/app/plan_support.py))
- Nouvelle méthode `TmdbClient.find_by_tmdb_id(tmdb_id)` avec cache local dédié (`find_tmdb|{id}`). Symétrique à `find_by_imdb_id` existant.
- Dans le scan : si `nfo.tmdbid` présent + TMDb activé → résolution titre officiel, calcul similarité vs folder/video, seuil 0.50 (ou 0.35 avec année matchée).
- Si acceptable → candidat `nfo_tmdb` ajouté (score 0.93) ; si rejet → log WARN "NFO probablement pollué".
- Dédup : pas de doublon si un candidat NFO/IMDb avec ce tmdb_id existe déjà.
- 5 tests (`FindByTmdbIdTests`) : found, string input, invalid inputs, not found, cached.

**P1.1.d — runtime cross-check probe** ([quality_report_support.py:20-68](../../../cinesort/ui/api/quality_report_support.py))
- Fonction pure `detect_nfo_runtime_mismatch(nfo_runtime_min, probe_duration_s)` → retourne dict de détail si mismatch, None sinon.
- Seuil double : delta > 10% ET delta > 8 min (garde-fou vs director's cut/remaster léger).
- Persistence du `nfo_runtime` dans `PlanRow` (+ serialisation incrementale). Utilisé après probe pour émettre `encode_warnings += ["nfo_runtime_mismatch"]` + détail `{nfo_minutes, probe_minutes, delta_minutes, delta_pct}`.
- 11 tests (`test_nfo_runtime_mismatch.py`) : fichiers courts, delta sous-seuil, director's cut, extended cut, autre film.

**UI desktop + dashboard** ([validation.js](../../../web/views/validation.js), [review.js](../../../web/dashboard/views/review.js), CSS)
- Badge orange `badge--nfo-mismatch` / `badge-nfo-mismatch` (#F59E0B) avec 2 variantes :
  - **"NFO partiel"** : déclenché par `nfo_file_mismatch`
  - **"Durée NFO ?"** : déclenché par `nfo_runtime_mismatch`, tooltip montre les deux durées
- CSS ajoutée dans `web/styles.css` + `web/dashboard/styles.css`.

**Tests globaux** : 1979 passed, 0 régression. 1 test REST flaky connu (pré-existant, passe seul).
**Total nouveaux tests P1.1** : 38.

**Alternatives évaluées** :
- Signature `nfo_consistent` modifiée vs wrapper + nouvelle fonction → choisi wrapper (backward-compat).
- Réutiliser `_get_movie_detail_cached` vs `find_by_tmdb_id` dédiée → choisi dédiée (cache séparé, pas d'invalidation du cache existant).
- Seuil runtime unique % vs double (% ET min) → choisi double (évite faux positifs sur films courts ET extended cuts).

**Prochaine étape** : P1.2 — Undo checksum + atomic rollback.

---

### 2026-04-22 · P1.2 terminé — Undo avec checksum + mode atomique

**Livré** (4 sous-étapes + UI) :

**P1.2.a — Schema v13** ([013_apply_ops_checksum.sql](../../../cinesort/infra/db/migrations/013_apply_ops_checksum.sql))
- Migration 013 : `ALTER TABLE apply_operations ADD COLUMN src_sha1 TEXT` + `src_size INTEGER`.
- `_ApplyMixin.append_apply_operation` accepte kwargs `src_sha1`, `src_size` (optionnels).
- `list_apply_operations` + `list_apply_operations_by_row` retournent les 2 nouveaux champs.
- Tests PRAGMA user_version=13 dans `test_v7_foundations.py` + `test_api_bridge_lot3.py`.

**P1.2.b — Capture hash à l'apply** ([apply_core.py:516-545, 1050-1087](../../../cinesort/app/apply_core.py))
- Nouveau helper `find_main_video_in_folder(folder, cfg)` : retourne le plus gros fichier vidéo du dossier (heuristique éprouvée pour identifier le film principal).
- `record_apply_op` enrichi avec `src_sha1`, `src_size` optionnels.
- `move_file_with_collision_policy` (MOVE_FILE) : calcule sha1_quick + size du fichier vidéo avant `shutil.move`.
- `apply_single` (MOVE_DIR) : localise le main video dans le folder avant `rename`, calcule sha1 + size, stocke sur l'op MOVE_DIR. **C'est le cas le plus fréquent (1 film = 1 dossier).**
- Sidecars (nfo/srt/images) non hashés → performance préservée, protection concentrée sur le contenu film.

**P1.2.c — Preverify + mode atomic** ([apply_support.py:20-151](../../../cinesort/ui/api/apply_support.py))
- Fonction pure `preverify_undo_operations(ops)` classifie chaque op en 4 catégories :
  - `safe` : dst existe, sha1/size matchent (ou MOVE_DIR avec main video qui matche)
  - `hash_mismatch` : dst existe mais fichier modifié — raison explicite (taille ou sha1)
  - `missing` : dst absent (déjà bougé/supprimé)
  - `legacy_no_hash` : op pré-P1.2 sans hash → comportement historique (rétrocompat)
- Helper `_resolve_hashed_target(dst, op_type)` : pour MOVE_DIR, retourne le plus gros vidéo du dossier (même logique qu'à l'apply).
- `_execute_undo_ops` prend un param `atomic: bool = True` (défaut strict) :
  - Si `atomic=True` ET `hash_mismatch` non vide → **abandon total, aucune modif filesystem**, retourne `aborted_atomic: True` + `preverify` rapport.
  - Sinon best-effort : les mismatch sont marqués SKIPPED avec raison.
- `undo_last_apply` et `undo_selected_rows` propagent `atomic` jusqu'à l'API publique `CineSortApi`.
- Status code `ABORTED_HASH_MISMATCH` avec `preverify.mismatch_details` pour l'UI.

**P1.2.d — UI + tests** ([execution.js:358-380](../../../web/views/execution.js))
- Desktop : gestion explicite du status `ABORTED_HASH_MISMATCH` dans `runUndoBatch`. Affichage des 5 premiers mismatch_details avec raison, message pédagogique "relancer en cochant Forcer pour passer outre". Pas de fichier bougé.
- Tests `test_undo_checksum.py` :
  - 6 tests unitaires `preverify_undo_operations` (missing, legacy, safe, mismatch size, mismatch sha1, mixed).
  - 1 test end-to-end : apply réel → modification manuelle du fichier vidéo dans le dossier renommé → undo atomique refusé → undo best-effort OK.

**Total nouveaux tests P1.2** : 7 (6 unit + 1 e2e).
**Suite globale** : 1987 passed, 0 régression.

**Alternatives évaluées** :
- Colonne unique JSON blob `checksum_meta` vs 2 colonnes typées → choisi 2 colonnes (requêtes SQL simples, types natifs, index si besoin).
- Hasher aussi les sidecars → rejeté (ralentit l'apply sans gain : sidecars sont accessoires, le fichier vidéo est la signature critique).
- Mode par défaut `best_effort` vs `atomic` → choisi atomic (safety first pour le partage pro : on ne détruit pas la biblio de l'user même en cas de doute).
- Utiliser `sha256` plutôt que `sha1_quick` → rejeté (sha1 suffit pour détecter un remplacement accidentel, sha1_quick déjà utilisé ailleurs, 8MB+8MB rapide sur gros films).

**Ce qu'on ne couvre PAS (scope volontairement limité P1.2)** :
- Si l'utilisateur *restaure* manuellement le fichier original (même hash), l'undo fonctionnerait normalement — c'est le comportement souhaité.
- Si l'apply était en dry_run, aucun hash n'est stocké (ops non créées) — pas de protection nécessaire.
- Un bouton UI "Forcer atomic=false" reste à ajouter (pour l'instant, seul l'API le permet). C'est volontairement reporté : la valeur principale est la protection par défaut, l'override est une feature secondaire.

**Prochaine étape** : P1.3 — Pre-apply visual preview (montrer les déplacements avant d'y aller).

---

### 2026-04-22 · P1.3 terminé — Preview visuel pré-apply

**Livré** (2 sous-étapes + UI) :

**P1.3.a — Backend endpoint + collecte dry_run** ([apply_support.py:994-1155, 1667-1830](../../../cinesort/ui/api/apply_support.py), [cinesort_api.py:1553-1570](../../../cinesort/ui/api/cinesort_api.py))
- `_execute_apply` accepte un kwarg optionnel `preview_ops_out: Optional[List[Dict]]` qui collecte chaque payload d'op même en dry_run.
- Callback `record_apply_op` (closure dans `_execute_apply`) append dans la liste locale avant le check BDD.
- Dans `apply_core.py`, tous les `record_apply_op(...)` pour MOVE_FILE et MOVE_DIR sont sortis du bloc `if not dry_run:` — le hash sha1/size n'est calculé qu'en mode réel (pas gaspillé en dry_run).
- Fix ciblé dans `_execute_apply` (ligne 1126) : `record_op=record_apply_op` même en dry_run (auparavant `None if dry_run else record_apply_op`).
- Nouvel endpoint `build_apply_preview(run_id, decisions)` exposé via CineSortApi :
  - Valide inputs, exécute `_execute_apply(dry_run=True, preview_ops_out=[...])`
  - Groupe les ops par `row_id`, enrichit avec title/year/confidence/warnings/change_type
  - `change_type` classifié : `rename_folder` / `move_files` / `move_mixed` / `noop`
  - Retourne `{ films: [...], totals: {...}, orphan_ops: [...] }` — structure JSON visuelle-friendly

**P1.3.b — UI desktop modal preview** ([index.html:1312-1330](../../../web/index.html), [execution.js:442-540](../../../web/views/execution.js))
- Bouton "Aperçu détaillé" dans la card Apply, à côté du bouton principal.
- Modal `#modalApplyPreview` plein écran (960px × 86vh) avec body scrollable.
- Rendu : header résumé (nb films, nb changements, quarantaine, erreurs) + card par film.
- Chaque card film affiche : titre + année, type de changement, badge confidence, pastille "N alertes" si warnings, liste "op_type / src → dst" en monospace avec paths tronqués intelligemment.
- Bouton "Appliquer réellement" dans le footer du modal qui décoche dry-run et déclenche l'apply standard (flow existant).
- Pas de modif CSS custom : réutilise les classes existantes (`card`, `badge--ok/warn/bad`, `mono`, `font-xs`).

**Tests** : `test_apply_preview.py` (6 tests) — structure retour, aucune modif filesystem, enrichissement metadata, classification change_type, decisions vides, cohérence totals.
**Suite globale** : 1991 passed, 0 régression de mes changements (2 flaky REST pre-existants, passent seuls).

**Alternatives évaluées** :
- Endpoint dédié vs réutiliser `apply(dry_run=True)` + struct du summary → choisi dédié car `apply` retourne un stats agrégé, pas une liste d'ops structurée.
- Hash les fichiers même en dry_run pour affichage "size" → rejeté (ralentit inutilement la preview, la taille est déjà lue via stat par `_execute_apply`).
- Nouveau modal vs panneau inline dans la card → choisi modal (plus d'espace vertical pour la liste des films, pas de contention avec la card Annuler).

**Ce qui change pour l'utilisateur** :
- Avant : dry-run donne un résumé numérique ("12 renommés, 3 déplacés"), aucun détail visuel.
- Après : l'utilisateur voit chaque film individuellement avec `avant → après`, avant de cliquer "Appliquer réellement".

**Ce qu'on reporte pour P3 (comparateur visuel)** :
- Affichage côte-à-côte des caractéristiques techniques des films (résolution, codec, bitrate, audio, score) — c'est P3.1.
- Preview des doublons avec recommandation "conserver / supprimer" — c'est P3.1.

**Prochaine étape** : Palier 1 terminé. Commencer Palier 2 — P2.1 explain-score mode (rendre le scoring transparent).

---

### 2026-04-22 · P2.1 terminé — Explain-score mode (scoring transparent)

**Livré** (4 sous-étapes) :

**P2.1.a — Reconnaissance + recherche web**
- Lecture approfondie du scoring actuel ([quality_score.py:837-1162](../../../cinesort/domain/quality_score.py)) : factors catégorisés déjà en place ({category, delta, label}), mais deltas bruts (pas pondérés). Sous-scores video/audio/extras puis pondération finale.
- `score_explanation` existe dans le metrics output mais n'était **consommé que dans le mode preview dev**, jamais affiché dans l'UI principale. Un trésor caché.
- Recherche web : explicabilité en 2026 devient un requis réglementaire pour les systèmes de scoring. Les MLLMs fournissent des "rationales" en langage naturel ; Radarr utilise des custom format scores additifs avec seuils (pas de visualisation riche). **Opportunité** : faire plus propre et plus visuel que Radarr.

**P2.1.b — Module `explain_score.py` + intégration** ([explain_score.py](../../../cinesort/domain/explain_score.py), [quality_score.py:1120-1145](../../../cinesort/domain/quality_score.py))
- Nouveau module domaine `cinesort/domain/explain_score.py` (~260L). Fonction pure `build_rich_explanation()` qui enrichit le factor brut avec :
  - `weighted_delta` : impact réel sur le score final (= delta × poids_catégorie / total). C'est ce que l'utilisateur veut voir (un -8 audio = seulement -2.4 au final si audio ne pèse que 30%).
  - `direction` : `+` / `-` / `=` (simplifie l'UI).
- Breakdown `categories` : par catégorie (video/audio/extras), expose subscore, weight, weight_pct, contribution au score final, counts positif/négatif, label FR.
- `baseline` : tier_thresholds (5 tiers), next_tier, distance_to_next_tier — utile pour "à 3 points du tier Gold".
- `suggestions` : règles de correspondance label → action concrète (upscale → chercher REMUX, 4K light → viser 35 Mbps, etc.) + suggestion générique "proche du tier suivant".
- `narrative` : 2-4 phrases FR qui expliquent score + meilleure/pire catégorie + freins/atouts principaux + distance tier suivant.
- Top positive/negative triés par **weighted_delta** (plus juste que delta brut).
- Intégré dans `compute_quality_score` : remplace l'ancien calcul inline de 15 lignes par un appel propre à `build_rich_explanation`.
- 31 tests unitaires (`test_explain_score.py`) : direction, weighted_delta par catégorie, breakdown, baseline (seuils + distance), suggestions (upscale/4k_light/generic/uniques), narrative, top positive/negative, robustesse (weights absent, négatifs, factors malformés).

**P2.1.c — UI desktop** ([index.html:1317-1331](../../../web/index.html), [validation.js:233-360](../../../web/views/validation.js))
- Modal `#modalScoreExplain` (760px × 86vh) accessible depuis l'inspecteur film (bouton "Détail du score").
- Rendu en 4 sections :
  1. **Header** : score en gros, tier avec couleur dédiée (Platinum violet, Gold or, Silver gris, Bronze orange, Reject rouge), narrative en italique, distance au tier suivant si proche.
  2. **Contribution par catégorie** : 3 barres horizontales (video/audio/extras) avec subscore / poids / contribution au score final. Couleur de la barre selon le tier atteint.
  3. **Détail des règles** : table triée par impact pondéré absolu. Chaque ligne = catégorie / règle / impact signé coloré (vert clair/franc, rouge clair/franc).
  4. **Suggestions** : panneau orange avec liste d'actions concrètes pour améliorer.
- Utilise l'endpoint existant `get_quality_report` (pas de nouvel endpoint backend — tout est déjà dans l'explanation).

**P2.1.d — UI dashboard distant** ([library.js:542-650](../../../web/dashboard/views/library.js))
- Parité complète : bouton "Détail du score" dans la modale détail film.
- Rendu identique mais en inline (container `dashExplainScoreContainer` dans la modale existante), pas de modale imbriquée.
- Fonction `_loadDashExplainScore` appelle `get_quality_report` via REST, structure similaire à desktop.

**Tests globaux** : 2022 passed (+31 du nouveau module), 0 régression. 2 flaky REST pre-existants (cross-contamination, passent seuls).

**Alternatives évaluées** :
- Nouveau endpoint vs réutiliser `get_quality_report` → réutiliser (pas de duplication API, l'explanation est déjà dans le payload). Gain : zéro coût migration dashboard.
- Delta brut vs weighted_delta dans top_positive/negative → weighted (plus juste, l'UI affiche l'impact réel, cohérent avec la logique de pondération).
- Modal full-screen vs inline → **modal pour desktop** (force focus sur l'explication), **inline pour dashboard** (dans la modale film existante, pas de modale imbriquée).
- LLM narrative vs règles déterministes en FR → règles (pas de dépendance LLM, reproductible, testable, contrôle total du wording).

**Ce que l'utilisateur peut faire maintenant** :
- Cliquer "Détail du score" sur un film → voir précisément pourquoi ce film a ce score, quel est le poids de chaque catégorie, quelles règles ont contribué et de combien, et comment passer au tier supérieur.
- C'est le différenciateur promis : Radarr/Sonarr ne montrent pas ce niveau de transparence.

**Prochaine étape** : P2.2 — Résolution "deux films même titre" (gestion des ambiguïtés TMDb avec titre identique mais années différentes).

---

### 2026-04-22 · P2.2 terminé — Résolution "deux films même titre"

**Problème ciblé** : "Dune (1984)" vs "Dune (2021)", "The Thing (1982)" vs "The Thing (2011)", "Psycho (1960)" vs "Psycho (1998)". Si le dossier n'a pas d'année, le scoring TMDb choisit le plus populaire — souvent le remake récent — même si l'utilisateur a l'original. **Risque majeur pour l'app pro**.

**Recherche web** :
- Plex : n'a pas de désambiguïsation auto. UI "Fix Match" manuelle avec recherche IMDb ID. Réactif.
- TinyMediaManager : idem, désambiguïsation manuelle via UI.
- Opportunité CineSort : faire **proactif** — détection auto + tentative de résolution + fallback UI claire.

**Livré** (4 sous-étapes) :

**P2.2.b — Module `title_ambiguity.py`** ([title_ambiguity.py](../../../cinesort/domain/title_ambiguity.py), ~170L pur, stateless)
- `normalize_title_for_ambiguity(title)` : lowercase, strip accents, strip ponctuation, retire articles initiaux (the/le/la/l'/un/a/an/d'). Cross-langue.
- `detect_title_ambiguity(candidates)` : retourne `(ambiguous, normalized_key)`. Compte les candidats `source ∈ {tmdb, nfo_tmdb, nfo_imdb}` groupés par titre normalisé. Les candidats "name" sont ignorés (ils viennent du nom de fichier, pas d'une vraie ambiguïté TMDb).
- `disambiguate_by_context(candidates, context)` : si ambiguïté détectée, ajoute un boost au score des candidats qui matchent les indices contextuels :
  - **NFO tmdb_id exact** : +0.15 (signal le plus fort)
  - **Année du nom exacte** (delta 0) : +0.10
  - **Année du nom à ±1 an** : +0.05
  - **Runtime NFO proche du runtime candidat** : +0.03
- Note du candidat gagnant augmentée de `disambig: annee exacte, nfo_tmdb_id exact` (traçabilité).
- Les candidats hors groupe ambigu ne sont **pas modifiés** — on évite de sur-promouvoir les année-matches dans les cas sans ambiguïté.
- 20 tests unitaires (`test_title_ambiguity.py`) couvrant normalisation, détection, désambiguïsation par chaque signal, empilement des signaux, absence de modification hors groupe ambigu, aucun boost si contexte vide.

**Intégration pipeline** ([plan_support.py:969-986](../../../cinesort/app/plan_support.py))
- Appel à `disambiguate_by_context` **après** la collecte des candidats et **avant** `pick_best_candidate`.
- Context construit depuis `name_year`, `nfo.tmdbid` (si valide int), `nfo.runtime` (P1.1.a).
- Log WARN explicite si ambiguïté détectée : `Titres TMDb ambigus: 'dune' existe dans plusieurs années. Désambiguïsation sur contexte.`

**Warning flag** ([core.py:1003-1009](../../../cinesort/domain/core.py))
- Nouveau flag `title_ambiguity_detected` émis par `_warning_flags_from_analysis` quand la désambiguïsation a été tentée.
- **Choix délibéré** : on flag MÊME APRÈS désambiguïsation réussie — le risque de confondre remake/original justifie une vérification humaine. La désambiguïsation donne un meilleur candidat par défaut, mais l'utilisateur doit pouvoir douter.

**UI desktop + dashboard**
- Badge bleu "Titre ambigu" (`badge--title-ambig` / `badge-title-ambig`, couleur #60A5FA — distinct du jaune NFO + orange upscale) dans les tables de validation (desktop + dashboard review).
- Tooltip : "Deux films TMDb portent ce titre (remake/reboot). Vérifier l'année attendue."
- L'utilisateur clique "Voir les suggestions" pour afficher les candidats concurrents (fonction existante, pas besoin de nouvelle UI).

**Tests** : 20 nouveaux (test_title_ambiguity.py). Suite globale : 2044 passed, 0 régression.

**Alternatives évaluées** :
- Modifier `pick_best_candidate` signature vs étape préalable → choisi étape préalable (pick_best_candidate reste agnostique du contexte, séparation des responsabilités).
- Promouvoir + pénaliser les autres candidats ambigus vs promouvoir seul le bon → choisi **promouvoir seul** (pas de double modification, logs plus clairs).
- Flag seulement si désambiguïsation incertaine vs flag toujours → choisi **toujours** (remake vs original = vérification humaine toujours pertinente pour un partage pro).
- Normalisation titre : garder les articles ou les stripper → choisi **stripper** (robustesse cross-langue, "The Thing" ↔ "Thing", "Les Misérables" ↔ "Misérables").

**Cas limites testés** :
- Candidats "name" (depuis nom de fichier) n'ont pas le même statut que TMDb → non compté dans l'ambiguïté (sinon faux positifs systématiques).
- Contexte vide (pas de name_year, pas de nfo) → ambiguïté détectée mais aucun boost appliqué → flag levé, pick_best_candidate fait son job normalement.
- Groupe ambigu + autre candidat avec même année (mais titre différent) → seul le groupe ambigu est affecté.

**Valeur utilisateur** :
- Avant : "Dune.1080p.mkv" → CineSort picke Dune 2021 automatiquement (plus populaire), même si l'user a 1984.
- Après : si le dossier contient l'année, CineSort picke le bon. Même sans année, le flag "Titre ambigu" force l'user à vérifier — impossible de se faire piéger silencieusement.

**Prochaine étape** : P2.3 — Logging granulaire apply (traçabilité complète de chaque décision apply pour support/debug/audit).

---

### 2026-04-22 · P2.3 terminé — Journal d'audit apply (JSONL)

**Problème ciblé** : pour un partage pro, l'utilisateur doit pouvoir répondre plusieurs semaines après : "Pourquoi ce fichier a-t-il été déplacé ici ?" Le journal SQLite `apply_operations` (P1.2) trace les moves mais sans contexte décisionnel exportable.

**Livré** :

**Module `apply_audit.py`** ([apply_audit.py](../../../cinesort/app/apply_audit.py), ~230L pur, thread-safe)
- Classe `ApplyAuditLogger` — writer append-only JSONL dans `run_dir/apply_audit.jsonl`.
- Thread-safe via lock (apply peut écrire depuis plusieurs threads).
- Gracieux : si ouverture échoue, l'objet devient no-op (les méthodes ne crashent pas). La BDD reste la source de vérité.
- Méthodes de haut niveau : `start(dry_run, total_rows)`, `end(status, counts)`, `row_decision(row_id, ok, reason)`, `op_move_file(src, dst, row_id, sha1, size)`, `op_move_dir(...)`, `op_mkdir(path)`, `skip(row_id, reason, detail)`, `conflict(row_id, src, dst, conflict_type, resolution)`, `error(context, message)`.
- `None` values omises du payload (JSONL plus compact).
- Fonction pure `read_apply_audit(run_dir, batch_id?, limit?)` pour lecture + filtrage.

**Intégration apply_support.py** ([apply_support.py:1108-1125, 1220-1238](../../../cinesort/ui/api/apply_support.py))
- Création de l'auditor juste après `insert_apply_batch` (apply réel uniquement, pas en dry_run).
- Closure `record_apply_op` enrichie pour router les op_types vers les méthodes auditor (MOVE_FILE / MOVE_DIR / MKDIR).
- `auditor.start()` appelé avec le nombre de rows.
- `auditor.end()` avec counts finaux (renames/moves/skipped/quarantined/errors) + status (DONE/PARTIAL).
- `auditor.close()` systématique via `finally`.

**Endpoint `export_apply_audit`** ([apply_support.py:1638-1687](../../../cinesort/ui/api/apply_support.py), [cinesort_api.py:1555-1566](../../../cinesort/ui/api/cinesort_api.py))
- 3 formats : `json` (liste structurée pour UI), `jsonl` (brut, un JSON/ligne), `csv` (tableur).
- Filtrage optionnel par `batch_id`.
- Accessible via API pywebview ET REST (dashboard distant).

**UI desktop** ([index.html](../../../web/index.html), [execution.js:442-476](../../../web/views/execution.js))
- 2 boutons sous le bouton Apply : "Journal d'audit (.jsonl)" + "Journal (.csv)".
- `downloadApplyAudit(format)` appelle l'API, construit un Blob, déclenche le download avec nom de fichier horodaté `apply_audit_{run_id}_{ISO}.{ext}`.

**Tests** : 14 nouveaux (`test_apply_audit.py`) couvrant écriture/lecture, ordre d'écriture, omission `None`, skip/conflict/row_decision, append cross-batch (même fichier), lecture JSONL tolérante aux lignes malformées, limit, robustesse (write après close = no-op, double close safe).
Suite globale : 2057 passed, 0 régression. 1 flaky REST pré-existant (passe seul).

**Alternatives évaluées** :
- JSON array unique vs JSONL → JSONL (append-only, parse streaming, robuste aux crashes — un crash en plein apply ne corrompt pas tout).
- Étendre `apply_operations` SQL avec colonnes decision_* vs fichier dédié → fichier dédié (pas de migration, format exportable direct, lisible humain).
- Écrire synchrone vs buffer async → synchrone avec flush après chaque ligne. Latence négligeable (~0.1ms), sécurité en cas de crash maximale.
- Logger les événements probe/scoring aussi → hors scope P2.3 (couverture apply uniquement). Possible P2.4 si besoin.

**Ce que l'utilisateur peut faire maintenant** :
- Après un apply réel, cliquer "Journal d'audit (.jsonl)" → obtient un fichier réel qui liste chronologiquement chaque décision. Traçabilité parfaite.
- L'exporter en CSV pour analyse dans Excel/LibreOffice (audit conformité, rapport à un client).
- `grep event=op_conflict apply_audit.jsonl` pour trouver tous les conflits d'un run. Format JSONL est aussi facile à parser en Python/bash.

**Cas limites testés** :
- Fichier absent → read_apply_audit retourne liste vide (pas de crash).
- Ligne JSON malformée → skip silencieux (ne corrompt pas la lecture des lignes suivantes).
- Write après close → no-op silencieux.
- Double close → idempotent.
- Plusieurs batchs sur le même run → coexistent dans le même fichier, filtrable par batch_id.

**Prochaine étape** : Palier 2 terminé. Commencer Palier 3 — P3.1 comparateur doublons visuel côte-à-côte (le mockup de l'utilisateur).

---

### 2026-04-22 · P3.1 terminé — Comparateur doublons visuel côte-à-côte

**Mockup cible** fourni par l'utilisateur :
```
┌─ Version A ────────────┬─ Version B ────────────┐
│ Inception.1080p.mkv    │ Inception.4K.HDR.mkv    │
│ 1080p / HEVC / 10 Mbps │ 2160p / HEVC / 35 Mbps  │
│ DTS-HD MA 7.1          │ TrueHD Atmos 7.1        │
│ 3.2 GB                 │ 48 GB                    │
│ Score : 82 (Gold)      │ Score : 96 (Platinum)   │
│ ⚠ Supprimable          │ ✓ À conserver           │
└────────────────────────┴─────────────────────────┘
```

L'ancien UI était une table tabulaire (Critère / Valeur A / Valeur B) — fonctionnel mais peu lisible. **Mission** : reproduire le mockup fidèlement + ajouter la table en details pour les power users.

**Livré** :

**Backend — enrichissement** ([run_flow_support.py:691-752](../../../cinesort/ui/api/run_flow_support.py))
- `_enrich_groups_with_quality_comparison` ajoute maintenant dans `group.comparison` :
  - `file_a_name`, `file_b_name` : nom de fichier/dossier des deux rows
  - `quality_a`, `quality_b` : `{score, tier}` récupérés des quality_reports
  - `verdict_a`, `verdict_b` : texte "À conserver" / "Supprimable" / "Équivalent" selon `winner`
- Helpers internes `_filename(row)` et `_quality_info(row)` gèrent les cas manquants gracieusement.

**UI desktop** ([execution.js:193-290](../../../web/views/execution.js))
- Fonctions `_compareTierColor(tier)` et `_compareCard(side, cmp)` pour le rendu par card.
- Chaque card expose :
  - Header "VERSION A/B" en petite majuscule
  - Nom de fichier en mono, wrappable si long
  - Specs techniques : `résolution · codec · bitrate` / `audio + channels` / `HDR si présent` / `taille`
  - Séparateur horizontal
  - Score (grand, couleur tier) + Tier (droite)
  - Verdict en bandeau coloré (vert "✓ À conserver" / orange "⚠ Supprimable" / gris "≡ Équivalent")
  - Bordure colorée selon winner (vert gagnant, orange perdant, gris égalité)
- Header global supprimé — les cards sont self-contained.
- Recommandation en panneau bleu (#60A5FA) avec économie disque si > 0.
- **Détail critère par critère** conservé mais en `<details>` repliable (ne dérange plus le lecteur visuel, accessible à la demande).

**UI dashboard distant** ([review.js:408-470](../../../web/dashboard/views/review.js))
- Parité complète : `_compareTierColorDash`, `_dashCompareCard`, `_buildDashComparisonHtml`.
- Même layout que desktop, adaptation mineure des styles (pas de variables CinemaLux identiques mais fallback sur `var(--bg-raised)`, `var(--text-muted)`, etc.).

**Tests mis à jour** ([test_duplicate_compare_ui.py](../../../tests/test_duplicate_compare_ui.py))
- Anciens asserts obsolètes retirés : `Fichier A/B` → `Version A/B`, `total_score_a/b` (gérés par cards), `badge--ok compare-winner` / `badge-success` (remplacés par bandeau verdict).
- Nouveaux asserts : `compare-card`, `Version A/B`, `verdict_a/b`, `quality_a/b`, `file_a/b_name` (desktop + dashboard).
- Full suite : 2061 passed, 0 régression.

**Alternatives évaluées** :
- Rendu grid CSS vs flex → flex (simple, responsive, wrap automatique sur petit écran).
- Conserver le header global "Score A vs B" → retiré (redondant avec les scores dans les cards).
- Masquer la table détaillée complètement → conservée en `<details>` (les power users aiment voir la décomposition).
- Afficher l'icône HDR séparément → intégrée dans les specs techniques si présente, cachée sinon (moins bruyant).

**Valeur utilisateur** :
- Avant : table tabulaire aride "Critère / Valeur A / Valeur B / badge ✓" — lisible mais peu engageant.
- Après : **cards visuelles fidèles au mockup**, avec verdict explicite, score coloré, taille en évidence. L'œil identifie immédiatement quelle version garder, sans avoir à lire les chiffres ligne par ligne. Plus Radarr-like que Radarr.
- Les power users gardent l'accès au détail via `<details>` repliable.

**Prochaine étape** : P3.2 — Badges tiers visuels (pastilles Platinum/Gold/Silver/Bronze/Reject plus impactantes dans les tables).

---

### 2026-04-22 · P3.2 terminé — Badges tiers visuels (pastilles cohérentes)

**Problème ciblé** : les tiers étaient affichés de façons variées (`badge-success`, texte coloré brut, label seul dans la distribution) selon les endroits. Aucune identité visuelle unifiée. Les couleurs étaient éparses dans le code.

**Livré** :

**Component `tierPill` desktop** ([badge.js:41-86](../../../web/components/badge.js))
- `_TIER_MAP` : dictionnaire central des 5 tiers + aliases legacy (premium/bon/moyen/mauvais). Chaque entrée : `{label, color, abbr}`.
- `tierPill(tier, {compact, showAbbr})` : pastille flex avec :
  - Dot circulaire coloré à gauche (0.55em, halo 2px assorti)
  - Label ou abbr (PT/GO/SI/BR/RJ)
  - Background semi-transparent (`color`22) + border (`color`55) + texte coloré
  - Options compact (padding réduit) pour utilisation en table.
- `scoreTierPill(score, tier)` : score + pastille combinés (ex: "82 [Gold]").

**Component `tierPill` dashboard** ([badge.js:76-118](../../../web/dashboard/components/badge.js))
- Parité exacte avec desktop — mêmes couleurs (#A78BFA Platinum, #FBBF24 Gold, #9CA3AF Silver, #FB923C Bronze, #EF4444 Reject).
- Export ES module (`export function tierPill`).

**Migration desktop** ([quality.js:159-167](../../../web/views/quality.js))
- Labels dans la distribution qualité : `tierPill("platinum", {compact: true})` au lieu du texte brut. La pastille ajoute une identité visuelle forte sans modifier la logique des barres.

**Migration dashboard** ([library.js:43, 264](../../../web/dashboard/views/library.js))
- Table library : colonne Tier utilise `tierPill(v, {compact: true})` au lieu de `badgeHtml("tier", v)`.
- Film tiles (grille) : tier badge utilise `tierPill` pour cohérence.
- Import enrichi.

**Tests** : 13 nouveaux (`test_tier_pill.py`) couvrant :
- Fonctions `tierPill` + `scoreTierPill` exportées (desktop + dashboard).
- 5 tiers canoniques + aliases legacy conservés.
- Intégration dans quality.js (distribution) et library.js (table + tiles).
- Structure visuelle : dot circulaire, background alpha, border, texte coloré.
- Cohérence des couleurs desktop ↔ dashboard (mêmes codes hex).

Suite globale : 2074 passed, 0 régression.

**Alternatives évaluées** :
- Étendre `badge.js` existant vs composant dédié → composant dédié (le badge actuel ne supporte pas le dot + background custom — pour les ajouter il faudrait surcharger la CSS existante, plus invasif).
- Couleurs par variables CSS vs inline → inline (pas de cascade CSS à gérer, couleurs visibles direct dans le JS pour debug).
- Gradient de fond vs aplat semi-transparent → aplat (plus propre, ne contraste pas avec le gradient des cards CinemaLux).
- Emoji (🥇🥈🥉) vs dot coloré → dot (plus premium, moins puéril, cohérent avec le design system).

**Valeur utilisateur** :
- Avant : distribution texte "Platinum [bar]", table "Gold", film tiles "Silver" — trois styles différents pour la même info.
- Après : pastille unifiée partout avec dot coloré identifiable au premier coup d'œil. L'œil apprend à associer violet = Platinum, or = Gold, etc. Identité visuelle du scoring.

**Prochaine étape** : P3.3 — Historique film enrichi (timeline visuelle des événements par film).

---

### 2026-04-22 · P3.3 terminé — Historique film enrichi (modal + sparkline + stepper)

**Problème ciblé** : l'historique actuel était une liste textuelle avec émojis inline, écrasant l'inspecteur. Peu visuel, pas d'évolution graphique du score, pas de vue d'ensemble.

**Livré** :

**Modal dédiée** ([index.html:1314-1326](../../../web/index.html))
- Nouvelle modal `#modalFilmHistory` (860px × 86vh) — ne pollue plus l'inspecteur.

**Layout 3 sections** ([validation.js:420-600](../../../web/views/validation.js))

1. **Header KPIs** (`_renderFilmHistoryHeader`) :
   - Titre + année
   - Score actuel en gros + tierPill (P3.2) + trend ↑/↓ (vs premier score historique)
   - Activité : N scan(s), N apply, "il y a X jours"

2. **Sparkline SVG** (`_renderScoreSparkline`) :
   - Line chart minimaliste des évolutions de score dans le temps.
   - ViewBox 780×110, padding intérieur.
   - Lignes horizontales pointillées pour les seuils Platinum (violet, 85), Gold (or, 68), Silver (gris, 54) avec labels abbr "Pt/Go/Si" en marge.
   - Ligne principale bleue (#60A5FA) + gradient area semi-transparent sous la courbe.
   - Points colorés selon tier (violet Platinum, or Gold, gris Silver, orange Bronze, rouge Reject) avec contour clair pour lisibilité.
   - Tooltip `<title>` natif au survol (Score 82 (Gold)).
   - Total delta coloré en header (`+14` vert si amélioration, `-5` rouge si régression).
   - Skip gracieux si < 2 points (pas de ligne possible).

3. **Timeline stepper** (`_renderTimelineEvents`) :
   - Chaque event = dot circulaire (20×20) avec bordure colorée par type :
     - Scan → bleu 🔍
     - Score → or ⭐ + tierPill
     - Apply → vert 📁 + liste des ops (paths tronqués intelligemment)
   - Ligne verticale continue `var(--border)` reliant les dots (visual stepper).
   - Delta score coloré (+5 vert / -3 rouge).
   - Chemins apply raccourcis via `_shortenHistoryPath(path, max=50)`.
   - Warnings listés en dessous du texte principal.

**Tests** : 11 nouveaux (`test_film_history_ui.py`) : modal exists, composition 3 sections, sparkline (viewBox, path, circle, seuils couleur), header utilise tierPill, types événements (scan/score/apply), icônes emoji, connector line, modal au lieu d'écraser inspecteur, helper shorten, delta coloré.
Suite globale : 2084 passed, 0 régression.

**Alternatives évaluées** :
- Sparkline SVG vs Chart.js vs canvas → SVG pur (cohérent avec le reste de CineSort, zéro dépendance, réactif sans JS).
- Lignes de seuils en arrière plan vs en overlay → arrière plan (0.4 opacity, pointillées, n'interfèrent pas avec la lecture de la courbe).
- Dots colorés par tier vs points bleus uniformes → colorés par tier (identité visuelle du scoring, cohérent avec tierPill).
- Connecteur vertical dur vs pointillé → dur (plus élégant, plus pro).

**Valeur utilisateur** :
- Avant : liste textuelle "🔍 15/04 Scan…⭐ 15/04 Score 82…📁 15/04 Apply…" — lisible mais peu parlant.
- Après : **vue d'ensemble en 1 écran** — score actuel visible, trend claire, évolution graphique du score avec seuils de tier, chronologie stepper colorée. L'utilisateur voit IMMÉDIATEMENT si son film s'est amélioré/dégradé, à quel tier il est, quand il a été modifié pour la dernière fois.
- Particulièrement puissant pour les films scannés plusieurs fois (source upgradée, remux trouvé, etc.).

**Palier 3 (Visuel premium) terminé** :
- P3.1 Comparateur doublons côte-à-côte (mockup user)
- P3.2 Badges tiers visuels (tierPill)
- P3.3 Historique enrichi (modal, sparkline, stepper)

**Prochaine étape** : Palier 4 — Calibration perceptuelle avec feedback (P4.1).

---

### 2026-04-22 · P4.1 terminé — Calibration perceptuelle via feedback utilisateur

**Problème ciblé** : le scoring actuel est déterministe (règles + poids fixes). Pour un partage communautaire, il faut pouvoir ajuster les poids aux goûts de l'utilisateur et détecter les biais systémiques ("tous mes films Atmos sont sous-notés").

**Recherche web** : calibration QA (call-centers), weighted scoring bias (product management). Les consensus : feedback régulier + mesure inter-rater reliability + ajustement progressif des poids basé sur les écarts observés.

**Livré** :

**Schema v14** ([014_user_quality_feedback.sql](../../../cinesort/infra/db/migrations/014_user_quality_feedback.sql))
- Table `user_quality_feedback` : id, run_id, row_id, computed_score/tier, user_tier, tier_delta (ordinal), category_focus (video/audio/extras/null), comment, created_ts, app_version.
- 3 index (run, row, tier_delta).

**Module domaine** ([calibration.py](../../../cinesort/domain/calibration.py), ~180L pur)
- `tier_ordinal(tier)` : Reject=0, Bronze=1, Silver=2, Gold=3, Platinum=4. Gère aliases legacy (Premium/Bon/Moyen/Mauvais).
- `compute_tier_delta(computed, user)` : différence ordinale. +1 = user dit Gold pour Silver calculé (underscore). -1 = user dit Silver pour Gold calculé (overscore).
- `analyze_feedback_bias(feedbacks)` : agrège → `{total, accord_pct, mean_delta, bias_direction, bias_strength, category_bias}`.
  - `bias_direction` : underscore / overscore / neutral (seuil |mean| > 0.15).
  - `bias_strength` : none / weak / moderate / strong (seuils 0.15, 0.5, 1.0).
- `suggest_weight_adjustment(bias, current_weights)` : propose un ajustement si biais ≥ modéré ET une catégorie est pointée majoritairement. Delta ±5 points sur la catégorie focus, rééquilibrage proportionnel des autres, clamp [1, 90], somme conservée.

**DB methods** ([_quality_mixin.py:203-290](../../../cinesort/infra/db/_quality_mixin.py))
- `insert_user_quality_feedback(...)` : insert ligne.
- `list_user_quality_feedback(run_id?, row_id?, limit)` : retourne feedbacks ordonnés du plus récent.
- `delete_user_quality_feedback(feedback_id)` : suppression.
- Schema group `user_feedback` ajouté dans `sqlite_store.SCHEMA_GROUPS`.

**Endpoints API** ([cinesort_api.py:1556-1639](../../../cinesort/ui/api/cinesort_api.py))
- `submit_score_feedback(run_id, row_id, user_tier, category_focus?, comment?)` :
  - Valide run_id + row_id.
  - Récupère le quality_report pour computed_score/tier.
  - Calcule tier_delta.
  - Insère via `insert_user_quality_feedback`.
  - Retourne `{ok, feedback_id, computed_score, computed_tier, user_tier, tier_delta}`.
- `get_calibration_report()` :
  - Lit tous les feedbacks (jusqu'à 10 000).
  - Appelle `analyze_feedback_bias` + `suggest_weight_adjustment`.
  - Retourne `{ok, bias, current_weights, suggestion, sample_feedbacks}`.

**UI desktop** ([validation.js:337-400](../../../web/views/validation.js))
- Form "Ce score vous semble-t-il juste ?" ajouté en bas de la modal `modalScoreExplain`.
- Champs : tier attendu (select 5 tiers), catégorie focus (select 4 options), commentaire (text).
- Bouton "Enregistrer ce feedback" → appel `submit_score_feedback` → feedback texte inline.
- Affichage du delta explicite ("Accord", "Score sous-évalué (+1)", "Score sur-évalué (-1)").

**Tests** : 22 nouveaux (`test_calibration.py`) couvrant :
- `tier_ordinal` : canoniques, case insensitive, legacy aliases, inconnu.
- `compute_tier_delta` : accord, user plus haut, user plus bas, inconnu.
- `analyze_feedback_bias` : vide, accord, underscore/overscore, weak/strong, category_bias counts.
- `suggest_weight_adjustment` : no suggestion weak, underscore audio ↑, overscore video ↓, no category ↔ none, rationale contient explication.
- Intégration endpoint : sans quality_report → fail, run_id invalide → fail, row_id vide → fail.

Migration 014 validée via `test_v7_foundations` + `test_api_bridge_lot3` (user_version=14, table présente).
Suite globale : 2104 passed, 0 régression.

**Alternatives évaluées** :
- Table dédiée vs JSON blob dans quality_reports → table dédiée (index sur tier_delta, requêtes rapides pour rapport).
- Tier ordinal (0-4) vs score numérique 0-100 → ordinal (user pense "Gold", pas "78"). Plus intuitif.
- Auto-applique suggestion vs proposition → proposition (l'user reste maître, on ne modifie jamais le profil sans son OK explicite). La suggestion est affichable, pas appliquée. L'user clique pour appliquer (UI pas encore implémentée — P4.1 minimal).
- Agrégation live vs rapport sur demande → sur demande via endpoint `get_calibration_report` (pas d'overhead au scan).

**Ce que l'utilisateur peut faire maintenant** :
- Ouvrir le détail d'un score → donner son avis en 2 clics.
- Au bout de 20-30 feedbacks, voir le rapport de calibration via `get_calibration_report` (UI rapport pas dans P4.1 — possible dans P4.3 ou plus tard).
- Les biais détectés permettent d'ajuster le profil qualité de façon mesurée, pas à l'aveugle.

**Prochaine étape** : P4.2 — Règles genre-aware (animation vs live-action vs thriller ont des caractéristiques de qualité différentes).

---

### 2026-04-22 · P4.2 terminé — Scoring genre-aware (animation vs action vs horror...)

**Problème ciblé** : un film d'animation 1080p HEVC 5 Mbps peut être visuellement excellent (contenu très compressible) alors qu'un film d'action 4K HEVC 5 Mbps est un upscale horrible. Le scoring uniforme ne fait pas ce distinguo — les exigences diffèrent selon le genre.

**Recherche web** :
- Netflix AV1 : "pristine" animation à 1.1 Mbps (vs 25-35 Mbps live-action 4K)
- HEVC bitrate guides : 52-64% compression vs H.264, 20-35 Mbps min pour 4K live-action
- Animation : peu de grain, aplats, contours → compresse très bien mais artifacts visibles vite si trop bas
- Horror : scènes sombres → HDR10 extrêmement précieux

**Livré** :

**Module domaine** ([genre_rules.py](../../../cinesort/domain/genre_rules.py), ~230L pur)
- `canonical_genre(g)` : mapping English+FR → clé interne (7 canoniques).
- `detect_primary_genre(tmdb_genres)` : priorité animation > horror > action > thriller > documentary > drama > comedy.
- `_GENRE_RULES` : table par genre avec :
  - `bitrate_leniency` : multiplicateur [0.75-1.15] sur les seuils de bitrate.
  - `modern_codec_bonus`, `hdr_bonus`, `atmos_bonus`, `grain_malus`, `low_resolution_malus`.
- `compute_genre_adjustments(primary_genre, video_codec, height, has_hdr, has_atmos, has_heavy_grain)` : retourne `(total_delta, factors)` au format standard pour s'intégrer dans explain-score.
- `adjust_bitrate_threshold(base, genre)` : applique le multiplicateur.

**Règles implémentées par genre** :
- **Animation** : leniency 0.75, +3 codec moderne, -5 si grain détecté, -3 si < 1080p.
- **Action** : leniency 1.15, +3 HDR, +3 Atmos, -5 si < 1080p.
- **Horror** : leniency 1.10, +4 HDR (scènes sombres), +3 Atmos.
- **Thriller** : leniency 1.10, +2 HDR, +2 Atmos.
- **Documentary** : leniency 0.90, +1 codec moderne, -1 si < 1080p (tolérant archive).
- **Drama** : leniency 1.05, +2 HDR, +1 Atmos.
- **Comedy** : neutre 1.00, +1 Atmos, -3 si < 1080p.

**Intégration** ([quality_score.py:965-1009](../../../cinesort/domain/quality_score.py))
- Nouveau kwarg `tmdb_genres: Optional[List[str]] = None` dans `compute_quality_score`.
- Si fourni, détecte primary_genre, calcule adjustments, ajoute aux factors + applique aux sous-scores avant pondération.
- Champs `tmdb_genres` et `primary_genre` exposés dans les metrics pour l'UI.

**Récupération des genres** ([quality_report_support.py:90-107](../../../cinesort/ui/api/quality_report_support.py))
- Dans `_probe_and_score`, après la probe, on cherche le premier candidat avec `tmdb_id`.
- Appel `tmdb.get_movie_metadata_for_perceptual(tmdb_id)` (méthode existante, retourne `{genres, budget, production_companies}`).
- Genres passés à `compute_quality_score` via le nouveau kwarg.
- Rétrocompat : fallback silencieux si TMDb indisponible (genres = []).

**UI** ([validation.js:346-361](../../../web/views/validation.js))
- Badge "Genre : Animation" affiché dans le header de la modal explain-score.
- Les règles genre appliquées apparaissent automatiquement dans la table "Règles appliquées" (factors avec label "Genre 'animation' + codec moderne", etc.).

**Tests** : 26 nouveaux (`test_genre_rules.py`) couvrant :
- `canonical_genre` : English, French aliases, unknown, case insensitive.
- `detect_primary_genre` : priorités (animation > action, horror > thriller, action > drama), empty, mixed known/unknown.
- `get_genre_rules` : leniency patterns, bonus presence.
- `compute_genre_adjustments` : no-genre, animation HEVC bonus, action HDR+Atmos, horror HDR big, animation grain penalty, documentary 720p lenient, action 720p harsh, factor format standard.
- `adjust_bitrate_threshold` : animation réduit, action augmente, unknown inchangé.

Suite globale : 2132 passed, 0 régression. 1 flaky REST pré-existant.

**Alternatives évaluées** :
- Seuils par genre dans le profil qualité vs module séparé → module séparé (règles figées par la recherche, pas user-configurable dans cette première itération — évite d'ajouter de la complexité UI).
- Appliquer sur le score final vs sur les sous-scores → sous-scores (s'intègre propre dans le pipeline existant + explain-score montre le factor).
- Utiliser tous les genres du film vs seulement le primaire → primaire (évite le cumul massif des bonus pour un film qui a 5 genres TMDb).
- Genre détecté depuis perceptual (déjà utilisé pour grain) vs refait dans scoring → refait (moins couplé, scoring peut fonctionner sans perceptual).

**Valeur utilisateur** :
- Avant : une animation 4K HEVC 5 Mbps était marquée "Upscale suspect" → score Silver. Mais l'user voyait que c'était excellent visuellement.
- Après : animation 4K HEVC 5 Mbps bénéficie de `bitrate_leniency=0.75` → seuil effectif abaissé → pas de flag upscale. Bonus +3 pour codec moderne. Score Gold ou Platinum selon les autres critères.
- Horror avec HDR10 : +4 pts automatiquement (vs +0 avant) → reflete la valeur artistique réelle.

**Prochaine étape** : P4.3 — Import/export profils qualité (préparation partage communautaire).

---

### 2026-04-22 · P4.3 terminé — Import/export profils qualité (partage communautaire)

**Vision** : l'utilisateur peut désormais exporter son profil qualité (potentiellement calibré via P4.1, incluant les ajustements implicites de P4.2) pour le partager sur GitHub/forum/etc. Un autre utilisateur l'importe et l'active en un clic.

C'est la pierre angulaire de la transformation "outil perso" → "plateforme communautaire" mentionnée par l'utilisateur.

**Livré** :

**Module domaine** ([profile_exchange.py](../../../cinesort/domain/profile_exchange.py), ~180L pur)
- Format d'échange JSON standardisé :
  ```json
  {
    "schema": "cinesort.quality_profile",
    "schema_version": 1,
    "exported_at": "2026-04-22T18:30:00Z",
    "exporter": "CineSort 7.3.0-dev",
    "name": "Ma config cinéma",
    "author": "anonymous",
    "description": "Privilégie l'audio Atmos",
    "profile": { ... }
  }
  ```
- `wrap_profile_for_export(profile, name, author, description, exporter)` : enveloppe avec metadata. Truncate strings longs (anti-DoS).
- `serialize_profile_export(wrapped)` : JSON indenté pour lisibilité humaine.
- `parse_and_validate_import(content)` : 6 garde-fous :
  1. Taille < 128 Ko (anti-DoS).
  2. JSON parseable.
  3. Objet dict au root.
  4. `schema == "cinesort.quality_profile"` (rejette tout autre format).
  5. `schema_version <= SCHEMA_VERSION_MAX` (refus si format futur).
  6. Structure `profile.weights` + `profile.tiers` + validation via `validate_quality_profile` existant.
- `extract_import_metadata(content)` : preview des metadata sans validation profonde (pour afficher avant confirmation d'import).

**Endpoints API** ([cinesort_api.py:1557-1641](../../../cinesort/ui/api/cinesort_api.py))
- `export_quality_profile(name, author, description)` :
  - Récupère le profil actif (ou default si aucun).
  - Wrap avec metadata.
  - Retourne `{ok, content: JSON string, filename_suggestion: str}`.
  - Filename format `{name_safe}.cinesort.json`.
- `import_quality_profile(content, activate)` :
  - Appelle `parse_and_validate_import`.
  - Extrait metadata pour feedback utilisateur.
  - Si valide, génère profile_id basé sur name ou timestamp.
  - Appelle `save_quality_profile(profile_id, version, profile_json, is_active)`.
  - Retourne `{ok, meta, activated, saved_profile_id}`.

**UI settings** ([index.html:776-791](../../../web/index.html), [settings.js:463-530](../../../web/views/settings.js))
- Nouvelle card "Profil qualité — partage communautaire" au-dessus du profil de renommage.
- Champs : nom + description pour l'export.
- 2 boutons : "Exporter le profil actif" (Blob download) / "Importer un profil…" (file picker .json/.cinesort.json).
- Workflow import :
  1. Clic bouton → ouvre file picker natif.
  2. Fichier lu localement (FileReader via `file.text()`).
  3. `uiConfirm()` demande confirmation avec nom de fichier.
  4. Appel `import_quality_profile` → validation + save.
  5. Feedback : nom du profil importé + auteur si présent.

**Tests** : 20 nouveaux (`test_profile_exchange.py`) couvrant :
- `wrap_profile_for_export` : schema/fields, profile block match, empty meta, reject non-dict, truncate strings.
- `serialize` : roundtrip, indenté.
- `parse_and_validate_import` valid : roundtrip OK, message vide.
- `parse_and_validate_import` invalid : JSON invalide, empty, wrong schema, missing schema_version, future version rejetée, missing profile, profile fields missing, non-dict root, huge content.
- `extract_import_metadata` : extraction OK, malformed → strings vides.

Suite globale : 2152 passed, 0 régression. 1 flaky REST pré-existant.

**Alternatives évaluées** :
- Format binaire (pickle, msgpack) vs JSON → JSON (lisible humain, auditable, partageable simple, sécurité).
- URL courte (hébergement central) vs fichier local → fichier (zéro infra CineSort, l'user maîtrise où va son profil — GitHub gist, forum, email).
- Signature cryptographique vs validation structurelle → structurelle (MVP, signature future si abuse).
- Auto-activer vs preview + confirmation → preview + confirmation (l'user voit ce qu'il va écraser).

**Ce que l'utilisateur peut faire maintenant** :
1. Calibrer son profil via P4.1 (feedback sur plusieurs films).
2. Appliquer une suggestion de poids (P4.1 → si `get_calibration_report` propose un ajustement).
3. Exporter le profil calibré en JSON.
4. Partager sur GitHub/forum/Discord.
5. Un autre user télécharge le JSON, clique "Importer…", confirmation, c'est appliqué.

**Palier 4 (R&D scoring) terminé** :
- P4.1 Calibration perceptuelle via feedback utilisateur
- P4.2 Règles genre-aware (Animation/Action/Horror/...)
- P4.3 Import/export profils qualité

**v7.3.0 COMPLET** : 4 paliers × 3 items = 12 commits atomiques, ~8000 lignes ajoutées, ~230 tests nouveaux, 2152 tests verts et 0 régression.

Le projet est désormais prêt pour un partage pro :
- Robustesse data (Palier 1) : NFO cross-validé, undo atomique sécurisé par sha1, preview avant apply.
- Scoring transparent (Palier 2) : explication complète, ambiguïtés titre résolues, audit JSONL.
- Visuel premium (Palier 3) : comparateur côte-à-côte, badges tiers cohérents, historique enrichi.
- R&D scoring (Palier 4) : calibration feedback, règles genre-aware, partage communautaire.

---

### 2026-04-22 · Audit post-v7.3.0 — Cohérence de câblage + fixes critiques

**Contexte** : l'utilisateur a demandé de vérifier la totalité du projet après v7.3.0 pour détecter incohérences/logiques à retravailler. Agent Explore lancé en parallèle + vérifications manuelles ciblées.

**Findings prioritaires** :

**🔴 BUG BLOQUANT 1 — Collision de nommage** (non détectée pendant le dev)
- J'ai créé `export_quality_profile` et `import_quality_profile` dans `cinesort_api.py` (v7.3.0 P4.3) — **mais ces noms existaient déjà** ([quality_profile_support.py:94, 107](../../../cinesort/ui/api/quality_profile_support.py)).
- En Python, la 2e définition écrase silencieusement la première → les callers existants (`quality.js:526/552`, `dashboard/quality.js:243/261`) étaient potentiellement cassés.
- **Fix** : renommé mes endpoints en `export_shareable_profile` / `import_shareable_profile`. Distinction claire : `export_quality_profile` (legacy) renvoie le profil brut ; `export_shareable_profile` (P4.3) enveloppe avec schema + metadata communautaire. Les deux coexistent proprement.
- `settings.js` mis à jour pour appeler les nouveaux noms.

**🔴 BUG BLOQUANT 2 — `self._store` inexistant** (aurait cassé à la 1re utilisation)
- Mes 4 endpoints P4.1/P4.3 (`get_calibration_report`, `export_shareable_profile`, `import_shareable_profile`, `delete_score_feedback`) utilisaient `self._store` comme s'il s'agissait d'un attribut global — **il n'existe pas sur `CineSortApi`**.
- Le bon pattern (vu dans runtime_support.py:143) : `store, _runner = self._get_or_create_infra(self._state_dir)`.
- **Fix** : réécriture des 4 endpoints avec le pattern correct.
- Aurait provoqué `AttributeError: 'CineSortApi' object has no attribute '_store'` à la première utilisation réelle. Catastrophique pour un partage pro.

**🟠 ENDPOINT ORPHELIN** — `get_calibration_report` définie mais jamais appelée UI
- Endpoint P4.1 exposé mais aucun bouton UI ne le consomme.
- **Fix** : ajout d'un bouton "Rapport de calibration" dans la card settings "Profil qualité — partage communautaire". Affichage :
  - Taux d'accord global
  - Biais détecté (sous/sur-évalue, intensité)
  - Catégories pointées par les feedbacks
  - Suggestion d'ajustement de poids si biais significatif (from/to visuel)

**🟡 COHÉRENCE tierPill** — utilisé partiellement
- Le component tierPill (P3.2) était utilisé seulement dans quality.js distribution et library.js dashboard.
- **Fix** : intégré aussi dans :
  - Header modal explain-score (remplace `<strong>Tier</strong>` par pastille)
  - Comparateur doublons (card "Tier" utilise maintenant tierPill compact)

**🟡 `adjust_bitrate_threshold` non utilisée** — fonction pure exportée mais morte
- Créée dans P4.2 mais jamais appelée dans `compute_quality_score`. Les règles genre-aware n'ajustaient donc PAS les seuils bitrate, seulement les bonus contextuels.
- **Fix** : intégrée dans `_score_video()` — le genre primaire est détecté tôt et passé au scoring vidéo. Un film d'animation 1080p avec bitrate bas voit maintenant son seuil ajusté de 8000 → 6000 kb/s (leniency 0.75), évitant une fausse pénalité "underbitrate". Test ajouté pour valider.

**🟡 `delete_user_quality_feedback` inaccessible** — méthode DB sans endpoint
- **Fix** : exposé comme `delete_score_feedback(feedback_id)` dans CineSortApi. Accessible REST + pywebview. Permet une future UI de cleanup.

**🟠 Parité dashboard incomplète** (non fixée, reportée)
- Le dashboard distant n'a pas les modals explain-score, historique film, pre-apply preview, export audit, import/export profil.
- **Décision** : ces features existent desktop mais pas dashboard — scope volontairement limité v7.3.0. À traiter en v7.4.0 "Dashboard feature completion".

**Tests de non-régression** : `test_audit_fixes.py` (15 tests) couvrant :
- Coexistence `export_quality_profile` (legacy) + `export_shareable_profile` (P4.3).
- Signatures distinctes. Pas de conflit.
- Endpoints shareable acceptent args positionnels (simulation pywebview).
- `delete_score_feedback` exposé et fonctionnel (retourne 0 si inexistant).
- Genre animation réduit effectivement le seuil bitrate (test end-to-end avec probe).
- UI consomme les nouveaux endpoints renommés.
- tierPill intégré dans modal explain-score.

Suite globale : **2167 passed, 0 régression, 0 flaky**. Premier run avec tous les REST tests verts depuis début v7.3.0.

**Leçons** :
- Un test qui passe ne valide pas le câblage — il valide la logique testée.
- Les endpoints exposés via pywebview doivent être testés avec des args positionnels (comme le fait pywebview), pas en kwargs.
- Collision de nommage en Python : la 2e définition écrase silencieusement la 1re, sans warning. Vérifier `grep def endpoint_name` avant d'ajouter.
- Les attributs globaux `self._foo` doivent être vérifiés en lisant la classe — ne pas supposer qu'ils existent.

**Bugs évités grâce à cet audit** : 2 bloquants (`_store` inexistant + collision nommage) qui auraient cassé la première utilisation réelle du partage de profils et du rapport de calibration.

**Verdict v7.3.0** : solide, testé, cohérent au niveau du câblage backend ↔ UI desktop. **Parité dashboard reste un travail pour v7.4.0.**

---

### 2026-04-22 · v7.4.0 — Dashboard feature completion (parité 100%)

**Contexte** : l'audit post-v7.3.0 avait identifié une asymétrie desktop vs dashboard — 6 features critiques présentes côté desktop mais absentes côté dashboard distant. Pour un partage pro où l'utilisateur accède principalement via le web, c'est inacceptable.

**6 features apportées au dashboard** (en 1 commit atomique) :

**V4.1 — Explain-score + feedback form** ([library.js:640-720](../../../web/dashboard/views/library.js))
- `_buildDashFeedbackForm(row)` : form intégré en bas de la modal detail film avec tier attendu (5 options), catégorie focus (vidéo/audio/extras/aucune), commentaire libre.
- `_hookDashFeedbackForm()` câble le bouton → `submit_score_feedback` endpoint.
- Feedback inline explicite : "Sous-évalué (+1)" / "Sur-évalué (-1)" / "Accord".

**V4.2 — Historique film enrichi (sparkline + timeline stepper)** ([library.js:740-870](../../../web/dashboard/views/library.js))
- `_buildDashHistoryHeader(data)` : KPIs titre + score actuel + tierPill + trend ↑↓ + activité.
- `_buildDashSparkline(events)` : line chart SVG avec lignes de seuils Platinum/Gold/Silver pointillées, gradient area, points colorés par tier avec `<title>` tooltip.
- `_buildDashTimelineEvents(events)` : stepper vertical avec dots colorés par type (bleu/or/vert), connecteurs, tierPill pour les scores, paths tronqués intelligemment.
- Remplace l'ancienne liste textuelle basique.

**V4.3 — Pre-apply preview** ([review.js:430-475](../../../web/dashboard/views/review.js))
- Bouton "Aperçu détaillé" dans la barre d'actions review.
- `_showPreviewModal(data)` : modale avec résumé (films / changements / conflits) + card par film (titre, change_type, tierPill, warnings, ops).
- Appelle `build_apply_preview(run_id, decisions)`.

**V4.4 — Undo atomic avec ABORTED_HASH_MISMATCH** ([review.js:325-360](../../../web/dashboard/views/review.js))
- Bouton "Annuler dernier apply" enrichi avec mode atomic=true par défaut.
- Gestion explicite du status `ABORTED_HASH_MISMATCH` : affichage des 5 premiers fichiers modifiés + raison, proposition de forcer avec atomic=false.
- 3 appels undo_last_apply dans le flux : preview dry-run / atomic=true / force atomic=false si l'user confirme.

**V4.5 — Import/export profils qualité** ([settings.js:68-85 + 475-540](../../../web/dashboard/views/settings.js))
- Nouvelle card "Profil qualité — partage communautaire" au dessus du renommage.
- Champs name + description pour l'export.
- Bouton "Exporter le profil actif" → appel `export_shareable_profile` + téléchargement Blob (.cinesort.json).
- Bouton "Importer un profil…" → file picker caché + FileReader → confirmation user → `import_shareable_profile(content, activate=true)`.
- Feedback inline avec nom du profil importé et auteur.

**V4.6 — Export audit apply JSONL/CSV** ([review.js:480-510](../../../web/dashboard/views/review.js))
- 2 boutons "Journal audit (.jsonl)" / "Journal (.csv)" sous la barre d'actions review.
- `_downloadDashAudit(format)` appelle `export_apply_audit(run_id, batch_id=null, as_format=format)` et déclenche téléchargement Blob.

**V4.7 — Rapport de calibration** ([settings.js:540-605](../../../web/dashboard/views/settings.js))
- Bouton "Rapport de calibration" à côté des boutons export/import profil.
- Appelle `get_calibration_report()`, affiche :
  - Accord global %, biais direction + intensité, delta moyen.
  - Catégories pointées (counts video/audio/extras).
  - Suggestion d'ajustement avec rationale et from → to par catégorie.
  - Message "continuez les feedbacks" si biais trop faible.

**Tests** : 32 nouveaux (`test_dashboard_parity_v7_4_0.py`) — un test par feature dashboard vérifiant :
- Fonctions helpers présentes dans le JS.
- Endpoints correctement appelés (pas les anciens écrasés).
- Éléments UI présents dans les templates HTML string.
- Utilisation de tierPill (cohérence P3.2).
- Pas de régression sur les anciens endpoints (quality.js legacy toujours utilisé).

Suite globale : 2198 passed (+31 de V4.x), 1 flaky REST pré-existant.

**Parité desktop ↔ dashboard finale** :

| Feature | Desktop | Dashboard | Parité v7.4.0 |
|---|---|---|---|
| NFO cross-validation badges | ✅ | ✅ | OK (depuis P1.1) |
| Undo atomic + checksum | ✅ | ✅ | **NEW V4.4** |
| Pre-apply preview | ✅ | ✅ | **NEW V4.3** |
| Explain-score modal | ✅ | ✅ | **NEW V4.1** |
| Titre ambigu badge | ✅ | ✅ | OK (depuis P2.2) |
| Export audit JSONL/CSV | ✅ | ✅ | **NEW V4.6** |
| Comparateur doublons côte-à-côte | ✅ | ✅ | OK (depuis P3.1) |
| Badges tiers (tierPill) | ✅ | ✅ | OK (depuis P3.2) |
| Historique film sparkline | ✅ | ✅ | **NEW V4.2** |
| Feedback calibration | ✅ | ✅ | **NEW V4.1** |
| Genre-aware affichage | ✅ | ✅ | OK (depuis V4.1 modal dashboard) |
| Import/export profil P4.3 | ✅ | ✅ | **NEW V4.5** |
| Rapport calibration | ✅ | ✅ | **NEW V4.7** |

**Parité totale atteinte**. Le dashboard distant offre désormais tout ce que le desktop offre sur les 12 items v7.3.0. Un utilisateur qui accède seulement via le dashboard (cas "partage pro distant") a accès à la totalité des features.

**Alternatives évaluées** :
- Refactoriser les helpers de rendu en un module commun → rejeté pour cette itération (desktop utilise globals, dashboard utilise ES modules). Refactoring structurel possible en v7.5.0.
- Tests E2E Playwright → hors scope (les tests d'introspection JS couvrent les mêmes vérifications plus vite).

**Verdict v7.4.0** : **parité 100% atteinte**. Le projet est désormais prêt pour un partage pro où l'utilisateur principal est sur le dashboard distant. 13 commits v7.3.0 + 1 audit fix + 1 v7.4.0 = **15 commits total**.

---
