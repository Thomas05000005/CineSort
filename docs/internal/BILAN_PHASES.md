# Bilan des Phases CineSort

Ce document recapitule les grandes vagues de travail successives sur le repo CineSort.
Pour le detail session-par-session, voir [CLAUDE_HISTORY.md](./CLAUDE_HISTORY.md).
Pour les audits ponctuels, voir [BILAN_AUDIT_TIERS.md](./BILAN_AUDIT_TIERS.md) et [BILAN_CORRECTIONS.md](./BILAN_CORRECTIONS.md).

---

## 6 Vagues completes (juin 2026)

Six vagues consecutives livrees entre le sprint-0-inventory et vague-r-complete
(FIN ROADMAP INITIALE 6 VAGUES).
Methodologie : multi-agents en parallele dans worktrees isoles, tags git poses a chaque batch
pour rollback fin, revue adversaire iterative (R1/R2) avant tag de cloture.

### Vue d'ensemble

| Vague | Periode | Items | Highlights |
|-------|---------|-------|------------|
| **M** | debut juin 2026 | 9 + 8 quickwins + 1 hotfix | Cloture refactor #84, bundle EXE casse a 2.33 GB puis stabilise 54 MB |
| **N** | juin 2026 | 17 | Chromaprint, scoring unifie, WCAG, pause cooperative, apply_audit logger |
| **O** | juin 2026 | 4 | SQLite pragmas profils, scan parallel, waterfall UI, OpType StrEnum |
| **P** | juin 2026 | 7 | apply atomique, tier TRaSH hierarchique, field locks Jellyfin, tri-etat, optimistic concurrency, TRaSH YAML, tags providers brackets |
| **Q** | fin juin 2026 | 3 | path_utils, quarantaine TTL, check_path_length MAX_PATH |
| **R** | fin juin 2026 | 3 | Fixes mineurs Vague O R2, TODOs nettoyes, bilan consolide |

**Total : 43 items livres (40 fonctionnels + 3 documentaires Vague R), 31+ workflows GitHub Actions, 5 migrations SQL neuves (027-031).**

---

### Vague M — Cloture refactor #84 + quickwins (9 items + 8 quickwins + 1 hotfix)

**Objectif** : terminer la dette du refactor god class CineSortApi (#84 etapes 2-4) avant
de repartir sur du nouveau scope.

**Items M-01 a M-09** :
- M-03-FINISH-REFACTOR-84 : inventaire lazy imports (73 restants, 4 conversions safes,
  garde-fou `tests/test_refactor_84_progress_v77.py` avec MAX_LAZY_IMPORTS=69)
- Cloture des dettes residuelles : facades 100% mockables, logging structure complete

**Hotfix bundle EXE** : le bundle PyInstaller a explose a **2.33 GB** apres inclusion
accidentelle de torch (transitif via onnxruntime mal isole). Rollback + isolation
stricte des deps perceptuelles -> retour a **54 MB stable** (vs 59 MB v166).

**8 quickwins** : petits fixes opportunistes (typos, dead code, telemetrie) livres en
fin de vague avant le tag `vague-m-quickwins-final`.

**Tags poses** : `sprint-0-inventory`, `vague-m-complete`, `vague-m-hotfix1`,
`vague-m-postmortem-final`, `vague-m-quickwins-final`.

---

### Vague N — Chromaprint + scoring + accessibilite + UX longue (17 items)

**Objectif** : combler les 17 ecarts identifies dans `ROADMAP_VAGUE_N_REVISEE.md`.

**Highlights** :
- **Chromaprint** : empreinte audio integree au module perceptuel (en plus du LPIPS video)
- **Scoring unifie** : une seule formule de score qualite partagee entre run/quality/library
  (fin du drift entre 3 implementations divergentes)
- **WCAG** : passe accessibilite complete sur l'UI (contrastes, focus, aria-labels,
  navigation clavier) — cible AA
- **Pause cooperative** : longs scans interruptibles a chaque etape (pas seulement
  entre fichiers), avec checkpoint persistant
- **apply_audit logger** : trace structuree de chaque apply (qui, quoi, avant/apres,
  reversibilite) — base pour la future feature undo

**Tags poses** : `vague-n-batch1`, `vague-n-batch2`, `vague-n-batch3`, `vague-n-complete`.

---

### Vague O — Perf + UI waterfall + types (4 items)

**Objectif** : optimisations ciblees apres profiling.

**Items** :
1. **SQLite pragmas profils** : 3 profils (`fast`, `safe`, `default`) pour ajuster
   `journal_mode`/`synchronous`/`cache_size`/`mmap_size` selon le contexte (scan
   massif vs apply prudent)
2. **Scan parallel** : ThreadPoolExecutor sur la phase probe (ffprobe/mediainfo) —
   gain mesure x2.5 sur bibliotheques > 1000 films
3. **Waterfall UI** : visualisation cascade des etapes de scan (probe -> hash ->
   perceptual -> scoring), temps reel
4. **OpType StrEnum** : remplacement des constantes `str` brutes par `StrEnum`
   (apply operations), avec mypy strict

**Tags poses** : `mini-recovery-o` (rollback intermediaire), `vague-o-batch1`,
`vague-o-batch2`, `vague-o-batch3`, `vague-o-complete`.

---

### Vague P — Robustesse apply + integrations (7 items)

**Objectif** : durcir le chemin critique apply + integrations Jellyfin/TRaSH.

**Items** :
1. **Apply atomique** : two-phase commit fichier + DB, rollback complet en cas d'echec
   partiel (avant : possibilite de DB out-of-sync avec disque)
2. **Tier hierarchie TRaSH** : alignement complet sur le modele TRaSH Guides
   (Bluray Remux > Bluray > WEB-DL > WEBRip > HDTV > DVD...) — ordre strict valide
3. **Field locks Jellyfin** : preservation des champs verrouilles cote Jellyfin (titre,
   poster, synopsis manuels) lors du sync — plus d'ecrasement silencieux
4. **Tri-etat** : checkboxes UI 3 etats (selectionne / exclu / par defaut) pour
   filtres library
5. **Optimistic concurrency** : tokens de version sur les writes DB cross-session
   (detection conflits multi-instances)
6. **TRaSH profiles YAML** : import/export des profils qualite au format TRaSH Guides
   standard (interop Radarr/Sonarr)
7. **Tags providers brackets** : parsing des tags `[provider:id]` dans les filenames
   (ex: `[tmdb:550] Fight Club.mkv`) — auto-link sans re-match

**Tags poses** : `mini-recovery-p`, `vague-p-batch1` a `vague-p-batch7`, `vague-p-complete`.

---

### Vague Q — Securite chemins + quarantaine (3 items)

**Objectif** : durcissement filesystem avant elargissement multi-OS futur.

**Items** :
1. **path_utils** : module centralise pour toutes les manipulations de chemins
   (normalisation, jonction safe, escape Windows reserves : CON, PRN, AUX...)
2. **Quarantaine TTL** : les fichiers deplaces vers `.cinesort-quarantine/` ont
   maintenant une duree de vie configurable (default 30j) avec purge automatique
3. **check_path_length MAX_PATH** : validation prealable des chemins > 260
   caracteres (limite Windows par defaut), avec proposition `\\?\` ou raccourcissement

**Tag pose** : `vague-q-complete`.

---

### Vague R — Audits manquants + Bilan consolide (3 items)

**Objectif** : cloturer la roadmap initiale 6 vagues, finaliser les coins
documentaires et les audits residuels des 5 vagues precedentes, produire un
bilan consolide pour permettre une reprise ulterieure sereine. Pas de nouvelle
fonctionnalite.

**Items** :
1. **VR-1 fixes Vague O R2 mineurs** : 5 corrections doc `ROADMAP_VAGUE_O.md`
   (typo path `plan_support`, enum `OpType KEEP/SKIP` -> `NOOP` x2, open
   question 7.2 tranchee, ajout sous-section "Fusion backend" VO-C). Backward
   compat absolue via alias `OP_TYPE_*` preserves.
2. **VR-2 TODOs nettoyes** : audit `TODO`/`FIXME`/`XXX` accumules apres 5
   vagues, ~20 cas annotes ou supprimes, references `KEEP/SKIP` obsoletes
   alignees sur l'enum canonique.
3. **VR-3 Bilan 5 vagues consolide** : `BILAN_PHASES.md` (recap public) +
   `SESSION_RECAP_5_VAGUES.md` (synthese long-cours interne, renommee
   `SESSION_RECAP_6_VAGUES.md` apres ajout de Vague R).

**Tag pose** : `vague-r-complete` (FIN ROADMAP INITIALE 6 VAGUES).

---

### Evolution du bundle EXE (PyInstaller onefile)

| Version | Taille | Note |
|---------|--------|------|
| v166 (avant vagues) | 59 MB | Baseline stable |
| Mid-vague-M (hotfix) | **2.33 GB** | torch inclus accidentellement (regression) |
| Post-hotfix vague-M | **54 MB** | Isolation stricte des deps perceptuelles, +5 MB economises vs baseline |
| Vagues N a Q | 54 MB | Stable, pas de derive |
| Vague R (doc only) | 53.7 MB | Stable (Vague R = doc only, pas de change code) |

---

### Migrations SQL livrees

| # | Migration | Vague | Sujet |
|---|-----------|-------|-------|
| 027 | (cf code) | N | apply_audit table |
| 028 | (cf code) | O | SQLite pragmas profils metadata |
| 029 | (cf code) | P | Optimistic concurrency version tokens |
| 030 | (cf code) | P | Field locks Jellyfin tracking |
| 031 | (cf code) | Q | Quarantaine TTL timestamps |

Toutes idempotentes, testees avec base pre-existante (pas seulement fraiche) — voir
feedback memoire `feedback_sqlite_migration_test_existing_db.md`.

---

### Tags git complets (chronologique)

```
sprint-0-inventory
vague-m-complete
vague-m-hotfix1
vague-m-postmortem-final
vague-m-quickwins-final
vague-n-batch1, vague-n-batch2, vague-n-batch3
vague-n-complete
mini-recovery-o
vague-o-batch1, vague-o-batch2, vague-o-batch3
vague-o-complete
mini-recovery-p
vague-p-batch1 ... vague-p-batch7
vague-p-complete
vague-q-complete
vague-r-complete
```

---

## Phase Q.5 — Hotfix6/7 stabilisation (juin 2026, en cours)

**Objectif** : consolider les Vagues M-R via un cycle adversarial intensif (5 rounds + audit)
suivi de 7 hotfixes ciblees. Pas de nouvelle feature ; uniquement durcissement, regressions
attrapees, et false positives ecartes. Mode autonomie totale, ultracode.

### Rounds adversariaux R1-R5 + audit — Convergence des bugs critiques

Sequence de bug hunts iteratifs (find -> verify -> judge) lances sur la branche
`fix/v150-batch-bugs` apres cloture Vague R. Chaque round affine le diagnostic precedent
en re-questionnant les fixes appliques.

| Round | Critical bugs | Notes |
|-------|---------------|-------|
| R1 | 10 critiques | Premier passage exhaustif post-Vague R |
| R2 | 5 critiques | Convergence, certains R1 invalides |
| R3 | 3 critiques | Re-tri, reduction du bruit |
| R4 | 1 critique + 17 high | Stabilisation critiques, focus high |
| R5 (audit) | 0 critique + 16 high | Plus aucun critical non explique |

**Verdict R1-R5** : convergence saine, plus aucun critical residuel apres R5. Reste
16 high signales en audit a traiter en Vague S+ (non bloquants release beta).

### Hotfixes 1-7 — Post-fix rates et regressions

Sept hotfixes consecutives appliquees entre les rounds, chacune avec son cycle
verify-fix-retest. Le "post-fix rate" mesure le % de bugs corriges du premier coup
(sans regression introduite).

| Hotfix | Post-fix rate | Regressions | Reverts | Notes |
|--------|---------------|-------------|---------|-------|
| Hotfix 1 | 79 % | 1 mineure | 0 | Premier passage, calibration |
| Hotfix 2 | 93 % | 0 | 0 | Maturation methodologie |
| Hotfix 3 | 100 % | 0 | 0 | Pic de stabilite |
| Mega-hotfix | 100 % | 0 | 0 | Consolide B01-B05 verify-cycle (tag `mega-hotfix`) |
| Hotfix 6 | 92 % (11/12) | 1 (auto-revert) | 1 | Sequence retest cassee, 0/4 retests OK |
| Hotfix 7 | EN COURS | — | — | BugHunt R6 sur 10 angles + sequence corrigee (worktree `w4yqqdf25`) |

**Convergence** : 4 premieres hotfixes ont stabilise les bugs structurels (79 -> 100 %).
Hotfix6 a touche un edge case dans la sequence de retest (revert auto declenche). Hotfix7
remet la sequence d'aplomb et lance le 6e round adversarial sur 10 angles d'attaque
distincts.

### Tests biblio virtuelle — 11 bugs verifies, 3 reels, 8 false positives

Suite de tests sur bibliotheque virtuelle synthetique (films generes proceduralement
pour couvrir les edge cases naming/tier/perceptuel). Lance pour valider hotfix7.

- **11 bugs candidats identifies** par l'adversarial harness
- **3 bugs reels confirmes** apres reproduction manuelle + verification cross-module
- **8 false positives** ecartes (artefacts du harness, conditions non-reproductibles en prod,
  attentes mal formulees du test virtuel)

Ratio 27 % de vrais positifs — coherent avec la convergence R5 (la plupart des
findings restants sont du bruit ou de l'over-fitting au harness).

### Etat actuel de l'architecture

Modules recents centralisateurs (extraits pendant Vagues M-R + hotfixes Q.5) :

- `domain/path_utils.py` (VQ-1) : feuille du graphe, casse cycle
  `core->duplicate_support->naming->core`, expose `norm_win_path`/`_norm_win_path`/`windows_safe`
- `domain/codec_ranks.py` : centralise `AUDIO_CODEC_RANK_PATTERNS` + `AUDIO_CODEC_RANK`
  + `format_audio_channels` (VN-F.1)
- `domain/tiers_helpers.py` (Vague M / SCORE-02) : `TIER_ORDER_BEST_FIRST`, defaults 70/66/55/40
  (calibration v1.5.7 853 films), AUCUNE couleur hex (couleurs invariantes dans
  `web/shared/tokens.css` uniquement)
- `domain/probe_models.py` : constantes `PROBE_QUALITY_FULL/PARTIAL/FAILED` + helpers
  (BUG-018 hotfix1)
- `infra/db/pragma_profile.py` (VO-A) : 4 profils SQLite (`local_ssd`/`local_hdd`/`nas_smb`/
  `nas_smb_slow`) + detection auto Windows
- `ui/api/_run_state.py` (ARCH-08 / M-07) : `RunState` extraite de `cinesort_api.py`
  (-165 LOC), thread-safe, `MAX_RUN_LOG_ITEMS=5000`
- 6 facades `ui/api/facades/` : `run` (36) + `settings` (20) + `quality` (40) +
  `integrations` (15) + `library` (23) + `runtime` (32) = **166 methodes**
- 47 modules `*_support.py` orchestrent les use-cases

Architecture verrouillee par `import-linter` (3 contracts : `domain_pure`, `infra_bounded`,
`app_bounded`). Aucune regression de cycle depuis cloture #83 en mai 2026.

### Reste a faire

1. **BugHunt R6 (hotfix7)** : finaliser les 10 angles d'attaque sur worktree `w4yqqdf25`,
   verifier la sequence retest corrigee, mesurer le post-fix rate final
2. **Audit complet post-hotfix7** : nouveau round adversarial complet une fois hotfix7
   merge, pour confirmer 0 critical et reduire les 16 high audit R5
3. **Audit 2026** : audit exhaustif annuel (Tier 1 statique + Tier 2 multi-agents + Tier 3
   docs) prevu apres stabilisation des hotfixes, vise v1.0 stable
4. **Push backlog** : 152 commits non pousses sur `fix/v150-batch-bugs` + 30 fichiers en
   working tree a integrer apres validation hotfix7
5. **Vague S+** (deferree) : Linux port, B8 cleanup (suppression mixins SQLite),
   8 methodes UI orphelines, traitement des 16 high audit R5

**Tags poses (Q.5)** : `verify-fix-retest-complete`, `mega-hotfix`, `vague-r-hotfix1-full`,
`vague-r-hotfix2-full`, `vague-r-hotfix3-full` (2026-06-02 / 2026-06-04).

---

## Historique des phases anterieures

### Phases A1-A8 / B1-B7 (mai 2026) — Refactor architectural

Cassure du cycle `domain -> app` (#83) + Repository pattern (#85) :
- 150 lazy imports convertis en top-level (sur ~165)
- 7 Repositories crees (composition au lieu d'heritage MRO)
- import-linter en CI (3 contracts) verrouille les boundaries
- 12 PRs mergees (#193-#212)

Detail : `REFACTOR_PLAN_83.md`, `REFACTOR_PLAN_84.md`, `BILAN_CORRECTIONS.md`.

### Refactor god class CineSortApi (#84) — mai 2026

Strangler Fig pattern : 104 -> 50 methodes publiques sur CineSortApi via 5 facades
(`run`, `settings`, `quality`, `integrations`, `library`). 198 sites
`return {"ok": False}` migres vers `_err_response()` categorise.

### Audit Tier 1/2/3 — 21 mai 2026

33 corrections appliquees (22 statiques + 11 multi-agents). Voir `BILAN_AUDIT_TIERS.md`.

---

## Note 2026-06-05 - Trakt non concerne

**Contexte** : la deadline du 30 juin 2026 concernant la refonte de l'API Trakt a souleve
la question de l'impact sur CineSort.

**Verification effectuee** :

```bash
grep -r 'trakt' --include='*.py' --include='*.js' cinesort/
```

**Resultat** : aucune utilisation en production.
- Occurrences `.venv/` : lexers Pygments (faux positifs, hors code projet).
- Occurrence test : `tests/test_log_scrubber.py` (1 reference isolee, sans appel API).
- Aucun module `infra/`, `app/`, `domain/`, `ui/` ne reference Trakt.
- Aucune dependance `trakt` / `pytrakt` / `trakt.py` dans `requirements*.txt` ni `pyproject.toml`.

**Action** : **AUCUNE**. La deadline 30 juin 2026 (refonte API Trakt) n'est pas applicable
a CineSort. Le projet integre TMDb, Jellyfin, Plex, Radarr et OMDb, mais pas Trakt.

---

*Last updated : 2026-06-05 (note Trakt non concerne — verification grep complete, deadline 30 juin 2026 non applicable). Precedent : 2026-06-04 (post-tag vague-r-complete + ajout Phase Q.5 Hotfix6/7 stabilisation).*
