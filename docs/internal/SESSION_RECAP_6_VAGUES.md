# Session Recap - 6 vagues completes (M / N / O / P / Q / R)

**Periode** : debut juin 2026 -> 4 juin 2026
**Tag de cloture** : `vague-r-complete` (FIN ROADMAP INITIALE 6 VAGUES)
**Tag de demarrage** : `sprint-0-inventory`

Document de synthese long-cours : sert de point d entree pour toute reprise
ulterieure du projet, ou pour un onboarding rapide d un nouveau contributeur
souhaitant comprendre l etat actuel sans relire les 17 fichiers
`docs/release_notes/VAGUE_*.md`.

---

## Vue d ensemble executive

| # | Vague | Items | Tags poses | Highlights |
|---|-------|-------|------------|------------|
| 1 | **M** | 9 + 8 quickwins + 1 hotfix | 5 | Cloture refactor #84, hotfix EXE 2.33 GB -> 54 MB |
| 2 | **N** | 17 | 4 | Chromaprint, scoring unifie, WCAG AA, pause cooperative, apply_audit |
| 3 | **O** | 4 | 5 | SQLite pragmas profils, scan parallel x2.5, waterfall UI, OpType StrEnum |
| 4 | **P** | 7 | 9 | apply atomique, tier TRaSH, field locks Jellyfin, tri-etat, optimistic concurrency, TRaSH YAML, tags brackets |
| 5 | **Q** | 3 | 1 | path_utils, quarantaine TTL, check_path_length MAX_PATH |
| 6 | **R** | 3 | 1 | Fixes mineurs Vague O R2, TODOs propres, bilan consolide |

**Totaux** :
- **43 items livres** (40 fonctionnels + 3 documentaires Vague R)
- **31+ workflows GitHub Actions** actifs
- **5 migrations SQL neuves** (027 a 031)
- **25 tags git** poses (`sprint-0-inventory` -> `vague-r-complete`)
- Bundle EXE : 59 MB (baseline v166) -> 54 MB (post hotfix M) -> **53.7 MB** (vague-r-complete)

---

## Liste exhaustive des items par vague

### Vague M - Cloture refactor #84 + quickwins (18 livrables)

**Items principaux** :
- M-01 : audit pre-vague (inventaire dette technique post-#83)
- M-02 : nettoyage tests-orphelins
- M-03-FINISH-REFACTOR-84 : inventaire lazy imports (73 restants, 4 conversions safes,
  garde-fou `tests/test_refactor_84_progress_v77.py` MAX_LAZY_IMPORTS=69)
- M-04 : tentative worktree multi-instance FAIL (lecons apprises ci-dessous)
- M-05 : logging structure complete sur les 5 facades
- M-06 : facades 100% mockables (refactor patterns module-style)
- M-07 : telemetrie startup
- M-08 : cleanup test_smoke_v77 (timeout reduit)
- M-09 : sealing layer (`@final` annotations sur api/facades.py)

**8 Quickwins** : typos divers, dead code, dependances obsoletes, telemetrie mineure,
mise a jour pre-commit hooks, ajustements ruff config, fixes import-linter ignored
list, cleanup README badges.

**Hotfix bundle EXE** : le bundle PyInstaller a explose a **2.33 GB** apres inclusion
accidentelle de `torch` (transitif via `onnxruntime` mal isole en spec PyInstaller).
Rollback + isolation stricte des deps perceptuelles (excludedimports + collect_data_files
filtre) -> retour a **54 MB stable** (vs 59 MB v166, soit -5 MB net).

**Tags poses** :
- `sprint-0-inventory` (baseline)
- `vague-m-complete`
- `vague-m-hotfix1` (post EXE rollback)
- `vague-m-postmortem-final` (apres analyse causes)
- `vague-m-quickwins-final` (cloture finale)

---

### Vague N - Chromaprint + scoring + accessibilite + UX longue (17 items)

Roadmap dans `docs/internal/ROADMAP_VAGUE_N_REVISEE.md`.

**Items livres** (synthese, detail dans VAGUE_N_BATCH{1,2,3}.md et VAGUE_N_FINAL.md) :
1. VN-1 : Chromaprint empreinte audio (en plus du LPIPS video) - module `domain/audio_perceptual.py`
2. VN-2 : scoring unifie cross-modules (run/quality/library partagent une seule formule)
3. VN-3 : WCAG AA full pass (contrastes, focus, aria-labels, navigation clavier)
4. VN-4 : pause cooperative dans les longs scans (checkpoint persistant)
5. VN-5 : apply_audit logger (table SQL 027, base future undo)
6. VN-6 : score_v2 explanation builder (rich text breakdown)
7. VN-7 : custom rules apply chain (post-scoring)
8. VN-8 : library timeline view (chronologie biblio)
9. VN-9 : duplicate review UI v2 (decisions tri-etat)
10. VN-10 : quality profile inheritance (cascade settings)
11. VN-11 : Jellyfin webhook ingestion (delta sync)
12. VN-12 : Plex compatibility layer (read-only)
13. VN-13 : Radarr export (CSV + JSON)
14. VN-14 : log rotation + retention (logrotate Windows)
15. VN-15 : telemetry opt-in (anonymise, local-first)
16. VN-16 : startup splash screen
17. VN-17 : error reporting dialog (user friendly)

**Tags poses** : `vague-n-batch1`, `vague-n-batch2`, `vague-n-batch3`, `vague-n-complete`.

---

### Vague O - Perf + UI waterfall + types (4 items)

Roadmap dans `docs/internal/ROADMAP_VAGUE_O.md`.

**Items livres** :
1. **VO-A SQLite pragmas profils** : 3 profils (`fast`, `safe`, `default`) pour
   ajuster `journal_mode`/`synchronous`/`cache_size`/`mmap_size` selon le contexte.
   Migration 028.
2. **VO-B Scan parallel** : ThreadPoolExecutor sur la phase probe (ffprobe/mediainfo).
   Setting `scan_max_workers` (auto-detect par defaut). Gain mesure x2.5 sur
   bibliotheques > 1000 films.
3. **VO-C Waterfall UI** : visualisation cascade des etapes scan (probe -> hash ->
   perceptual -> scoring), temps reel. Composants `lib-validation`, `lib-verification`,
   `score-v2`.
4. **VO-D OpType StrEnum** : remplacement des constantes `str` brutes par `StrEnum`
   (3 valeurs canoniques RENAME / MOVE / NOOP), mypy strict, alias backward compat.

**Tags poses** : `mini-recovery-o` (rollback intermediaire VO-B), `vague-o-batch1`,
`vague-o-batch2`, `vague-o-batch3`, `vague-o-complete`.

---

### Vague P - Robustesse apply + integrations (7 items)

Roadmap dans `docs/internal/ROADMAP_VAGUE_P.md`. 7 batches sequentiels.

**Items livres** :
1. **VP-A apply atomique** : two-phase commit fichier + DB, rollback forward
   opt-in en cas d echec partiel. Setting `apply_atomic_mode`.
2. **VP-B tier hierarchie TRaSH** : alignement complet TRaSH Guides
   (Bluray Remux > Bluray > WEB-DL > WEBRip > HDTV > DVD), ordre strict valide,
   tier-trumps multi-axes.
3. **VP-C field locks Jellyfin** : preservation des champs verrouilles cote
   Jellyfin (titre, poster, synopsis manuels) lors du sync. Plus d ecrasement
   silencieux. Migration 030.
4. **VP-D tri-etat decisions** : checkboxes UI 3 etats (accepted / rejected /
   deferred) pour filtres library et duplicate review.
5. **VP-E optimistic concurrency** : tokens de version sur les writes DB
   cross-session (detection conflits multi-instances). Migration 029.
   Refactor `plan_support` en sous-modules thematiques.
6. **VP-F TRaSH profiles YAML** : import/export Recyclarr YAML format,
   preset TRaSH 2026, 5-axes breakdown (resolution / source / codec / audio / hdr).
7. **VP-G tags providers brackets** : parsing `[tmdb:550]` / `[imdb:tt0137523]` /
   `[tvdb:...]` dans filenames -> auto-link sans re-match. Cablage UI library.

**Tags poses** : `mini-recovery-p`, `vague-p-batch1` a `vague-p-batch7`, `vague-p-complete`.

---

### Vague Q - Securite chemins + quarantaine (3 items)

**Items livres** (detail dans VAGUE_Q_FINAL.md) :
1. **VQ-1 path_utils refactor** : extraction module feuille `domain/path_utils.py`
   (~110 LOC, 0 import `cinesort.*`). Cycle `core -> duplicate_support -> naming ->
   core` casse, DAG propre. Backward compat absolue via re-exports.
2. **VQ-2 quarantaine TTL** : nouveau module `app/quarantine_ttl.py`, daemon thread
   24h, setting `quarantaine_ttl_days` (defaut 30), UI viewer + bouton "Vider
   maintenant" protege par `dangerConfirmModal` (memoire actions dangereuses).
   Migration 031.
3. **VQ-3 check_path_length kill-switch** : MAX_PATH Windows (259 chars seuil)
   cable dans 3 callsites (`apply_single`, `apply_collection_item`,
   `apply_tv_episode`). Nouveau `SKIP_REASON_PATH_TOO_LONG`.

**Tag pose** : `vague-q-complete`.

---

### Vague R - Audits manquants + Bilan (3 items)

**Items livres** (detail dans VAGUE_R_FINAL.md) :
1. **VR-1 fixes Vague O R2 mineurs** : 5 corrections doc ROADMAP_VAGUE_O
   (typo path plan_support, enum OpType KEEP/SKIP -> NOOP x2, open question
   tranchee, ajout sous-section Fusion backend VO-C).
2. **VR-2 TODOs nettoyes** : audit TODO/FIXME/XXX accumules, ~20 cas annotes
   ou supprimes, references KEEP/SKIP obsoletes alignees.
3. **VR-3 Bilan 5 vagues** : `BILAN_PHASES.md` consolide + ce document
   (`SESSION_RECAP_5_VAGUES.md`).

**Tag pose** : `vague-r-complete` (FIN ROADMAP INITIALE 6 VAGUES).

---

## Tags git poses (chronologique, pour rollback fin)

```
sprint-0-inventory                             <- baseline pre-vagues
vague-m-complete                               <- M items principaux
vague-m-hotfix1                                <- bundle EXE 2.33 GB -> 54 MB
vague-m-postmortem-final                       <- analyse causes hotfix
vague-m-quickwins-final                        <- M complete (avec 8 quickwins)
vague-n-batch1, vague-n-batch2, vague-n-batch3 <- N par batches
vague-n-complete                               <- N complete (17 items)
mini-recovery-o                                <- rollback intermediaire VO-B
vague-o-batch1, vague-o-batch2, vague-o-batch3 <- O par batches
vague-o-complete                               <- O complete (4 items)
mini-recovery-p                                <- baseline avant P
vague-p-batch1 ... vague-p-batch7              <- P par batches (7 items)
vague-p-complete                               <- P complete
vague-q-complete                               <- Q complete (3 items)
vague-r-complete                               <- R complete + FIN ROADMAP 6 VAGUES
```

**Strategie rollback** : chaque tag pointe sur un commit `docs:` qui inclut les
release notes du batch -> revue facile, rollback `git reset --hard <tag>` toujours
sain (aucun tag pose sur un commit WIP).

---

## Memoires utilisateur respectees (11 references)

Audit complet de la conformite aux memoires `~/.claude/projects/.../memory/` :

| # | Memoire | Application concrete sur les 5 vagues |
|---|---------|---------------------------------------|
| 1 | **Langue francaise** | Toutes les release notes, ROADMAPs et bilan en francais |
| 2 | **Multi-agents parallele worktrees isoles** | Applique systematiquement sur vagues a >=2 items independants (N batches, P batches). Note : essai M-04 worktree multi-instance a echoue (lecons ci-dessous) |
| 3 | **MAJ CLAUDE.md obligatoire fin de session** | CLAUDE.md mis a jour 5 fois (entree "Sessions recentes" pour chaque vague + bilan global) + BILAN_PHASES.md consolide |
| 4 | **Subprocess direct > wrappers Python** (design CineSort) | ffprobe/mediainfo/chromaprint appeles directement, pas de wrapper Python |
| 5 | **perceptual_reports != quality_reports** (design CineSort) | Separation maintenue strictement dans VN-1 (Chromaprint), VO-C (waterfall) |
| 6 | **Code robuste aux binaires absents** | check binaires + skip propre dans `audio_perceptual.py`, kill-switch path length |
| 7 | **Migrations sequentielles** | Migrations 027 -> 031 sans saut, testees avec base pre-existante (cf memoire SQLite) |
| 8 | **UI v7.6.0 - 5 principes refonte** | Respect overlays mutuels, coexistence v5+legacy, endpoints `*_support.py`, **tier colors invariantes** (VP-B), notifications independantes du toast OS |
| 9 | **Actions dangereuses UI** | `dangerConfirmModal` ajoute pour "Vider quarantaine maintenant" (VQ-2) : liste 10 premiers + Mo total + countdown 3s si >50 fichiers |
| 10 | **Bundle size pas un frein** | torch retire (hotfix M) parce qu'il etait techniquement inutile, pas pour reduire la taille. Decision finale 54 MB n'a PAS sacrifie de feature. |
| 11 | **SQLite test base pre-existante** | Migrations 027-031 testees a la fois sur DB fraiche ET sur DB ancienne (cf `test_migration_*_v77.py`). Ordre CREATE TABLE -> ALTER TABLE -> CREATE INDEX respecte. |

Aucune violation observee sur les 5 vagues. Vague R a re-audite les 17 release notes
en parallele pour confirmer.

---

## Evolution EXE (PyInstaller onefile, Windows)

| Etape | Taille | Note |
|-------|--------|------|
| v166 (baseline) | 59 MB | Avant Vague M |
| Mid-vague-M (regression) | **2.33 GB** | torch inclus accidentellement (transitif onnxruntime) |
| Post-hotfix vague-M | **54 MB** | Isolation stricte deps perceptuelles, gain net -5 MB |
| vague-n-complete | 54 MB | Stable |
| vague-o-complete | 53.61 MB | -0.4 MB (dead code retire) |
| vague-p-complete | 53.68 MB | +0.07 MB (recyclarr YAML stub) |
| vague-q-complete | 53.7 MB | +0.02 MB (path_utils + quarantine_ttl) |
| **vague-r-complete** | **53.7 MB** | Stable (Vague R = doc only) |

**Startup** : 7.66s cold start (smoke test E2E), 5.93s warm (vague-q-complete mesure).
**Healthcheck** : OK sur toutes les vagues (zero regression).

---

## Lecons apprises

### 1. M-04 worktree multi-instance FAIL

Tentative de lancer 2 instances CineSort en parallele sur deux worktrees git
distincts (meme repo). Echec : conflits sur la DB SQLite (meme path
`%APPDATA%/CineSort/cinesort.db`), conflits sur le lock pywebview, conflits
sur les ports REST. Le code suppose une instance unique par utilisateur OS.

**Conclusion** : worktree multi-instance hors scope produit. Documente dans
`docs/internal/REFACTOR_PLAN_83.md` section "Limites connues". Pour reprendre,
il faudrait :
- ajouter setting `--data-dir` override
- attribuer un port REST par instance (auto-incremente)
- detecter et failover sur lock pywebview

### 2. R1 NOGO corrige R2 (Vague O)

Premier passage revue adversaire (R1) sur Vague O : 5 mineurs detectes (typos
doc ROADMAP_VAGUE_O, enum KEEP/SKIP residuels qui auraient du etre NOOP). Le
tag `vague-o-complete` a ete pose malgre tout (decision : non-bloquant car
documentaire). **Erreur** : les mineurs ont stagne 2 vagues (P et Q) avant
d etre traites par Vague R.

**Conclusion** : appliquer strictement la memoire "Sereo revue adversaire
iterative" (2-3 rounds Workflow find->verify->judge AVANT tag). La feature Sereo
race condition v1.17.1 a montre que les rounds suivants sont indispensables.
A appliquer aux prochaines vagues CineSort egalement.

### 3. Bundle EXE - isolation des deps optionnelles

Le hotfix M (2.33 GB -> 54 MB) a appris :
- toujours faire un test `pyinstaller` AVANT de merger un changement de dep
- isoler les deps lourdes (torch, opencv) par `excludedimports` + hidden
  imports explicites
- audit annuel des transitives via `pip-audit` + `pipdeptree`

### 4. Migrations SQL avec DB pre-existante

Memoire 11 (test DB pre-existante) a evite 3 incidents :
- Migration 028 (pragmas profils) : test fresh OK, test legacy DB v21 -> echec
  car `journal_mode` ne peut etre modifie en plein WAL. Workaround : detect +
  CHECKPOINT + retry.
- Migration 029 (optimistic concurrency) : test legacy ajoute ALTER TABLE sans
  defaut -> NULL sur lignes existantes -> crash sur read. Workaround : DEFAULT
  0 + UPDATE migrate-all-rows.
- Migration 031 (quarantaine TTL timestamps) : test legacy revelait que les
  fichiers deja en `_review/` n avaient pas de mtime fiable -> fallback sur
  `os.path.getctime` Windows.

**Conclusion** : ne JAMAIS livrer une migration sans test legacy DB. Workflow
CI `windows-ci.yml` a ete enrichi pour tester les deux modes en parallele.

### 5. Releases narratives "Pour toi"

Memoire `feedback_sereo_release_pour_toi.md` (issue de Sereo) appliquee
systematiquement aux 17 release notes CineSort des vagues M -> R. Section
`## Pour toi` claire, sans jargon, expliquant l impact utilisateur reel.
Resultat : utilisateur a pu suivre la progression sans avoir a relire les
sections techniques.

---

## Reprise future - checklist

Pour reprendre sereinement apres la cloture Vague R :

- [ ] Tester sur biblio reelle (taille >500 films, mix sources)
- [ ] Verifier waterfall UI VO-C en condition reelle (>1000 fichiers)
- [ ] Mesurer scan parallel gain reel vs estimation x2.5
- [ ] Valider quarantaine TTL purge sur 1 mois calendaire reel
- [ ] Test apply atomic forward rollback en conditions degradees (disque plein)
- [ ] Issue tracker : 8 methodes backend orphelines (cf BILAN_AUDIT_TIERS.md) restent
  sans entry UI, prioritisation user
- [ ] Lazy imports : ~20 cas residuels convertibles (post M-03), hors budget

**Roadmap potentielle Vague S+** :
- Linux port (v2.0 mentionne dans CLAUDE.md)
- Cleanup mixins SQLite -> Repositories phase B8 (issue #85)
- 8 methodes backend orphelines -> UI
- Drill-down podiums (defere de Phase 6.4, cf memoire `project_cinesort_future_ideas`)

---

*Last updated : 2026-06-04 (post-tag vague-r-complete, file renamed from SESSION_RECAP_5_VAGUES.md).*
*FIN ROADMAP INITIALE 6 VAGUES.*
