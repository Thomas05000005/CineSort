# Vague P COMPLETE - Apply atomique & Verrous (7 batches, 7 sub-lots, 83h)

## Resume executif

La Vague P cloture le cycle "Apply atomique & Verrous" avec 7 batches livres (VP-A a VP-G)
representant 83h reelles sur un budget plan de 109h. Elle introduit la solidite
transactionnelle (apply rollback-able), la hierarchie de qualite TRaSH/Radarr a axes
multiples, les field locks Jellyfin-style, les decisions tri-etat, la protection contre
les modifications concurrentes (HTTP 409), les profils qualite TRaSH-compatibles avec
import/export YAML Recyclarr, et le cablage final de l UI library.

Build EXE : 53.68MB, startup 5.32s, healthcheck OK.

## Batch 1 - VP-A Fondations transactionnelles + migration 029 (15h)

Mise en place de `apply_atomic` opt-in avec rollback complet en cas d echec partiel.
Migration 029 introduit les tables de journalisation des operations et les colonnes
de tracking d etat. Tests unitaires sur scenarios rollback (interruption au milieu
d un batch de 50 films).

## Batch 2 - VP-B Hierarchie tier-trumps multi-axes TRaSH/Radarr (10h)

Implementation du systeme de "tier trumps" : un 4K HDR Dolby Vision bat TOUJOURS
un 720p quel que soit son score brut. 5 axes hierarchises (resolution, HDR format,
audio, source, codec) alignes sur la matrice TRaSH/Radarr 2026.

## Batch 3 - VP-C Field locks Jellyfin + merge_metadata migration 030 (15h)

Field locks par-champ a la Jellyfin : les corrections manuelles (titre, annee,
genres) sont preservees lors des rescans TMDb. Migration 030 ajoute la table
`field_locks` et la colonne `merge_strategy` sur `metadata_overrides`.

## Batch 4 - VP-D Decisions tri-etat + migration 031 backward compat ok:bool (12h)

Decisions passees de bool a tri-etat (accept/reject/defer). Migration 031 conserve
la compatibilite descendante : les anciens enregistrements `ok:true` sont remappes
sur `accept`, `ok:false` sur `reject`, l etat `defer` est nouveau.

## Batch 5 - VP-E Refactor plan_support haute LOC (10h partial)

Refactor partiel du module `plan_support` (~2300 LOC initialement) : extraction de
3 sous-modules (planning, validation, persistence). Reste 1 sous-module a extraire
en Vague Q (defere par decision plan).

## Batch 6 - VP-F Quality profiles facade TRaSH-compatible YAML (11h)

Facade `quality_profiles` avec import/export YAML compatible Recyclarr/TRaSH Guides.
Preset TRaSH 2026 livre par defaut. Breakdown 5 axes expose dans l UI.

## Batch 7 - VP-G Audit complementaire + integration finale UI library (10h)

Cablage final de l UI library v5 (composants modernes) avec coexistence legacy.
Audit complementaire sur les chemins critiques (apply, locks, decisions). Note :
le parsing INPUT des tags providers `{tmdb-680}` / `[imdbid-tt0133093]` dans les
noms de dossier n est PAS encore implemente cote scanner (seul l OUTPUT via
`naming.py` produit ces tags). Le sidecar `.nfo` reste la seule source
deterministe d identification (tmdbid/imdbid lus depuis XML). Feature parsing
input planifiee en Vague Q.

## Bilan

- Total : 83h reel sur 109h budget plan (76% du budget consomme)
- 7 batches livres, 7 sub-lots
- 3 migrations DB (029, 030, 031) toutes backward-compatible
- Build EXE : 53.68MB
- Startup : 5.32s
- Healthcheck : OK

## Pour toi

Vague P apporte la solidite et le controle:
- Apply transactionnel rollback-able : si un batch foire au milieu, tout est annule (apply_atomic opt-in)
- Hierarchie qualite juste : un 4K HDR Dolby Vision bat TOUJOURS un 720p meme tres bien score (TRaSH/Radarr)
- Field locks Jellyfin-style : tes corrections manuelles de titre/annee resistent au rescan TMDb
- Decisions tri-etat : tu peux Reporter une decision au lieu d etre force Accepter/Rejeter
- Protection contre les modifications concurrentes : HTTP 409 si deux clics simultanes Sauvegarder
- Profils qualite TRaSH-compatible avec import/export YAML (compatible Recyclarr)
- Tags providers en SORTIE : le renommage produit `{tmdb-680}` dans le nom de fichier final (compatible Plex/Jellyfin). Pour forcer une identification deterministe en ENTREE (avant scan), utilise un sidecar `.nfo` avec `<tmdbid>` / `<imdbid>` -- le parsing direct des tags depuis le nom de dossier arrive en Vague Q.

L app demarre toujours en 5.32s et pese 53.68MB.
