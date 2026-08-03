# Vague O COMPLETE - Performance & Infra (4 batches, 4 items)

## Resume executif

Vague O cloture une roadmap "Performance & infra" decoupee en 4 items VO-A / VO-B /
VO-C / VO-D, livres en 4 batches thematiques : optimisation SQLite par profil de
stockage (A), typage rigoureux des operations de rename (D), inspecteur waterfall
scoring pour la dashboard (C), parallelisation du scan FS local Phase 1 (B). Chaque
batch a fait l'objet de release notes intermediaires (`VAGUE_O_BATCH1.md`,
`VAGUE_O_BATCH2.md`, `VAGUE_O_BATCH3.md`) ; ce document consolide l'ensemble.

Pas de bump VERSION (decision differee a la fin de Vague Q, conformement a la roadmap
strategique). Build EXE final : 53.61 MB, startup 5.49s, smoke tests (starts, health)
OK, verify GO.

## Batch 1 (VO-A) : SQLite pragmas profils + NAS validation - 26h

**VO-A - Profils SQLite par type de stockage** :
- VO-A-backend (`1ab45ca`) : module `cinesort/infra/pragma_profile.py` avec 4 profils
  (`ssd_local`, `hdd_local`, `nas_smb`, `fallback`), detection automatique du type de
  stockage et application des PRAGMAs adaptes (journal_mode, synchronous, cache_size,
  mmap_size, temp_store, wal_autocheckpoint). Profil `nas_smb` force `synchronous=FULL`
  et desactive WAL pour eviter la corruption sur partages reseau.
- VO-A-migration (`17556ee`) : migration 028 introduisant `pragma_history` (audit
  persiste des profils appliques, comparaison perf avant/apres).
- VO-A-UI (`ea1dd16`) : section "Avance" dans Parametres avec visualisation du profil
  actif + override manuel via `dangerConfirmModal` en mode EXCLUSIVE (action consideree
  dangereuse car impacte durabilite et perf).
- VO-A-NAS (`c61b335`) : benchmark NAS lancable depuis Parametres (latence write/read/
  fsync reelle) + `DB_LOCAL_GUARD` qui detecte les chemins UNC au demarrage et alerte
  si la DB est sur un partage reseau.

Batch fondateur sur la fiabilite SQLite : il garantit que les PRAGMAs sont coherents
avec le stockage reel, et il ferme une voie de corruption silencieuse identifiee dans
les audits de Vague N (utilisateurs avec DB sur SMB par defaut).

## Batch 2 (VO-D) : OpType StrEnum ex nihilo - 8h

**VO-D - Typage strict des operations de rename** :
- VO-D-1 (`22e74fc`) : `StrEnum OpType` (`RENAME`/`MOVE`/`NOOP`) dans
  `cinesort/domain/probe_models.py` comme source unique de verite pour
  `RenameProposal.op_type`. Les constantes `OP_TYPE_*` deviennent des alias derives
  de `OpType.<member>.value`, garantissant la backward compat totale (StrEnum
  equality + isinstance str). Helper `OpType.from_str()` pour normaliser les entrees
  externes (case insensitive, strip).
- VO-D-2 (`1fbf998`) : migration des 4 call-sites tests vers `OpType.*` pour type
  safety + IDE/mypy discovery, aliases `OP_TYPE_*` preserves dans `__all__`. Bonus
  durcissement `RenameProposal.to_dict()` : normalisation `OpType -> str` pour
  garantir l'invariant json-safe.

Batch court (8h) mais a fort effet de levier : il ouvre la voie a la migration
progressive des autres "magic strings" du domaine (action_type, decision_type, ...)
sans casser les call-sites existants.

## Batch 3 (VO-C) : Score waterfall UI - 13h

**VO-C - Inspecteur waterfall scoring inspire Radarr Custom Formats** :
- VO-C-BACKEND (`78a7298`) : helper PURE `compose_score_explanation` dans
  `cinesort/ui/api/dashboard_support.py` qui fusionne `build_rich_explanation` +
  `apply_custom_rules` en une structure waterfall consommable par le frontend
  (cle `score_explanation_full` du row payload).
- VO-C-FRONTEND-3 (`86ead12`) : composant `score-v2` etendu avec opts
  `scoreExplanationFull` / `profileRulesById` / `showWaterfall` + nouveau module
  `web/dashboard/core/score-helpers.js` (~225 LOC, 5 helpers reutilisables). CSS
  prefix `.score-waterfall-*` EXCLUSIF, tier colors via `var(--tier-*)` INVARIANTES.
- VO-C-FRONTEND-2 (`6dbacca`) : rendu du waterfall dans la modale "Pourquoi ce cas ?"
  de l'inspecteur lib-verification.
- VO-C-FRONTEND-1 (`7a93fe3`) : meme inspecteur cote lib-validation + panneau
  "Custom Formats impact" qui detaille les regles appliquees.

Aucune regression sur le `perceptual_score` (memoire user respectee :
`perceptual_reports != quality_reports`). Aucun bump VERSION, aucune nouvelle
dependance.

## Batch 4 (VO-B) : Scan FS parallel Phase 1 - 30h

**VO-B - Parallelisation du scan local Phase 1** :
- VO-B-analysis (`bbe110e`) : analyse du chemin chaud `_filter_dossiers_phase` (FS
  scan + extension whitelist + tri par mtime), identification des points de
  parallelisation safe (iteration repertoires) vs sequentiels (write-back partages).
- VO-B-refactor (`41425fe`) : ThreadPoolExecutor sur la Phase 1 du scan FS locale
  (parcours des dossiers candidats). Gain x5-x8 attendu sur NAS SMB (latence reseau
  amortie), x1.5-x2 sur SSD local (parallelisme IO).
- VO-B-config (`e79370b`) : settings `scan_max_workers` (auto-detect par defaut, fixe
  a 1 force le sequentiel), synergie avec VO-A : si profil `nas_smb` detecte, augmente
  automatiquement le degre de parallelisme par defaut.

Phase 1 uniquement : la parallelisation des phases 2-3 (probe ffmpeg, hash) est
laissee en backlog (Vague P), car elles touchent ffmpeg subprocess et la DB write
path qui necessitent une coordination plus fine.

## Total effort et budget

- Batch 1 (VO-A) : 26h
- Batch 2 (VO-D) : 8h
- Batch 3 (VO-C) : 13h
- Batch 4 (VO-B) : 30h
- **Total : 77h reel + 25% buffer = 96.25h budget**

## Build EXE final

- Taille : **53.61 MB**
- Startup : **5.49s** (mesure smoke test)
- Healthcheck : OK
- Verify : **GO**

## 🎁 Pour toi

Vague O c'est plus de performance et plus de transparence :

- **SQLite optimise selon ton stockage** : l'app detecte si ta base est sur SSD, HDD
  ou NAS SMB, et applique automatiquement les bons reglages internes pour chaque cas
  (avec profils dedies).
- **Scan FS parallelise sur NAS** : le balayage de tes dossiers films est maintenant
  multi-thread (gain x5-x8 attendu sur SMB, x1.5-x2 sur SSD).
- **Detail complet du score de chaque film** : un nouvel inspecteur "waterfall"
  affiche tout ce qui a contribue au score (baseline profil, video, audio, extras,
  regles custom) - inspire de Radarr Custom Formats.
- **Garde-fous anti-corruption** : si ta DB est sur un chemin reseau UNC, l'app
  t'avertit au demarrage (interdit par defaut) et te demande une confirmation
  EXCLUSIVE avant d'y toucher.
- **Typage operations rigoureux** : les operations de renommage utilisent maintenant
  un StrEnum Python 3.13 (`OpType`), ce qui evite des bugs silencieux sur les
  comparaisons et te donne une meilleure auto-completion si tu scriptes.

L'app demarre toujours en **5.49s** et pese **53.61 MB**.
