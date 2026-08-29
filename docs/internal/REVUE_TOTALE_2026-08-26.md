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
- [x] **T-SEC-4 · FAIT le 2026-08-29** (`sec(logs)`, commit local `51ca9bca`). Le constat était
  juste et **plus large** : mesure sur 18 noms de paramètre standards, **12 fuyaient** — dont
  `access_token`, `refresh_token`, `auth_token`, `id_token`. Cause : `\b` ne matche pas *entre
  deux caractères de mot*, et `_` en est un. Fuite reproduite **de bout en bout jusqu'au fichier
  de log** par la chaîne de production, le témoin `?token=` étant rédigé sur la ligne voisine.
  ⚠️ **Le premier correctif était pire que le défaut.** Préfixer le motif par `[\w-]*` rend une
  sortie *strictement identique* mais fait passer 40 000 caractères sans correspondance de
  **0,91 ms à 24 338 ms** — un ReDoS (CWE-1333) dans un filtre qui traite des lignes de requête,
  donc du texte contrôlé par l'appelant. Il a **bloqué la batterie** des 12 fichiers liés :
  371 s de CPU pour 439 s écoulées, sans terminer. Aucun test ne pouvait le voir : les quatre
  variantes de motif sont fonctionnellement vertes. D'où le garde
  `test_motif_de_query_string_ne_redose_pas` (budget 2 s pour un échec à 24 s).
  Correctif retenu : **retirer le `\b`, rien d'autre**. 5 tests ajoutés au garde EXISTANT
  (33 → 34). Mutation composée : `\b` remis tue les 3 fonctionnels, `[\w-]*` tue le garde ReDoS
  **seul**, motif neutralisé tue 3 + 6 préexistants, `=` rendu optionnel tue le contre-test.
- [ ] **T-SEC-5 · Cesser de faire transiter le jeton dans l'URL.** C'est la cause amont de T-SEC-3
  et T-SEC-4. `app.py:854` tronque déjà volontairement le jeton pour son propre log : le serveur,
  lui, journalise la ligne de requête entière.
- [~] **T-SEC-6 · RÉFUTÉE le 2026-08-29 — et son remède aurait été nuisible.** Le fait est exact
  (glob `settings.json.bak.*`, les `.bak_ITER*` hors champ) mais ce **n'est pas un défaut de la
  rotation**. Mesuré : l'écrivain de sauvegardes du produit (`settings_support.py:157`) n'emploie
  QUE `.bak.` — tout ce qu'il crée entre dans la rotation ; et **rien sous `cinesort/` ne produit
  de `.bak_ITER*`**. Le seul producteur de `.bak_` du dépôt est `scripts/observe.py:313`, un
  script de diagnostic, qui sauvegarde la **base**, pas les réglages. Ces fichiers sont donc
  étrangers au produit.
  Élargir le glob ferait **supprimer silencieusement au produit des fichiers qu'il n'a jamais
  créés**, sauvegarde manuelle de l'utilisateur comprise — la règle inviolable n°3 prise à
  revers. Le bon remède est la purge locale (T-SEC-3), qui appartient à Thomas.
- [x] **T-SEC-7 · FAIT le 2026-08-29 (cliquet sur le COMPTE) — voir le Journal.** Et le « trois »
  de cette ligne est FAUX : `pip-audit` bloque sur la production, seuls bandit et mypy étaient
  aveugles. ~~Retirer les `|| true` des trois checks REQUIS~~ — ou les sortir de la liste des
  requis. `bandit.yml:89`, `mypy.yml:92`, `pip-audit.yml:87` (`continue-on-error`). La protection
  de `main` en annonce sept ; **quatre mordent**.
- [ ] **T-SEC-8 · Ajouter une règle gitleaks qui mord sur un secret nu entre backticks en prose.**
  Le secret n'était **pas** dans `.gitleaksignore` : ce n'était pas une exemption assumée, c'était
  une non-détection. Corriger aussi `CLAUDE.md:658` et l'en-tête de `gitleaks.yml`, qui affirment
  « 56 détections, ZÉRO secret réel ».
- [x] **T-SEC-9 · FAIT le 2026-08-29** (`docs(rest)`, commit local `985bae18`) — confirmée sur la
  doc, **très réduite** sur la sécurité, et elle a ouvert deux constats neufs.
  La justification morte est réelle : trois commentaires invoquaient le bypass retiré le
  2026-08-07 (`/api/poster`, et **deux** sur `bind_host`, mesuré MORT — 2 écritures, 0 lecture).
  Corrigés ; couvre aussi T-DOC-14.
  Mais la route n'est pas nue : `_poster_trusted_caller` limite les appelants non fiables à la
  lecture du cache. Mesuré en bac à sable (témoin : `POST` sans jeton → **401**) : `/api/poster`
  ne rend **jamais** 401, mais la défense en couches tient.

- [x] **T-SEC-10 · NEUF, FAIT le 2026-08-29 — la route jaquettes se gardait par le SITE, pas par
  l'ORIGINE** (`sec(poster)`, commit local `ce5eaaf8`). CWE-200 + CWE-346.
  `_poster_trusted_caller` acceptait `Sec-Fetch-Site: same-site` comme fiable. Or le « site » au
  sens Fetch Metadata est le domaine enregistrable : **le port n'en fait pas partie**. Sur
  `127.0.0.1`, tout autre service web local est donc `same-site`.
  **Mesuré au navigateur réel**, deux serveurs locaux (18801/18802) : une image demandée à un
  AUTRE PORT porte `same-site`, jamais `cross-site`. Puis contre CineSort en bac à sable : une
  page servie sur 18801 obtenait la jaquette en cache de l'instance du 18742 (**image chargée,
  1×1**) et un refus sur un id absent. Deux conséquences : un **oracle d'énumération de la
  bibliothèque** sans aucun credential, et le **privilège** `force=1` + fetch TMDb.
  ⚠️ **Le repli par IP était la seconde moitié du défaut, et seule l'ÉCRITURE DU TEST l'a
  révélée** : exiger `same-origin` sans y toucher aurait laissé un navigateur `same-site` sur la
  boucle locale retomber sur `_LOCAL_CLIENT_IPS` et redevenir fiable.
  **Pourquoi personne ne l'avait vu** : `_poster_trusted_caller` et `Sec-Fetch-Site`
  n'apparaissaient dans **aucun** fichier de `tests/`. Leur unique exercice est
  `docs/internal/r8/r8_f3_poster_trusted_diff.py`, un script que nul workflow ne lance, dont la
  table couvre `same-origin` et `cross-site` — **jamais `same-site`**. L'en-tête a quatre
  valeurs ; la preuve en énumérait deux, les deux extrêmes.
  Vérifié **dans un vrai navigateur** après correctif : la page tierce n'obtient plus rien (les
  deux réponses devenues identiques), le dashboard charge toujours sa jaquette. Garde neuf :
  `tests/test_poster_frontiere_origine.py`, 7 tests dont **4 contre-tests**.

- [x] **T-SEC-11 · NEUF, périmètre balayé le 2026-08-29 : le défaut de frontière est PROPRE à la
  route jaquettes.** Mesuré, pas déduit — le chemin POST refuse une origine d'un autre port local
  avec **403, jeton valide compris**, y compris sur `settings.reset_database` : `_allowed_origin`
  contraint bien le port. Les 6 routes GET n'appellent aucune authentification, mais aucune ne
  sert de donnée utilisateur — les trois racines statiques pointent vers `web/dashboard`,
  `web/shared` et `locales`. Traversée de chemin éprouvée sur les trois : **contenue** (le seul
  200, `/shared/../dashboard/index.html`, atteint un fichier déjà public ; toute sortie de `web/`
  rend 404).
  **Reste ouvert, non corrigé** : `GET /api/spec` rend **80 182 octets** de spécification OpenAPI
  complète sans jeton — la carte des 172 endpoints, routes destructives comprises. Non lisible
  *cross-site* (aucun en-tête `Access-Control-Allow-Origin` n'est émis pour une origine tierce),
  donc exploitable seulement par un processus local, ou en LAN sous `--public`. À arbitrer.

---

## LOT 1 — Débloquer la file (au 2026-08-26 : 12 infusionnables sur 22 ; remesuré le
2026-08-28 : **17 sur 28** — 16 BLOCKED + 1 UNSTABLE)

- [x] **T-CI-1 · FAIT le 2026-08-29 — voir le Journal du 2026-08-29.** Éprouvé sur #1133 puis
  généralisé : 4 PR passées à `CLEAN`. Le reste de cette entrée est conservé pour la mémoire du
  raisonnement.
  ~~Éprouver le remède sur UNE seule PR.~~ Sept PR (#1125 #1128 #1130 #1133 #1134
  #1137 #1148) portent **0 des 7 checks requis** : leurs 10 à 44 runs sont parqués en
  `conclusion=action_required`. Discriminant mesuré : le **`triggering_actor` du push** —
  `claude[bot]` passe, `github-actions[bot]` est parqué.
  **La cause racine n'est PAS mesurée** (l'API GitHub n'expose pas le réglage d'approbation) et le
  remède n'a jamais été testé. Approuver les runs de **#1133** et observer.
  ⚠️ **Ne PAS fermer/rouvrir, ne PAS squasher** : une première lecture accusait le *nombre de
  commits*, réfutée par 7 contre-exemples (#1099, #1104…). Ces remèdes visent le mauvais mécanisme
  — et le finding `a3610492` de PR #1148 les recommande **à tort, avec une confiance de 0,95**.
- [x] **T-CI-2 · FAIT le 2026-08-28 — et la parade n'était PAS d'une ligne.** Le label `blocked`
  **n'existait pas dans le dépôt** : la commande prescrite échouait. Témoin à réponse connue :
  `gh pr edit --add-label 'zzz-temoin-inexistant'` rend `not found` et ne crée rien. `stale.yml`
  *déclarait* `blocked` dans `exempt-pr-labels` ; le dépôt ne le *définissait* pas. **Lire un
  fichier de configuration ne dit rien de l'existence de ce qu'il nomme.**
  Label créé (`#B60205`) puis posé sur **8** PR, pas 7 : `#1125 #1128 #1130 #1133 #1134 #1137
  #1148 #1152` (#1152, rapport du 27, a rejoint le lot). **Zéro run CI déclenché** (32 572 runs
  avant et après ; `grep -rn labeled .github/workflows/` rend 0). Les 8 `updatedAt` repoussés à
  aujourd'hui : marquage ~27 septembre, fermeture ~4 octobre. C'est un sursis, pas la parade.
  **Deux mesures rectifiées.** « Cinq de ces PR sont des rapports d'audit » était faux sur les 7
  d'origine — il y en avait **quatre** (#1130 #1134 #1137 #1148) ; cinq aujourd'hui avec #1152.
  Et l'enjeu est plus large que les rapports : comparées à `origin/main` fichier par fichier,
  **les 8 portent au moins un fichier absent de `main`**, #1125 #1128 #1133 portant chacune un
  **fichier de test unique**. Une suppression de branche détruirait **13 fichiers**, pas 5.
  ⚠️ **Non éprouvé, et non éprouvable aujourd'hui** : que l'exemption se *déclenche*. `stale.yml`
  n'a pas de `debug-only`, et un `workflow_dispatch` ne traiterait rien tant qu'aucune PR
  n'atteint son seuil (max 8 j pour 30). Seules les **trois préconditions** sont vérifiées : le
  label existe, son nom est identique octet pour octet (`cat -A` → `blocked$`), il est attaché
  aux 8.
- [ ] **T-CI-19 · Quatre des cinq exemptions PR de `stale.yml` sont des labels FANTÔMES.**
  `exempt-pr-labels: "pinned,security,wip,work-in-progress,blocked"` — mesuré le 2026-08-28 sur
  les 32 labels réels du dépôt : seul **`security`** existait (`blocked` créé depuis, cf. T-CI-2).
  `pinned`, `wip` et `work-in-progress` ne peuvent **structurellement** jamais s'appliquer. Côté
  issues, `exempt-issue-labels` en nomme 7 dont **2 fantômes** (`pinned`, `good-first-issue`).
  Une liste d'exemptions qui nomme des labels inexistants donne l'illusion d'un filet — c'est le
  motif de #1096 (la règle absolue impossible), appliqué à une garde. Trancher : créer les
  labels, ou élaguer la liste à ce qui existe.
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

- [x] **T-PROD-1 · FAIT le 2026-08-29** (`rel(rollback)`) — le constat est RÉEL, son mécanisme
  était FAUX, et le vérifier a changé le correctif.
  **Reproduit** avec la fonction de production, 3 ops sur un volume absent : `ok=True`,
  `ROLLED_BACK_BY_ATOMIC`, `done=0 skipped=3 failed=0`, « 0 revert / 3 skipped ». Trois films non
  restaurés, annoncés comme un succès franc.
  **Mais `ROLLBACK_PARTIAL` n'est PAS inatteignable** — il est produit à `:486` dès que
  `failed>0 et done>0`. Le défaut est qu'un `SKIPPED` n'entre dans **aucun** des deux compteurs
  qui font basculer le verdict.
  ⚠️ **Ce que la vérification a sauvé** : `test_rollback_5_of_10_partial` asserte *explicitement*
  que 5 done + 5 skipped rendent `ok=True`. Compter les SKIPPED comme des échecs aurait **éteint
  cette garde délibérée** et fait échouer des rollbacks valides. Mutation à l'appui : le mutant
  « sur-durcir » tue mon contre-test **et les deux gardes préexistantes**.
  **Discriminant mesuré** (3 cas dont un UNC réellement injoignable) : `dst.exists()` rend False
  partout, `dst.parent.is_dir()` sépare « rien à restaurer » de « je ne sais pas ». Correctif à la
  **classification**, pas dans l'agrégation.
  Reste ouvert : les deux autres raisons de saut qui signifient « je n'ai pas pu » —
  `src/dst vides` et `orphan_backup_present` — non mesurées, donc non traitées.
  ~~`apply_rollback.py:106, :139-150, :460, :477` — un rollback qui ne restaure rien
  et se déclare réussi.~~ Un partage réseau momentanément injoignable (winerror 53 → `ENOENT`,
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
- [x] **T-PROD-3 · FAIT le 2026-08-29** (`83ed5cfb`) — modale corrigee (le texte mentait dans les deux sens) ; AUCUNE garde backend — elle aurait eteint test_issue_448 et gele la retention 90 j.
  ~~Enonce d'origine ci-dessous.~~
  · **T-PROD-3 (enonce d'origine) · `web/dashboard/views/historique.js:1648` — supprimer un run détruit le journal
  d'undo, et la modale annonce l'inverse.** Le texte promet « le run + son plan + son log » :
  **faux**, aucun fichier n'est touché (`history_support.py:731-732`). Et il **tait** le seul effet
  grave : `run.py:726` fait `DELETE FROM apply_batches`, dont la cascade détruit
  `apply_operations`. Supprimer un run de moins de 24 h rend son apply **définitivement non
  annulable**, sans aucune garde de réversibilité.
- [x] **T-PROD-4 · FAIT le 2026-08-29** (`83ff4a94`) — 6 sites (pas 4) ; lignes du constat toutes derivees ; sous WAL seuls les chemins d'ECRITURE tombent.
  ~~Enonce d'origine ci-dessous.~~
  · **T-PROD-4 (enonce d'origine) · Quatre sites `except OSError` sur du SQLite.** La règle inviolable n°4
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
- [x] **T-GARDE-4 · FAIT le 2026-08-29** (`83ff4a94`) — recensement elargi : 63 -> 65 (2 sites hors radar) -> 59 apres correctifs ; plafond resserre.
  ~~Enonce d'origine ci-dessous.~~
  · **T-GARDE-4 (enonce d'origine) · Le cliquet `sqlite3.Error` est aveugle à un renommage de variable.**
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
- [x] **T-GARDE-13 · FAIT le 2026-08-29** (`df74274f`) — le job verifie desormais ; `uv lock --check` echouait deja sur HEAD.
  ~~Enonce d'origine ci-dessous.~~
  · **T-GARDE-13 (enonce d'origine) · `ci.yml:48-72` — le job « Generate/Verify uv.lock » ne vérifie rien** :
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

- [x] **T-DOC-1 · FAIT le 2026-08-29** (`ce0b2912`) — DEUX prompts, TROIS comptes, aucun juste ; le chiffre porte desormais sa date et sa commande.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DOC-1 (enonce d'origine) · `.github/workflows/claude.yml:104` — priorité.** Le prompt du bot d'audit
  hebdomadaire (cron `0 4 * * 1`) injecte « 4277 tests unitaires, coverage seuil 80 % ».
  Réel : **9 276 items** (mesuré `--collect-only -q` le 2026-08-26), seuil **75 %**.
- [x] **T-DOC-2 · FAIT le 2026-08-29** (`5f7db3f0`) — le `target: 80%` de codecov est legitime ; c'est son COMMENTAIRE qui mentait.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DOC-2 (enonce d'origine) · Seuil de couverture annoncé à 80 % dans quatre fichiers** — `.codecov.yml:5`,
  `README.md:194`, `claude.yml:104`, `docs/internal/CLAUDE.md:521` — alors que `ci.yml:211` dit
  `--fail-under=75`. Nuance : `.codecov.yml:13` `target: 80%` est un réglage codecov distinct,
  légitime ; c'est le **commentaire** de `:5` (« aligné avec `--fail-under=80` ») qui ment.
- [ ] **T-DOC-3 · Le seuil « temporaire » a 99 jours.** `ci.yml:205` : « seuil temporairement
  baissé de 80 à 75 suite à la migration B (PR #257) […] la couverture remontera quand les
  nouveaux tests dashboard seront ajoutés ». Introduit le 2026-05-19, jamais relevé — et les
  « nouveaux tests dashboard » promis sont précisément les 98 tests que rien n'exécute (T-GARDE-3).
- [ ] **T-DOC-4 · Quatre comptes de tests différents circulent**, tous faux : 4277 (README ×3 +
  `claude.yml`), 6062 (`docs/internal`), 9140 (`/CLAUDE.md`).
- [x] **T-DOC-5 · FAIT le 2026-08-29** (`5f7db3f0`) — `--timeout=60` mesure : exit 4, zero test ; et ci.yml n'en porte aucune occurrence.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DOC-5 (enonce d'origine) · `README.md:186` et `docs/internal/CLAUDE.md:573`** publient
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
- [x] **T-DOC-10 · FAIT le 2026-08-29** (`5f7db3f0`) — six affirmations du README fausses, mesurees une par une.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DOC-10 (enonce d'origine) · `README.md:18,21,158,196,283`** — version, compte de tests, taille et nombre de
  façades tous faux : le document public est trois versions mineures en retard.
- [x] **T-DOC-11 · FAIT le 2026-08-29** (`199439d4`) — 8 releases renseignees depuis GitHub ; les « trois mois » du constat sont en realite DEUX JOURS.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DOC-11 (enonce d'origine) · `CHANGELOG.md:8` s'arrête à v1.2.0-beta (17 mai)** : les versions 1.3, 1.4 et
  1.5.x n'y existent pas — trois mois de livraisons non documentées.
- [x] **T-DOC-12 · FAIT le 2026-08-29** (`199439d4`) — 1.0.0-beta -> 1.5.2-beta.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DOC-12 (enonce d'origine) · `CITATION.cff:35`** figé à `1.0.0-beta`.
- [x] **T-DOC-13 · FAIT le 2026-08-29** (`199439d4`) — `scripts/bump_version.py` n'a JAMAIS existe ; renvoi vers le garde reel.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DOC-13 (enonce d'origine) · `pyproject.toml:4-5`** renvoie à `scripts/bump_version.py`, qui **n'a jamais
  existé**.
- [x] **T-DOC-14 · À MOITIÉ FAIT le 2026-08-29** — les résidus de `rest_server.py:538-541,1627`
  (bind_host) sont corrigés par `docs(rest)`. Reste `apply_core.py:3066`, la docstring
  d'`apply_tv_episode` qui décrit encore un renommage supprimé.
  ~~Résidus documentaires dans le code~~ : `apply_core.py:3066` — la docstring
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
- [x] **T-DEPS-2 · FAIT le 2026-08-29** (`df74274f`) — lockfile regenere : la derive tenait en UNE ligne.
  ~~Enonce d'origine ci-dessous.~~
  · **T-DEPS-2 (enonce d'origine) · `uv.lock:139` est périmé** : `pytest-playwright >=0.8.0,<0.9` alors que les deux
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

## Journal du 2026-08-29 — 11 commits locaux, suite CI verte (9 279 passed, 0 échec)

### Débloqué

- [x] **T-CI-1 · ÉPROUVÉ, puis généralisé — le remède marche.** Les runs parqués de #1133 ont
  été approuvés, puis ceux des 7 autres (83 runs au total). Résultat mesuré :

  | PR | Checks requis | État |
  |---|---|---|
  | #1128 #1134 #1148 #1152 | **7/7 verts** | **`CLEAN`, fusionnables** |
  | #1137 | 7/7 verts | bloquée par 1 fil de revue |
  | #1125 | 6/7 | + 1 fil de revue |
  | #1130 #1133 | 6/7 | **1 check rouge légitime** |

  Ni fermeture, ni réouverture, ni squash : le finding `a3610492` de la PR #1148 est
  **réfuté par l'expérience**. Et T-CI-8 avait raison — approuver ne suffit pas là où un fil
  de revue traîne.
- [ ] **T-CI-3 · #1133 a un vrai défaut, pas seulement un gel.** Son `Lint, Tests, Build`
  échoue sur `tests/test_contract_settings.py::test_every_canonical_key_has_backend_reader` :
  la clé canonique `history_retention_days` n'a **pas de lecteur backend**. Mesuré dans le
  journal du run, pas déduit. À corriger avant fusion — la PR porte par ailleurs le correctif
  du « 0 = désactivé » d'un cron destructif (T-PROD-2).
- [x] **T-SEC-7 · FAIT — cliquet sur le COMPTE** (`ci(sec)`). Retirer les `|| true` d'un coup
  aurait rendu `main` rouge sur **103 éléments** (33 findings bandit dont 1 HIGH/HIGH,
  70 erreurs mypy dans 34 fichiers). Le compte est figé ; la montée échoue, **la baisse aussi**
  (un gain non verrouillé se reperd), et un rapport illisible échoue. Logique extraite des
  workflows et jouée sur **9 cas contrôlés**. ⚠️ `actionlint` n'est pas installable localement :
  c'est la CI qui le passera.

### Deux défauts de sécurité NEUFS, dans le périmètre jamais audité

- [x] **T-PROD-9 · NEUF — un `.nfo` amplifiait 500 octets en gigaoctets** (`sec(nfo)`, CWE-776).
  Trouvé *en mesurant la dette bandit*. `parse_movie_nfo` appelait `ET.fromstring` sans garde ;
  mesure par la fonction de production : 226 o → ~0 Mo, 336 o → 0,7 Mo, **391 o → 6,6 Mo**
  (×10 par niveau). Atteignable par la planification (`plan_support_replan.py:783`), et un
  `.nfo` arrive **avec le torrent** — donc écrit par le releaser.
  Le commentaire en place justifiait l'inaction par « pas un input venant d'un attaquant » :
  faux. Sa conclusion ne valait que pour **XXE**, que j'ai vérifié réellement fermé
  (`ParseError: undefined entity`). Garde précis sur `<!ENTITY`, jamais sur `<!DOCTYPE`.
  Après : 501 o → 0,01 Mo. Mutation 3/3.
- [x] **T-PROD-10 · NEUF — le comparateur de doublons archivait un Blu-ray au profit d'un DivX**
  (`fix(doublons)`). `_video_codec_rank_value` faisait `.get(codec, 0)` : `vc1`, `mpeg2video`,
  `vp9`, `prores`, `wmv3` tombaient **sous `xvid`**. Verdict mesuré sur un probe construit par
  `_build_pseudo_probe` : Blu-ray VC-1 25 Mbps 21 Go contre DivX 1,5 Mbps 1,3 Go →
  **« Garder B, archiver A »**, les deux débits affichés juste à côté. Applicable en masse par
  « Auto-décider tous ».
  Le remède **n'invente aucun rang** : il distingue « inconnu » de « pire », ce que la fonction
  faisait déjà pour un codec VIDE. Après : verdict `tie`. Témoin HEVC/XVID : inchangé.
  ⚠️ **Le saut du critère bitrate entre codecs différents n'est PAS un défaut** — il est
  délibéré et gardé par `test_different_codec_skip_bitrate`. Ne pas le « corriger ».

### Ce qui reste ouvert, et ce qu'il faut savoir avant d'y toucher

- [ ] **T-SEC-12 · `GET /api/spec` rend 80 182 octets sans jeton** — la carte des 172 endpoints,
  routes destructives comprises. Non lisible *cross-site* (aucun `Access-Control-Allow-Origin`
  émis pour une origine tierce), donc exploitable par un processus local ou en LAN sous
  `--public`. À arbitrer.
- [ ] **T-SEC-13 · Les 3 findings bandit à HAUTE confiance ne sont pas triés** : B324 SHA1
  (`plan_support_core.py:264`, correctif trivial `usedforsecurity=False`), B310 `urlopen`
  (`updater.py:220`), et les 27 B608 (SQL par construction de chaîne) probablement faux
  positifs à vérifier un par un.
- [~] **T-DOM-1 · 27 pistes** — UNE traitée le 2026-08-29 (`scene_parser`), et un constat
  préalable : **le détail des 27 n'existe nulle part sur disque.** Seul le résumé ci-dessous
  les évoque, et il n'en NOMME que six. Les autres ne sont pas vérifiables faute de source.
  ✅ **`scene_parser` — CONFIRMÉE et bien pire qu'annoncé.** Sept mots de `_NOISE_RE` sont de
  vrais titres : `Cam (2018)` et `Opus (2025)` rendaient une chaîne **VIDE**, `Internal Affairs`
  rendait `Affairs`, `Complete Unknown` rendait `Unknown`. Cause : `_NOISE_RE` (étape 3)
  s'applique PARTOUT, y compris avant l'année, et s'exécute quatre étapes AVANT le traitement
  position-aware (étape 7). `cam`, `proper` et `repack` figuraient dans les DEUX listes —
  la première les consommait, la seconde ne les voyait jamais. 6 mutants, 6 morts, dont un
  survivant qui a révélé que ma propre correction recréait la redondance.
- [ ] ~~**T-DOM-1 · 27 pistes non vérifiées**~~ issues d'un audit de `cinesort/domain/` et `web/`
  (5 lecteurs + 5 réfutateurs). **Ce sont des PISTES, pas des constats** : une seule a été
  remesurée à la main et livrée (T-PROD-10). Les autres portent sur le score qualité (plafond
  SD inatteignable, rétro-compat legacy morte, `enable_4k_light` qui allège au lieu de pénaliser,
  lossless FLAC/PCM sans bonus, un `add_reason(-4)` sans effet, un signe de facteur inversé),
  la comparaison de doublons, le parsing de titres (`scene_parser` strippe `cam` et `opus`
  inconditionnellement) et le front. **Vérifier chacune avant d'y toucher.**
  ⚠️ **Le harnais qui les a produites a menti sur son propre bilan** : il a rapporté
  « 28 confirmés, 0 réfutés » parce que le classificateur ne lisait que le PREMIER MOT du
  verdict. **17 verdicts sur 28 portent une réserve explicite** dans leur corps, dont un qui
  détruit deux affirmations d'impact. Un taux de réfutation de 0 % est en soi un signal
  d'alarme — la revue du 2026-08-26 réfutait 52 %.

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
