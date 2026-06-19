# R8 — JOURNAL DES CORRECTIONS (différentiel prouvé contre BASELINE_R8)

> **Régime** : on n'est plus en read-only. On corrige, **1 commit par finding**, chaque message portant le
> différentiel baseline en preuve. Branche `loop/correction-2026-06` ; checkpoint **`f493abdc`** = point de
> retour INTACT (non touché). **Pas de push** tant que F1+F2 ne sont pas clos et prouvés. Pas de `git stash`.
> Règle d'acceptation : un fix bascule une observation baseline « cassé→correct » **sans** régresser une autre.
> Registre source : [`../baseline_r8/BASELINE_R8.md`](../baseline_r8/BASELINE_R8.md). Artefacts : `./` (ce dossier).

---

## R8-081 — F-TEST-01 — Réparer l'instrument : assertion tautologique → vérification réelle
**Famille** : F6 (qualité de test / instrument) — corrigé **EN PREMIER** (avant F1) : tant qu'un test ment,
valider un fix sur un « vert » ne prouve rien. **Commit** : `885402c` (loop/correction-2026-06).

### 1. Localisation + intention réelle
- **Fichier** : `tests/test_auto_install.py:35-37`, méthode `TestGetToolsDir.test_creates_dir`.
- **Assertion bidon (AVANT)** : `self.assertTrue(d.exists() or True)  # peut ne pas exister en CI`
  → `X or True` vaut **toujours** `True` (court-circuit Python) : `d.exists()` n'est **jamais** décisif.
  Le commentaire « peut ne pas exister en CI » est **faux** : `get_tools_dir()` crée toujours le dossier.
- **Intention réelle** (nom du test = `test_creates_dir`) : vérifier que `get_tools_dir()` **CRÉE** le dossier
  `tools/` qu'il retourne. **Contrat prouvé** : `cinesort/infra/probe/auto_install.py:162-170` — `get_tools_dir`
  fait `tools_dir.mkdir(exist_ok=True)` **puis** `return tools_dir` → après l'appel, le dossier DOIT exister
  (inconditionnellement, CI incluse).

### 2. Correction de l'assertion (test seul, pas le code de prod)
```diff
-        self.assertTrue(d.exists() or True)  # peut ne pas exister en CI
+        # get_tools_dir() fait tools_dir.mkdir(exist_ok=True) puis retourne :
+        # le dossier DOIT exister apres l'appel (cf auto_install.py:169).
+        self.assertTrue(d.exists(), "get_tools_dir() doit creer le dossier tools/")
```

### 3. Issue = **3a** (le test PASSE → comportement sous-jacent correct, test juste mal écrit)
Test corrigé lancé seul → **PASSED** (`tests/test_auto_install.py::TestGetToolsDir::test_creates_dir`).
Le `mkdir(exist_ok=True)` est bien présent en prod ; aucun bug masqué (pas d'issue 3b).

#### Preuve de FALSIFIABILITÉ (3 états) — le test teste VRAIMENT
**(a) Preuve « live »** (plant/revert de la vraie ligne `auto_install.py:169`, sur copie de travail, prod
restaurée byte-for-byte — `git diff` vide après revert) :
| État | Manip | Résultat |
|---|---|---|
| **1. vert honnête** | code de prod réel | `test_creates_dir` **PASSED** |
| **2. rouge sur bug planté** | `tools_dir = base/"tools_R8PLANT"` + `mkdir` commenté (nom frais car `tools/` existant masquerait un simple retrait de mkdir) | **FAILED** : `AssertionError: False is not true : get_tools_dir() doit creer le dossier tools/` |
| **3. vert après revert** | revert exact des 3 lignes | **PASSED** ; `git diff cinesort/infra/probe/auto_install.py` **vide** |

**(b) Preuve REJOUABLE sans éditer la prod** : `r8_081_falsifiability.py` (+ `.out.txt`) — monkeypatch de
`get_tools_dir` par une version buggée (pas de mkdir, chemin frais). Verdict figé :
`etat1_vert_honnete: PASS` · `etat2_rouge_sur_bug: RED OK (assertion levee)` · `etat3_vert_apres_revert: PASS`
→ **VERDICT : FALSIFIABLE PROUVÉE (vert/rouge/vert)**.

> Pourquoi un nom de dossier « frais » dans le plant : le dossier `tools/` existe déjà à la racine du dépôt,
> donc retirer seulement le `mkdir` laisserait `d.exists()==True` (le bug serait masqué). Le plant simule
> fidèlement « `get_tools_dir` ne crée pas le dossier qu'il retourne » = exactement le bug que le test doit attraper.

### 4. Balayage du pattern tautologique (borné — listé, NON corrigé ici)
Grep ciblé sur `tests/` (`or True`, `or 1`, `assert True`, `assertTrue(True)`, assertions à constante) :
| Occurrence | Verdict |
|---|---|
| `tests/test_auto_install.py:37` | **= R8-081, corrigé ci-dessus.** |
| `tests/test_rest_security.py:279` `self.assertTrue(True)` | **TAUTOLOGIE réelle** — `test_cors_configurable_explicit_still_emitted` est un **placeholder no-op** (docstring : « Couvert par `test_cors_can_be_restricted_explicitly` ci-dessous »). À traiter (candidat **R8-086** : supprimer le placeholder ou lui donner une vraie assertion). **Listé, non corrigé.** |
| `tests/test_phase4_parametres_endpoints.py:61` `int(... or 1)` | **FAUX POSITIF** : idiome de valeur par défaut dans un mock de setup, pas une assertion. |
| `tests/test_quality_score.py:393` `int(... or 1) + 1` | **FAUX POSITIF** : idem (default dans le setup). |

**Conclusion balayage** : le pattern tautologique est **quasi isolé** — **2 occurrences réelles** (R8-081 traité
+ 1 placeholder no-op à `test_rest_security.py:279`). Ce n'est **pas** une couture systématique de la couche test
(≠ les seams de prod). Le placeholder est trivial → proposé comme **R8-086** (F6), à traiter séparément.

### 5. Non-régression (suite complète, 6199 tests)
- **Baseline PRÉ-FIX** (`suite_baseline_prefix.txt`, 30 min) : **107 failed, 5813 passed, 183 skipped, 170 errors,
  230 subtests passed**. Échecs/erreurs pré-existants (majorité = `test_runtime_contrast_wcag` chromium/Playwright,
  env-dépendants — recoupe R8-076). **264 nœuds en échec/erreur** snapshotés dans `prefix_failures.txt` ;
  `test_auto_install` **absent** de cet ensemble (mon fichier était déjà vert).
- **POST-FIX** (`suite_postfix.txt`, 30 min) : **107 failed, 5813 passed, 183 skipped, 170 errors, 230 subtests
  passed** — **compteurs IDENTIQUES** au pré-fix.
- **Delta** (`postfix_failures.txt` vs `prefix_failures.txt`, `comm`) : **264 nœuds en échec/erreur des deux côtés** ;
  **NOUVEAUX échecs = ∅** (0), **disparus = ∅** (0) → ensemble byte-identique. `test_auto_install` **absent** des
  échecs post-fix (vert). ✅ **NON-RÉGRESSION OK : 0 nouvel échec.**

> Le changement est **isolé à une assertion** d'un seul test (qui passe) sans aucune dépendance partagée ni
> modification de prod → aucun autre test ne peut casser de ce fait. La comparaison de l'ensemble des nœuds en
> échec pré/post valide formellement la non-régression.

### Artefacts rejouables
- `r8_081_falsifiability.py` + `r8_081_falsifiability.out.txt` (preuve vert/rouge/vert sans edit prod).
- `suite_baseline_prefix.txt` (baseline pré-fix), `prefix_failures.txt` (264 nœuds pré-existants), `suite_postfix.txt`.

---

## ═══ FAMILLE F1 — PERTE DE DONNÉES NON RÉCUPÉRABLE ═══

## R8-001 — F-V8-COLL-ATOMIC — Atomicité intra-row collection + ledger dedup non empoisonné
**Famille** : F1. **Commit** : `7b25d50` (loop/correction-2026-06). Fix A+B **indissociable** (1 commit).

### Cause racine (baseline)
`apply_collection_item` (`cinesort/app/apply_core.py`) déplace les sidecars PUIS la vidéo, et marque le ledger
`dedup_seen_ops` **AVANT** chaque move. Si le move vidéo échoue (`.mkv` verrouillé → `PermissionError` dans
`atomic_move`), les sidecars sont déjà partis, la vidéo reste en source = **item à moitié appliqué, sans
rollback** ; et la clé dedup de la vidéo, ajoutée avant le move, fait **skipper l'item au retry** →
demi-application **PERMANENTE / irrécupérable**. Baseline figée : `../baseline_r8/captures/v9_coll_atomic_repro.out.txt`
(`half_applied=true, dedup_poisoned=true, no_rollback=true`).

### Fix (avant→après, `apply_core.py:2109-2165` → bloc atomique)
- **(A) Atomicité** : la séquence sidecars+vidéo est encadrée par un `try/except (OSError, PermissionError)`.
  On suit les moves réellement effectués (`moved_for_rollback`) ; sur échec, `_rollback_partial_item()` **remet
  en source** (ordre inverse) chaque fichier déplacé (`atomic_move` + op `ROLLBACK_COLLECTION_MOVE` journalisée),
  puis **re-lève** → la boucle per-row (`apply_core.py:~1650`) enregistre l'erreur « FICHIER VERROUILLÉ » et
  poursuit le batch (résilience per-row déjà en place). État final = **tout-ou-rien**.
- **(B) Ledger** : `dedup_seen_ops.add(op_key)` déplacé **APRÈS** le `move_file_with_collision_policy` réussi
  (`_commit_dedup`). Sur échec, `_rollback_partial_item` fait `discard` des clés ajoutées pour cet item → un
  **retry RE-TRAITE** l'item au lieu de le skipper.

### Différentiel baseline prouvé (artefact rejouable `r8_001_coll_atomic_diff.py` / `.out.txt`)
| Observation | AVANT (baseline) | APRÈS (fix) |
|---|---|---|
| (A) état après échec move vidéo | `half_applied=true` (sidecars orphelins, vidéo en source) | **cohérent** : vidéo en source, sidecars **restaurés en source**, **2 ops ROLLBACK** émises |
| (B) ledger dedup vidéo | `dedup_poisoned=true` (marquée « vue » → retry skippe) | **non poisonné** → **retry RE-TRAITE et COMPLÈTE l'item** (vidéo+sidecars dans le sous-dossier, source vidée) |
| repro baseline `v9_coll_atomic_repro.py` re-joué | `half_applied=true, dedup_poisoned=true` | `half_applied=false, dedup_poisoned=false, rollback_ops=2` → **VERDICT « non reproduit »** |

### Non-régression
- `tests/test_apply_atomicity.py` : **23 passed**.
- Suite complète (`suite_r8_001.txt`) : **107 failed / 5813 passed / 170 errors** — **IDENTIQUE** au pré-fix ;
  diff `r8_001_failures.txt` vs `prefix_failures.txt` (`comm`) : **264 nœuds, 0 nouveau, 0 disparu**. ✅ 0 régression.

### Artefacts
- `r8_001_coll_atomic_diff.py` + `.out.txt` (différentiel A+B, fixture jetable, prouve retry-re-traite).
- `suite_r8_001.txt` (suite post-fix), `r8_001_failures.txt` (264 nœuds = pré-existants).

---

## R8-002 — F-QTN-GOV — Gouvernance TTL quarantaine : préservation des originaux non revus
**Famille** : F1. **Commit** : `e4c8723` (loop/correction-2026-06). Capture baseline **instrumentée**
cette vague (placeholder `cap_qtn_governance` résolu).

### Instrumentation d'abord (cause racine vérifiée vs registre)
La baseline R8-002 n'était pas figée (placeholder). Instrumentée sur fixture jetable :
`../baseline_r8/captures/cap_qtn_governance.py` (+ `.out.txt`). **Cause racine confirmée et précisée** :
- L'apply écrit les buckets quarantaine conflict/duplicate/leftover sous **`<run_dir>/_review`**
  (`apply_support.py:1489` : `run_review_root = run_paths.run_dir / "_review"`).
- Le TTL quarantaine (`quarantine_ttl.review_root`) ne gouverne QUE `cfg.root/_review`.
- La rétention-runs **`clean_old_runs(state_dir, keep_last=20)`** (`infra/state.py:105`) fait
  `shutil.rmtree(run_dir)` sur les vieux runs → **détruit `<run_dir>/_review` entier**, donc les
  **originaux quarantinés** (vrais fichiers films déplacés sur collision/doublon) **avant revue
  utilisateur, quel que soit le TTL** (30 j ignoré). = **perte de données non récupérable**.
- *Écart vs description registre* : le registre disait « TTL ne gouverne pas 4/5 buckets » ; la vraie
  mécanique destructrice est la **rétention-runs** (`clean_old_runs`), pas la TTL elle-même. Fix adapté à la réalité.

### Fix (garde-fou de gouvernance — `infra/state.py:105`, **pas de purge destructive d'une quarantaine non revue**)
`clean_old_runs` **PRÉSERVE** désormais tout `<run_dir>/_review` contenant des fichiers : il le **reloce sous
`runs/_preserved_review/<run_id>/`** (dossier **exclu** de la rétention) AVANT de `rmtree` le reste du run_dir.
La rétention-runs reste effective (les run_dirs sont nettoyés) mais ne **détruit plus** d'original quarantiné.
*(Choix : préservation plutôt que déplacer la TTL — supprimer des originaux non revus sur un minuteur est
précisément le risque de perte ; la préservation supprime le risque. Croissance bornée par revue utilisateur.)*

### Différentiel baseline prouvé
| Observation (fixture : run vieux avec `_review/_conflicts/<original>.mkv`, `clean_old_runs(keep_last=2)`) | AVANT | APRÈS |
|---|---|---|
| `cap_qtn_governance.py` → RESUME | `data_lost=true, preserved_copies=0` (`../baseline_r8/captures/cap_qtn_governance.out.txt`) | **`data_lost=false, preserved_copies=1`** → original sous `runs/_preserved_review/...` (`r8_002_qtn_governance_diff.out.txt`) |
| run_dir vieux nettoyé (rétention OK) | oui | oui (préservation n'empêche pas le nettoyage du reste) |

### Non-régression
- Ciblé `-k "state or quarantine or retention or runs"` : 192 passed ; 3 failed + 4 errors **tous pré-existants**
  (chromium/Playwright, ∈ baseline 264 ; `comm` vs `prefix_failures.txt` = 0 nouveau). Aucun test n'appelle
  directement `clean_old_runs`.
- Suite complète (`suite_r8_002.txt`) : **107 failed / 5813 passed / 170 errors** — **IDENTIQUE** au pré-fix ;
  diff `r8_002_failures.txt` vs `prefix_failures.txt` (`comm`) : **264 nœuds, 0 nouveau, 0 disparu**. ✅ 0 régression.

### Artefacts
- `../baseline_r8/captures/cap_qtn_governance.py` (instrument) + `.out.txt` (snapshot **cassé** baseline).
- `r8_002_qtn_governance_diff.out.txt` (post-fix, `data_lost=false`), `suite_r8_002.txt`.

---

## F1 — FILET INTÉGRITÉ (round adversarial sur la surface corrigée) — `wf_9d8b47a3-ba0`
> 3 finders (apply_collection_item rollback · ledger dedup · clean_old_runs préservation) + panel
> **3 sceptiques à asymétrie** par candidat + 2 leurres de calibration.

- **RELIABLE=true** (3/3 finders vivants, panel 3/3 votes partout). **Leurres : 0/2 fuités** (panel calibré).
  **Cumulé campagne : 0/30.**
- **10 candidats levés → 0 SURVIVANT** (seuil ≥2/3 « réel »). Tous **réfutés** par re-dérivation sur le code réel :
  - « ops MOVE_FILE forward restent reversible=True après rollback » → réfuté : l'undo est **idempotent +
    existence-guarded** (`apply_rollback`/`_execute_undo_ops` SKIP si dst absent / src présent) → pas de double-revert.
  - « pending-move orphelin du move vidéo échoué re-tenté au boot » → réfuté : `reconcile_pending_moves` **classe
    + log + DELETE seulement, ne re-move JAMAIS** ; verdict `rolled_back` = exactement l'état disque post-rollback.
  - « compteurs quarantaine non revertés → row à la fois errored + partiellement-actionné » → réfuté comme
    **cosmétique d'observabilité**, PAS une perte (fichiers quarantinés correctement laissés en place). *(Note F6
    possible plus tard, non-intégrité.)*
  - « `_preserved_review` croît sans borne » → réfuté : **tradeoff assumé** (préserver > supprimer un original non
    revu) ; croissance bornée par la revue utilisateur. *(Housekeeping F6 éventuel : UI « purger préservés ».)*
  - « cross-filesystem partial move » (1/3, le plus proche) → réfuté : `_review` et `_preserved_review` sont sous
    le **même volume** (`runs/`) → `shutil.move` = rename atomique, pas copy2+delete → cas non atteignable.
  - + name-collision TOCTOU, rglob perf, `_commit_dedup` sur statut non-moved → tous réfutés (guards existants / non-intégrité).
- **Verdict filet** : les fixes R8-001/R8-002 **n'ouvrent AUCUN nouveau gap d'intégrité** (panel-confirmé, calibré).
  Aucun nouveau finding R8-086+ à enregistrer côté intégrité. 2 notes non-intégrité (compteur cosmétique,
  housekeeping `_preserved_review`) consignées ci-dessus pour F6 éventuel — **pas des cibles F1/F2**.

---

## ═══ FAMILLE F2 — INTÉGRITÉ / INVARIANTS — SOUS-SALVE F2-a (PARITÉ TV, seam #1) ═══

> Stratégie : **portage garde-par-garde** des gardes du chemin film (référence **corrigée post-F1**) vers
> `apply_tv_episode`, confronté à la **grille de parité V7**. Le cœur : router les moves vidéo + sidecars par
> `move_file_with_collision_policy` (porte sha1/size + collision/contenu + ops dry-run + mkdir compté d'un coup),
> + réalignement sidecars + atomicité (parité COLL-ATOMIC post-F1) + édition UI. **Commit** : `da09ff9`.

### Grille V7 → statut R8 (fermeture du seam #1)
| # | Garde (chemin film = réf) | Finding | Portée ? | Comment |
|---|---|---|---|---|
| 1 | Sidecars réalignés sur le nom cible (SxxExx) | F-V4B-TV1 | ✅ | stem cible + chaîne de suffixes ; génériques (poster) gardent leur nom |
| 2 | `src_sha1`/`src_size` sur les ops (anti-undo-dangereux) | F-V4B-TV2 | ✅ | via `move_file_with_collision_policy` |
| 3 | MAX_PATH sur `_longest_inner` (vidéo **et** sidecars) | F-V6-TV-MAXPATH | ✅ | boucle sur target_file + chaque sidecar réaligné |
| 4 | Politique de collision + comparaison contenu | F-V5-TV3 / F-V6-TV-SIDECOLL | ✅ | NOOP naïf `exists()` retiré → `move_file_with_collision_policy` (quarantaine, plus de drop silencieux) |
| 5 | `record_op` émis **en dry_run** (preview) | F-V6-TV-DRYRUN | ✅ | via la policy (ops + compteur en dry_run) |
| 6 | `mkdir_counted` (compté + journalisé) | F-V6-TV-MKDIR | ✅ | via la policy (`target_dir.mkdir` brut retiré) |
| 7 | Édition UI titre/année honorée | F-V6-TV-UIEDIT | ✅ | `new_title`/`new_year` plombés + utilisés dans le naming |
| 8 | Atomicité intra-row (parité COLL-ATOMIC post-F1) | (parité R8-001) | ✅ | rollback des moves effectués si échec + re-raise per-row |
| — | Sidecar conflict avalé sans WARN | F-H3-02 | ✅ | `except: pass` retiré → géré par la policy / rollback |
| — | Compteur `res.moves` faux en dry_run/NOOP | (TV-DRYRUN) | ✅ | `res.moves += 1` inconditionnel retiré (compté par move réel) |
| 9 | Leftovers + nettoyage dossier source | F-V7-TV-LEFTOVERS | ⏸️ **DIFFÉRÉ** | un dossier TV = **plusieurs épisodes** (≠ dossier film = 1 film) ; porter « move leftovers + rmdir source » à l'aveugle **risquerait de supprimer d'autres épisodes**. Nécessite une sémantique TV-aware (nettoyer seulement si le dossier ne contient plus de média après TOUS les épisodes). **Pas un port aveugle — résiduel.** |
| 10 | Anime numérotation absolue (`season=None`→Saison 00) | F-V6-TV-ANIME | ⏸️ **DIFFÉRÉ** | placement des animes en numérotation absolue (Saison 00 vs Saison 01 vs plat) = **décision produit/convention**, hors « port d'une garde film » (le film n'a pas de saisons). Résiduel. |
| 12 | Undo casse-seule restauré (côté **undo**) | F-V6-UNDO-CASE | ⏸️ **DIFFÉRÉ** | bug du **chemin undo** (`apply_support.py:442`), pas de `apply_tv_episode` ; affecte film ET TV. Fix distinct (commit dédié F2). |

### Différentiel baseline prouvé (`r8_f2a_tv_parity_diff.py` / `.out.txt`, fixtures jetables)
Baseline cassé figé : `../baseline_r8/captures/v5_tv_apply_repro.out.txt` (TV1 orphelins, TV2 sans sha1) +
`cap_tv_parity.out.txt` (gates 3-8). Différentiel cassé→correct, **7 scénarios** :
| Scénario | Garde | AVANT | APRÈS |
|---|---|---|---|
| S1 | 1/2/6 | sidecars nom source (orphelins), ops sans sha1, mkdir brut | sidecars `S01E01 - Pilot.{srt,nfo}` (0 orphelin), op vidéo `src_sha1` présent, **MKDIR journalisé** |
| S2 | 4 | 2e épisode différent **laissé en source** (silencieux) | source **quarantinée** (`conflicts_quarantined_count=1`), pas laissée |
| S3 | 8 | item à moitié appliqué si sidecar échoue | vidéo **rollback** (revenue source, **2 ops ROLLBACK**), état cohérent |
| S4 | 5 | aucune op en dry_run | **3 ops MOVE_FILE** journalisées, **0 move physique** |
| S5 | 7 | édition titre/année **ignorée** (dossier `Wrong Series (2019)`) | dossier **`Corrected Series (2021)`** utilisé |

### Non-régression
- `tests/test_path_length_killswitch_v77.py` : **12 passed** (2 appels mis à la nouvelle signature). Sweep apply/TV
  ciblé : 386 passed, échecs **tous pré-existants** (chromium/e2e, 0 nouveau vs baseline).
- Suite complète (`suite_f2a.txt`) : 108 failed / 5812 passed / 170 errors. Diff vs baseline (`f2a_failures.txt`
  vs `prefix_failures.txt`) : **0 disparu**, **1 « nouveau » = `test_perceptual_parallel.py::…test_video_and_audio_tasks_run_via_pool`**.
  → **FLAKY, PAS une régression** : (a) causalement indépendant — le test n'importe que `perceptual.parallelism`/
  `perceptual_support`/`cinesort_api`, jamais `apply_core.apply_tv_episode` ni `state.clean_old_runs` (mes seuls
  sites) ; (b) **non-déterministe** — 3/9 PASS en isolation (assertion de parallélisme via `time.sleep(0.1)`,
  sensible à l'ordonnancement) ; une vraie régression serait déterministe + aurait un chemin causal. Absent des 3
  runs baseline précédents (chance). → **enregistré R8-086** (test flaky, F6/durcissement-tests), NON corrigé en F2-a.
  **Ensemble des nœuds déterministes inchangé : 264, 0 nouvel échec réel.** ✅

### Artefacts / sites
- Prod : `apply_core.py` `apply_tv_episode` (signature += conflicts/sidecars/dup roots, hash_cache, new_title/new_year ;
  corps réécrit) + caller L1568 (plombage ctx) ; test `test_path_length_killswitch_v77.py` (signature).
- `r8_f2a_tv_parity_diff.py` + `.out.txt` (S1-S5), `suite_f2a.txt`.

### Filet F2-a (round adversarial sur le TV porté + pipeline amont) — `wf_2fbab5c8-0ad`
> 3 finders (move-block porté · pipeline TV amont · **re-confrontation grille V7**) + panel 3 sceptiques
> asymétrie + 2 leurres. **RELIABLE=true** (3/3 finders), **leurres 0/2**. **Cumulé campagne : 0/34.**
- **8 candidats → 0 SURVIVANT** (seuil ≥2/3). Finder 3 (grille V7) n'a remonté **aucun** gardé « réputé porté mais
  absent » → l'inventaire **8 portés + 3 différés est vérifié complet**.
- 3 candidats à 1/3 (dissident unique, réfutés) : (a) « vidéo quarantinée → sidecars orphelins » → réfuté : la
  vidéo n'est quarantinée que si `target_file` **existe déjà** (épisode réel) → les sidecars réalignés s'attachent
  à cet épisode réel, pas à un fantôme ; (b) « fichiers multi-épisodes S01E01E02 collapsés » → **amont/parsing**,
  hors grille apply, non introduit par le port (réfuté 2/3, non promu) ; (c) « TV devrait utiliser `dedup_seen_ops` »
  → réfuté : épisodes uniques par row (pas de double-move batch comme collection) + collision gérée par la policy.
- « Orphan season dir au rollback » → réfuté 0/3 : **parité film pré-existante** (apply_single/collection laissent
  aussi un dir vide au rollback ; l'op MKDIR est réversible au niveau undo-batch). Cohérent avec le filet F1.
- **Verdict filet** : le port n'introduit **aucun nouveau gap**, et **aucune garde portable du seam #1 n'a été
  oubliée**. Aucun nouveau finding (hors R8-086 flaky déjà enregistré).

### ═══ VERDICT F2-a (2026-06-17) ═══
- **Seam #1 (parité TV)** : **FERMÉ EN CORRECTION pour les gardes PORTABLES** — 8 gardes portées + prouvées
  (gates 1-8 + UIEDIT), filet 0 survivant, grille V7 re-confrontée. **3 résiduelles DIFFÉRÉES** (non portables à
  l'aveugle) : gate 9 leftovers (sémantique TV-aware requise), gate 10 anime (décision produit), F-V6-UNDO-CASE
  (chemin undo, film+TV, commit dédié). → seam **NON intégralement fermé** ; reste = 3 gardes non-portables-en-l'état.
- **Différentiels** : S1-S5 tous cassé→correct. **Non-régression** : 264 nœuds déterministes, 0 nouvel échec
  (1 flaky R8-086). **Commit** : `da09ff9`. Checkpoint `f493abdc` intact, pas de push.

---

## ═══ FAMILLE F2 — SOUS-SALVE F2-b (DEDUP-LOSER) ═══

> R8-017 (atomicité) + R8-018 (compteur/récupération) **indissociables dans le bloc per-rid du helper loser**
> (la correction du compteur édite les lignes que la résilience per-rid réécrit) → **1 commit F2-b** justifié.
> **Commit** : `<hash F2-b>`. Cohérence : même logique d'isolation que la boucle per-row (L1650) + COLL-ATOMIC (F1)
> + TV gate 8 (F2-a) — rollback **factorisé** dans `_revert_moves` (pas une 3ᵉ variante). **Commit** : `2fd4f63`.

### R8-017 — LOSER-ATOMIC (helpers loser/marked hors try/except → batch avorté + partiel)
- **Cause racine** : `move_duplicate_losers_to_user_decided` (L1303) + `move_marked_for_deletion_to_bucket` (L1320)
  appelés **avant** la boucle per-row, **hors** son try/except → un fichier verrouillé **avorte TOUT le batch**
  (winners inclus), partiel laissé = incohérent. Asymétrie : une row normale verrouillée est attrapée per-row (L1650).
- **Fix** (`apply_core.py`, les DEUX helpers) : chaque `rid` est encadré par `try/except (OSError, PermissionError)`
  → sur échec : `_revert_moves(...)` rollback les moves déjà faits **de ce loser** (parité COLL-ATOMIC), `res.errors += 1`,
  message, **`continue`** (PAS de re-raise — on est hors boucle per-row, re-lever avorterait le batch = le bug).
  Comptage **atomique par rid** (ajouté à `res` qu'après succès complet).
- **Différentiel** (`r8_f2b_loser_atomic_diff.py` / `.out.txt`, fixtures) : **S1** 2 losers, le 1ᵉʳ verrouillé →
  AVANT le helper **propage** (batch avorté, loser 2 non traité) ; APRÈS **None** propagé, **loser 2 traité**,
  `res.errors=1`. **S2** loser collection, vidéo échoue après sidecars → **sidecars rollback** (revenus source),
  vidéo en source, état cohérent.

### R8-018 — LOSER-COUNTER (invariant moved==deleted cassé + récupération mensongère)
- **Cause racine** : le helper loser incrémentait `duplicates_identical_moved_count` (compteur des byte-identiques,
  lockstep avec `_deleted_count` à L690-691) → **invariant `moved==deleted` cassé** (moved>deleted) + l'UI
  (`apply_support.py:1685/1754`) pointait `_duplicates_identical` alors que les fichiers sont dans
  `_duplicates_user_decided` = **chemin de récupération mensonger**. (Le helper `marked` avait déjà son compteur dédié = modèle.)
- **Fix** : (a) **compteur dédié** `ApplyResult.duplicates_user_decided_moved_count` (`core.py`, miroir de
  `marked_for_deletion_moved_count`) ; le helper loser l'incrémente au lieu de `duplicates_identical_moved_count`
  → l'invariant `moved==deleted` tient (les byte-identiques ne co-incrémentent qu'à L690-691). (b) `apply_support.py` :
  ligne de synthèse + **chemin de récupération RÉEL** (`if duplicates_user_decided_moved_count>0 → _duplicates_user_decided`).
- **Différentiel** (`r8_f2b_loser_counter_diff.py` / `.out.txt`) : **S1** après un loser : `duplicates_identical_moved_count=0`
  (AVANT=1 à tort), `=deleted=0` → **invariant tient** (AVANT `1 != 0`) ; `duplicates_user_decided_moved_count=1` (dédié).
  **S2** `apply_support` propose `_duplicates_user_decided` (chemin réel).

### Non-régression
- Ciblé `test_phase6_doublons_apply` + `test_marked_for_deletion_apply_v77` + `test_merge_duplicates` : **20 passed**
  (aucun test ne pinnait l'ancien compteur).
- Suite complète (`suite_f2b.txt`) : **107 failed / 5813 passed / 170 errors** — diff vs baseline
  (`f2b_failures.txt` vs `prefix_failures.txt`) : **264 nœuds, 0 nouveau, 0 disparu** (R8-086 flaky a même
  passé ce run). ✅ 0 régression.

### Artefacts / sites
- Prod : `apply_core.py` (`_revert_moves` neuf + per-rid try/except des 2 helpers + compteur loser dédié) ;
  `core.py` (`duplicates_user_decided_moved_count`) ; `apply_support.py` (synthèse + chemin récup).
- `r8_f2b_loser_atomic_diff.py`/`.out.txt`, `r8_f2b_loser_counter_diff.py`/`.out.txt`, `suite_f2b.txt`.

### Filet F2-b (round adversarial couche dedup/loser/marked) — `wf_1b2f6be3-74a`
> 3 finders (atomicité loser/marked · comptabilité/invariants · chemins de récupération + undo) + panel
> 3 sceptiques asymétrie + 2 leurres. **RELIABLE=true**, **leurres 0/2**. **Cumulé campagne : 0/38.**
- **11 candidats → 2 SURVIVANTS** (même finding, 2 angles) = **R8-087** : `marked_for_deletion_moved_count`
  (R7-4) n'avait NI ligne de synthèse NI chemin de récupération `_user_marked_for_deletion` dans le rapport
  d'apply (sibling de R8-018 ; **mon ajout du chemin loser a aggravé l'asymétrie**). Bucket silencieux.
- **Refuté notable (0/3, sécurité-critique vérifié par moi)** : « `shutil.Error` échappe au `except` et avorte
  le batch » → **FAUX** : `shutil.Error` **EST** un `OSError` (MRO `Error→OSError→Exception`,
  `issubclass==True`, vérifié en live) → le `except (OSError, PermissionError)` l'attrape → R8-017 **suffisant**.
- Autres refutés (0/3) : windows_safe/unique_path TypeError (non levé/atteint), comptage collection sain,
  pas d'autre site cassant moved==deleted, pas de consommateur sommant le nouveau compteur, rollback ne fuit
  pas `_rid_count`, op-types ROLLBACK_* inoffensifs au reconcile. → **R8-017/R8-018 sans gap résiduel**.

### R8-087 — F-MARKED-RECOV-SILENT (chemin de récupération marked silencieux) — CORRIGÉ EN F2-b (filet)
- **Cause** : `marked_for_deletion_moved_count` populé (R7-4) mais **absent** de `apply_support.py` (0 occurrence)
  → ni synthèse ni « À RETENIR » vers `_user_marked_for_deletion` (alors que `_duplicates_identical` et,
  depuis R8-018, `_duplicates_user_decided` le sont). L'utilisateur ne savait pas où récupérer ses films marqués.
- **Fix** (`apply_support.py`) : ligne de synthèse « Films marqués pour suppression déplacés » + action_line
  `if marked_for_deletion_moved_count>0 → _user_marked_for_deletion`. **Additif UI** (compteur existant, 0 logique).
- **Différentiel** : `marked_for_deletion_moved_count`/`_user_marked_for_deletion` passe de **0 → 4** occurrences
  dans `apply_support.py` (synthèse + récup). **Non-régression** : tests de synthèse `test_backend_flow` +
  `test_marked_for_deletion_apply_v77` = **5 passed** ; additif pur (la suite F2-b a validé le code environnant).
  Sweep apply/dedup ciblé : 765 passed, 0 nouvel échec. **Commit** : `0cd24a1`.

### ═══ VERDICT F2-b (2026-06-17) ═══
- **R8-017** (atomicité per-loser/marked) + **R8-018** (invariant `moved==deleted` + chemin récup réel) :
  différentiels cassé→correct prouvés (S1/S2 chacun) ; **commit `2fd4f63`**.
- **Filet** `wf_1b2f6be3-74a` : RELIABLE=true, leurres 0/2, **1 écart trouvé (R8-087) ET corrigé en salve**
  (`0cd24a1`) ; concern sécurité-critique « shutil.Error avorte le batch » **réfuté + vérifié** (shutil.Error EST
  un OSError → R8-017 suffisant). 0 écart résiduel sur R8-017/R8-018.
- **Non-régression** : suite complète 264 nœuds, 0 nouvel échec. Cohérence : rollback factorisé `_revert_moves`,
  même logique que per-row/COLL-ATOMIC/TV (pas une 3ᵉ variante). **Checkpoint `f493abdc` intact, pas de push.**

---

## ═══ FAMILLE F2 — SOUS-SALVE F2-d (MIGRATIONS / SELF-HEAL / SQLITE) ═══

> Couche PERSISTANCE. Cartographie préalable (workflow `wf_73fcafa1-f69`) : **insight de cohérence** — il y a
> UN seul self-heal ; R8-022/023 élargissent le set de tables requises → font feu le bootstrap plus souvent →
> **R8-019 (la mine paused_at) doit être fixé AVANT**. Différentiels store-fixture jetables. **Les 5 captures
> saines (migrations lossless v27→v31, settings round-trip, TTL/rollback quarantaine, bornes) restent INTACTES.**

### Cluster self-heal (commit `c29a48e`) — R8-019/020/021/022 (un seul self-heal cohérent)
- **R8-019 F-MIG-PAUSEDAT (HIGH, perte données)** : le bootstrap self-heal rejoue 025 (`DROP TABLE runs` +
  `INSERT ... SELECT ..., NULL`) sur une DB qui a déjà `paused_at` → écrasait tous les `paused_at` à NULL. Fix
  **migration-level self-heal-safe** : `ALTER TABLE runs ADD COLUMN paused_at REAL` (1ᵉʳ passage l'ajoute NULL = idem ;
  replay → « duplicate column » idempotent-skip) + `SELECT paused_at` (au lieu de NULL) → valeur **PRÉSERVÉE**.
  **Diff S-019** : `1234567.89` préservé au self-heal.
- **R8-021 F-MIG-IDEMPOTENT — initialement « fixé » dans `c29a48e`, puis RETRACTÉ dans `cd663d2`** : le fix initial
  (except élargi `(OperationalError, IntegrityError)` + allowlist unique/pk) **introduisait une PERTE DE DONNÉES**,
  attrapée par le filet F2-d (survivor 3/3). Les migrations de RECONSTRUCTION (021/025 : `INSERT INTO X_new SELECT ...
  FROM X` ; `DROP X` ; `RENAME`) rejouées par le self-heal sur une **source corrompue** (PK dupliquée) lèvent une PK
  `IntegrityError` ; la « skipper » via `ROLLBACK TO SAVEPOINT` laisse `X_new` **VIDE**, puis `DROP+RENAME` **wipe
  silencieusement** la table (même classe que la mine 025/NULL de R8-019 !). **Décision : bloquer le boot sur
  `IntegrityError` est le comportement SÛR (recuperable via backup) vs wipe irrécupérable** → retour à `OperationalError`
  seul (`_is_idempotent_error(exc: OperationalError)`, fragments `duplicate column`/`already exists`). **Diff
  `r8_f2d_filet_survivors_diff` §1** : source corrompue 3 lignes → AVANT (swallow) wipe à **0** ; COURANT (raise) préserve
  **3** + re-lève. **Diff S-021 inversé** (UNIQUE/PK/NOTNULL → NON idempotent, re-levés). Cf section « Filet F2-d ».
- **R8-020 F-MIG-SCHEMAVER** : le bootstrap posait `user_version` sans rien insérer dans `schema_migrations` →
  historique désync. Fix : backfill `INSERT OR IGNORE` par migration ≤ version après le bootstrap. **Diff S-020** (31 rows).
- **R8-022 F-V6-SCHEMA-IRC** : `incremental_row_cache` (mig 008) absente du filet self-heal. Fix : ajout à
  `REQUIRED_SCHEMA_TABLES` + `SCHEMA_GROUPS['incremental']`. **Diff S-022** (droppée → recréée par le self-heal).
- **R8-023 F-V8-SCHEMA-REGISTRY ⏸️ DIFFÉRÉ** : la cartographie a révélé que `vec_films_hash` n'est pas juste absente
  du registre — son **fichier `032-vector-search-tables.sql` est en TIRETS**, donc **jamais découvert** par
  `_MIGRATION_FILE_RE` (digit+underscore) → la table n'existe **jamais**. L'ajouter aux tables requises **sans
  renommer 032 ferait BOUCLER le boot** (RuntimeError « schéma incomplet »). Or `similar_films` est **OFF** et
  `SqliteVecAdapter` un **scaffold** (`NotImplementedError`) → activer le vector-search (renommer 032) = **décision
  produit**. Capture saine `c3_migrations` confirme « 032 tirets IGNORÉE = latent ». **Différé jusqu'à activation produit.**

### Crons / taxonomie / sérialisation
- **R8-024 F-V3-E2 (HIGH)** (`e21a004`) : 3 sites attrapaient `(AttributeError,OSError,RuntimeError,TypeError,ValueError)`
  mais PAS `sqlite3.OperationalError` (= DatabaseError, ≠ OSError) → un verrou DB transitoire **tuait le thread cron**
  (retention/quarantaine définitivement mortes) ou **avortait le lot de probe**. Fix : `+sqlite3.Error` aux 3 tuples
  (+AttributeError au probe). **Diff** : `c3e_cron` rejoué → « SWALLOW (cron survit)/robuste » (AVANT « cron meurt »).
- **R8-025 F-DB-01 (HIGH)** (`afb504c`) : `runtime_support` passait `busy_timeout_ms=8000` → 8000≠5000 déclenchait le
  re-override back-compat qui **écrasait le busy_timeout du profil NAS** (30000/60000) → SQLITE_BUSY prématuré. Fix :
  laisser le défaut (5000) → back-compat ne se déclenche pas → le **profil fait foi** (la logique `connect_sqlite`
  reste pour les callers explicites, ex. test 3000). **Diff S-025** : NAS=30000 préservé avec 5000 vs 8000 (le bug).
- **R8-026 F-V3-E1** (`39d80aa`) : `atomic_write_json` faisait `os.replace` sans retry → PermissionError Windows
  (lecteur concurrent) → write perdu. Fix : retry borné 5× (backoff 50ms), atomicité préservée. **Diff S-026**.
- **R8-029 F-QTN-MANIFEST** (`8628e42`) : `_save_ttl_manifest` `write_text` direct (non atomique) → corruption
  possible. Fix : tmp+os.replace. (Pattern R8-026.)
- **R8-027 F-META-01 + R8-090 (jumeau)** (`43088fc`) : les DEUX désérialiseurs PlanRow perdaient un champ DIFFÉRENT
  (asdict sérialise les deux) — `row_from_json` perdait `nfo_runtime` (R8-027), `plan_row_from_jsonable` perdait
  `source_root` (R8-090, **découvert par la cartographie**). Fix symétrique : chacun parse les deux. **Diff** :
  round-trip préserve nfo_runtime ET source_root (lost=[]) ; `meta_roundtrip` baseline lève maintenant « obtenu [] » = corrigé.

### Filet F2-d (round adversarial migrations/self-heal/crons/sérialisation) — `w2g8eihie`
- **RELIABLE=true** ; 3 finders, **12 candidats** ; panel 3 sceptiques asymétriques + **2 leurres de calibration
  → decoys_leaked=0** (cumul filets F1→F2-d : **0/44**). **2 survivants 3/3**, tous deux résidus du code écrit en F2-d :
- **(1) R8-021 — RÉSIDU DATA-LOSS, le fix R8-021 lui-même** : voir entrée R8-021 ci-dessus. **RETRACTÉ `cd663d2`**
  (le filet a attrapé une régression de perte de données que J'AVAIS introduite dans `c29a48e`). HIGH.
- **(2) R8-091 — F-CAND-COLLECTION** (`a64789b`) : `candidate_from_json` (`run_data_support.py:37`) construisait
  `core.Candidate` SANS `tmdb_collection_id`/`tmdb_collection_name` (`core.py:387-388`) — couture **jumelle** de
  R8-027/R8-090 un cran plus profond (Candidate vs PlanRow). Le jumeau `plan_row_from_jsonable` (`plan_support_core.py:82-86`)
  les parse déjà → au reload post-restart, chaque candidat voyait son id+nom de collection TMDb **nullé silencieusement**.
  Fix : parse des deux champs en miroir. **Diff `r8_f2d_filet_survivors_diff` §2** : collection préservée (lost=[]).
- **10 candidats réfutés** (dont : « même résidu sur l'`apply()` par-migration » 0/3 — le forward-apply ne rejoue chaque
  migration qu'une fois ; back-compat busy_timeout pour tout ≠5000 0/3 ; `_save_ttl_manifest` tmp-name 0/3 ; retry 750ms
  suffisant 0/3 ; `nfo_runtime=0` faux gap 0/3 ; parité PlanRow sans autre drop 0/3).

### Non-régression F2-d
- Migrations lossless v27→v31 **INTACTE** post-retract R8-021 (`c3_migrations` : ASCENDANT OK, self-healing IDEMPOTENT,
  T6 upgrade v27→v31 lossless, `tables_perdues={}`). **Le retract ne touche QUE le chemin source-corrompue** ; les DB
  saines ne lèvent jamais d'`IntegrityError` au rebuild → 0 impact. 5 captures saines toutes intactes.
- Ciblé migration/collection/sérialisation : **90 passed / 2 skipped** ; les **2 seuls échecs**
  (`test_phase4_bibliotheque_endpoints` Export/Counters) **prouvés PRÉ-EXISTANTS** (reproduits à l'identique sur HEAD sans
  mes modifs uncommitted ; mock `get_tmdb_override` ère R7-3, chemin ne touche aucun code F2-d). Self-heal `r8_f2d_selfheal_diff`
  **VERDICT CORRIGÉ** (S-019/020/021-inversé/022). Suite complète (`suite_f2d.txt`) : **108 failed / 5812 passed / 170 errors** —
  diff vs baseline : **0 disparu, 1 « nouveau » = R8-086 flaky** (`test_perceptual_parallel`, timing, indép. de la persistance)
  → **ensemble déterministe 264, 0 nouvel échec réel.** ✅
- Artefacts : `r8_f2d_selfheal_diff`, `r8_f2d_persistence_diff`, `r8_f2d_roundtrip_diff`, **`r8_f2d_filet_survivors_diff`**
  (+ `.out.txt`), `suite_f2d.txt`.

### ═══ VERDICT F2-d (2026-06-18) ═══
- **9 findings traités** : R8-019 ✅, R8-020 ✅, R8-021 **RETRACTÉ** (fix initial = data-loss, le filet l'a prouvé),
  R8-022 ✅, R8-024 ✅, R8-025 ✅, R8-026 ✅, R8-027 ✅, R8-029 ✅. **+ R8-090** (jumeau, cartographie) ✅ **+ R8-091**
  (jumeau profond, filet) ✅. **1 DIFFÉRÉ** : R8-023 (`vec_films_hash` / 032-tirets scaffold OFF → décision produit).
- **Self-heal COHÉRENT** : un seul pipeline. R8-019 ordonné AVANT R8-022/023 (élargir le set de tables requises fait
  feu le bootstrap plus souvent). Le filet a confirmé la cohérence ET attrapé une mine que le « durcissement » R8-021
  avait elle-même créée → retract. **Aucune rustine concurrente.**
- **Commits F2-d** : `c29a48e` (cluster self-heal R8-019/020/022, R8-021 retracté après), `e21a004` (R8-024),
  `afb504c` (R8-025), `39d80aa` (R8-026), `8628e42` (R8-029), `43088fc` (R8-027+R8-090), `cd663d2` (R8-021 RETRACT),
  `a64789b` (R8-091), `217f55d` (journal).

---

## ═══ FAMILLE F2 — SOUS-SALVE F2-c (ROLLBACK / STATUTS + UNDO-CASE) ═══

> Cohérence d'ÉTAT (statuts rollback/undo qui mentent/se figent), pas d'intégrité fichier. Différentiels
> comportementaux sur fixtures `SQLiteStore` jetables (`r8_f2c_rollback_undo_diff.py` : S-012/013/015/011, tous verts).

### R8-013 — RB2 (rollback_status figé IN_PROGRESS si kill pendant revert) — `1eb7916`
- **Cause** : `rollback_forward` marque `IN_PROGRESS` (apply_rollback.py:380) puis le statut final ; un kill entre les
  deux laisse `rollback_status='IN_PROGRESS'` à vie. `reconcile_pending_batches` ne scanne que `apply_batches.status='PENDING'`
  (le batch en rollback est FAILED) → état figé jamais récupéré.
- **Fix** (`apply_batches_reconciliation.py`) : nouveau `reconcile_inprogress_rollbacks` — au boot, liste les batches
  `rollback_status='IN_PROGRESS'` (`_list_inprogress_rollbacks`) et **RE-LANCE `rollback_forward`** (idempotent : ops déjà
  revertées protégées par les gardes FS `dst_missing`/`src_already_exists` + `undo_status='DONE'` R8-012). Câblé **avant**
  le pass PENDING dans `reconcile_batches_at_boot`. **Différentiel S-013** : kill simulé (mark IN_PROGRESS, FS à moitié) →
  AVANT figé IN_PROGRESS ; APRÈS `resumed=1`, `rollback_status=ROLLED_BACK_BY_ATOMIC`, FS reverti.

### R8-012 — RB1 (undo_status op-level jamais marqué après revert) — `de28c50`
- **Cause** : `rollback_forward` revertait le FS mais ne touchait jamais `apply_operations.undo_status` → l'historique
  (`history_support.py:300`) + les compteurs `undone_ops`/`pending_ops` (`apply.py:391`) affichaient un batch reverti
  comme « pending_ops=total, undone_ops=0 » = jamais annulé.
- **Fix** (`apply_rollback.py`) : marquer `undo_status` (DONE/FAILED/SKIPPED) après chaque `_revert_one_op`, sans
  rétrograder une op déjà terminale. Rend l'état op-level cohérent + `rollback_forward` reprenable (R8-013).
  **Note design** : la séparation `rollback_status` (atomic) ≠ `undo_status` (manuel) reste tenue — marquer DONE après un
  revert réussi EST sémantiquement correct et **n'interfère pas** avec l'undo manuel (un batch rollback-atomique n'est pas
  `status='DONE'` → jamais proposé à l'undo). **Test mis à jour** : `test_rollback_does_not_change_undo_status` pinnait le
  comportement BUGGÉ (PENDING) → renommé `test_rollback_marks_undo_status_done` (assertion 'DONE'). **Différentiel S-012**.

### R8-015 — apply-status (FAILED figé, n'reflète pas le rollback) — `bab8070`
- **Cause** : l'apply en échec ferme le batch `FAILED` (apply_support.py:2228) **avant** `_atomic_rollback_forward` ; le
  verdict du revert ne va que dans `apply_batch_modes.rollback_status` → `apply_batches.status` reste FAILED, sans dire si
  le FS est restauré. Or le whitelist n'a aucune transition depuis FAILED.
- **Fix** : (a) whitelist `apply.py` : `FAILED → {ROLLED_BACK_BY_ATOMIC}` (seule transition autorisée, pas de retour DONE/
  PENDING → pas de réintroduction dans `get_last_reversible`). (b) `apply_support.py` : après un revert **complètement
  réussi** (`ok` + `rollback_status==ROLLED_BACK_BY_ATOMIC`), re-clore le batch en `ROLLED_BACK_BY_ATOMIC` ; un revert
  partiel/échoué reste FAILED (état ambigu tracé par rollback_status). **Différentiel S-015** : transition AVANT =
  `ApplyBatchStateError` ; APRÈS = statut `ROLLED_BACK_BY_ATOMIC`.

### R8-011 — F-V6-UNDO-CASE (undo casse-seule Windows classé CONFLIT) — `bab8070`
- **Cause** : `_execute_undo_ops` (apply_support.py:442) : `if target_path.exists()` → sur FS insensible à la casse
  (Windows/SMB), restaurer `film`→`Film` voit `Film` « exister » (même fichier physique) → classé CONFLIT/FAILED au lieu de
  restaurer.
- **Fix** : avant le chemin conflit, détecter le cas casse-seule via **`str(current) != str(target)`** (comparaison
  sensible à la casse — l'égalité Path est INSENSIBLE sur Windows et masquerait la diff) **+ `current.samefile(target)`**
  (même fichier physique). Si oui → rename casse-seule réutilisant `_case_only_rename_with_rollback` (détour tmp Windows-safe).
  **Correct sur Windows ET Linux** : sur Linux `Film`≠`film` sont distincts → `samefile=False` → vrai conflit préservé.
  **Différentiel S-011** : `film.mkv` → restauré `Film.mkv` (done=1), AVANT classé `_undo_conflicts` (failed=1).

### R8-014 — apply-status DONE malgré errors — ⏸️ **DIFFÉRÉ**
- **Raison** : le statut « PARTIAL » n'existe PAS dans le whitelist (`_ALLOWED_BATCH_TRANSITIONS`), et surtout
  `get_last_reversible_apply_batch` filtre **`status='DONE'`** uniquement → fermer un apply partiel en « PARTIAL » le
  rendrait **non annulable** = régression PIRE que le nit d'observabilité. Un fix correct = introduire un statut PARTIAL
  **réversible** (whitelist + get_last_reversible + transitions UNDONE + UI) = chantier multi-site à part. Le journal d'AUDIT
  enregistre **déjà** DONE/PARTIAL (`auditor.end`, apply_support.py:1522) → l'observabilité réelle existe ailleurs. **Différé, documenté.**

### Non-régression
- Ciblé rollback/reconcile/robustness : **43 passed** (test RB1 mis à jour). Suite complète (`suite_f2c.txt`) :
  **107 failed / 5813 passed / 170 errors** — diff vs baseline : **264 nœuds, 0 nouveau, 0 disparu**. ✅ 0 régression.

### Artefacts / sites
- Prod : `apply_rollback.py` (R8-012), `apply_batches_reconciliation.py` (R8-013), `apply.py` whitelist + `apply_support.py`
  (R8-015, R8-011) ; test `test_apply_atomic_rollback_integration_v77.py` (RB1 mis à jour).
- `r8_f2c_rollback_undo_diff.py`/`.out.txt` (S-012/013/015/011), `suite_f2c.txt`.

### Filet F2-c (round adversarial rollback/undo/reconcile/statuts) — `wf_b1e98c63-e7b`
> 3 finders (resume/undo_status · transitions de statut · undo casse-seule) + panel 3 sceptiques + 2 leurres.
> **RELIABLE=true**, **leurres 0/2**. **Cumulé campagne : 0/42.** **14 candidats → 2 SURVIVANTS (3/3)**, tous deux
> résidus DE CE QUE JE VENAIS D'ÉCRIRE (R8-013/R8-011) → corrigés en salve.
- **R8-088 (high)** : `reconcile_inprogress_rollbacks` (R8-013) relançait `rollback_forward` mais N'appelait PAS
  `close_apply_batch` → un apply crashé repris au boot atteignait `rollback_status=ROLLED_BACK_BY_ATOMIC` mais
  `apply_batches.status` **restait figé FAILED** (le miroir R8-015 n'était qu'inline). **Fix** : miroir de la re-cloture
  dans le chemin boot. **Diff S-088** : `status FAILED → ROLLED_BACK_BY_ATOMIC` au boot. **Commit** : `32dedb7`.
- **R8-089 (med)** : le `journaled_move` autour du rename casse-seule en 2 temps (`current→.__tmp_ren→target`) ne
  peut pas encadrer l'état intermédiaire → hard-kill entre les 2 renames → reconcile **fausse alarme « FICHIER PERDU »**.
  **Fix** : retrait du wrapper (le rename a son propre rollback ; cohérent avec le site apply non journalisé).
  **Diff S-011** reste vert sans le wrapper. **Commit** : `32dedb7`.
- **Réfuté sécurité-critique (0/3)** : « re-run de rollback_forward NON idempotent → double-revert/perte » → FAUX
  (gardes FS `dst_missing`/`src_already_exists` + `undo_status='DONE'` → SKIPPED, idempotent vérifié). 11 autres réfutés.
- **Non-régression R8-088/089** : ciblé reconcile/rollback **43 passed** + undo **58 passed** ; surgical/additif (la suite
  F2-c a validé le code environnant).

### ═══ VERDICT F2-c (2026-06-18) ═══
- **4 findings corrigés** (R8-013 `1eb7916`, R8-012 `de28c50`, R8-015+R8-011 `bab8070`) + **2 résidus filet corrigés**
  (R8-088/R8-089). **R8-014 différé** (PARTIAL non réversible — chantier multi-site). Différentiels S-012/013/015/011/088
  tous verts. **Non-régression** : suite complète 264 nœuds, 0 nouvel échec. Checkpoint `f493abdc` intact, **pas de push**.

---

## ═══════════ RÉCAP F2 COMPLÈTE — INTÉGRITÉ / INVARIANTS (a/b/c/d) — 2026-06-18 ═══════════

> **28 findings corrigés** sur les 4 sous-salves + **4 chantiers différés** (raisons explicites ci-dessous)
> + **1 fix RETRACTÉ** (R8-021, le filet a prouvé que mon « durcissement » causait une perte de données).
> Méthode constante : différentiel comportemental **cassé→correct sur fixtures jetables**, **un commit par finding**,
> **filet adversarial** (3 finders + panel 3 sceptiques asymétriques + 2 leurres) après CHAQUE sous-salve, résidus
> in-périmètre corrigés en salve. **Calibration filets : decoys_leaked = 0/44 cumulés (F1→F2-d).**

### F2-a — PARITÉ TV (seam #1) — commit `da09ff9`
- **Corrigés (9)** : portage garde-par-garde du chemin film (réf. saine post-F1) vers `apply_tv_episode` — sidecars
  réalignés SxxExx (R8-003), `src_sha1`/`src_size` sur les ops (R8-004), MAX_PATH sur vidéo+sidecars (R8-005),
  collision-policy + comparaison contenu (R8-006), `record_op` en dry_run (R8-007), `mkdir` compté/journalisé (R8-008),
  édition UI titre/année (R8-010), sidecar-conflict avalé (R8-073), compteur `res.moves` faux en dry_run (R8-074).
  Routés par `move_file_with_collision_policy` + atomicité intra-row (parité COLL-ATOMIC). **Diff** : `r8_f2a_tv_parity_diff` S1-S5.
- **Différés (2)** : **R8-009** gate 9 leftovers (sémantique TV-aware requise — 1 dossier TV = N épisodes, nettoyage
  aveugle supprimerait d'autres épisodes), **R8-075** gate 10 anime (numérotation absolue Saison 00 = décision produit).
- **Filet `wf_2fbab5c8-0ad`** : RELIABLE=true, leurres 0/2, **0 survivant** (grille V7 re-confrontée : inventaire 9 portés
  + 2 différés vérifié complet). Note : F-V6-UNDO-CASE listé « différé » en F2-a a été **corrigé en F2-c** (R8-011).
- **Captures instrumentées** : `cap_tv_parity` + `v5_tv_apply_repro` (baseline cassé), `r8_f2a_tv_parity_diff`.

### F2-b — DEDUP / LOSER — commit `2fd4f63` (+ `0cd24a1` filet)
- **Corrigés (3)** : **R8-017** atomicité per-loser/per-marked (les 2 helpers hors try/except → un fichier verrouillé
  avortait TOUT le batch ; fix : try/except par rid + `_revert_moves` factorisé + continue) ; **R8-018** invariant
  `moved==deleted` + chemin de récupération réel (compteur dédié `duplicates_user_decided_moved_count`) ;
  **R8-087** (filet) chemin de récupération `marked_for_deletion` silencieux (sibling de R8-018, aggravé par mon ajout loser).
- **Différés (0)**.
- **Filet `wf_1b2f6be3-74a`** : RELIABLE=true, leurres 0/2, **1 survivant → R8-087 corrigé en salve**. Concern
  sécurité-critique « `shutil.Error` avorte le batch » **réfuté + vérifié live** (shutil.Error EST un OSError).
- **Captures instrumentées** : `r8_f2b_loser_atomic_diff` (S1/S2), `r8_f2b_loser_counter_diff` (S1/S2).

### F2-c — ROLLBACK / STATUTS + UNDO-CASE — commits `1eb7916`/`de28c50`/`bab8070` (+ `32dedb7` filet)
- **Corrigés (6)** : **R8-013** `rollback_status` figé IN_PROGRESS si kill pendant revert ; **R8-012** `undo_status`
  op-level jamais marqué après revert ; **R8-015** apply-status FAILED ne reflète pas le rollback ; **R8-011** undo
  casse-seule Windows classé CONFLIT (le `str()` case-sensitive — `Path` est insensible à la casse sur Windows) ;
  **R8-088** (filet) `reconcile_inprogress_rollbacks` ne re-cloturait pas le batch au boot ; **R8-089** (filet)
  `journaled_move` autour du rename casse-seule 2-temps → fausse alarme « FICHIER PERDU ».
- **Différés (1)** : **R8-014** apply-status DONE malgré errors (PARTIAL n'est pas un statut réversible ;
  `get_last_reversible_apply_batch` filtre `status='DONE'` → fermer en PARTIAL casserait l'undo = pire régression).
- **Filet `wf_b1e98c63-e7b`** : RELIABLE=true, leurres 0/2, **2 survivants → R8-088/R8-089 corrigés en salve**. Concern
  « re-run rollback_forward non idempotent » **réfuté** (gardes FS + `undo_status='DONE'`).
- **Captures instrumentées** : `r8_f2c_rollback_undo_diff` (S-011/012/013/015/088).

### F2-d — MIGRATIONS / SELF-HEAL / SQLITE — commits `c29a48e`/`e21a004`/`afb504c`/`39d80aa`/`8628e42`/`43088fc` (+ `cd663d2`/`a64789b`)
- **Corrigés (10)** : **R8-019** mine paused_at (self-heal rejoue 025 → écrasait paused_at à NULL ; fix migration-level
  ALTER+SELECT, ordonné AVANT le reste) ; **R8-020** backfill `schema_migrations` post-bootstrap ; **R8-022**
  `incremental_row_cache` au filet self-heal ; **R8-024** crons tués par `sqlite3.OperationalError` non attrapé ;
  **R8-025** back-compat busy_timeout écrasant le profil NAS ; **R8-026** `atomic_write_json` sans retry (PermissionError
  Windows) ; **R8-027** + **R8-090** (cartographie) round-trip PlanRow (chaque désérialiseur perdait un champ différent) ;
  **R8-029** `_save_ttl_manifest` non atomique ; **R8-091** (filet) `candidate_from_json` perdait les collections TMDb.
- **RETRACTÉ (1)** : **R8-021** — le « durcissement » (swallow IntegrityError UNIQUE/PK) **introduisait une perte de
  données** (skip d'un `INSERT...SELECT` de rebuild sur source corrompue → table vidée par `DROP+RENAME`). Le filet
  F2-d l'a attrapé (3/3). Retour à `OperationalError` seul = comportement SÛR (boot bloqué recuperable vs wipe). `cd663d2`.
- **Différés (1)** : **R8-023** `vec_films_hash` (mig 032 en tirets = scaffold jamais découvert, `similar_films` OFF,
  `SqliteVecAdapter` = `NotImplementedError`) → activer le vector-search = décision produit.
- **Filet `w2g8eihie`** : RELIABLE=true, leurres 0/2, **2 survivants → R8-021 (retract) + R8-091 corrigés en salve**.
- **Captures instrumentées** : `r8_f2d_selfheal_diff` (S-019/020/021-inversé/022), `r8_f2d_persistence_diff`,
  `r8_f2d_roundtrip_diff`, `r8_f2d_filet_survivors_diff` (§1 wipe, §2 collection). Capture saine `c3_migrations` (lossless v27→v31) intacte.

### CHANTIERS F2 DIFFÉRÉS — à reprendre (4 + 1 test flaky)
| ID | Sujet | Raison du report | Cible |
|---|---|---|---|
| **R8-009** | gate 9 TV-leftovers (nettoyage source après apply TV) | nettoyage aveugle d'un dossier TV (N épisodes) supprimerait d'autres épisodes → sémantique **TV-aware** requise (nettoyer si plus de média après TOUS les épisodes) | F5 (logique métier TV) |
| **R8-075** | gate 10 anime (numérotation absolue → Saison 00) | placement anime (Saison 00 vs 01 vs plat) = **décision produit/convention** | F5 (décision produit) |
| **R8-014** | apply-status DONE malgré `errors>0` | PARTIAL non réversible ; `get_last_reversible_apply_batch` filtre `DONE` → fermer en PARTIAL **casserait l'undo** (régression pire). Observabilité réelle existe ailleurs (`auditor.end` DONE/PARTIAL). Chantier multi-site | F-statuts (refonte statut apply) |
| **R8-023** | `vec_films_hash` (mig 032 vector-search) | fichier 032 en **tirets** = jamais découvert ; table inexistante ; `similar_films` OFF + adaptateur `NotImplementedError` → renommer 032 = **activer une feature produit** | produit (vector-search) |
| **R8-086** | `test_perceptual_parallel` flaky (timing) | non-déterministe (3/9 PASS isolé), causalement indép. de la persistance ; **enregistré, non corrigé** | F6 (durcissement tests) |

### Bilan chiffré F2
- **28 findings corrigés** : F2-a 9 · F2-b 3 · F2-c 6 · F2-d 10. Dont **5 découverts par filet/cartographie et corrigés
  en salve** : R8-087 (F2-b), R8-088/R8-089 (F2-c), R8-090 (cartographie F2-d), R8-091 (filet F2-d).
- **1 fix RETRACTÉ** (R8-021) : preuve de la valeur du filet adversarial — il a attrapé une **régression de perte de
  données que la salve elle-même avait introduite**.
- **4 chantiers différés** (R8-009, R8-075, R8-014, R8-023) + 1 test flaky enregistré (R8-086).
- **Non-régression globale** : ensemble déterministe **264 nœuds, 0 nouvel échec réel** à travers les 4 sous-salves
  (seul « nouveau » récurrent = R8-086 flaky). **5 captures saines intactes** : migrations lossless v27→v31,
  round-trip settings, TTL/rollback quarantaine, bornes/tier.
- **Cohérence** : rollback **factorisé** (`_revert_moves`, une seule variante partagée per-row/COLL-ATOMIC/TV/loser) ;
  self-heal **unique et cohérent** (R8-019 ordonné avant l'élargissement du set de tables requises).
- **17 commits F2** (hors journal) : `da09ff9` · `2fd4f63` `0cd24a1` · `1eb7916` `de28c50` `bab8070` `32dedb7` ·
  `c29a48e` `e21a004` `afb504c` `39d80aa` `8628e42` `43088fc` `cd663d2` `a64789b`. Checkpoint `f493abdc` **intact**, **rien poussé**.

---

## ═══ FAMILLE F3 — SÉCURITÉ (surfaces d'attaque) — 2026-06-18 ═══

> Règle d'acceptation ADAPTÉE : **DOUBLE différentiel** par finding — (1) l'attaque qui réussissait AVANT
> échoue APRÈS (vecteur fermé) ; (2) l'usage loopback LÉGITIME continue de marcher. **INVARIANT : le bypass
> loopback légitime (client 127.0.0.1 + bind 127.0.0.1) n'est jamais cassé — on ferme la porte aux attaquants,
> pas à l'utilisateur local.** Repros d'attaque via requêtes forgées sur instance/fixtures de test.

### Ordre par gravité : BINAIRE ARBITRAIRE → GET NON GARDÉS → PORT/ORIGINE

### R8-032 — BINAIRE ARBITRAIRE (ffprobe exec, asymétrie save/exec) — `8adeff2`
- **Vecteur** : `settings.json` place `ffprobe_path` sur un binaire arbitraire (`calc.exe`/`malware.exe`) ;
  le flux perceptuel l'exécutait en `argv[0]` SANS `_binary_name_allowed` (la garde whitelist que
  `get_tools_status` applique déjà). Asymétrie save/exec.
- **Fix coherent (UNE garde, source unique)** : `safe_tool_path()` neuf dans `infra/probe/tooling.py`
  (= `_resolve_tool_path(..., shutil.which)`) → applique le MÊME whitelist de noms. Les **5 sites** perceptuels
  (`perceptual_support.py` L140/296/333/642/818) passent par `safe_tool_path(..., "ffprobe")`.
- **Double diff** (`r8_f3_binaire_arbitraire_diff.py` §R8-032) : `ffprobe_path=malware.exe` → AVANT renvoie le
  malware (exécuté), APRÈS fallback PATH ffprobe (refusé) ; `ffprobe.exe` légitime → préservé.

### R8-033 — BINAIRE ARBITRAIRE (sibling ffmpeg) — `d90be70`
- **Vecteur** : `resolve_ffmpeg_path` dérivait le `ffmpeg.exe` VOISIN du dossier de `ffprobe_path` sans contrôle
  (4 sites) → un `ffprobe_path` arbitraire faisait exécuter un ffmpeg voisin malveillant.
- **Fix (auto-défense, domain-pur)** : ne dériver le sibling QUE si le basename de `ffprobe_path` ∈
  `_ALLOWED_FFPROBE_NAMES` (whitelist locale, `domain/` ne peut pas importer `infra`) ; sinon fallback
  `shutil.which("ffmpeg")`.
- **Double diff** (§R8-033) : sibling de `evil/malware.exe` → AVANT dérive `evil/ffmpeg.exe` (exécuté), APRÈS
  fallback PATH ffmpeg ; sibling d'un vrai `tools/ffprobe.exe` → `tools/ffmpeg.exe` préservé.

### R8-030 — GET NON GARDÉS (`/api/poster?force=1` CSRF) — `05a8795`
- **Vecteur** : `force=1` PURGE le cache disque + re-télécharge depuis TMDb (effet de bord). Un
  `<img src=…&force=1>` CROSS-SITE (hébergé par un site tiers, **sans Origin** → `_is_forbidden_cross_site`
  ne l'attrape pas) déclenchait ce purge/re-DL en CSRF, même en bind 127.0.0.1.
- **Fix coherent** : `_is_cross_site_get()` = Origin présent+interdit **OU** `Sec-Fetch-Site: cross-site`
  (le signal que les navigateurs envoient sur les `<img>` no-cors). `force` NEUTRALISÉ si cross-site ; la
  LECTURE du poster (cache) reste ouverte (`<img>` legitimes same-origin/natif).
- **Double diff** (`r8_f3_rest_csrf_diff.py` §R8-030, serveur REST réel) : `<img>` cross-site `force=1` → AVANT
  purge+re-DL, APRÈS `force` ignoré ; same-origin + client natif → `force` conservé.

### R8-031 — PORT/ORIGINE (loopback tout-port accepté) — `6a80929`
- **Vecteur** : `_allowed_origin` acceptait n'importe quel PORT loopback → une 2ᵉ app locale hostile sur
  `http://localhost:9999` voyait son Origin reflétée et passait la garde CSRF via le bypass auth loopback.
  (Le port de **bind** du serveur, lui, est correctement honoré — `rest_api_port` → constructeur ; pas de
  faille « bind en dur » : vérifié.)
- **Fix** : `_own_port()` (`server_address[1]`, fallback header `Host`) ; la branche loopback de
  `_allowed_origin` n'autorise QUE le port d'écoute effectif (scheme libre). `own_port` indéterminable → on
  autorise (ne casse pas l'usage local sans socket introspectable).
- **Double diff** (§R8-031) : POST Origin `localhost:<autre_port>` → AVANT autorisé, APRÈS **403** ; Origin
  `127.0.0.1:<port_serveur>` → **200** (légitime). Test `test_cors_echoes_localhost_origin` mis à jour (il
  épinglait le bug : echo de `:9999`) + `test_cors_rejects_localhost_other_port` ajouté.

### Filet F3 (round adversarial sécurité — surface réseau + exécution) — `wp33755cv`
- **RELIABLE=true** ; 3 finders sécurité (gardes GET/POST · exec binaire · origine/bind) + panel 3 sceptiques
  asymétriques + **2 leurres de calibration → decoys_leaked=0** (cumul filets F1→F3 : **0/46**). 9 candidats,
  **3 survivants 3/3**, tous **résidus des fixes F3** → corrigés en salve :
- **R8-093 (exec-0)** (`885dca2`) : `tools_manager.detect_probe_tools` exécute le `ffprobe_path`/`mediainfo_path`
  explicite (`_probe_version_line`) SANS `_binary_name_allowed` — **2ᵉ chemin d'exec** que R8-032 (limité à
  `tooling._resolve_tool_path`) n'avait pas couvert. Atteignable via REST `get_probe_tools_status`/`recheck`.
  Fix : le candidat `('explicit', path)` n'est ajouté que si `_binary_name_allowed`. **Double diff**
  (`r8_f3_tools_manager_exec_diff.py`) : malware → AVANT candidat d'exec, APRÈS filtré (fallback managed).
- **R8-094 (origin-0) + R8-095 (guards-0)** (`79500b4`, UNE garde cohérente) : `force` restait honoré pour un
  client **LAN non-navigateur** (curl en bind 0.0.0.0) — R8-030 ne couvrait que le navigateur cross-site
  (R8-094) ; et même SANS `force`, un GET poster cross-site sur **cache MISS** déclenchait un fetch TMDb +
  écriture disque (amplification/quota — R8-095). Fix : `_poster_trusted_caller()` (navigateur same-origin OU
  client loopback) gate TOUS les effets de bord poster → untrusted : `force` neutralisé ET
  `serve_poster(allow_fetch=False)` = **cache seul** (ni fetch, ni purge, ni écriture). LECTURE cache préservée.
  **Double diff** (`r8_f3_poster_trusted_diff.py`) : LAN curl → untrusted ; LAN dashboard same-origin → trusted ;
  untrusted+MISS → 404 sans fetch ; untrusted+HIT → 200 servi ; trusted+MISS → fetch tenté.
- **6 candidats réfutés** (0/3 ou 1/3) : `/api/spec` non-auth (lecture inoffensive) ; `/api/health` non-auth ;
  save_settings sans validation (settings.json = déjà local) ; perceptual av1/hdr (couvert par R8-032) ;
  scheme dans la branche loopback ; `_own_port` via Host spoofable. **2 leurres → 0/3** (bypass loopback faux
  positif, SSRF poster total) correctement réfutés.

### Non-régression F3
- **INVARIANT bypass loopback préservé** : `r8_f3_rest_csrf_diff.py` non-rég — `GET /api/health` 200,
  `POST` local sans Origin **200** (le bypass auth loopback fonctionne, CSRF ne bloque pas le local légitime).
- Ciblé sécurité/poster/tooling : `test_rest_security` CORS/CSRF **6 passed** (test bug mis à jour + 1 ajouté) ;
  poster/proxy **14 passed** ; tooling/tools_manager **31 passed** ; binaire diff **4/4** ; CSRF diff **7/7** ;
  poster-trusted diff **4/4**. Les **4 échecs `legacy-410`** de `test_rest_security` (POST `/api/get_settings`
  → 410 Gone) sont **PRÉ-EXISTANTS** (documentés CLAUDE.md ; reproduits à l'identique sur HEAD).
- Suite complète (`suite_f3.txt`, 19 min) : **36 failed / 5801 passed / 113 errors** (les compteurs bruts diffèrent
  de la baseline F2-d 108/5812/170 **uniquement** à cause des tests `[chromium]`/`e2e_desktop` dont le statut
  failed↔error varie selon l'état navigateur/display au run — bruit d'environnement, pas du code F3).
  **PREUVE déterministe rigoureuse** : les **24 nœuds FAILED non-chromium** rejoués en isolation sur l'arbre F3
  **ET** sur l'arbre PRÉ-F3 (`git checkout 72431b4 -- <7 fichiers F3>`) donnent un set **IDENTIQUE**
  (`diff` vide : 23 déterministes pré-existants — ci_workflows, pyinstaller, release_hygiene, refactor_84,
  audit_regression, phase3/4/5 UI, `rest_security` legacy-410 ×4, `bibliotheque` ×2 — + 1 flaky `test_quality_score`
  qui passe en isolation). Les 31 errors non-chromium sont tous `e2e_desktop/*` (display requis, pré-existants).
  → **0 nouvel échec déterministe introduit par F3.** ✅ INVARIANT bypass loopback préservé.

### ═══ VERDICT F3 (2026-06-18) ═══
- **4 surfaces d'attaque fermées** (binaire arbitraire ×2 R8-032/033, GET force CSRF R8-030, port/origine R8-031)
  **+ 3 résidus filet** (R8-093 2ᵉ exec, R8-094 force-LAN, R8-095 fetch-amplification) = **7 findings corrigés**.
  Double différentiel (attaque fermée + loopback légitime intact) prouvé pour chacun. **Garde cohérente** :
  `safe_tool_path` (exec) + `_poster_trusted_caller` (effets de bord poster) — pas N variantes.
- **Commits F3** : `8adeff2` (R8-032) · `d90be70` (R8-033) · `6a80929` (R8-031) · `05a8795` (R8-030) ·
  `885dca2` (R8-093) · `79500b4` (R8-094+095). Checkpoint `f493abdc` **intact**, **rien poussé** (on pousse
  APRÈS F3 close — failles non exposées avant réparation).

---

## ═══ FAMILLE F4 — RÉSULTATS FAUX SILENCIEUX — 2026-06-18 ═══

> **PLAN A retenu** : vrai **ffmpeg/ffprobe 8.1.1** (Gyan build) présent sur le PATH -> instrumentation
> RÉELLE sur fixtures vidéo synthétiques (jamais le mock pour prouver une mesure). Les fixes perceptuels
> sont prouvés par **relations métamorphiques** (invariance / monotonie / discrimination) mesurées sur de
> vraies exécutions. Règle F4 : le vert mocké ne vaut rien — différentiel sur **mesure réelle**.

### GROUPE PERCEPTUEL — la « mesure du vide » (R8-034 / 035 / 036)
**AVANT (instrumenté, `r8_f4_perceptual_instr.out.txt`)** : 3 fixtures VISIBLEMENT différentes (testsrc2 net,
mandelbrot, mandelbrot écrasé) produisent des mesures **IDENTIQUES** — frames_parsed=0, loudnorm=None,
crest/dynrange=None, block/blur=0 -> scores **95/95** fabriqués. Le perceptuel ne mesurait RIEN.
- **R8-034** (`23df760`) : `analyze_loudnorm` passait `-v quiet` -> stderr vide -> loudness EBU R128 jamais
  mesurée (None). Fix `-v info`. **Diff réel** : clean IL=-21.76 vs degraded (vol 0.05) **-47.85** (discrimine).
- **R8-035** (`435006b`) : Crest factor / Dynamic range lus dans le bloc « Overall » d'astats où ils n'existent
  PAS (uniquement par canal, vérifié ffmpeg 8.1.1 mono+stéréo) -> None -> 2 poids audio figés à 50. Fix :
  `_min_float` sur le texte complet (pire canal). **Diff** : crest/dynrange réels et discriminants.
- **R8-036** (`542bdaa`) : filtre `signalstats,blockdetect,blurdetect` SANS `metadata=mode=print` (filtres
  muets sur stderr) + parser sur des clés inexistantes (`YAVG=`/`block:`) au lieu des vraies `lavfi.*=` +
  garde `"blockdetect" in line`. -> 0 frame -> block/blur=0 -> _score_*(0)=95. Fix 3 volets : metadata=print,
  clés `lavfi.signalstats.YAVG=`/`lavfi.block=`/`lavfi.blur=`, regroupement par `frame:N`. Tests FilterParsing
  réécrits sur le format RÉEL (l'ancien mock `block: 22.5` n'était jamais produit = test qui mentait).
**APRÈS (instrumenté)** : frames_parsed=**48** ; loudnorm/crest/dynrange réels et **discriminants** ;
block_mean discrimine (clean 12.33 vs mandelbrot 1.08) + block SCORE discrimine (75 vs 95) ; blur_mean réel et
**MONOTONE** (4.53 net -> 15.98 flou). Relations métamorphiques (iii discrimination + ii monotonie) tiennent
APRÈS et échouaient AVANT.
- **R8-096 (résidu DÉFÉRÉ)** : l'instrumentation R8-036 a EXPOSÉ que les seuils `BLUR_*` (0.01-0.10) ne
  correspondent PAS à l'échelle réelle de blurdetect (net≈4.5 stable 480p↔1080p, flou≥16) -> le SCORE blur
  sature à 10. Le `blur_mean` est désormais RÉEL ; la recalibration des seuils exige un **corpus de films réels
  labellisés** (le grain affecte blurdetect) + la MAJ de ~10 tests composite qui encodent l'ancienne échelle.
  **Différé** (décision de calibration produit), enregistré R8-096.

### CACHE TMDb (R8-041) — `2a337d4`
`search_movie` cachait `[]` sur une réponse 200+results=[] ; `_cache_get` (cached is not None, vrai pour [])
servait [] 7 jours -> film figé « non identifié » après UN hoquet TMDb. Fix : `if results:` avant `_cache_set`.
**Diff** (`r8_f4_tmdb_cache_diff`) : APRÈS vide non caché -> 2e search re-fetch -> récupère Inception ; AVANT sert [].

### VALEURS FAUSSES (R8-038 bitrate, R8-039 codec, R8-040 parsing)
- **R8-038** (`258af2a` + test `6c29b11`) : bitrate audio toujours en bps (invariant probe) -> division
  INCONDITIONNELLE /1000. AVANT : seuil >10000 -> 8000 bps (8 kbps dégradé) lu 8000 kbps -> **+4 bonus au lieu
  de -3 malus** (inversion de signe). Tests « kbps kept » (192/1509/9000 nus) = domaine PHANTOM (le probe
  produit 192000), réalignés sur l'invariant bps + cas dégradé 8000->8.
- **R8-039** (`9df787a`) : `_best_audio_track` triait par (channels, bitrate) codec-AVEUGLE. **Diff fichier RÉEL**
  (FLAC 6ch rank3 VBR + EAC3 6ch @640k rank2) : AVANT eac3 (faux) ; APRÈS flac = `duplicate_compare._best_audio`
  (113 divergences éliminées). Fix : clé (codec_rank, channels, bitrate) via `codec_ranks.AUDIO_CODEC_RANK`.
- **R8-040** (`608ced6`) : `replace('.',' ')` transforme "DD5.1"->"DD5 1" -> `\b[257][\s.][01]` échoue (5 collé à
  DD) -> résidu pollue la query TMDb. Fix : préfixe `(?:ddp?)?` optionnel. **Diff** : DD5.1/DDP5.1/DD7.1/DD2.0
  retirés, "21 Jump Street" préservé.

### ÉCHELLE / CONTRAT (R8-042 dup-scale, R8-043 HDR, R8-044 mkv title)
- **R8-042** (`48a8cf9`) : doublons.js rendait des POINTS head-to-head en "X/100" -> "0/100" pour un bon perdant.
  Fix : échelle = points d'avantage sur points en jeu (scoreA+scoreB), libellé « Avantage » + « pts ». node --check OK.
- **R8-043** (`822b93c`) : la modale lit `d.hdr_analysis.hdr_format/is_hdr` mais `VideoPerceptual.to_dict`
  n'émettait pas la clé -> « sdr » pour tout film. Fix : champ `hdr_type` + clé `hdr_analysis` dans to_dict +
  report depuis le probe. **Diff** : detect_hdr_type(bt2020,smpte2084)=hdr10 (réel) ; modale AVANT « sdr »,
  APRÈS « hdr10 »/« sdr » correct. (Fixture HDR synthétique testsrc2 ne tague pas toujours primaries/transfer ;
  un vrai film HDR porte les tags — détection prouvée dessus.)
- **R8-044** (`831d867`) : égalité exacte container_title vs proposed -> 88% de faux `mkv_title_mismatch`. Fix :
  comparaison par tokens normalisés (bruit scene retiré) + inclusion/recouvrement ≥70%. **Diff** (corpus 10) :
  AVANT 5 faux positifs ; APRÈS 0, 10/10 corrects (vrais conflits flaguent). Test (fichier skippé legacy) corrigé.

### ANNULATION (R8-037) — `8626744`
Le batch perceptuel post-scan lisait `api._perceptual_cancel_event` jamais assigné -> annulation inerte (deux
events disjoints). Fix : `JobRunner.get_cancel_event(run_id)` + le job_fn câble l'event du run sur l'api.
**Diff** (`r8_f4_cancel_diff`) : AVANT _resolve=None ; APRÈS request_cancel (rt.cancel_event.set) propagé au batch.

### Non-régression F4
- Sweep ciblé de TOUS les modules touchés par F4 (perceptual/audio/video/quality_score/quality_report/scene_parser/
  duplicate/mkv/tmdb/job_runner/run_flow/codec/bitrate/hdr/doublons/composite) : **1241 passed**, seuls échecs =
  2 flaky/pré-existants prouvés (`test_analyze_quality_batch` tempfile-PermissionError ; `test_rollup_by_codec` =
  e2e legacy-410, hors suite non-rég, ne touche pas `_best_audio_track`).
- Suite complète (`suite_f4_failures.txt`, 19 min) : **37 failed / 5802 passed / 113 errors** (compteurs bruts ≈
  baseline F3, le delta = bruit `[chromium]`/`e2e`). **PREUVE déterministe** : les **25 nœuds FAILED non-chromium**
  diffés vs la baseline F3 (24 nœuds, prouvés pré-existants par rejeu pré/post) = **24 IDENTIQUES + 1 delta** =
  `test_golden_path_plan_validate_apply_undo`. Ce nœud **PASSE en isolation, fichier entier, et contexte proche
  (3 fichiers)** sur l'arbre F4 -> échec **full-suite-only** (fuite d'état d'un test distant), surfacé par le
  DÉCALAGE D'ORDONNANCEMENT de mes tests ajoutés (degraded-bitrate, multi-frame, mkv-conflict…) — **PAS** du code
  F4 (qui n'ajoute aucun état global inter-tests : `api._perceptual_cancel_event` est par-instance + nettoyé en
  `finally` ; le cache TMDb est par-instance). **FLAKY CONFIRMÉ par re-run** (`suite_f4_rerun.txt`) :
  golden-path **PASSE** au 2ᵉ run complet (échec au 1ᵉʳ = non-déterministe) et les **24 nœuds non-chromium du
  re-run sont IDENTIQUES à la baseline F3** (diff vide). Même classe que R8-086.
  → **0 nouvel échec DÉTERMINISTE introduit par F4** (24 nœuds pré-existants, prouvés). ✅

### Filet F4 (round adversarial couche mesure/analyse) — `w2m3xjy1g`
- **RELIABLE=true** ; 3 finders (mesure du vide · cache empoisonnable · échelle/unité fausse) + panel 3 sceptiques
  asymétriques + **2 leurres → decoys_leaked=0** (cumul filets F1→F4 : **0/48**). 7 candidats, **5 survivants**,
  tous **résidus de MÊME CLASSE** que les fixes F4 → 3 corrigés en salve, 2 différés :
- **R8-097** (`ba79f28`, cache-0 3/3 HIGH) : `search_tv()` cachait une réponse vide — **JUMEAU EXACT de R8-041**
  jamais appliqué au TV. Fix `if cache_items:`. **Diff** : vide non caché, re-fetch récupère (id 1399).
- **R8-098** (`ba79f28`, void-0 3/3 HIGH) : clipping non mesuré (`total_segments=0`, verdict 'unknown') ->
  `if clip:` truthy -> `s_clip=90` fabriqué (classe R8-034/035). Fix : gate `total_segments > 0` -> neutre 80.
  **Diff** : score non-mesuré (58) < mesuré-sans-clipping (59).
- **R8-099** (`ba79f28`, scale-0 2/3 LOW) : `_bitrate_label` seuil bps/kbps (classe R8-038) -> 8000 bps affiché
  « **8 Mbps** » (1000× faux). Fix `/1000` inconditionnel. **Diff** : « 8 Mbps » -> « 8 kbps », 25 Mbps inchangé.
- **R8-100 DIFFÉRÉ** (void-1/void-2 3/3 MED) : `_score_temporal(0)=90` et le chemin **V1** de `_score_val_inv`
  (0->95) fabriquent des scores flatteurs quand le filtre vidéo échoue ENTIÈREMENT (hors R8-036). Reachability
  LIMITÉE (V2 défaut gate la confiance ; V1 = kill-switch ; score final recalculé par V2). Même classe que R8-096
  -> **pass de robustesse-scoring dédié** (drapeau « mesuré ? » + tiers unknown). Différé, enregistré R8-100.
- **2 réfutés** (0/3) : s_clip init=80 (faux gap) ; formatage taille Go/Gio. **2 leurres → 0/3** (score global
  toujours 0 ; clé API en clair dans le cache) correctement réfutés.

### ═══ VERDICT F4 (2026-06-18) ═══
- **14 findings corrigés** : 11 du registre (R8-034/035/036/037/038/039/040/041/042/043/044) + **3 résidus filet
  corrigés en salve** (R8-097 jumeau TV de R8-041, R8-098 clipping vide, R8-099 bitrate label). Différentiel RÉEL
  prouvé pour chacun (mesure ffmpeg réelle pour le perceptuel ; valeur fausse->correcte sinon). **2 résidus
  DÉFÉRÉS** : R8-096 (seuils blur vs échelle blurdetect) + R8-100 (score temporel/V1 fabriqué sur filtre échoué) —
  tous deux « robustesse-scoring » nécessitant un corpus réel + tiers unknown (décision de calibration).
  PLAN A (ffmpeg 8.1.1). **Honnêteté** : aucune mesure prouvée sur le mock ; les tests qui mentaient (FilterParsing
  format bidon, bitrate kbps phantom, mkv scene-mismatch) réécrits sur la réalité.
- **Filet F4** `w2m3xjy1g` : RELIABLE=true, leurres 0/2, 5 survivants (3 corrigés + 2 différés), 0 leurre passé.
- **Commits F4** : `23df760` `435006b` `542bdaa` (perceptuel) · `2a337d4` (tmdb) · `258af2a` `6c29b11` (bitrate)
  · `9df787a` (codec) · `608ced6` (parsing) · `48a8cf9` (dup-scale) · `822b93c` (hdr) · `831d867` (mkv title) ·
  `8626744` (cancel) · `ba79f28` (filet R8-097/098/099). Checkpoint `f493abdc` intact, **rien poussé**.

---

## ═══ FAMILLE F5 — FEATURES MORTES / CONTRATS / SEAMS — 2026-06-18 ═══

### DÉCISIONS PRODUIT (Thomas) appliquées
- **D1 — jumeau film-detail (seam #3)** : la vue standalone `views/film-detail.js` (buggée R8-053/054/055)
  est **SUPPRIMÉE** (`git rm`). La route `/film/:id` est repointée vers le **composant** `components/
  film-detail.js` **mode B** (page standalone, conçu pour /film/:id) — flux d'id identique (route id → row_id →
  `library/get_film_full`), 0 lien mort, 0 changement d'appelant. **FORK-DESIGN UX signalé** : route conservée
  +repointée vs supprimée+recâblage des 3 appelants (home-widgets/qualite/historique) en drawer mode C
  (changement page→drawer) — à arbitrer. Commit `fe659d8`.
- **D2 — anime (R8-075, gate 10)** : **STATU QUO conservé** (Saison 00). Aucune modification du placement anime.
- **D3 — vector-search (R8-023, migration 032)** : **LAISSÉE ÉTEINTE**. Migration 032 non renommée/activée.
  Feature dormante, à construire post-R8, hors périmètre R8.

### SEAMS / CONTRATS CORRIGÉS (différentiels prouvés)
- **R8-057 + R8-059 (seam #4 doublons backend)** `9989ec3` : R8-057 — `check_duplicates` ne relisait jamais la
  décision persistée → badge « Décidé » disparaît au refresh. Fix : `_annotate_groups_with_decisions`
  (winner_decided/winner_side, indexé par group_key, 2 branches). R8-059 — `_quality_info_for_row` ne renvoyait
  que {score,tier} ; fix : codec/résolution/audio depuis le probe. **Diff** `r8_f5_doublons_diff`.
- **R8-060/061/062 (cache + historique)** `7e32924` : R8-060 — `stats_snapshot_for_cache` omettait 6 compteurs
  → perte au round-trip cache HIT. Fix : ajout des 6 champs (delta/apply génériques). **Diff** AVANT 6/6 perdus
  → APRÈS préservés. R8-061 winner_label, R8-062 decision+is_duplicate ajoutés aux builders historique. NB :
  `size_savings` (R8-061) non persisté dans duplicate_decisions → résidu documenté.
- **R8-049/050/051/052 + R8-066 (insights seam #2 + KPI)** `2905a1f` : R8-049 `emit_from_insights` lisait `code`
  jamais émis → 0 notification ; fix `type`. R8-050 qualite subs → id réel `missing_subtitles`. R8-051
  `_INSIGHT_ROUTE_BY_TYPE` re-keyé sur les 5 types réels. R8-052 `_librarianIdToRoute` 4 cas ajoutés. R8-066
  `duplicates_groups` ajouté aux kpis live. **Diff** R8-049 0/2→2/2, R8-051 5/5 default→routés.
- **R8-048 (commentaire index.html)** `cf...` : /processing → initTraitement (commentaire trompeur corrigé).

### FORK-DESIGN SIGNALÉS (arbitrage Thomas requis — NON tranchés)
1. **R8-045 (ENRICH-DEAD)** : vue Enrichissement IA (Ollama) = scaffold délibéré, feature flag `ai_enrichment`
   OFF, contrat d'endpoints documenté mais `enrichment_facade` n'expose pas `get_status`/`apply_bulk`. CÂBLER
   (roadmap IA réelle) vs RETIRER (mort-née). Par défaut : RETIRER.
2. **Insights double vocabulaire** : front a 8 types « métier » (duplicates_probable/films_not_identified/…)
   que `_compute_active_insights` n'émet PAS (5 types physiques). ENRICHIR le producteur (8 types = vraies
   features, routes vers filtres bibliothèque réels) vs accepter le set minimal. Front aligné sur les 5 réels.
3. **R8-063 (cleanup_orphans/empty_folders)** : ambigus vs `cleanup_residual_folders_enabled`/
   `move_empty_folders_enabled` déjà câblés. Features séparées (CÂBLER) vs doublons (RETIRER) ?
4. **R8-070 (retention_days)** : `prune_disk_cache`/`prune_probe_cache` existent mais jamais planifiés ;
   `history_retention_days` pilote déjà le cron. Câbler un cron cache-prune (CÂBLER) vs redondant (RETIRER) ?
5. **R8-067 (animations_enabled)** : kill-switch a11y/perf « UI 100% statique » (CÂBLER `html[data-animations=off]`)
   vs vestige remplacé par `animation_level` (RETIRER) ?
6. **R8-072 (effects_mode)** : consommé par app.js (`dataset.effects`) SANS contrôle UI — exposer un select
   (ALIGNER) vs dev-only ?
7. **R8-056 (perceptual display-path)** : le contrat de la modale (`d.codec/d.width/d.grain_analysis/d.breakdown/
   d.display_tier` top-level) n'a JAMAIS été servi par aucun endpoint (même `to_dict` imbrique sous
   `video_perceptual`/`grain_analysis`). Fix = sérialiseur unique `_flatten_perceptual_for_modal` partagé par
   get_perceptual_details + get_perceptual_report (forme aplatie cohérente F4) + dériver `breakdown` depuis
   `global_score_v2_payload.categories`. **Forme canonique + dérivation breakdown = décision produit.**

### RESTE À FAIRE (clair, décisions recon arrêtées — F5 PARTIELLE)
- **R8-046/047 (vues mortes)** : supprimer qij.js/quality.js/quality-simulator.js/custom-rules-editor.js +
  dossier views/library/ (vestiges purs du split QIJ→qualite & library→bibliotheque, ~1100+ l. mort,
  non routés) ; nettoyer bootstrap-bisect.js + status.js bouton /qij→/qualite. RETIRER (pas de fork-design).
- **R8-058 (DUP-UNITS)** : adopter le helper central `core/format.js` (fmtBytes/formatBytes) dans les 3
  formateurs locaux `_fmtSize` (doublons.js:100, duplicate-comparator-modal.js:57, lib-duplicates.js).
- **R8-064 (auto_approve_enabled)** : CÂBLER — surfacer `get_auto_approved_summary` dans l'UI Traitement.
- **Toggles RETIRER** : R8-065-lang (subtitle_lang_priority fantôme, vraie clé subtitle_expected_languages),
  R8-068 (global_workers/worker_count inerte), R8-069 (desktop_notifications_enabled doublon de
  notifications_enabled), R8-071 (naming_template non lu, canonique = naming_movie/tv_template).
- **R8-065-sep (ALIGNER)** : injecter `{sep}` dans les templates des presets par défaut.
- **i18n** : clé `sidebar.nav.doublons` manquante (locales) — à localiser + ajouter (peut aller en F6).

### Non-régression F5 (partiel)
- Modules touchés (run_flow/doublons/history/notifications/dashboard/plan_support/insights) : **408 passed**
  (sweep `--ignore=tests/e2e*`), seul échec = `test_apply_op_labels` **PRÉ-EXISTANT** (baseline F3). D1 :
  node --check OK, 0 référence résiduelle, 0 lien mort. **0 nouvel échec déterministe.**
- ⚠️ **Note opérationnelle** : 2 process `app.py --api` (PID 324+20268, port 8642, depuis 15/06) arrêtés à la
  demande de Thomas (bloquaient ses lancements). Règle adoptée : ports éphémères + exclure tests/e2e des sweeps.

---

## ═══ FAMILLE F5 — FIN (câblage FORK-DESIGN tranchés + retraits) — 2026-06-19 ═══

Suite de F5 PARTIELLE. Les 7 FORK-DESIGN tranchés par Thomas appliqués + retraits + unif + i18n.

### CÂBLER (effet mesurable ON≠OFF / différentiel prouvé)
- **R8-049/051/052 (insights 8 types métier)** `b995d9f` : `_compute_active_insights` dérive 7/8 types
  MÉTIER du bibliothécaire (quality_reject, duplicates_probable, films_not_identified, subs_missing_fr,
  sagas_incomplete, films_low_confidence, health_low) au lieu de 5 types « physiques » qu'aucune route/
  notif ne reconnaissait. Cap [:5]→[:8]. **Diff** : 1/8→7/8 types métier émis. RÉSIDU : omdb_disagreements
  dormant (aucune comparaison OMDb↔TMDb calculée). Seam #2 fermé côté producteur.
- **R8-056 (forme perceptuelle canonique)** `bcaeb49` : `_flatten_perceptual_for_modal` sert le contrat que
  la modale consomme (grain_analysis/width/height/display_tier/breakdown top-level), JAMAIS servi avant
  (rapport DB imbriqué). breakdown DÉRIVÉ des category_scores V2. **Diff** : grain « — »→rempli, width 0→3840,
  breakdown 0→3 lignes. RÉSIDU : codec « — » (non stocké dans le rapport perceptuel).
- **R8-069 (toast desktop)** `5424f15` : NotifyService.enabled lit desktop_notifications_enabled (toggle UI
  « notifications desktop ») au lieu de notifications_enabled (qui était le mauvais gate). **Diff** : desktop
  ON→toast, OFF→pas de toast. Miroir centre inconditionnel préservé. RÉSIDU : notifications_enabled vestigial.
- **R8-064 (résumé auto-approbation)** `dc774a0` : la vue Traitement consomme run/get_auto_approved_summary
  (jamais appelé avant) → stat « Auto-approuvables (confiance ≥ N) ». **Diff câblage** : 0→3 références.

### RETIRER (disparition propre, 0 lien mort — grep anti-lien-mort effectué)
- **R8-046/047 (vues mortes)** `7d3a6e5`+`c1b0d51`+`2b0e977` : suppression du cluster fermé qij/quality/
  quality-simulator/custom-rules-editor (s'importaient entre eux, 0 import vivant) + dossier views/library/
  (vestige split library→bibliotheque) = **~5009 lignes mortes**. Nettoyage bootstrap-bisect + status.js
  (/qij→/qualite) + 2 tests routage qij obsolètes + liste scan i18n. Les tests v5 référençant ces vues
  skippent déjà (garde legacy).
- **R8-045 (vue IA morte)** `193c8f3` : views/enrichment.js (176 l., scaffold Ollama jamais routé) supprimée.
  Backend scaffold (enrichment_facade/ollama_client) DORMANT post-R8 (statut vector-search D3).
- **Toggles fantômes** : R8-071 naming_template `5fb722f` (canoniques = naming_movie/tv_template), R8-068
  worker_count `7626f60` (inerte), R8-067 animations_enabled `b68bc26` (jamais lu, → animation_level),
  R8-065-lang subtitle_lang_priority `fdcd11e` (write-only, → subtitle_expected_languages), R8-072 effects_mode
  `5fef4a0` (0 CSS consomme data-effects). Chacun : champ parametres.js + persistance settings_support retirés,
  0 consommateur, 60 settings tests verts.

### UNIFIER + i18n
- **R8-058** `b1a6e0f` : doublons.js + duplicate-comparator-modal.js délèguent à formatBytes (core/format.js).
  **Diff** : AVANT divergent 3/4 tailles (Mo/Go ≠ Mio/Gio) → APRÈS identique. (3e formateur lib-duplicates.js
  supprimé en R8-047.)
- **i18n** `c4e57c9` : clé sidebar.nav.doublons ajoutée (fr=Doublons, en=Duplicates) — sidebar-v5.js la lisait,
  t() retombait sur la clé brute.

### D1 — queue de régressions de tests réparée
- `82c9e22` : la suppression de la vue film-detail (D1, session 1) cassait 3 fichiers de tests qui la lisaient
  (FileNotFoundError). Retargetés sur le composant (test_audit_2026_05_24 + test_phase3_2_alert_labels, classes
  film-detail-alert*) ou skip-guard (test_film_detail_v5_ported, exports ES spécifiques à la vue). 0 régression.

### SIGNALÉ (rejoint le chantier données/quarantaine F1 ou sécurité torrent — NON tranché, arbitrage Thomas)
1. **R8-063 (cleanup_orphans)** : le toggle n'a AUCUNE fonction de nettoyage à câbler (write-only). Construire
   la suppression d'orphelins = feature DESTRUCTIVE neuve qui doit être gouvernée par le garde-fou quarantaine
   F1 (ne pas supprimer un orphelin non revu). **Rejoint le chantier TTL/quarantaine → SIGNALÉ** plutôt que
   bâcler une suppression de fichiers non gouvernée.
2. **R8-070 (retention_days cache)** : prune_disk_cache/prune_probe_cache existent mais ne sont JAMAIS planifiés ;
   history_retention_days pilote déjà le cron run-history. Câbler un cron de purge de cache = décision de
   cycle de vie des données (cohérence F1). **Rejoint le chantier conservation → SIGNALÉ.**
3. **R8-065-sep (séparateur dans presets)** : injecter {sep} dans les templates de presets par défaut ferait
   APPLIQUER le séparateur où il était ignoré → **MASS-RENAME potentiel (rupture de seeding torrent)** pour tout
   utilisateur ayant réglé un séparateur ≠ espace, sur surface large (naming.py L42/L127-145, settings_support
   L847/L1052). Touche l'invariant le plus protégé (nom de fichier/torrent). **SIGNALÉ** : la décision
   d'accepter le mass-rename-au-prochain-apply (prévisualisé mais réel) revient à Thomas.

### Non-régression F5-fin
- Sweeps ciblés (insights/perceptual/notify/traitement/i18n/settings/dead-code, `--ignore=tests/e2e*`) :
  **0 nouvel échec déterministe** vs baseline F3. Seuls échecs = pré-existants (test_apply_op_labels,
  4× SettingsDispatcherSections [refactor lock wrapper pré-R8], test_bulk_approve_shows_toast_5s,
  3× bibliotheque). py_compile + node --check OK partout.

---

## ═══ FILET F5 (workflow wf_b1348d50, RELIABLE=true) — 2026-06-19 ═══

Filet adversarial : 3 finders (dead-links / toggles fantômes / contrats résiduels) + panel 3 sceptiques
à asymétrie d'info + 2 leurres de calibration. **RELIABLE=true : 0/2 leurres passés** (les 2 claims faux
— qij.js encore importé, toggle theme fantôme — correctement réfutés 0/3). 6 résidus confirmés.

### Corrigés en salve (résidus triviaux + 1 bug réel de mon propre fix)
- **R8-056b (HDR, 3/3 votes)** `6843e0c` : MON fix R8-056 oubliait de remonter `hdr_analysis` (sibling de
  resolution sous video_perceptual) -> `d.hdr_analysis` undefined -> la modale affichait « sdr » FAUX pour
  TOUS les films (y compris vrais HDR10/DV/HLG), valeur fausse et non « unknown » (faux silencieux F4).
  Fix : lever hdr_analysis au top-level. Diff : HDR10 « sdr »->« hdr10 ».
- **R8-101 (windows_safe, 3/3)** `e0a71d1` : toggle fantôme — windows_safe() appliquée INCONDITIONNELLEMENT
  (aucun gate). Retiré (l'échappement Windows reste toujours actif = sécurité).
- **R8-102 (entrées de route mortes, 2/3)** `cd2587d` : new_rejects/duplicates_to_resolve dans
  _INSIGHT_ROUTE_BY_TYPE morts après le re-keying R8-049 (-> quality_reject/duplicates_probable). Retirés.

### Enregistrés (NON tranchés — câbler vs retirer = décision produit, comme R8-063)
- **cleanup_empty_folders** (3/3) : toggle « Supprimer les dossiers vides après apply » write-only (absent de
  Config/build_cfg). DISTINCT de move_empty_folders_enabled (« Déplacer », bien câblé). Câbler une SUPPRESSION
  de dossiers vides vs retirer le fantôme = décision Thomas (intention distincte du move).
- **excluded_patterns** (3/3) : champ « motifs d'exclusion » write-only — le moteur de scan ne lit JAMAIS
  excluded_patterns. AUCUN hook d'exclusion n'existe dans app/ ou domain/ : câbler = feature scan neuve.
  Câbler les exclusions de scan (vraie feature utile) vs retirer le fantôme = décision Thomas.
- **cleanup_orphans** (3/3) : re-confirme R8-063 déjà SIGNALÉ (destructif, gouvernance quarantaine F1).

### Verdict filet
RELIABLE=true (taux faux-positifs panel 0%). Décoys 0/2. 3 corrigés (HDR + 2 résidus), 3 enregistrés
(cleanup_empty_folders, excluded_patterns, cleanup_orphans) pour arbitrage — tous des phantom-features
« câbler vs retirer » alignés sur le pattern R8-063/F-PROM-02.

---

## ═══ FAMILLE F6-a — COSMÉTIQUE / a11y / i18n / HYGIÈNE TESTS — 2026-06-19 ═══

### a11y (différentiels mesurés Playwright)
- **R8-076 (contraste OMDb)** `f2ffdb9` : `.omdb-status--error` #b91c1c -> 2,79-2,91:1 sur les 5 thèmes
  (tous sombres) = sous WCAG AA 4.5:1. Fix : couleur -> #f87171 -> **6,51-6,80:1** (mesuré getComputedStyle +
  compositing alpha, fixture docs/internal/r8/fixtures/omdb_contrast.html). Fond/bordure inchangés, aucun
  thème conforme cassé. SIGNALÉ (siblings hors périmètre) : --warning (3,94) et --info (3,83) aussi sous AA.
- **R8-078 (focus-trap modale reset)** `a8437bf` : `_openResetModal` (overlay custom) sans trapFocus -> le
  focus s'échappait. Fix : import + `trapFocus(overlay)` (MÊME helper modal.js, pas une variante) + focus
  initial sur l'input. Diff (fixture focus_trap.html, Tab/Shift+Tab réels) : AVANT Tab depuis le dernier ->
  focus="" (échappe) ; APRÈS Tab dernier->premier + Shift+Tab premier->dernier (piégé).

### i18n
- **Résiduelle : CLEAN.** Scan exhaustif des 147 clés t() littérales du frontend vs fr.json+en.json :
  0 clé manquante réelle (les 2 « manquantes » détectées — `...` et `missing.key` — sont des EXEMPLES dans
  la docstring de core/i18n.js, pas des appels). La seule vraie clé absente (sidebar.nav.doublons) a été
  ajoutée en F5. Rien à corriger.

### Observabilité quarantaine (F2-d) — VÉRIFIÉ NON-ISSUE
- Tracé exhaustivement : `conflicts_quarantined_count` est PER-APPLY-RESULT (éphémère), l'undo ne le révise
  pas (correct : le résumé d'apply est un instantané historique de CET apply), il N'EST PAS persisté dans
  l'historique (history_support ne l'affiche pas), et le résumé liste chaque compteur indépendamment (pas de
  total sommé qui double-compterait — les compteurs sont par-OPÉRATION, pas par-row). La réfutation F2-d
  tient : **aucune incohérence d'affichage concrète**. Honnêteté > faux vert -> pas de fix fabriqué.

### Hygiène de la suite de tests
- **R8-086 (flaky)** `3a5f449` : test_perceptual_parallel prouvait le parallélisme par timing (time.sleep +
  elapsed<0.35s, ~3/9 PASS). Fix : threading.Barrier(2) -> déterministe (libérée QUE si video+audio
  atteignent .wait() simultanément ; serial -> timeout -> échec franc). **10/10 PASS consécutifs.**
- **R8-087/hygiène (test no-op)** `9f73eab` : test_cors_configurable_explicit_still_emitted = assertTrue(True),
  0 assertion (ne peut échouer). Son intention est DÉJÀ couverte par test_cors_can_be_restricted_explicitly
  (OPTIONS sans Origin -> asserte la valeur CORS configurée). Retiré comme redondant. NB ID : dans le registre,
  R8-087 = F-MARKED-RECOV-SILENT (déjà corrigé F2-b) ; ce no-op était un item d'hygiène distinct non numéroté.
- **Balayage final** : `assertTrue(True)`/`or True`/`and False` = 0 occurrence réelle restante (seul match = un
  commentaire). Scan AST des méthodes test_* sans assertion : 146 brut -> 34 hors e2e/visual -> TOUTES
  légitimes (smoke/no-raise type `_assert_https`, délégué `_node_check`/`_assert_loaded_after_await`, mock,
  import-smoke, skip). **0 nouveau test menteur** apparu depuis l'Étape 0 (les 2 d'origine traités).

### Filet F6-a (workflow wf_3e044bd9, RELIABLE=true)
3 finders (a11y-contraste / focus-trap / tests-menteurs) + panel 3 sceptiques asymétriques + 2 leurres.
**RELIABLE=true : 0/2 leurres passés** (« reset modal n'a toujours pas trapFocus » et « omdb-error encore
#b91c1c 2,9:1 » correctement réfutés 0/3 — les fixes R8-076/078 tiennent). **7 résidus confirmés (3/3)** :
TOUS des overlays custom aria-modal sans focus-trap (même famille que R8-078) -> **corrigés en salve**
(R8-078b `901c06c`) : command-palette, demo-wizard, processing (drawer inspecteur), aide (drawer doc),
library-advanced-drawer, qualite-filters-drawer, film-detail (recherche TMDb manuelle). Le candidat
a11y-contraste (.parametres-tier-badge--bronze) a été **RÉFUTÉ** (0/3) -> pas de fix.
Verdict : RELIABLE=true (faux-positifs panel 0%), 7 corrigés (focus-trap), 0 enregistré.

---

## ═══ F6-b PHASE 2 — option (a) + vérif sécurité + PUSH PUBLIC — 2026-06-19 ═══

### Étape 1 — option (a) : untrack + gitignore (réversible, disque intact) — `f8cf3dd`
`git rm -r --cached` de **1913 artefacts régénérables** (sans suppression disque) + ajout au .gitignore :
docs/internal/observe (1608), dist_backup_AVANT_REBUILD (252), test_library (27), FAIL_*.png (26).
Disque INTACT (vérifié). Historique passé inchangé (les blobs y restent — purge = chantier b séparé).
Artefacts de RÉFÉRENCE R8 (baseline_r8/ 29, docs/internal/r8/ 74) **gardés suivis**. check-ignore confirme
observe/test_library/dist_backup ignorés ; FAIL_*.png plus suivis.

### Étape 2 — vérif sécurité finale (gate avant push) : VERT, 0 secret réel
Re-scan sur l'EXACT origin/main..HEAD (426 commits) : **settings.json réel = 0** (jamais tracké), token réel
= 0, PEM = 0, network.json avec token = 0 (capturent {url,status,method,resource_type} seulement). Seuls
« tokens » littéraux = **fixture de test** `good-token-test-…` (auto-définie+auto-utilisée dans
scripts/_check_iter14_rate_limit_429.py pour tester le rate-limiter) + faux positifs (identifiants longs,
messages d'erreur). settings.json.example = placeholder (`^[A-Z_]+$`). 19 .err trackés = bruit dev sans secret.
Plus gros blobs du push = bloat historique CONNU (dist_backup 53,7 Mo + test_library), pas de nouveau gros blob.
**Verdict : push sûr côté secrets.**

### Étape 3 — PUSH PUBLIC (push normal, PAS de --force) : RÉUSSI
`git push origin loop/correction-2026-06` -> **`* [new branch]`** créée sur github.com/Thomas05000005/CineSort
au hash **f8cf3dd**, EXIT=0. Warning GitHub informatif (CineSort.exe 53,75 Mo > 50 Mo recommandé, non bloquant).
**main du distant NON touchée** (toujours sur son tip), **f493abdc INTACT**, aucun SHA réécrit. 426 commits
(audit + R6/R7 + R8 F2→F6) publiés comme sauvegarde distante + état publié des corrections.

⚠️ Observation : le `main` distant est à `0882c5047…`, en AVANCE sur la ref locale dernier-fetch (`f502570`,
2026-05-25) — le public a avancé depuis. Le push n'y a pas touché. La réconciliation loop→main (décision
Thomas séparée) devra se faire contre le main distant ACTUEL, pas la ref périmée.

### Reste post-R8 (non fait, voulu)
- Purge historique (option b, filter-repo/force-push) pour alléger les 325 Mo = **chantier séparé**, irréversible.
- Merge loop→main / release/tag = **décision Thomas séparée** (non faite cette phase).
