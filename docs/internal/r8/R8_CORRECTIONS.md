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
