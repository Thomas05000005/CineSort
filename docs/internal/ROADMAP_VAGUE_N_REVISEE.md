# ROADMAP Vague N (revisee post-audits)

> **Branche** : `fix/v150-batch-bugs`
> **Date** : 2026-06-01
> **Statut** : GO_WITH_FIXES
> **Total** : 28 items / 118.5h / 6 sub-lots
> **Verdict source** : Workflow Deep + Logic adversariel post-Vague M

---

## 1. Introduction

Apres la cloture de la Vague M (hotfix 1 inclus : bundle -94%, startup speedup, off-by-one RunState logs), deux audits exhaustifs ont ete menes :

1. **Audit Deep** (composite_score, tier V1/V2, seuils confidence, Chromaprint dormant, presets dormants, apply_audit dead, encoding cp1252)
2. **Audit Logic** (adversariel : convergences cross-modules, dette technique reelle vs perçue, magic numbers non-calibres, OpType case desalignement)

Les deux audits ont converge sur **7 dossiers CRITIQUES** et **11 HIGH**. Les **8 quickwins** prevus pour Vague N (CRITICAL quickwins identifies par les audits) ont ete planifies mais **non encore appliques** (0/8) - ils seront traites en debut de Vague N dans le sub-lot VN-A et VN-E.

La presente roadmap regroupe les 28 items en 6 sub-lots executables, et liste les 19 items explicitement deferred vers les Vagues O / P / Q / R.

---

## 2. Tableau des sub-lots

| lot_id | Titre | Items | Heures |
|--------|-------|-------|--------|
| **VN-A** | Stabilisation Vague N initiale (heritage recovery) | 5 | 18h |
| **VN-B** | Tier V1/V2 reconciliation (CRITICAL convergence) | 4 | 17h |
| **VN-C** | Seuils & decisions UI unifiees (CRITICAL convergence) | 3 | 16h |
| **VN-D** | Detection doublons cross-langue (CRITICAL convergence) | 3 | 42h |
| **VN-E** | Plomberie apply / observability (HIGH convergence) | 4 | 20.5h |
| **VN-F** | Hygiene code mort (HIGH gains immediats) | 4 | 5h |
| **TOTAL** | | **23** | **118.5h** |

> Note : 28 items totaux (5 deja inclus dans VN-A comme batches techniques courts groupes).

---

## 3. Items detailles par sub-lot

### VN-A - Stabilisation Vague N initiale (heritage recovery) - 18h

1. **Probe quality flag + design system stabilisation** (heritage `w2rozrg13`)
2. **CSS toast warning + z-index tokens unifies**
3. **Focus trap + modal XSS hardening** (`dangerConfirmModal` preserves)
4. **WCAG 2.2.1 toast** (target size 24x24 min) + `auto_install` SHA256 verify
5. **DevTools conditional** + NFC edition + codec unknown fallback + `file_size` reel + cache mtime + mediainfo parity (lots techniques courts groupes)

### VN-B - Tier V1/V2 reconciliation - 17h

1. `composite_score` : supprimer v1+v2 parallele, garder une seule source de verite (**8h**)
2. Reconcilier tier V1 (70/66/55/40) vs V2 (90/80/65/50) + `display_tier` explicite end-to-end (**8h**)
3. `_TIER_MAP` audio legacy `audio_analysis.py:L35` -> canoniques platinum/gold/silver/bronze (**0.5h**)
4. Reclamper score apres custom_rules (eviter Platinum frauduleux >100) (**0.5h**)

### VN-C - Seuils & decisions UI unifiees - 16h

1. Unifier seuils confidence backend/frontend (75/50 vs 80/60 vs 85/60 vs 90 hardcode) -> source unique config (**6h**)
2. Remplacer DOM-as-truth `_buildDecisions` par state JS Map (perte silencieuse bulk-approve) (**4h**)
3. Bulk-approve : retirer hardcode 90, lire seuil depuis config + `dangerConfirmModal` si >50 elements (**6h**)

### VN-D - Detection doublons cross-langue - 42h

1. Brancher Chromaprint + fuzzy title `rapidfuzz>=88` + year +-1 dans dup detection (**28h**, ressuscite code mort)
2. TMDb `alternative_titles` quand `sim_best<0.85` (cross-langue FR/EN) (**8h**)
3. Filtre runtime HARD scoring TMDb (delta >60min sans edition flag) (**6h**)

### VN-E - Plomberie apply / observability - 20.5h

1. `tracked_run` `plugin_hooks.py:L175` `encoding='utf-8'` (crash cp1252 films FR) (**0.2h CRITICAL quickwin**)
2. Cleanup PENDING-zombi `apply_batches` au boot (**4h CRITICAL**)
3. Pause cooperative : `_should_pause_factory` + injection `job_fn` (**8h**)
4. Apply audit logger 4 events `row_decision/skip/conflict/error` non emis (**8h**)

### VN-F - Hygiene code mort - 5h

1. Centraliser `_CODEC_RANK` + `_channels_label` (3 implementations divergentes) (**2.5h**)
2. Subtitle scoring 27 LOC : toggle `include_subtitles` dans profils ou retrait (**0.5h**)
3. `scan_helpers` `stream_scan_targets/iter_scan_targets` 81 LOC 0 caller prod : supprimer (**1.7h**)
4. OpType case alignment `probe_models` lowercase -> UPPERCASE journal/apply (**0.3h**)

---

## 4. Convergences Deep + Logic (CRITICAL)

Les sept convergences cross-audits qui justifient la priorisation Vague N :

1. **Tier V1/V2 schizophrenie** - 2 vocabulaires contradictoires (`reference/excellent/bon` vs `platinum/gold/silver/bronze`) + 2 echelles (70/66/55/40 vs 90/80/65/50) melangees dans `library_support`. **CRITICAL convergent**
2. **Chromaprint/audio fingerprint mort** - `compare_audio_fingerprints` + `classify_fingerprint_similarity` calcules et stockes mais jamais appeles en prod (Plex DupeFinder le fait). **CRITICAL convergent**
3. **Magic numbers non-calibres** - subtitle scoring 27 LOC + presets `streaming_optimal` + bases 8/12/70 + deltas +34/+24/+14 + `_TIE_THRESHOLD=5` sans framework A/B. **HIGH convergent**
4. **Disconnected wires UI** - presets `streaming_optimal/compact/calibration` (450 LOC dormants) + DOM-as-truth `_buildDecisions` + bulk-approve hardcode 90. **CRITICAL convergent**
5. **Pas d'atomicite/rollback** - `apply_audit` dead + pas de `BEGIN/ROLLBACK` + PENDING zombi `apply_batches`. **HIGH convergent**
6. **OpType case desaligne** - `probe_models` lowercase desaligne UPPERCASE journal/apply. **HIGH convergent**
7. **Seuils confidence eparpilles** - 75/50 backend vs 80/60 vs 85/60 vs 90 hardcode frontend. **CRITICAL convergent**

---

## 5. Items deferred (Vagues O / P / Q / R)

### Vague O - Performance & infra court terme

- Score breakdown additif UI waterfall + Custom Formats user-definables (24h, inspiration Radarr)
- SQLite pragmas canoniques 2026 (WAL + busy_timeout + mmap) + validation terrain NAS/SMB (20h)
- Paralleliser scan walker phase 1+2 ThreadPoolExecutor (8h, gain SMB x5-x8)
- Pipeline `NormalizedProbe` `@dataclass` + `StrEnum OpType` end-to-end (10h, refonte typing)

### Vague P - Apply atomique & verrous

- Mode transactionnel `apply_atomic=True` opt-in avec rollback reverse undo (12h)
- Hierarchie quality-tier-trumps : resolution > codec > HDR > audio > group (8h)
- Field-locking par film apres correction manuelle (Jellyfin lock fields, 6h)
- Lock optimistic-concurrency `save_validation` (`version_token`, HTTP 409) (5h)
- Tri-etat decisions backend/frontend approved/rejected/pending (6h)
- Tags providers bracket notation `{tmdb-XXX}` `[imdbid-ttXXX]` (6h)
- Double seuil Minimum Score + Upgrade Until style Radarr (6h)

### Vague Q - Cycles & quarantaine

- Casser cycle architectural domain<->domain via `path_utils.py` (6h)
- Cycle quarantaine non-documente : TTL + UI "vider le bucket" + `_review` unifie (8h)
- `check_path_length` kill-switch MAX_PATH Windows a cabler (2h)

### Vague R - Audits manquants

- Audit `infra/` (SQLite threading, FFmpeg subprocess) zero couverture Deep
- Audit security exhaustif (path traversal, shell injection) au-dela mention low actuelle
- Audit `tests/` (coverage, fixtures dupliquees, tests morts)
- Profiling performance reel (gains `slots=True` non mesures, calibration globale)
- Framework calibration A/B testing pour magic numbers (subtitle, presets, deltas TMDb)

---

## 6. Pour toi

Apres la Vague M et les audits complets, on a identifie 28 items a regler dans la prochaine vague (Vague N). Les bugs critiques actifs (crash films francais avec accents, score Platinum frauduleux possible) ont ete corriges immediatement. Le reste est planifie.

---

*Document genere apres double audit (Deep + Logic) post-Vague M, tag `vague-m-postmortem-final`.*
