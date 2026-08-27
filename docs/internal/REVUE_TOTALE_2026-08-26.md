# Revue totale du 2026-08-26 — état, blocages et file de travail

> **Méthode.** 145 agents, 11 domaines balayés en parallèle, chaque constat remis à un
> **réfutateur indépendant** chargé de le détruire (refus par défaut en cas de doute), puis une
> synthèse et un **critique de complétude** payé pour attaquer la synthèse elle-même.
>
> **132 constats examinés → 63 confirmés, 69 réfutés (52 %).** Le taux de réfutation est le
> chiffre à retenir : sans réfutateur, cette revue aurait livré 69 faux constats, dont plusieurs
> avec des remèdes visant le mauvais mécanisme.
>
> Périmètre : **lecture seule**. Ni l'application ni la suite complète n'ont été exécutées
> (le cron de purge TTL agit sur la bibliothèque RÉELLE de l'utilisateur). Aucun correctif n'a
> été appliqué : **les remèdes ci-dessous sont raisonnés, pas éprouvés.**

État au moment de la revue : `main` @ `2b07c04e`, v1.5.2-beta, 22 PR ouvertes, 16 issues ouvertes.

---

## LOT 0 — Sécurité, avant tout le reste

L'ordre compte : **révoquer d'abord**. Réécrire l'historique ne dé-publie pas ce qui est déjà
public (le dépôt a un fork, et les caches GitHub existent).

- [ ] **T-SEC-1 · Régénérer le jeton REST.** Le jeton Bearer **actif** est en clair dans
  `docs/internal/BILAN_ITER4_2026-06-08.md:272` et `BILAN_ITER13_2026-06-08.md:1174`, suivis à
  HEAD d'un dépôt **PUBLIC**, depuis le commit `650d1620` (2026-06-20, 67 jours). Également
  présent dans `e05ed6f4` et `9d8b8e95`. Vérifié identique au jeton en service par déchiffrement
  DPAPI de `rest_api_token_secret`.
- [ ] **T-SEC-2 · Écraser les deux lignes** (écraser, **jamais supprimer** — `gitleaks` scanne une
  plage de commits, message de commit inclus). Décider ensuite si l'historique est réécrit.
- [ ] **T-SEC-3 · Purger les 24 fichiers locaux** porteurs de la valeur, sur 129 889 balayés sous
  `%LOCALAPPDATA%/CineSort` : 6 `settings.json.bak*`, 13 `db/cinesort.sqlite.bak_ITER*`,
  `logs/cinesort.log`, et **4 artefacts WebView2** (`History`, `Top Sites`, `Favicons`,
  `Local Storage/leveldb`) — le jeton voyage en query string, le navigateur embarqué l'archive.
- [ ] **T-SEC-4 · Boucher le scrubber.** `infra/log_scrubber.py:41` ne rédige pas `ntoken=` : son
  `\b` amont a été ajouté pour éviter `mytoken=`, et le boot desktop passe le jeton sous ce nom
  exact (`app.py:846`), journalisé brut par `rest_server.py:543`. Couvrir `ntoken=` et tout
  `*token=` en query string, avec un test **vu rouge**.
- [ ] **T-SEC-5 · Cesser de faire transiter le jeton dans l'URL.** C'est la cause amont de T-SEC-3
  et T-SEC-4. `app.py:854` tronque déjà volontairement le jeton pour son propre log : le serveur,
  lui, journalise la ligne de requête entière.
- [ ] **T-SEC-6 · Réparer la rotation des sauvegardes.** `SETTINGS_BACKUP_PREFIX` vaut `.bak.` donc
  le glob est `settings.json.bak.*` : trois sauvegardes nommées `.bak_ITER7_pre`,
  `.bak_iter13_s2`, `.bak_ITER13_S5_*` sont hors champ de `_rotate_settings_backups` depuis juin
  et n'en sortiront jamais.
- [ ] **T-SEC-7 · Retirer les `|| true` des trois checks REQUIS** — ou les sortir de la liste des
  requis. `bandit.yml:89`, `mypy.yml:92`, `pip-audit.yml:87` (`continue-on-error`). La protection
  de `main` en annonce sept ; **quatre mordent**.
- [ ] **T-SEC-8 · Ajouter une règle gitleaks qui mord sur un secret nu entre backticks en prose.**
  Le secret n'était **pas** dans `.gitleaksignore` : ce n'était pas une exemption assumée, c'était
  une non-détection. Corriger aussi `CLAUDE.md:658` et l'en-tête de `gitleaks.yml`, qui affirment
  « 56 détections, ZÉRO secret réel ».
- [ ] **T-SEC-9 · `GET /api/poster` n'est pas authentifiée** (`rest_server.py:1183-1191`) et sa
  justification écrite est morte : elle invoque un « bypass loopback de `_check_auth` » supprimé.

---

## LOT 1 — Débloquer la file (12 PR sur 22 sont infusionnables)

- [ ] **T-CI-1 · Éprouver le remède sur UNE seule PR.** Sept PR (#1125 #1128 #1130 #1133 #1134
  #1137 #1148) portent **0 des 7 checks requis** : leurs 10 à 44 runs sont parqués en
  `conclusion=action_required`. Discriminant mesuré : le **`triggering_actor` du push** —
  `claude[bot]` passe, `github-actions[bot]` est parqué.
  **La cause racine n'est PAS mesurée** (l'API GitHub n'expose pas le réglage d'approbation) et le
  remède n'a jamais été testé. Approuver les runs de **#1133** et observer.
  ⚠️ **Ne PAS fermer/rouvrir, ne PAS squasher** : une première lecture accusait le *nombre de
  commits*, réfutée par 7 contre-exemples (#1099, #1104…). Ces remèdes visent le mauvais mécanisme
  — et le finding `a3610492` de PR #1148 les recommande **à tort, avec une confiance de 0,95**.
- [ ] **T-CI-2 · Poser le label `blocked` sur les 7 PR gelées.** `stale.yml` porte
  `delete-branch: true` (30 j → stale, +7 j → close). Cinq de ces PR sont des rapports d'audit qui
  n'existent **QUE** sur leur branche — motif exact de #1089. `exempt-pr-labels` contient déjà
  `blocked`. **Échéance : fin septembre.**
- [ ] **T-CI-3 · #1133 en priorité dans le lot** : elle rétablit le « 0 = désactivé » d'un cron
  **destructif** (cf. T-PROD-2).
- [ ] **T-CI-4 · Fusionner #1145 et #1142 ensemble.** Dependabot a coupé une modification
  indivisible en deux PR : `codeql-action/init` d'un côté, `analyze` de l'autre, vers le même SHA.
  Chacune seule rend rouges les deux checks requis CodeQL. Erreurs symétriques :
  `Loaded a configuration file for version '4.37.6', but running version '4.37.8'` et l'inverse.
- [ ] **T-CI-5 · Ajouter un bloc `groups:` à l'écosystème `github-actions`** de
  `.github/dependabot.yml` (seul `pip` en a un) : sans lui, les sous-chemins d'une même action
  montent en PR séparées et se cassent mutuellement. Deux des cinq créneaux dependabot sont gelés
  à vie par ce couple.
- [ ] **T-CI-6 · #1141 (ruff 0.16.3 → 0.16.4)** : ne monte que 2 des 5 ancrages
  (`pyproject.toml`, `requirements-dev.txt`). Restent `.pre-commit-config.yaml:18`, `uv.lock`,
  et `CLAUDE.md:49-50,102`. Le garde `test_ruff_version_is_identical_everywhere` a **tiré, comme
  conçu**. Compléter la PR avec le reformatage dans le même commit, ou la fermer.
- [ ] **T-CI-7 · #1124** : le diff retire `ApplyOperationError` de `ApplyResponse` — sa seule
  lecture — en le disant « ré-exporté ». `schemas/__init__.py` ne l'importe pas et la PR ne le
  touche pas. Supprimer le symbole ou le câbler.
- [ ] **T-CI-8 · #1136 passe par une AUTRE voie** : ses 7 checks requis sont **verts**.
  `required_conversation_resolution: true` + 2 fils de revue non résolus. Même cause partielle sur
  #1125 (1 fil), #1133 (1), #1137 (1) : **approuver leurs runs ne suffira pas.**
- [ ] **T-CI-9 · Corriger #1123 AVANT de la fusionner** (cf. T-PROD-5).
- [ ] **T-CI-10 · #1146 et #1147 sont fusionnables** : correctifs justes, minimaux, portant un test
  qui aurait été rouge. Vérifiés sur le code réel, pas sur la description.
- [ ] **T-CI-11 · #1140 #1143 #1144 sont des VERTS QUI NE PROUVENT RIEN** : ce sont les trois bumps
  **majeurs** (labeler 6→7, stale 10→11, download-artifact 5→8) et aucun des workflows modifiés ne
  s'exécute sur une `pull_request`. Le vert n'a rien testé.

---

## LOT 2 — Défauts de production (ils touchent la donnée)

- [ ] **T-PROD-1 · `apply_rollback.py:106, :139-150, :460, :477` — un rollback qui ne restaure rien
  et se déclare réussi.** Un partage réseau momentanément injoignable (winerror 53 → `ENOENT`,
  winerror 21 lecteur non prêt) fait rendre `False` à `Path.exists()` ; l'op passe
  `SKIPPED/dst_missing`, l'`undo_status` est persisté, la reprise au boot ressort immédiatement, et
  comme `failed == 0` le statut final est `ROLLBACK_DONE` / `ok=True` / `done=0`. **Chaîne
  reproduite en 2 passes.** Le module se contredit lui-même : `:24-26` annonce un
  `ROLLBACK_PARTIAL` qui n'arrive jamais.
  → **C'est aussi le module au plancher de couverture le plus BAS du cliquet (61 %,** contre 97 %
  pour `move_journal`). Personne n'avait relié le pire défaut au module le moins couvert.
- [ ] **T-PROD-2 · `app.py:512` et `:526` — le « 0 = désactivé » d'un cron destructif est avalé.**
  `int(settings.get("quarantaine_ttl_days") or _Q_DEFAULT_TTL)` : le `or` remplace le 0 de
  l'utilisateur avant que la garde `if days <= 0` puisse le voir. Elle est **inatteignable**, et
  `_review/` se purge à 30 jours malgré le réglage. Correctif = PR #1133, gelée.
- [ ] **T-PROD-3 · `web/dashboard/views/historique.js:1648` — supprimer un run détruit le journal
  d'undo, et la modale annonce l'inverse.** Le texte promet « le run + son plan + son log » :
  **faux**, aucun fichier n'est touché (`history_support.py:731-732`). Et il **tait** le seul effet
  grave : `run.py:726` fait `DELETE FROM apply_batches`, dont la cascade détruit
  `apply_operations`. Supprimer un run de moins de 24 h rend son apply **définitivement non
  annulable**, sans aucune garde de réversibilité.
- [ ] **T-PROD-4 · Quatre sites `except OSError` sur du SQLite.** La règle inviolable n°4
  (`sqlite3.Error` n'hérite PAS d'`OSError`) est déjà appliquée trois fois ailleurs. Manquent :
  - `apply_support.py:3076` (`_restore_jellyfin_watched`) — un apply **intégralement réussi sur
    disque** est annoncé `{ok: False}` quand la base est verrouillée ;
  - `cinesort_api.py:572` — l'exception sort **DU handler d'erreur lui-même** et masque
    l'exception d'origine ;
  - `run_control_support.py:224` et `run_flow_support.py:2152` — lectures/invalidations
    best-effort qui remontent en HTTP 500.
- [ ] **T-PROD-5 · PR #1123 : le verdict d'undo compare deux populations disjointes.** `avant` est
  pris sur `reversible_ops` (filtre `reversible == 1`, `apply_support.py:284`, ligne 1493) ;
  `apres` relit **toutes** les ops du lot (`list_apply_operations(batch_id=…)`, ligne 1461, aucun
  filtre). Les `MKDIR` sont journalisés `reversible=False` (`apply_core.py:601-607`) et
  `_undo_mkdir_ops` (ligne 1523, **avant** le verdict) les marque `DONE`.
  Mesure reproduite (2 MOVE + 1 MKDIR) : `{'coherent': False, 'code':
  'undo_compte_restaure_diverge'}`, message « l'undo annonce 2 restauration(s) mais le journal
  n'en a inscrit que 3 » — absurde — et **une notification d'erreur publiée**. Chaque `move` crée
  le dossier parent de sa destination (`apply_core.py:1005`) : c'est l'undo **ORDINAIRE**.
  Le test `tests/test_verdicts_undo.py:274` mocke `_undo_mkdir_ops` à `0` : il ne pouvait pas le voir.
- [ ] **T-PROD-6 · `apply_support.py:3262-3266`** — un apply réel dont `insert_apply_batch` a
  échoué (`apply_batch_id = None`, mode dégradé documenté) échappe au verdict.
- [ ] **T-PROD-7 · `apply_support.py:3602/3604`** — le verdict d'apply n'est calculé que sur le
  chemin de retour **nominal**. L'`except Exception` (l'apply qui casse après avoir déplacé) n'en
  produit aucun.
- [ ] **T-PROD-8 · `apply_core.py:2817` et `:775`** — `apply_single` (le chemin le plus fréquent)
  et la migration de la racine de collection ne passent pas par `move_journal.atomic_move` : elles
  renomment puis appellent `record_apply_op`. Le **journal write-ahead n'est pas posé**, et c'est
  lui qui rend le déplacement réconciliable si l'app meurt entre les deux — la docstring
  d'`atomic_move` le dit mot pour mot.
  ⚠️ **Ce n'est PAS une régression de la PR #969** : la ligne était déjà un `folder.rename(dst)` nu
  avant elle ; #969 n'a fait qu'y ajouter la reprise. Trou pré-existant, pas garde éteinte.

---

## LOT 3 — Gardes inertes (le motif dominant)

Le dépôt n'est pas sous-protégé : il est protégé par des instruments dont plusieurs ne peuvent
**structurellement** rien détecter. Chacun rend un vert.

- [ ] **T-GARDE-1 · `tests/test_axe_dashboard.py:114-116`** — le gate d'accessibilité WCAG ne peut
  pas rougir : sa seule assertion dure est **commentée**, il imprime un `WARN`. Et il ne tourne
  jamais en CI, faute d'un jeton (`CINESORT_API_TOKEN`) qu'aucun workflow ne pose.
- [ ] **T-GARDE-2 · `tests/visual/test_responsive_viewports.py`** — son jumeau (10 viewports × 6
  routes) n'a **aucune assertion** dans tout le fichier, et audite une route `/validation` qui
  n'existe pas.
- [ ] **T-GARDE-3 · `tests/e2e_dashboard/` — 98 tests lancés par AUCUN workflow.** `grep -rn
  'e2e_dashboard' .github/` ne rend qu'une seule ligne : un `--ignore`. Et l'étape `ci.yml:313`
  **nommée « Tests E2E Dashboard »** exécute `tests/e2e/` — un autre répertoire — avec
  `continue-on-error: true` et `-x` (`ci.yml:319-321`), donc zéro signal, à l'intérieur du job
  `Lint, Tests, Build` qui est un check **requis**.
- [ ] **T-GARDE-4 · Le cliquet `sqlite3.Error` est aveugle à un renommage de variable.**
  `tests/test_sqlite_error_hors_oserror_cliquet.py:70-76` filtre sur des **préfixes de variable**
  (`store.`, `self._store.`) : `resolved_store.run.insert_error` et
  `default_store.run.list_pending_runs()` échappent au recensement. 63 sites vus, plafond 63,
  **2 vrais accès hors radar**.
- [ ] **T-GARDE-5 · `tests/_etat_reel_guard.py:116-132`** — le garde qui empêche la suite d'ouvrir
  la base RÉELLE **imprime**, il ne fait jamais rougir, n'a aucun test à lui, et son mode de panne
  est le **silence** : une redirection cassée rend exactement la même sortie qu'un fonctionnement
  correct.
- [ ] **T-GARDE-6 · `tests/test_contract_dead_symbols.py:60`** — le cliquet de code mort est
  aveugle à un **module orphelin entier** : `USE_ROOTS` inclut le fichier déclarant lui-même.
- [ ] **T-GARDE-7 · `tests/test_import_cycle_guard.py:44`** — garde à vide :
  `_BASELINE_APP_MODULES_LOADED = 6` comparé par `assertLessEqual`, alors que la mesure réelle est
  **0**. Il tolère 6 nouveaux imports sans broncher.
- [ ] **T-GARDE-8 · `tests/test_cliquet_couverture_triangle.py:182-186`** — une des quatre
  assertions du cliquet des routes destructives est **infalsifiable par construction**. Et le
  cliquet mesure les routes **marquées**, pas les routes destructives.
- [ ] **T-GARDE-9 · 990 tests sur 9 276 (10,6 %)** n'ont pour seules assertions que des sous-chaînes
  de **code source**, réparties sur ~94 fichiers. C'est une **dette mesurée**, pas un faux vert
  démontré : combien survivraient à une mutation composée reste **inconnu** (aucune analyse de
  mutation n'a été faite, elle exige d'écrire dans le dépôt).
- [ ] **T-GARDE-10 · 8 `pytest.skip` en corps de test** dans `test_runtime_apply_history_labels.py`
  (:97, :139, :155, :170) transforment la panne cherchée en vert : « l'historique ne charge pas en
  10 s », « aucune entrée cliquable ». Indiscernable d'un succès dans un rapport `-q`. Celui de
  `:170` est **structurellement toujours pris**.
- [ ] **T-GARDE-11 · `tests/test_tmdb_single_chosen.py:112,133,165,215`** — les 4 SEULS tests de
  l'invariant « un seul candidat TMDb porte `chosen=True` » se sautent eux-mêmes, de façon
  déterministe.
- [ ] **T-GARDE-12 · Deux bugs réels masqués par des `pytest.xfail()` dynamiques** (exit 0) dans
  `test_lotd_chain_doublons.py`, dont un sur le chemin **destructif** (`files_identical_quick`).
- [ ] **T-GARDE-13 · `ci.yml:48-72` — le job « Generate/Verify uv.lock » ne vérifie rien** :
  `run: uv lock` nu, sans `--check`, sans `--locked`, sans `git diff --exit-code`. Il **régénère**.
  `uv lock --check` sort déjà en code 1 sur `HEAD`.
- [ ] **T-GARDE-14 · `tests/test_pyproject_pep621_v77.py:91-113`** — le garde d'alignement
  `pyproject` ↔ `requirements.txt` ne compare que des **noms** de paquets, jamais les bornes :
  5 mutations testées, 5 restent vertes.
- [ ] **T-GARDE-15 · `export_support.py:36`** — `_SECRET_KEYS` liste `smtp_password` alors que la
  clé réelle est `email_smtp_password` ; `docs/EXPORT_FORMAT.md:53` promet à l'utilisateur un
  masquage qui ne s'applique pas.
- [ ] **T-GARDE-16 · `build_windows.bat:31`** — le garde de version Python n'a **pas de plancher** :
  `sys.version_info < (3, 14)`. Python 3.9 à 3.12 passent silencieusement.
- [ ] **T-GARDE-17 · `build_windows.bat:40-43`** — l'EXE se construit avec des paquets **sous les
  planchers de sécurité déclarés** : si 4 imports passent, `pip install -r requirements-build.txt`
  est sauté. `.venv313` porte `urllib3==2.6.3` alors que `requirements.txt:6` épingle `>=2.7.0`.
- [ ] **T-GARDE-18 · `check_project.bat:5-8,38,45` — un SIXIÈME ancrage ruff, ni épinglé ni gardé.**
  Le gate local résout `.venv313` (ruff 0.15.6) puis `.venv` (0.15.13) alors que les 5 points
  gardés valent 0.16.3. Écart mesuré : **52 fichiers de moins** vus par `ruff format --check` en
  local qu'en CI.

---

## LOT 4 — Documents faux qui pilotent des agents

Ces fichiers ne sont pas lus par des humains : ils sont **injectés dans des prompts**.

- [ ] **T-DOC-1 · `.github/workflows/claude.yml:104` — priorité.** Le prompt du bot d'audit
  hebdomadaire (cron `0 4 * * 1`) injecte « 4277 tests unitaires, coverage seuil 80 % ».
  Réel : **9 276 items** (mesuré `--collect-only -q` le 2026-08-26), seuil **75 %**.
- [ ] **T-DOC-2 · Seuil de couverture annoncé à 80 % dans quatre fichiers** — `.codecov.yml:5`,
  `README.md:194`, `claude.yml:104`, `docs/internal/CLAUDE.md:521` — alors que `ci.yml:211` dit
  `--fail-under=75`. Nuance : `.codecov.yml:13` `target: 80%` est un réglage codecov distinct,
  légitime ; c'est le **commentaire** de `:5` (« aligné avec `--fail-under=80` ») qui ment.
- [ ] **T-DOC-3 · Le seuil « temporaire » a 99 jours.** `ci.yml:205` : « seuil temporairement
  baissé de 80 à 75 suite à la migration B (PR #257) […] la couverture remontera quand les
  nouveaux tests dashboard seront ajoutés ». Introduit le 2026-05-19, jamais relevé — et les
  « nouveaux tests dashboard » promis sont précisément les 98 tests que rien n'exécute (T-GARDE-3).
- [ ] **T-DOC-4 · Quatre comptes de tests différents circulent**, tous faux : 4277 (README ×3 +
  `claude.yml`), 6062 (`docs/internal`), 9140 (`/CLAUDE.md`).
- [ ] **T-DOC-5 · `README.md:186` et `docs/internal/CLAUDE.md:573`** publient
  `pytest --timeout=60` : le plugin n'est pas installé → **exit 4, zéro test exécuté**. Et
  `/CLAUDE.md:43` interdit explicitement ce drapeau. Corriger aussi `pyproject.toml:105-106`, qui
  affirme que `--timeout=60` est dans `ci.yml`.
- [ ] **T-DOC-6 · `docs/internal/CLAUDE.md` épingle ruff `0.15.22`** (réel 0.16.3) : c'est un
  **sixième** point d'ancrage, périmé, dans un fichier présenté comme « la référence détaillée ».
- [ ] **T-DOC-7 · `docs/internal/CLAUDE.md:558-564`** — une section « Issues ouvertes (3) »
  présente #14 et #85 comme ouvertes : les deux sont **fermées**.
- [ ] **T-DOC-8 · `docs/internal/CLAUDE.md:184,198`** — les deux repères de navigation dans le
  serveur REST sont faux (taille du fichier +50 %, `compare_digest` déplacé).
- [ ] **T-DOC-9 · `docs/internal/CLAUDE.md:536`** — annonce Opus 4.8 / effort `ultra` pour les deux
  workflows ; le bot d'audit tourne en Opus 5 avec `--effort max`.
- [ ] **T-DOC-10 · `README.md:18,21,158,196,283`** — version, compte de tests, taille et nombre de
  façades tous faux : le document public est trois versions mineures en retard.
- [ ] **T-DOC-11 · `CHANGELOG.md:8` s'arrête à v1.2.0-beta (17 mai)** : les versions 1.3, 1.4 et
  1.5.x n'y existent pas — trois mois de livraisons non documentées.
- [ ] **T-DOC-12 · `CITATION.cff:35`** figé à `1.0.0-beta`.
- [ ] **T-DOC-13 · `pyproject.toml:4-5`** renvoie à `scripts/bump_version.py`, qui **n'a jamais
  existé**.
- [ ] **T-DOC-14 · Résidus documentaires dans le code** : `apply_core.py:3066` — la docstring
  d'`apply_tv_episode` décrit encore le renommage **supprimé**, sur la règle inviolable n°1 ;
  `rest_server.py:538-541,1627` — `bind_host` mort dont le commentaire affirme qu'un bypass
  loopback existe encore.

*(Corrigés dans `/CLAUDE.md` par la présente revue : le 404 → 410, la présentation de #965 comme
défaut ouvert, « neuf modules > 1 000 lignes » → dix-neuf, « total d'items stable à 9140 » → 9 276,
et l'ajout de la mesure d'artefacts + du piège `git branch -r`.)*

---

## LOT 5 — Dette structurelle

- [ ] **T-ARCH-1 · 1 618 lignes de scaffold sans aucun appelant runtime** : `audio_neural_fp.py`,
  `vision_embedding.py`, `dinov3_model.py`, `vector_search/`, `windows_hello_gate`,
  `similar_films_facade`, `enrichment_facade`, `ollama_client`. Trancher : câbler ou supprimer.
- [ ] **T-ARCH-2 · 19 modules > 1 000 lignes, 11 > 1 500**, aucun cliquet de taille. Les
  **fonctions** sont bornées depuis #778 ; les **modules** ont pris +1 250 lignes depuis et aucun
  n'a diminué. `apply_support.py` 4 057 l., `apply_core.py` 3 436, `cinesort_api.py` 3 288.
- [ ] **T-ARCH-3 · `rest_server.py:280-292`** — toute méthode publique ajoutée à une façade ouvre
  **automatiquement** une route REST, sans revue : `for method_name in dir(facade)`.
- [ ] **T-ARCH-4 · `.importlinter:9-11`** — `app.py` (1 169 lignes, `main()` de 525 lignes) est le
  point de composition RÉEL du produit et il est **hors du périmètre** des 3 contrats.
- [ ] **T-ARCH-5 · 4 cycles d'imports réels** subsistent (composantes fortement connexes sur le
  graphe grimp), dont un de 10 modules et un de 7.
  ⚠️ **L'issue #779 est périmée dans les deux sens** : elle annonce 89 imports paresseux
  intra-`ui/api` ; mesure AST du 2026-08-26 : **22**. Corriger le titre ou fermer.
- [ ] **T-ARCH-6 · `scripts/measure_codebase_health.py`** sait mesurer mais retourne toujours 0 et
  n'est câblé dans aucun workflow.
- [ ] **T-CI-12 · Le même EXE PyInstaller est construit DEUX fois par PR** (`ci.yml:274-276` dans le
  job requis, `windows-ci.yml:129` dans un job requis par rien), plus un 3ᵉ runner qui rejoue
  lint+tests via `check_project.bat`.
- [ ] **T-CI-13 · `windows-ci.yml:61,101`** — la porte qualité Windows n'est **pas bloquante**.
- [ ] **T-CI-14 · `smoke-exe.yml:9-14`** — le smoke test de l'exécutable packagé **n'a jamais
  tourné** depuis la création du dépôt : son unique déclencheur est `workflow_dispatch`.
- [ ] **T-CI-15 · 13 références d'action non épinglées par SHA** alors que la convention du dépôt
  (~40 autres) est l'épinglage + commentaire `# vN`, et qu'OpenSSF Scorecard tourne ici.
- [ ] **T-CI-16 · `claude.yml:16-27`** — déclencheur trop large (`issue_comment`,
  `pull_request_review`, `issues`, `pull_request`) sans filtre en amont.
- [ ] **T-CI-17 · `audit-module.yml` n'a AUCUNE étape `if: failure()`** (0 occurrence). Taux
  d'échec mesuré du producteur de ~3 PR/jour : **3 sur 15 (20 %)**, les 18, 24 et 25 août. Un run
  rouge visible dans l'onglet Actions n'est pas une alerte qui atteint quelqu'un.
- [ ] **T-CI-18 · `pr-title-lint.yml:52`** — rouge permanent sans signification : GitHub n'efface
  pas les check-runs périmés d'un même nom. Non bloquant (documenté), mais il apprend à ignorer.
- [ ] **T-DEPS-1 · `requirements.lock` (49 000 lignes) n'est installé ni audité par personne** :
  0 occurrence hors `docs/internal/`. Artefact mort qui donne l'illusion d'une reproductibilité.
- [ ] **T-DEPS-2 · `uv.lock:139` est périmé** : `pytest-playwright >=0.8.0,<0.9` alors que les deux
  manifestes disent `<0.10` depuis #1112.
- [ ] **T-DEPS-3 · `perceptual_support.py:1059`** importe Pillow en dur alors que Pillow n'est pas
  une dépendance runtime.
- [ ] **T-DEPS-4 · `requirements.txt:11`** — `zipp>=3.23.1 # pinned by Snyk` est un fantôme : aucun
  code ne l'importe, aucune autre dépendance ne le tire, et il n'a pas de borne haute.
- [ ] **T-BACK-1 · 5 des 16 issues ouvertes ont déjà reçu des correctifs FUSIONNÉS** et n'ont
  jamais été fermées : #1000, #1010, #1031, #1052, #779. La file affiche une dette déjà payée.
- [ ] **T-BACK-2 · Issue #1089 : son titre est faux depuis le lendemain de son écriture.**
  « 4 correctifs jamais repris » → 3 des 4 sont dans `main` (vérifié par **contenu**, pas par
  ascendance). Le 4ᵉ (`radarr_sync.py:35`, accepter un `tmdb_id` en chaîne) paraît **inatteignable**
  : les deux seuls producteurs de `Candidate.tmdb_id` coercent déjà en `int`.
- [ ] **T-BACK-3 · `wip/b4-main-uncommitted-2026-06` (`0a485a25`) est un exemplaire UNIQUE** portant
  1 commit inédit. `doublons.js` et `processing.js` n'ont jamais été arbitrés — alors que
  `docs/internal/CLAUDE.md:96,256` et `BILAN_PHASES.md:365` affirment « wip/b4 réconcilié ».
  **À reprendre avant toute suppression.**
- [ ] **T-BACK-4 · Findings d'audit toujours ouverts sur `main`** : `06054e1b` (#1105,
  `apply_rollback.py:138,455-462`), `a19mi002` (#1116, `_normalize_mediainfo.py:94-105`, truehd
  atmos / dts-hd ma en `probe_backend=mediainfo`), et les 2 findings de #1100
  (`film_support.py:43`, `run_support`) intacts 10 jours après.
- [ ] **T-BACK-5 · Le corpus `docs/internal/audits/findings/*.jsonl` ne porte AUCUN état de
  traitement** : agréger « les findings non traités » est impossible sans rouvrir le code. Ajouter
  un champ d'état, sinon chaque revue future repaiera l'agrégation.
- [ ] **T-BACK-6 · La mémoire anti-doublon du bot d'audit a un angle mort** : cinq rapports
  consécutifs (2026-08-20 → 08-26) sont bloqués en PR non fusionnées, donc invisibles à sa
  déduplication.

---

## Ce que cette revue N'A PAS regardé

Établi par un critique de complétude payé pour attaquer la synthèse. C'est la partie la plus utile.

1. **Le moteur de décision du produit.** `cinesort/domain/` = 70 fichiers, **28 644 lignes** ;
   `quality_score.py` = 2 669 lignes, 53 fonctions, 5ᵉ plus gros module du dépôt. Il n'apparaît
   dans **aucun** des 132 constats ni des 69 réfutations. Idem `duplicate_compare`,
   `duplicate_multi_signal`, `film_identity`, `encode_analysis`, `fusion_score`, `genre_rules`,
   `custom_rules`, `runtime_matching`. Les 11 domaines étaient **tous** process/infra ;
   `invariants-produit` n'a couvert qu'apply/undo/rollback, **jamais le tri lui-même**.
   → *C'est le premier périmètre de la prochaine revue.*
2. **Le front.** `web/` = 62 fichiers, **47 234 lignes** — plus grosse zone du dépôt hors tests, et
   sans aucun filet : `package.json` ne déclare qu'un `check:js` de syntaxe Node, **zéro
   dépendance npm, zéro test unitaire**, et la suite e2e n'est pas exécutée. La revue a audité
   100 % de la chaîne de livraison et ~0 % de l'interface.
3. **`scripts/`** — 39 fichiers, 8 434 lignes, **zéro test**. Et c'est ce répertoire qui produit
   les sauvegardes SQLite porteuses des secrets : une réfutation a conclu « aucun code du PRODUIT
   ne crée ces fichiers » et a classé l'affaire, sans auditer l'outil qui, lui, les crée
   (`scripts/observe.py:313`).
4. **Les 32 migrations SQLite** — ordre d'application, reprise sur base PRÉ-EXISTANTE, absence de
   rollback : regardés par personne.
5. **Aucune exécution.** Ni l'application, ni la suite complète, ni un parcours utilisateur (scan
   réel, apply réel, undo réel). Les défauts d'invariants sont établis par lecture + sondes en
   mémoire sur les vraies fonctions.
6. **Rien n'a été vérifié après correction.** Aucun correctif appliqué, aucun test vu rouge puis
   vert. En particulier, **il n'est pas prouvé qu'approuver les runs débloque les 7 PR**, ni que
   fusionner #1142 débloque #1145.
7. **L'exploitabilité du jeton n'est pas mesurée de bout en bout** : le bind par défaut est
   `127.0.0.1`, donc l'exploitation exige une session locale ou un opt-in LAN. La fuite et la
   validité sont **certaines** ; l'immédiateté de l'attaque ne l'est pas.
8. **Aucune analyse de mutation** (elle exige d'écrire dans le dépôt) : les 990 tests
   « assertIn sur du source » restent une dette **mesurée**, pas un faux vert **démontré**.

---

## Pièges de mesure rencontrés (à ne pas repayer)

- **`gh pr checks` dédoublonne** les check-runs côté client, et `statusCheckRollup.state` rend
  `SUCCESS` interrogé seul et `FAILURE` interrogé avec `contexts(first:100)` — **sur le même
  commit**. Seul le rendu HTML a tranché. Tout constat fondé sur `gh pr checks` seul est à
  ré-arbitrer.
- **`mergeable: MERGEABLE` ne parle que des conflits de fichiers**, jamais des checks. Lire
  `mergeStateStatus`.
- **`git branch -r` rend 620 refs pour 63 branches réellement sur `origin`** — les refs périmées ne
  sont jamais élaguées. `git fetch --prune` d'abord.
- **Les échantillons choisis mentent.** Le discriminant du blocage CI se vérifiait 15/15… sur les
  seules PR ≥ #1124. Élargi : 7 contre-exemples. Idem pour les fils de revue non résolus (4 PR,
  pas 1). Tout chiffre non recompté sur la population entière est un **minorant**.
- **Une sonde au périmètre choisi rend un faux négatif.** Ma première recherche du jeton sur disque
  a rendu **0** : j'avais exclu les dossiers `cache` et limité les extensions. La sonde complète
  (129 889 fichiers) en trouve **24**.
- **Les comptes GitHub bougent d'une heure à l'autre** et ne portent pas leur date : runs
  `action_required` mesurés entre 107 et 111, artefacts vivants 1 892 à 1 915. Ils se remesurent.
- **Remesurer avant de « corriger » un chiffre qui dérange.** La synthèse annonçait 3,18 Go
  d'artefacts « et non 36 Go comme le dit CLAUDE.md », et proposait de corriger le document.
  Mesure : **41,05 Go**. C'est `CLAUDE.md` qui avait raison.

---

## Pistes sondées et rendues NÉGATIVES

À ne pas repayer.

- **i18n** — parité parfaite : 647 clés de chaque côté, 0 manquante dans les deux sens. Résidu non
  tranchable sans exécuter le front : 17 valeurs identiques fr/en de plus de 12 caractères,
  possiblement des non-traductions volontaires.
- **Packaging** — `CineSort.spec` ne référence **aucun** fichier absent (0 sur tous les tuples
  `datas`). La piste « le .spec pointe vers des chemins morts » est close.
- **Contrats d'architecture** — `./.venv/Scripts/lint-imports.exe` sort en **code 0** :
  « Analyzed 234 files, 685 dependencies », les trois contrats de couches tiennent.
- **Baselines de contrat** — aucune n'a grossi. Il n'en existe qu'une
  (`tests/contract_baselines/css_used_undefined.json`) et son cliquet fonctionne.
- **CVE** — dernier `pip-audit` sur `main` (2026-08-24) : « No known vulnerabilities found » sur
  les trois fichiers de dépendances. *(Le check ne peut pas échouer — cf. T-SEC-7 — mais son
  verdict, lui, est lisible.)*
- **`dist/CineSort.exe`** date du 2026-07-10, **antérieur** aux modules scaffold ajoutés le 07-16 :
  un grep dessus n'aurait aucune valeur.

---

*Un rapport de lecture (page consultable) accompagne ce document ; son URL n'est pas versée ici,
le dépôt étant public et le lien pointant vers une page privée — `lychee` la verrait comme un lien mort.*
