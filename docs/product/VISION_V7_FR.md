# Vision Produit v7 (adaptee)

## Objectif
Faire de CineSort un produit "bibliotheque cinema" robuste, explicable et pilotable:
- audit qualite (video/audio/metadata) + anomalies,
- plan d'actions sur (dry-run, validation, rollback),
- dashboard + moteur de regles.

## Ce qui est ajuste par rapport a la proposition initiale
- Priorite a la fiabilite: d'abord architecture + base de donnees + jobs solides.
- Deploiement progressif: v7.0 -> v7.1 -> v7.2 (pas un "big bang").
- Packaging stable explicite:
  - QA interne = `onedir`
  - release utilisateur = `onefile`
  - une seule spec produit les deux artefacts.
- Score qualite et anomalies "explicables" (toujours raisons textuelles).

## Architecture cible

### 1) `domain/`
- Entites:
  - `MediaFile`
  - `MovieMatch`
  - `QualityReport`
  - `Anomaly`
  - `PlanAction`
  - `Run`
- Regles metier pures:
  - scan logique,
  - detection/analyse,
  - calcul score,
  - generation plan.

### 2) `app/`
- Use-cases:
  - `ScanLibraryUseCase`
  - `BuildPlanUseCase`
  - `ApplyPlanUseCase`
  - `RollbackUseCase`
  - `ExportUseCase`
- Orchestration + transactions.

### 3) `infra/`
- `FileSystemAdapter` (ops atomiques + recycle bin interne)
- `TmdbClient` + cache + rate limiter
- `FfprobeAdapter` + cache
- `Persistence` (SQLite)
- `Logger` (JSON + texte)

### 4) `ui/`
- API Webview fine:
  - `start_scan`, `get_progress`, `get_run_summary`,
  - `get_dashboard`, `build_plan`, `apply_plan`, `rollback`, `export`.
- L'UI consomme des modeles de sortie, sans logique metier lourde.

## Base de donnees v7 (SQLite)

Tables minimales:
- `runs(id, status, started_at, ended_at, config_json, stats_json)`
- `movies(id, run_id, title, year, tmdb_id, confidence, source, notes)`
- `files(id, run_id, movie_id, path, size, mtime, hash, streams_json, tags_json)`
- `quality_reports(id, run_id, movie_id, score, reasons_json, metrics_json)`
- `anomalies(id, run_id, movie_id, code, severity, message, context_json)`
- `actions(id, run_id, type, before_path, after_path, safe_flag, status, error_msg)`
- `errors(id, run_id, step, code, message, context_json)`

Migration:
- `PRAGMA user_version`
- scripts SQL versionnes `migrations/001_init.sql`, `002_...sql`, etc.

## Roadmap pragmatique

## v7.0 Foundations
- Refactor couches (`domain/app/infra/ui`).
- Job runner robuste:
  - etats `PENDING/RUNNING/DONE/FAILED/CANCELLED`,
  - annulation propre,
  - reprise partielle.
- Persistence SQLite + historique runs.
- Logs structures JSON + log texte.
- API stable + tests de non-regression.

## v7.1 Audit qualite
- Integrer `ffprobe` (cache des streams).
- Calcul `QualityReport` (0-100) explicable.
- Detection anomalies par severite:
  - mismatch titre/annee,
  - duree incoherente,
  - NFO/art manquants,
  - codec audio/video non conforme.
- Dashboard initial:
  - repartition resolutions/codecs/HDR/audio,
  - top dossiers lourds,
  - fichiers a revoir.

## v7.2 Plan avance + regles
- Rule Engine JSON (import/export) lisible.
- Dry-run visuel (arborescence cible + actions).
- Seuils de securite:
  - confirmation si gros volume d'actions,
  - soft delete (corbeille interne),
  - checksum optionnel mode parano.
- Rollback base sur `actions`.
- Exports CSV/JSON des decisions et actions.

## Specification "Score Qualite" (v1)
- Resolution:
  - 2160p +25
  - 1080p +15
  - 720p +5
- HDR:
  - DV +12
  - HDR10+ +10
  - HDR10 +8
  - SDR +0
- Codec video:
  - HEVC +8
  - AVC +5
- Bitrate:
  - courbe logarithmique + penalites plancher selon resolution
- Audio:
  - Atmos/TrueHD +12
  - DTS-HD MA +10
  - DTS +6
  - AAC +3
- Metadata:
  - NFO + posters/backdrops +10

Sortie obligatoire:
- `score`
- `reasons[]` (explications humaines)
- `metrics` (valeurs techniques)

## Specification "Anomalies" (v1)
- `INFO`: metadata manquante non bloquante.
- `WARN`: incoherence probable (annee, duree, source tag).
- `ERROR`: operation risquee/impossible.

Regles initiales:
- `duration_diff > 10%` -> `WARN`
- `title_similarity faible + year mismatch` -> `WARN`
- `poster/backdrop manquant` -> `INFO`
- `audio non supporte cible` -> `WARN`

## Packaging & exploitation
- Build CI:
  - lint + tests + build exe + artefacts.
- `VERSION` + `CHANGELOG.md`
- crash report local (fichier + dernier run_id).
- Distribution:
  - `onedir` pour QA/stabilite (`dist/CineSort_QA/`),
  - `onefile` pour release utilisateur (`dist/CineSort.exe`).

## KPIs produit
- taux de runs sans erreur,
- temps moyen scan/analyse,
- ratio auto-fix correct (sans correction manuelle),
- baisse des `med/low` sur jeux reels,
- nombre de conflits detectes avant apply.
