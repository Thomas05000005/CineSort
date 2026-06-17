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
