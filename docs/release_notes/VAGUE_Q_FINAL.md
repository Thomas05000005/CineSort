# Vague Q COMPLETE - Nettoyage des coins sombres (3 items)

## Resume executif

La Vague Q boucle 3 items chirurgicaux issus de la ROADMAP_VAGUE_N : nettoyage
automatique du bucket de quarantaine `_review` avec TTL filesystem, cassure du
cycle d imports domain<->domain par extraction d un module feuille `path_utils`,
et cablage en production du kill-switch MAX_PATH Windows (260 chars) qui etait
jusqu ici une fonction orpheline. Trois items autonomes, zero dette nouvelle,
1 module domain neuf, 0 migration DB.

Build EXE : 53.7MB, startup 5.93s, healthcheck OK.

## VQ-1 - PATH-UTILS : extraction du module feuille (refactor)

Extraction des helpers FS purs (`windows_safe`, `_norm_win_path`) depuis
`cinesort/domain/core.py` vers un nouveau module feuille
`cinesort/domain/path_utils.py` (~110 LOC, zero import `cinesort.*`).

Avant : `core -> duplicate_support -> (lazy) naming -> core` (cycle).
Apres : `core -> path_utils`, `naming -> path_utils` (DAG).

Le lazy import dans `duplicate_support.py` est remplace par un alias eager
top-level. Re-exports dans `core.py` preservent la backward compatibility
absolue : 14+ callers externes intacts, zero ligne modifiee chez eux,
`core.windows_safe IS path_utils.windows_safe`.

Tests : 20 nouveaux dans `tests/test_path_utils_v77.py`, contract domain_pure
KEPT, 109+20 tests verts.

## VQ-2 - QUARANTAINE-TTL : purge automatique du bucket `_review`

Nouveau module `cinesort/app/quarantine_ttl.py` :
- Constante centrale `REVIEW_FOLDER_NAME = "_review"`
- `purge_review_bucket(cfg, ttl_days)` : purge files > TTL des sous-dossiers
  `_conflicts`, `_conflicts_sidecars`, `_duplicates_identical`, `_leftovers`
  + rows top-level. **`_duplicates_user_decided` JAMAIS purge** (decisions UI).
- `purge_review_bucket_all(cfg)` : action "Vider maintenant" UI
- `list_review_bucket_files(cfg)` : inventaire pour viewer (tri mtime DESC)
- `start_quarantine_ttl_cron(api, ttl_days)` : daemon thread 24h

Setting `quarantaine_ttl_days` (defaut 30, 0=desactive), clamp [0, 3650],
persiste via `_save_section_advanced`. Cron demarre au boot dans `app.py`
(mode `--api` ET mode pywebview).

API : `api.run.purge_quarantine_bucket(ttl_days, dry_run)`,
`api.run.purge_quarantine_bucket_all(dry_run)`,
`api.run.list_quarantine_bucket(limit)`.

UI Parametres > Avance > "Quarantaine" : champ TTL, bouton "Voir le bucket"
(inventaire 20 premiers + ventilation par sous-dossier + Mo total), bouton
"Vider maintenant" protege par `dangerConfirmModal` (liste 10 premiers + Mo
total + countdown 3s si >50 fichiers) conformement a la memoire actions
dangereuses.

Tests : 24 + 13 = 37 nouveaux verts.

## VQ-3 - PATH-LENGTH KILL-SWITCH : MAX_PATH Windows cable

`check_path_length` etait orpheline en production (3 tests unitaires, ZERO
caller). Sur Windows, un dossier produisant un path cible > 260 chars generait
un OSError obscur ou un rename partiel.

Nouvelle fonction `check_path_length_killswitch(target_path) -> Optional[str]`
dans `domain/naming.py` (seuil 259 chars = MAX_PATH 260 avec terminateur null).
Nouveau `SKIP_REASON_PATH_TOO_LONG` + label FR "Chemin trop long (MAX_PATH
Windows)".

3 callsites cables dans `app/apply_core.py` :
- `apply_single` : verifie dst avant rename
- `apply_collection_item` : verifie sub_dir/video.name (anime saga)
- `apply_tv_episode` : verifie target_file (Serie/Saison/SxxExx + ep title)

Pattern uniforme : log WARN, `res.error_messages.append`, `_mark_skip`,
return. Backward compat absolue : tout path <= 259 chars passe sans
changement de comportement.

Tests : 12 nouveaux dans `tests/test_path_length_killswitch_v77.py`.

## Bilan

- 3 items VQ livres (VQ-1 refactor, VQ-2 quarantaine, VQ-3 kill-switch)
- 1 module domain neuf (`path_utils.py`)
- 1 module app neuf (`quarantine_ttl.py`)
- 0 migration DB
- 69 nouveaux tests (20 + 37 + 12)
- 1 cycle d imports casse (domain<->domain)
- 1 fonction sortie de l etat orpheline et cablee en prod
- Build EXE : 53.7MB
- Startup : 5.93s
- Healthcheck : OK

## Pour toi

Vague Q nettoie les coins sombres : les fichiers en quarantaine (rejets de
scan, conflits) sont desormais nettoyes automatiquement apres 30 jours, avec
un bouton vider manuellement. L architecture interne est plus propre (cycle
d imports casse). Et si un chemin Windows depasse 260 caracteres, l app skip
proprement au lieu de planter.

L app demarre toujours en 5.93s et pese 53.7MB.
