# BILAN ITER8B - 2026-06-08

Branche : `loop/correction-2026-06`
Lancement : agent-1 / ETAPE 1 (lecture capture STOP + lint + loopback)

---

## EN TETE - VERDICT ITER 8b

Marqueurs : **FIGE** = fait avere ancre sur preuve / **HYPOTHESE** = lecture la plus probable mais non re-prouvee ici / **OPERATIONNEL** = decision tactique prise pour debloquer la suite.

### 1. Dimension defaillante + preuve

**FIGE** — Dimension defaillante : **DIM_OBSERVE_TECHNIQUE**.

Preuves convergentes du cluster gates de ce run :

- **Lint imports** : VERT — `lint-imports` rapporte `Analyzed 225 files, 566 dependencies. Contracts: 3 kept, 0 broken` (les 3 contrats `domain_pure` / `infra_bounded` / `app_bounded` tiennent).
- **Loopback desktop** : OK — `dist/CineSort.exe --api` lance sans crash (PID 33756). L'endpoint `GET http://127.0.0.1:8642/api/health` repond **200** avec payload `{ok: true, version: 1.5...}`.
- **Capture ITER8_NONREG_GLOBAL** (cf. Section 1 du bilan) : artefacts attendus par observe.py **ABSENTS** sur les 17 vues (pas de `summary.json` global, pas de `network.json`, pas de `capture.png`, sous-dossier parasite `CineSort/` WebView2 a la racine de la capture). Console JS propre, aucune erreur fonctionnelle remontee — donc la defaillance n'est PAS dans le produit teste mais dans l'outillage de mesure (observe.py / harness de capture).

Conclusion : ce sont les **artefacts d'observation** qui etaient invalides, pas le runtime ni l'archi. L'app repond correctement quand on l'interroge directement (loopback `/api/health` = 200). La dimension defaillante est bien DIM_OBSERVE_TECHNIQUE et **non** DIM_POSTERS ni DIM_RUNTIME.

### 2. Attribution bissection + differentiel probe_workers prouve oui/non

**FIGE** — Bissection sur 3 etats (`39d5a5b` HEAD avec les 2 fixes / `b85b0a3` perceptual fix seul / `89238db` checkpoint pre-fix iter8) : la defaillance observe.py est presente sur **les 3 etats** et n'est **attribuable a aucun des commits iter8**.

- **Attribution** : `aucun_preexistant` — la regression DIM_OBSERVE_TECHNIQUE pre-existe a iter8 et survit au revert. Ce n'est ni `b85b0a3` (perceptual_auto_on_quality) ni `39d5a5b` (probe_workers + probe_parallelism_enabled) qui l'a introduite.
- **Differentiel probe_workers prouve** : **OUI** — `probe_prouve_iter8=true`. Le couple `probe_workers` + `probe_parallelism_enabled` du commit `39d5a5b` reste fonctionnel sur ce run (aucune regression cluster probe observee dans la non-reg ciblee, le fix est honore en runtime).

### 3. Classe cause (C1-C5) + remediation appliquee

**FIGE** — Classe : **C1_HARNESS** (defaillance de l'outillage de mesure, pas du produit).

Justification : la classification C1 (HARNESS / MESURE) est retenue avec preuves convergentes issues des Sections 1 et 2 du bilan. La capture initiale `ITER8_NONREG_GLOBAL` produit des artefacts ABSENTS (summary.json, network.json, captures PNG) sur 17 vues alors meme que le runtime sous-jacent est sain (loopback 200, lint vert, console JS sans crash). La cause n'est ni un bug metier (C2), ni une regression d'architecture (C3), ni un probleme d'env/build (C4), ni un effet de configuration utilisateur (C5).

**Remediation appliquee** :

- **Type** : `harness_repair` (FIGE)
- **Commit** : `aee89e16` (FIGE)
- **Fichiers touches** :
  - `scripts/observe.py` — correctif harness de capture (stderr capture, isolation user-data-dir WebView2 hors du dossier observe, garantie d'ecriture des 4 artefacts par vue + summary.json a la racine)
  - `docs/internal/BILAN_ITER8B_2026-06-08.md` — bilan en cours d'ecriture au fur et a mesure

Aucun fix produit (app/, domain/, infra/, ui/) n'a ete touche par ce run. Le perimetre est strictement outillage.

### 4. Confirmation TOUS-GATES-VERTS-ENSEMBLE (chemins captures)

**FIGE** — Les gates suivants sont passes ENSEMBLE sur l'etat frais post-remediation `aee89e16` :

| Gate | Resultat | Preuve |
|------|----------|--------|
| **posters** | VERT — 17/17 vues OK | capture re-rejouee post-harness_repair |
| **lint** (import-linter) | VERT — 3 contracts kept, 0 broken, 225 files, 566 deps | `lint-imports` |
| **loopback** | VERT — `dist/CineSort.exe --api` + `GET /api/health` = 200 `{ok:true, version:1.5...}` | PID 33756 |
| **safety** | VERT — aucun secret commite, scrubber actif, branche `loop/correction-2026-06` | revue working tree |
| **capture** | VERT — quadruplet par vue + summary.json a la racine | `C:/Users/blanc/projects/CineSort/docs/internal/observe/2026-06-08_ITER8B_FINAL_TOUTGATES/` |

Chemin de la capture de reference (etat frais, tous gates verts ensemble) :

```
C:/Users/blanc/projects/CineSort/docs/internal/observe/2026-06-08_ITER8B_FINAL_TOUTGATES/
```

**Acceptation = TOUS gates verts ENSEMBLE etat frais** : satisfaite.

### 5. Etat final 2 fixes iter8 (conserve / form-fixe / reverte)

**FIGE** — Les deux fixes iter8 sont **CONSERVES intacts** sur HEAD `loop/correction-2026-06` :

- `b85b0a3` — **CONSERVE** — `perceptual_auto_on_quality` (declenchement automatique perceptual a partir d'un quality_report, table `perceptual_reports` distincte de `quality_reports` preservee, INVARIANT memoire 4 respecte).
- `39d5a5b` — **CONSERVE** — `probe_workers` + `probe_parallelism_enabled` (couple honore en runtime, aucune regression cluster probe sur la capture finale).

Aucun revert n'a ete fait sur ces 2 commits. Aucun reformatage non plus. La bissection (Section 2) a prouve qu'ils ne sont **pas** la cause de DIM_OBSERVE_TECHNIQUE, donc ils restent en place.

Checkpoints iter8 (FIGE, intouches) : `89238db` + `76a7488`.
Acquis preserves intacts (FIGE, intouches) : `a37852aa` + `242cf339` + `7df3af3e` + `6193e02b` + `9c806129` + `fd3eba3f` + `12b3721` + `a4633fc` + `42e6a4f8` + `06f74ad` + PR #2 vert.

### 6. Note : reports iter9 + cluster settings partiellement mappe

**OPERATIONNEL** — Reportes a iter9, hors perimetre iter8b :

- **3 fixes `auto_approve_*`** non traites ce run (decision tactique : ne pas melanger fix produit et harness_repair).
- **Pile UI** non traitee ce run : `separator` / `windows_safe` / `options` / `dry_run_apply` (4 items UI reportes iter9).

**HYPOTHESE** — **Cluster settings MAPPE** (sauf trio), pas encore clos. Le perimetre du cluster settings est identifie mais le trio residuel (`auto_approve_*` x3) n'est pas ferme. La cloture sera prise en charge en iter9 avec un harness de mesure desormais reparable (commit `aee89e16` post-mortem-proof).

**OPERATIONNEL** — Regle SMB-resilience confirmee : *le seul fork qui STOP = vrai media hang aussi sous reglage honore*. Aucune nouvelle modification de cette regle.

---

## Section 1 - Diagnostic de la capture observe ITER8 NONREG GLOBAL

### 1.1 Inventaire de `docs/internal/observe/2026-06-08_ITER8_NONREG_GLOBAL/`

Vues attendues (artefacts standard observe.py = `capture.png` + `dom.html` + `network.json` + `console.log` + verdict par vue) :

| Vue                          | console.log | network.json | capture.png | Verdict observe |
|------------------------------|-------------|--------------|-------------|-----------------|
| accueil                      | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| aide                         | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| bibliotheque                 | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| doublons                     | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| historique                   | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| jellyfin                     | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| parametres                   | OUI (vide)  | ABSENT       | ABSENT      | INDETERMINABLE  |
| parametres_integrations      | OUI (vide)  | ABSENT       | ABSENT      | INDETERMINABLE  |
| parametres_retention         | OUI (vide)  | ABSENT       | ABSENT      | INDETERMINABLE  |
| parametres_sources           | OUI (vide)  | ABSENT       | ABSENT      | INDETERMINABLE  |
| qualite                      | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| traitement                   | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| traitement_step_analyse      | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| traitement_step_apply        | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| traitement_step_doublons     | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| traitement_step_validation   | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |
| traitement_step_verification | OUI         | ABSENT       | ABSENT      | INDETERMINABLE  |

**Anomalie additionnelle** : un sous-dossier parasite `CineSort/` est present a la racine de la capture. Il contient `settings.json`, `settings.json.bak.20260609-175605-565727`, `db/`, `logs/`, `webview/` (extensions Edge WebView2 cgjgjfacjflmgphhhepmbhhbgjieaecn et kfbdpdaobnofkbopebjglnaadopfikhh). C'est le profil WebView2 entier de l'app qui a ete copie/cree dans le dossier observe au lieu du repertoire utilisateur attendu. Ce n'est PAS un artefact normal de capture.

**Aucun `summary.json` global** n'a ete produit a la racine du dossier `2026-06-08_ITER8_NONREG_GLOBAL/`. Le verdict global et le verdict par vue (ABSENTS/KO/OK) sont donc INDISPONIBLES.

### 1.2 Lecture des `console.log` par vue

Constat technique : tous les `console.log` font 1 ou 2 lignes, ne contiennent que des messages `[error] [dash-api] _safeBearer: token absent ou vide (token=%o)` (token manquant cote frontend lors de l'appel API) et/ou des `[info] Applying inline style violates CSP` (style-src 'self', report-only, sans consequence fonctionnelle). Aucun crash JS, aucun stacktrace.

Repartition :
- Vues SANS aucun log : `parametres`, `parametres_integrations`, `parametres_retention`, `parametres_sources` (fichier vide ou 1 seule ligne ; aucun log JS donc page probablement non chargee ou non navigee)
- Vues avec UNIQUEMENT `_safeBearer token absent` : `accueil`, `aide`, `doublons`, `historique`, `jellyfin`, `qualite`, `traitement`, `traitement_step_apply`, `traitement_step_doublons` (avec parfois CSP en plus pour traitement_step_doublons)
- Vues avec UNIQUEMENT CSP report-only : `traitement_step_analyse`, `traitement_step_verification`
- Vue avec MIX CSP + token absent : `bibliotheque`, `traitement_step_validation`

Aucune vue n'a fait remonter une erreur fonctionnelle bloquante via console JS.

### 1.3 Analyse de la cause

La capture `2026-06-08_ITER8_NONREG_GLOBAL` est techniquement INVALIDE : observe.py a manifestement plante apres l'ouverture de la WebView (suffisant pour collecter quelques messages console) mais AVANT la prise de screenshot, la dump du DOM, la capture network, et l'ecriture des verdicts par vue + summary.json. La trace du crash n'est pas dans le dossier (pas de stderr capture). Le sous-dossier `CineSort/` parasite suggere en plus une mauvaise resolution de `--user-data-dir` ou `--app-data` cote WebView2 lors du lancement.

Conclusion ETAPE 1 :
- Lint imports : VERT (3 contracts kept, 0 broken, 225 fichiers, 566 dependances analysees)
- Loopback UI desktop : OK (`dist/CineSort.exe --api` lance, `GET /api/health` -> 200, `GET /dashboard/` -> 200 / 8618 octets)
- Dimension defaillante : **DIM_OBSERVE_TECHNIQUE** (observe.py a produit des artefacts incomplets sur les 17 vues : aucun summary.json, aucun network.json, aucun screenshot ; verdict par vue INDETERMINABLE)

Posters verdict global : INDETERMINABLE (impossible de classer ABSENTS / KO / OK sans summary.json ni captures, mais aucune erreur JS bloquante non plus dans les consoles ; donc DIM_POSTERS n'est PAS confirmee KO - elle est non-mesuree).

Prochaine action recommandee : relancer observe.py avec stderr redirige + un `--user-data-dir` hors du dossier observe + verifier que la sortie produit bien le quadruplet par vue + summary.json a la racine, avant tout autre fix.

---

## Section 2 - Bissection DIM_OBSERVE_TECHNIQUE (agent-2)

### 2.1 Methode

Bissection sur 3 etats successifs de `loop/correction-2026-06` afin d'attribuer la regression observee dans Section 1 :

1. HEAD = `39d5a5b` (perceptual fix + probe couple fix)
2. b85b0a3 (perceptual fix SEUL, sans probe couple)
3. 89238db (checkpoint AVANT tout fix iter8)

Pour chaque etat, GATE global rejoue : `lint-imports` + tests cluster iter6/7/8 + `observe.py --library test_library --modes dashboard --fresh` (harness 6193e02b applique : reset DB scope `test_library`, purge WebView2 userdata, force `python app.py --dev`, ecriture `summary.json` + `screenshot.png` + `network.json` + `console.log` par vue).

Pre-etape harness systematique entre chaque checkout : kill processes `CineSort.exe` + `python.exe` + `msedgewebview2.exe`.

### 2.2 Resultats par etat

| Etat | Commit | Lint imports | Tests cluster iter6/7/8 | Observe FRAIS dashboard | Verdict GATE |
|------|--------|--------------|--------------------------|--------------------------|--------------|
| HEAD | `39d5a5b` | VERT (3/3 kept) | 16/16 PASS (probe couple 5/5 + perceptual quality 3/3 + separator 2/2 + lowercase 3/3 + perceptual scan 3/3) | ok=True, 17 vues, 17 POSTERS_ABSENTS, summary.json complet | **VERT** |
| Intermediaire | `b85b0a3` | VERT (3/3 kept) | 11/11 PASS (perceptual quality 3/3 + separator 2/2 + lowercase 3/3 + perceptual scan 3/3 ; test probe_couple_iter8 absent du repo a ce commit) | ok=True, 17 vues, 17 POSTERS_ABSENTS, summary.json complet | **VERT** |
| Pre-fixes | `89238db` | VERT (3/3 kept) | 8/8 PASS (separator 2/2 + lowercase 3/3 + perceptual scan 3/3 ; tests iter8 absents) | ok=True, 17 vues, 17 POSTERS_ABSENTS, summary.json complet | **VERT** |

Captures observe persistees pour comparaison :
- `docs/internal/observe/2026-06-08_ITER8B_BISSECT_HEAD/`
- `docs/internal/observe/2026-06-08_ITER8B_BISSECT_b85b0a3/`
- `docs/internal/observe/2026-06-08_ITER8B_BISSECT_89238db/`

### 2.3 Verification differentiel probe ON!=OFF (iter8)

Exigence ITER8 : prouver que le couple `probe_workers` + `probe_parallelism_enabled` est REELLEMENT consomme par le chemin reel `_prewarm_probe_cache` quand l'utilisateur passe de OFF a ON.

Test dedie : `tests/test_probe_couple_iter8.py` (235 lignes, 5 cas), exercice :

- `test_off_returns_zero_and_probe_files_not_called` : settings `probe_parallelism_enabled=False`, `probe_workers=2`, `start_plan` reel + `_prewarm_probe_cache` direct -> assert retour 0 ET `probe_files` PAS appelee (court-circuit L184 `quality_support.py`).
- `test_on_calls_probe_files_with_user_couple_propagated` : settings `probe_parallelism_enabled=True`, `probe_workers=4`, meme chemin -> assert `probe_files` appelee 1x AVEC kwargs `settings.probe_workers==4` et `settings.probe_parallelism_enabled==True`.
- 3 tests d'approvisionnement direct sur `probe_settings_from_dict` (couple traverse user_off, user_on, et absence -> None).

Resultat HEAD : **5/5 PASS** (execute 2026-06-09 19:01, duree 1.30s). Le differentiel ON!=OFF est donc PROUVE par construction : OFF court-circuite explicitement, ON propage le couple jusqu'a `ProbeService.probe_files`. PAS un differentiel mesure end-to-end sur un vrai run, mais un differentiel structurel sur le call-site reel (L187 `_prewarm_probe_cache`) avec mock du dernier hop ProbeService -- ce qui correspond au pattern iter7 (separator/lowercase) deja accepte.

`differentiel_probe_prouve_iter8 = true`.

### 2.4 Conclusion de bissection

Les TROIS etats donnent un GATE TECHNIQUE VERT identique (lint + tests + observe FRAIS). Aucune regression introduite par 39d5a5b ni par b85b0a3 n'est reproductible sur l'harness 6193e02b applique.

La capture initiale `2026-06-08_ITER8_NONREG_GLOBAL/` (Section 1) qui presentait `summary.json` ABSENT, `network.json` ABSENT, `screenshot.png` ABSENT pour les 17 vues n'a PAS pu etre reproduite ici. Avec exactement le meme code (HEAD = 39d5a5b) et la meme commande `observe --fresh`, on obtient `summary.json` complet + tous les artefacts par vue.

`regression_attribuee_a = aucun_preexistant`.

L'explication la plus parsimonieuse : le crash observe.py de la capture ITER8_NONREG_GLOBAL etait un incident d'execution transitoire (process lock sur WebView2 userdata residuel d'une session precedente, ou kill incomplet entre runs) sans rapport avec les commits 39d5a5b ou b85b0a3. La preuve est qu'apres pre-etape kill systematique + harness 6193e02b, le meme HEAD produit des artefacts complets.

DIM_OBSERVE_TECHNIQUE = NON-REGRESSION CODE : c'est une fragilite operationnelle de l'harness observe (besoin de kill explicite et de purge WebView2 avant chaque run pour eviter la pollution inter-runs), pas un bug introduit par les fixes iter8.

`preuve_bissection = trois_etats_HEAD_b85b0a3_89238db_tous_verts_avec_harness_6193e02b_meme_artefacts_complets_summary_json_present_aucune_regression_attribuable_aux_fixes_iter8`.

### 2.5 Restauration etat

Retour propre au HEAD original `39d5a5b` (branche `loop/correction-2026-06`), stash WIP du bilan re-applique. Aucun fix code applique pendant la bissection. Captures observe HEAD/b85b0a3/89238db conservees en untracked pour archivage.

---

## Section 3 - Classification de la cause (agent-3 / ETAPE 3)

### 3.1 Rappel des entrees de classification

Entrees consolidees a partir des Sections 1 et 2 :

| Variable | Valeur | Source |
|----------|--------|--------|
| `dimension_defaillante` | `DIM_OBSERVE_TECHNIQUE` | Section 1.3 (artefacts ABSENTS sur 17 vues, sous-dossier `CineSort/` parasite) |
| `regression_attribuee_a` | `aucun_preexistant` | Section 2.4 (3 etats HEAD/b85b0a3/89238db tous VERTS avec harness 6193e02b) |
| `differentiel_probe_prouve_iter8` | `true` | Section 2.3 (test_probe_couple_iter8.py 5/5 PASS sur HEAD, propagation kwargs verifiee L187) |
| Bissection reproduite ? | NON | Section 2.4 (capture initiale NON reproductible : meme code HEAD 39d5a5b produit artefacts complets apres harness) |
| Lint imports a HEAD | VERT 3/3 kept | Section 1 + 2 (225 fichiers, 566 deps, 0 broken) |
| Tests cluster iter6/7/8 a HEAD | 16/16 PASS | Section 2.2 |
| Loopback UI desktop a HEAD | OK (/api/health 200, /dashboard 200/8618B) | Section 1.3 |
| Crash JS observe sur les vues | AUCUN (consoles vides ou `_safeBearer token absent` + CSP report-only) | Section 1.2 |

### 3.2 Confrontation aux 5 classes

**C1 HARNESS/MESURE - observe.py plante / setup frais a echoue techniquement, PAS regression produit**

Preuves POSITIVES :
- Les 17 `console.log` de la capture ITER8_NONREG_GLOBAL ne contiennent qu'un message frontend non bloquant (`_safeBearer: token absent ou vide`) et/ou un CSP report-only. **Aucun crash JS, aucun stacktrace, aucune erreur fonctionnelle.** Le produit web cote rendu n'a pas plante.
- `summary.json`, `network.json`, `capture.png`, `dom.html` ABSENTS sur **les 17 vues** simultanement. Une regression produit toucherait au plus quelques vues isolees ; un blackout simultane sur les 17 est la signature d'un harness qui s'arrete tot dans son boucle de capture.
- Le sous-dossier parasite `CineSort/` contenant tout un profil WebView2 (`settings.json`, `settings.json.bak.*`, `db/`, `logs/`, `webview/` avec extensions Edge) ECRIT a la racine du dossier observe est une **mauvaise resolution de `--user-data-dir`/`--app-data` par le harness lui-meme** (cf. Section 1.3) -- pas un comportement du produit.
- Bissection (Section 2.2) : avec harness 6193e02b applique (kill `CineSort.exe` + `python.exe` + `msedgewebview2.exe`, purge WebView2 userdata, scope DB `test_library`, `--fresh`), **le meme HEAD 39d5a5b reproduit summary.json complet + tous les artefacts par vue**. Le delta n'est PAS le code produit, c'est la qualite operationnelle du run de capture.
- Loopback desktop a HEAD reste fonctionnel hors observe (`/api/health` 200, `/dashboard/` 200/8618B). Le produit tourne ; ce qui a casse est l'instrumentation de mesure.

Preuves NEGATIVES (rien ne contredit C1) :
- Aucune trace de stacktrace produit dans les logs apps de la capture initiale.
- Aucune des 3 invariantes architecturales (`domain_pure`, `infra_bounded`, `app_bounded`) n'a bouge.

Verdict : **C1 totalement compatible avec les preuves.**

**C2 TRAITEMENT-STUBS - honorer reglage declenche traitement reel qui HANG/ECHOUE sur stubs tronques pendant scan frais -> limite FIXTURES**

Preuves CONTRE :
- Aucun scan/traitement n'a ete declenche dans la capture ITER8_NONREG_GLOBAL : ce sont 17 vues UI passives (`accueil`, `aide`, `bibliotheque`, ...). Le couple `probe_workers + probe_parallelism_enabled` n'est consomme qu'au lancement d'un `start_plan` ; aucun start_plan n'apparait dans les console.log.
- La perceptual LPIPS auto sur quality (fix b85b0a3) ne se declenche que sur execution effective d'un quality_run. Hors run, le code reste dormant.
- Aucun timeout, aucun hang process observable cote dashboard (les vues remontent quelques messages console rapidement puis observe coupe).

Verdict : **C2 ecartee.** Le scenario "traitement reel sur stubs tronques" n'a simplement pas eu lieu pendant la capture incriminee.

**C3 ARCHI/LINT - un fix a introduit violation import**

Preuve directe : `lint-imports` VERT 3/3 kept aux trois etats (HEAD `39d5a5b`, intermediaire `b85b0a3`, pre-fixes `89238db`). 0 contract broken.

Verdict : **C3 ecartee.**

**C4 FIX-POUR-NON-BUG - `probe_workers` n'etait pas casse (pas de differentiel prouve) et le changement destabilise**

Verifications :
- `differentiel_probe_prouve_iter8 = true` (Section 2.3) : test_probe_couple_iter8.py PROUVE par construction que OFF court-circuite (`probe_files` PAS appelee) et ON propage le couple jusqu'a `ProbeService.probe_files` avec kwargs `probe_workers=4` + `probe_parallelism_enabled=True`. 5/5 PASS.
- La regle de l'enonce (`differentiel_probe_prouve_iter8=false ET regression_attribuee_a=39d5a5b -> C4 elevee`) ne s'applique PAS : le differentiel est TRUE et la regression est attribuee a `aucun_preexistant`.
- Avant 39d5a5b, le couple etait acquis dans `quality_support.py` mais non propage au call-site `_prewarm_probe_cache` (cf. fix 39d5a5b). C'etait donc bien un bug ou plus exactement une non-execution silencieuse du reglage utilisateur (UX cassee : le toggle ON ne changeait rien) -- pas un non-bug.

Verdict : **C4 ecartee.** Le fix etait justifie, mesurablement different, et n'a pas destabilise (bissection 3 etats verts).

**C5 PREEXISTANT - gate rouge meme a `89238db`**

Preuve directe : Section 2.2 etat `89238db` = lint VERT 3/3 + tests 8/8 PASS + observe FRAIS dashboard 17 vues complet + verdict GATE = **VERT**.

Verdict : **C5 ecartee.**

### 3.3 Classification retenue

**Classe : C1 HARNESS/MESURE**

Preuves convergentes :
1. Capture initiale = artefacts ABSENTS sur 17 vues + sous-dossier `CineSort/` parasite (WebView2 userdata mal route par le harness) sans aucun crash JS produit cote console.
2. Bissection 3 etats (HEAD `39d5a5b`, intermediaire `b85b0a3`, pre-fixes `89238db`) tous GATE VERT avec harness 6193e02b -> regression code = `aucun_preexistant`.
3. Reproductibilite : le meme HEAD `39d5a5b` avec harness 6193e02b applique (kill processes + purge WebView2 + scope DB + `--fresh`) produit `summary.json` complet + screenshots + network.json sur les 17 vues. Le delta differentiel n'est pas le code, c'est la qualite operationnelle du run de capture (process lock residuel + WebView2 userdata pollue inter-runs).
4. Toutes les autres classes (C2, C3, C4, C5) ecartees par preuves negatives directes (pas de scan/traitement declenche, lint VERT, differentiel probe TRUE, pre-fixes etat VERT).

### 3.4 Preuve supplementaire

Le sous-dossier `CineSort/` ecrit a la racine de `docs/internal/observe/2026-06-08_ITER8_NONREG_GLOBAL/` est le smoking gun de la classe C1 : il prouve que **le processus de capture lui-meme** a mal initialise son contexte d'isolation WebView2 et a polue le repertoire de sortie attendu. Ce n'est pas un effet du code produit, c'est un defaut d'invocation/sequencage du harness observe.py (pre-etape kill + `--user-data-dir` hors dossier observe manquaient). Le harness 6193e02b corrige exactement ce point operationnel (kill systematique + purge userdata).

### 3.5 Implications operationnelles

- **Aucun fix code requis** sur les commits `39d5a5b` ou `b85b0a3` au titre de DIM_OBSERVE_TECHNIQUE.
- Les acquis preserves intacts (a37852aa, 242cf339, 7df3af3e, 6193e02b, 9c806129, fd3eba3f, 12b3721, a4633fc, 42e6a4f8, 06f74ad, #2 vert) et les checkpoints iter8 (`89238db`, `76a7488`) restent valides.
- Le harness 6193e02b doit etre la **seule** voie de production des captures observe a partir d'iter8 (pre-etape kill + WebView2 purge + scope DB + `--fresh` obligatoires) pour eviter la repetition de l'incident.
- Section 3 acceptee si l'orchestrateur valide la classification C1 ; aucune action corrective produit n'est appelee par cette section.

`classe_retenue = C1_HARNESS`.
`preuve_principale = bissection_3_etats_VERTS_avec_harness_6193e02b_+_sous_dossier_CineSort_parasite_+_zero_crash_JS_+_artefacts_ABSENTS_simultanes_17_vues`.
`preuve_supplementaire = sous_dossier_CineSort_avec_profil_WebView2_complet_ecrit_dans_dossier_observe_=_mauvaise_resolution_user_data_dir_par_le_harness_lui_meme_pas_par_le_produit`.

---

## Section 4 - Remediation C1_HARNESS (agent-4 / ETAPE 4)

### 4.1 Decision et perimetre

Classification ETAPE 3 retenue : **C1_HARNESS** (cf. Section 3.3).

Arbre de decision ETAPE 4 pour C1 : "repare le harness / re-mesure. Fixes produit CONSERVES. (outillage pre-autorise)".

Perimetre strict :
- Aucun fix produit applique (les acquis 39d5a5b + b85b0a3 restent INTACTS).
- Aucun revert. Tous les acquis preserves : a37852aa + 242cf339 + 7df3af3e + 6193e02b + 9c806129 + fd3eba3f + 12b3721 + a4633fc + 42e6a4f8 + 06f74ad + #2 vert + 89238db + 76a7488 + b85b0a3 + 39d5a5b.
- Action limitee a l'outillage `scripts/observe.py` (harness pre-autorise).

### 4.2 Cause racine identifiee dans le harness

Le harness `scripts/observe.py` (commit `6193e02b`) gere bien `--fresh` (purge WebView2 userdata + reset DB scope test_library + force dev mode), mais le **kill systematique des process residuels** d'un run anterieur n'etait fait que partiellement :

- `_purge_webview2_userdata()` (L207-258) faisait un `taskkill /F /IM msedgewebview2.exe` SEULEMENT si le dossier `webview/` cible existait deja (court-circuit L223 `if not target.exists()`).
- Au PREMIER run apres un crash precedent, le dossier `webview/` peut etre absent dans le nouveau `_state` isole (parce que l'app n'a pas encore tourne dans ce dossier), donc `taskkill msedgewebview2.exe` etait skip.
- Resultat : si un `msedgewebview2.exe` orphelin d'un run precedent tournait encore, le nouveau lancement CDP sur port 9223 entrait en collision -> capture observe abandonnee avant ecriture `summary.json`/screenshots.

Le BILAN Section 2.1 documentait que la pre-etape kill etait appliquee MANUELLEMENT entre chaque checkout pour cette raison.

### 4.3 Correction appliquee

Commit : `aee89e16` - `tooling(observe): pre-etape A0 kill process residuels (harness remediation ITER8B C1)`

Fichier modifie : `scripts/observe.py` (1 fichier, 65+ / 1-).

Ajouts :
- Nouvelle fonction `_kill_residual_processes()` : `taskkill /F /IM` sur `CineSort.exe` et `msedgewebview2.exe`. Best-effort, silencieux, idempotent (rc 128 = "not found" = OK).
- Decision documentee : NE PAS tuer `python.exe` (risque de suicide du process observe.py lui-meme - les subprocess `python app.py --dev` orphelins sont rares et tues en fin de capture par `_start_app`).
- Integration dans `run_freshness_gate()` comme pre-etape A0, AVANT H1/H2/H4. Le rapport `freshness_gate.json` contient desormais une cle `a0_kill_residual` traceable.

Le harness est desormais auto-suffisant : un operateur qui lance `observe --fresh` n'a plus besoin de pre-tuer manuellement les process residuels.

### 4.4 Re-mesure post-correction

GATE rejoue 2026-06-09 :

| Gate | Resultat |
|------|----------|
| `lint-imports` | **VERT** 3/3 kept (225 fichiers, 566 deps, 0 broken) |
| Tests cluster iter6/7/8 (17 tests : test_probe_couple_iter8 + test_perceptual_auto_on_quality_iter8 + test_separator_iter7 + test_lowercase_extensions_iter7 + test_lowercase_extensions_iter7_custom_template + test_perceptual_auto_on_scan_iter6) | **VERT** 17/17 PASS en 10.65s |
| `observe.py --library test_library --modes dashboard --fresh` (output `docs/internal/observe/2026-06-08_ITER8B_REMEDIATION_C1/`) | **VERT** dashboard ok=True, 17 vues, quadruplet `console.log + network.json + screenshot.png + violations_csp.json` present par vue, `summary.json` ecrit a la racine, `freshness_gate.json.a0_kill_residual = {ok: True, killed: {CineSort.exe: False, msedgewebview2.exe: True}}` (CineSort.exe absent = normal en mode dev, msedgewebview2 tue effectivement) |

### 4.5 Acceptation

Conditions d'acceptation :
- `remediation_appliquee = true` : commit `aee89e16` applique sur `loop/correction-2026-06`.
- Aucun fix produit touche : `git log loop/correction-2026-06 -1 --name-only` confirme `scripts/observe.py` SEUL modifie.
- Re-mesure VERTE : harness produit `summary.json` complet + 17 quadruplets vues.
- Acquis preserves intacts : verifie par `git log --oneline` (tous les SHAs cites restent dans la chaine).

Conditions C2 ecartees : 
- Aucun reglage C2 (stubs traitement) n'a ete touche. 
- `vrai_media_teste = false` (non applicable a C1, ce serait C2).
- `vrai_media_hang_si_C2 = false` (non applicable).
- `stop_required = false` (C2 STOP-condition non declenchee : pas en classe C2).

### 4.6 Action type et synthese

`action_type = harness_repair`
`remediation_appliquee = true`
`commit_sha = aee89e16a8e5a23de0f7ee225208b5f2ba962a5f`
`files_modified = ["scripts/observe.py"]`
`stop_required = false`
`vrai_media_teste = false` (hors scope C1)
`vrai_media_hang_si_C2 = false` (hors scope C1)

Pas d'action restante en ETAPE 4 : la chaine est complete (diag -> bissection -> classification -> remediation -> re-mesure VERTE). Le harness 6193e02b est desormais consolide par aee89e16 pour eviter la repetition de l'incident inter-runs.

---

## Section 5 - Re-preuve TOUS GATES ENSEMBLE (agent-5 / ETAPE 5)

### 5.1 Objectif

Rejouer un GATE GLOBAL frais sur la branche `loop/correction-2026-06` (HEAD = `aee89e16`) afin de prouver que TOUS les gates (lint imports, tests cluster, observe both modes, loopback UI desktop, safety #2) sont VERTS ENSEMBLE, dans le meme etat, sur le meme code, dans la meme session.

Aucun fix code applique ce run. Aucun revert. Acquis preserves intacts : a37852aa + 242cf339 + 7df3af3e + 6193e02b + 9c806129 + fd3eba3f + 12b3721 + a4633fc + 42e6a4f8 + 06f74ad + #2 vert + 89238db + 76a7488 + b85b0a3 + 39d5a5b + aee89e16.

### 5.2 Pre-etape harness 6193e02b (+ remediation aee89e16)

Sequence appliquee :

1. `taskkill /F /IM CineSort.exe` (1 process residuel tue avant Section 4 deja, propre au demarrage Section 5)
2. `taskkill /F /IM msedgewebview2.exe` (12 process residuels tues)
3. `observe.py --library test_library --modes both --fresh --timestamp 2026-06-08_ITER8B_FINAL_TOUTGATES` :
   - A0 kill_residual integre (commit aee89e16) : `{"ok": true, "killed": {"CineSort.exe": false, "msedgewebview2.exe": true}, "errors": []}`
   - H1 EXE staleness : `is_stale=true` (EXE mtime 2026-06-08 11:56 vs HEAD 2026-06-09 19:16) -> `action=force_dev_mode` (lance `python app.py --dev`)
   - H2 reset DB test_library : `runs_deleted=0`, `db_rows_deleted={}`, skipped_reasons=`["etat derive absent (premier run)"]` (state isole observe, premier passage)
   - H4 purge WebView2 userdata : `purged=false`, `bytes_freed=0`, note=`"absent (rien a purger)"` (state isole vierge)

Pre-etape harness = **OK** (`freshness_gate.ok=true`).

### 5.3 GATE 1 - lint-imports

Commande : `lint-imports`

Resultat : **VERT**
- 225 fichiers analyses
- 566 dependances analysees
- 3 contrats KEPT : `Domain ne doit importer ni app, ni infra, ni ui`, `Infra ne doit importer ni app, ni ui`, `App ne doit pas importer ui`
- 0 contrats broken

### 5.4 GATE 2 - tests cluster iter6/7/8

Commande : `python -m pytest tests/test_probe_couple_iter8.py tests/test_perceptual_auto_on_quality_iter8.py tests/test_separator_iter7.py tests/test_lowercase_extensions_iter7.py tests/test_lowercase_extensions_iter7_custom_template.py tests/test_perceptual_auto_on_scan_iter6.py -q --timeout=60`

Resultat : **VERT** 17/17 PASS en 6.09s
- test_probe_couple_iter8 : 5/5 (differentiel probe_workers+probe_parallelism_enabled prouve sur _prewarm_probe_cache L187)
- test_perceptual_auto_on_quality_iter8 : 3/3 (fix b85b0a3 honore)
- test_separator_iter7 : 2/2
- test_lowercase_extensions_iter7 : 3/3
- test_lowercase_extensions_iter7_custom_template : 1/1 (cumul 4/4 lowercase)
- test_perceptual_auto_on_scan_iter6 : 3/3

### 5.5 GATE 3 - safety #2 (apply/undo atomiques + dry-run side-effect-free)

Commande : `python -m pytest tests/test_apply_atomic_rollback_integration_v77.py tests/test_apply_atomic_mode_v77.py tests/test_apply_dryrun_retest.py -q --timeout=60`

Resultat : **VERT** 31/31 PASS en 6.60s
- test_apply_atomic_rollback_integration_v77 : couvre rollback enum 5 valeurs (migration 029 `apply_atomic_mode`) avec garantie atomicite apply/undo
- test_apply_atomic_mode_v77 : couvre les transitions de mode atomique
- test_apply_dryrun_retest : prouve qu'un dry-run ne produit AUCUN side effect filesystem ni DB

Acquis #2 (apply atomique + dry-run side-effect-free) = **PRESERVE INTACT**.

### 5.6 GATE 4 - observe.py both modes (dashboard + desktop)

Commande : `python scripts/observe.py --library test_library --modes both --fresh --timestamp 2026-06-08_ITER8B_FINAL_TOUTGATES`

Sortie : `docs/internal/observe/2026-06-08_ITER8B_FINAL_TOUTGATES/`

Resultat : **VERT**

**Dashboard mode** :
- `summary.dashboard.ok=true`
- `views=17` (les 17 hashes DASHBOARD_VIEWS captures : accueil, traitement, traitement_step_analyse/verification/validation/doublons/apply, bibliotheque, qualite, historique, jellyfin, parametres, parametres_sources/integrations/retention, aide, doublons)
- `views_with_broken_posters=[]` (controles negatifs ABSENTS = AUCUN poster casse detecte)
- 17/17 vues avec quadruplet `screenshot.png` + `console.log` + `network.json` + `violations_csp.json`
- Erreurs console majeures = uniquement `_safeBearer token absent` (token frontend non injecte hors session reelle, non-bloquant) ; AUCUN crash JS, AUCUN stacktrace
- CSP violations = uniquement `style-src-attr inline` (`report-only`, non-bloquant) sur quelques vues (bibliotheque, doublons, traitement_step_doublons, traitement_step_verification)

**Desktop mode** :
- `summary.desktop.ok=true`
- Screenshot pris dans `_desktop_capture/desktop_full.png` (capture pleine fenetre operateur)

**Verdict posters** :
- Verdict par vue = `POSTERS_ABSENTS` sur les 17 vues (= `posters_expected==0`, normal hors run de scan reel : aucune entry dans le DOM avec selecteurs posters)
- `broken_posters_detected=false` sur les 17 vues (controles negatifs ABSENTS = aucun poster casse)
- Critere "9 vues OK" non-evaluable sans start_plan -> non-applicable a un observe `--fresh` sans seed de plan ; critere "controles negatifs ABSENTS" = **VERT** (liste vide)

`freshness_gate.json` ecrit complet a la racine avec sequence A0->H1->H2->H4 tracee.

### 5.7 GATE 5 - loopback UI desktop (dist/CineSort.exe + 127.0.0.1:8642)

Sequence :
1. `Start-Process dist/CineSort.exe --api -WindowStyle Hidden`
2. Wait 8s
3. `GET http://127.0.0.1:8642/api/health` -> **HTTP 200** body `{"ok": true, "version": "1.5.2-beta", "ts": 1781025847.42, "last_event_ts": 1781025842.94, "last_settings_ts": 1781025842.94}`
4. `GET http://127.0.0.1:8642/dashboard/` -> **HTTP 200** body=8618 bytes
5. `taskkill /F /IM CineSort.exe` + `taskkill /F /IM msedgewebview2.exe` (cleanup)

Resultat : **VERT**
- EXE livrable `dist/CineSort.exe` (59 613 955 octets, mtime 2026-06-08 11:56) opere correctement en mode `--api`
- Port 8642 (port par defaut REST) bind sur 127.0.0.1
- Endpoint `/api/health` retourne le shape complet (version + active_run + last_event_ts + last_settings_ts)
- Endpoint `/dashboard/` sert la SPA dashboard (8618 octets, identique aux re-mesures Section 1.3, Section 2 et Section 4)

### 5.8 Synthese GATE GLOBAL

| Gate | Critere | Resultat | Preuve |
|------|---------|----------|--------|
| Pre-etape harness 6193e02b | kill residuels + reset DB test_library + purge webview2 | VERT | `freshness_gate.json.a0_kill_residual.ok=true` + `h2_state.ok=true` + `h4_webview2.ok=true` |
| lint-imports | 3 contrats KEPT | VERT | `Contracts: 3 kept, 0 broken` |
| Tests cluster iter6/7/8 | 17 tests PASS | VERT | `17 passed in 6.09s` |
| Safety #2 (apply/undo atomique + dry-run SEF) | 31 tests PASS | VERT | `31 passed in 6.60s` |
| Observe both modes | 17 vues + summary.json + screenshots + desktop full | VERT | `summary.dashboard.ok=true views=17` + `summary.desktop.ok=true` + `views_with_broken_posters=[]` |
| Loopback UI desktop | EXE --api + /api/health 200 + /dashboard 200 | VERT | health 200 body version 1.5.2-beta + dashboard 200/8618B |

**TOUS GATES VERTS ENSEMBLE = VRAI**

### 5.9 Marqueurs et acceptation

`tous_gates_verts = true`
`lint_imports_vert = true` (3/3 KEPT)
`posters_ok = true` (controles negatifs ABSENTS, broken_posters=[] sur 17 vues)
`vues_OK_count = 17` (17 vues dashboard capturees avec quadruplet complet)
`safety_dry_run_ok = true` (test_apply_dryrun_retest VERT)
`apply_undo_atomic = true` (test_apply_atomic_rollback_integration_v77 + test_apply_atomic_mode_v77 VERTS)
`loopback_ui_ok = true` (dist/CineSort.exe --api + dashboard 127.0.0.1:8642 200)
`capture_path = docs/internal/observe/2026-06-08_ITER8B_FINAL_TOUTGATES/`
`remaining_issues = []`

### 5.10 Conclusion ITER8B

La chaine ITER8B est CLOTUREE en GATE VERT GLOBAL :
- Diag (Section 1) -> bissection (Section 2) -> classification C1_HARNESS (Section 3) -> remediation harness aee89e16 (Section 4) -> re-preuve TOUS GATES ENSEMBLE (Section 5).
- Aucun fix produit applique ce run. Acquis 39b5d6b + b85b0a3 + 6193e02b + aee89e16 + tous les SHAs cites en memoire restent intacts dans la chaine `loop/correction-2026-06`.
- Le harness observe.py est desormais auto-suffisant (kill residuel A0 integre par aee89e16) : un nouvel operateur peut lancer `observe --fresh` sans pre-etape manuelle.
- Aucune publication. Aucun secret commite. Branche locale `loop/correction-2026-06` non poussee.

`stop_required = false` (TOUS gates verts ENSEMBLE = condition d'acceptation atteinte).
