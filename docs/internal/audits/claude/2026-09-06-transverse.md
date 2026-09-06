# Audit Claude — 2026-09-06 — Couche transverse

**Modele** : celui impose par `--model` dans `.github/workflows/audit-module.yml`, effort
de raisonnement max. **Niveau** : modere. **Ouverture de PR** : oui.

## Budget d'ouverture

Mesure au demarrage, par `gh` :

```
gh pr list    --state open --limit 400  ->  15 PR ouvertes
gh issue list --state open --limit 400  ->  26 issues ouvertes
                                   SOMME =  41
```

Tres en dessous du plafond de 150 de `.github/audit-prompt.md`. Budget nominal :
au plus 3 PR, au plus 5 issues. **Consomme : 3 PR (deux de code, une
documentaire) et 2 issues (un finding, la synthese).**

Sur les 15 PR ouvertes, 6 sont Dependabot et 9 viennent des lots des 2-5
septembre. **Aucune ne touche `run_flow_support.py`, `run_facade.py`, `app.py`,
`test_axe_dashboard.py` ni `test_responsive_viewports.py`** — verifie par
`gh pr list --json files`, pas suppose. C'est la lecon du 2026-08-29, ou un lot
a reimplemente un correctif que la PR #1128 portait deja depuis huit jours.

## Contrainte d'execution

Comme les runs des 08-09, 08-15, 08-16 et 08-23, ce bac a sable **refuse toute
execution**. Mesure de ce run : `python3 --version` passe ; `python3 -c ...`,
`python3 <fichier>`, `pytest`, `ruff`, `node` sont refuses par la politique de
permissions. `git`, `gh`, la lecture et `grep` passent.

Consequences, ecrites pour que personne ne les deduise a tort :

- **tous les findings ci-dessous sont etablis par LECTURE.** Chaque affirmation
  porte son `fichier:ligne` ou `fichier:symbole` ;
- les `id` du fichier de findings sont des **slugs lisibles**, pas les prefixes
  `sha256(...)[:8]` du schema : je ne pouvais pas les calculer. Meme convention
  que les runs des 08-15, 08-16 et 08-23 ;
- les deux PR de code portent la mention exigee, et la seconde precise en outre
  **ce que la CI ne peut PAS attester** (les harnais qu'elle corrige sont
  skippes en CI ; seul le garde ajoute y tourne).

---

## Resume executif

Le fil du jour est le **canal** : une donnee change de route, et les
consommateurs restent sur l'ancienne. Deux des trois findings sont de cette
forme, sur deux couches sans rapport.

| # | Sev. | Persona | Finding | Suite |
|---|---|---|---|---|
| 1 | 3 BUG | RELIABILITY / UX | « ▶ Reprendre » un run apres redemarrage annonce **« Run repris. »**, ne relance rien, et **retire** la reprise : le run passe `RUNNING` sans worker, sort de `list_pending_runs` et n'est plus resumable. | **Issue #1226** |
| 2 | 2 QUALITY | RELIABILITY | `_mirror_decisions_to_sql` appelait `set_decision` en position d'instruction : ses **deux refus par retour** disparaissaient. Et `_ = DECISION_REJECTED` « forcait » sous un commentaire qui l'annoncait. | **PR #1224** |
| 3 | 2 QUALITY | UX / SECURITY | Deux harnais d'audit (a11y WCAG, captures responsive) fournissent le jeton par `?ntoken=` — canal que `app.js` **ne lit plus** depuis #1207. Ils auditent des ecrans en 401 et rendent un verdict propre. | **PR #1225** |
| 4 | 1 STYLE | ARCHITECT | Deux docstrings de `save_validation` (support **et** facade) affirment au present un cablage `upgrade_deferred_to_accepted` qui n'existe pas (AC-3 non tenu). | **PR #1224** |
| 5 | 1 STYLE | ARCHITECT | Trois commentaires d'`app.py` decrivent encore `?ntoken=` en query, et deux pointent `app.js:75-112` ou `_detectNativeBoot` n'est plus. | **PR #1225** |

Rien de severite 4. Aucun secret expose, aucune violation d'architecture, aucun
appel JS vers une methode de facade inexistante.

**Le finding 2 n'est pas neuf** : c'est `8dfa8aa5`, releve le 2026-08-22 avec une
confiance de 0,92, **jamais corrige**. Je le dis avant de le decrire — il est
ouvert en PR precisement *parce qu'il a deja ete instruit* : le re-signaler une
troisieme fois en rapport n'aurait rien produit.

---

## Les 5 points du prompt transverse

### 1) Fonctions > 100 L par ROI — SANS OBJET

Issue **#215 fermee le 2026-08-06**. Le cliquet vivant est
`tests/test_function_size_budget.py` (`MAX_LINES = 100`, allowlist `PLAFONDS`
gelee a la taille mesuree, marge zero, **et cliquet descendant** :
`test_les_plafonds_ne_sont_pas_PERIMES` exige qu'un gain soit verrouille).

Son perimetre s'est elargi le 2026-08-31 a `app.py` et `scripts/`
(`_RACINES = ("cinesort", "app.py", "scripts")`) — pas a `tests/`. **Ce point a
change la forme d'un de mes correctifs** : les commentaires d'`app.py` du
finding 5 vivent dans `main()`, dont le plafond est `514` a marge zero. La
correction est donc **neutre en nombre de lignes** (8+/8−) au lieu d'etre
redigee au plus clair. C'est le meme piege que #1207 a rencontre (« le seul
ajout du commentaire portait `main` de 525 a 535 »).

> **Correction d'un point recopie.** J'avais d'abord ecrit ici, a la suite des
> rapports des 08-09, 08-16 et 08-23, que « le prompt decrit toujours #215 comme
> ouverte ». **C'est faux depuis** : `.github/audit-prompt.md:1642` dit
> desormais « issue #215, **FERMEE le 2026-08-06**. Point sans objet sauf
> regression mesuree », et le paragraphe voisin (l. 1640) consigne meme l'erreur
> passee. La correction demandee par trois runs A ete appliquee.
>
> Je le laisse ecrit parce que le mecanisme compte plus que le fait : j'ai
> recopie l'etat d'un rapport anterieur au lieu de le mesurer, sur un prompt que
> j'avais lu integralement dix minutes plus tot. C'est la faute exacte que ce
> depot documente sous « remesurer avant de corriger un chiffre qui derange ».

### 2) Duplication desktop/dashboard — SANS OBJET

`web/dashboard/` est le seul arbre JS. Confirme pour la **cinquieme** fois.

### 3) Imports inter-couches interdits — 0 VIOLATION

```
(from|import) cinesort.(app|infra|ui)  dans cinesort/domain/  -> 2 hits, 2 faux positifs
   cinesort/domain/core.py:55       -> sous `if TYPE_CHECKING:`, deja dans ignore_imports
   cinesort/domain/_runners.py:84   -> DANS UNE DOCSTRING (celle de `tracked_run`)
(from|import) cinesort.(app|ui)     dans cinesort/infra/      -> aucun
(from|import) cinesort.ui           dans cinesort/app/        -> aucun
```

Les deux fichiers ont ete **ouverts**, pas seulement grepes. C'est la cinquieme
consigne consecutive sur `_runners.py:84` : la ligne
`from cinesort.infra.subprocess_safety import tracked_run` existe litteralement,
dans la docstring qui documente l'import que le Service Locator a remplace.

> `lint-imports` n'a PAS pu etre execute. Cette verification est une lecture des
> imports, pas un passage du contrat.

### 4) Repository pattern — 0 MIXIN SQL RESIDUEL

`_[A-Za-z]+Mixin` sur `cinesort/` rend **11 occurrences dans 8 fichiers, aucune
pertinente** : 8 docstrings de `infra/db/repositories/*.py` qui documentent la
suppression, et 3 pour `_PeerGuardMixin` (`infra/_http_utils.py`), mixin de
connexion urllib3 du garde SSRF. **Identique aux mesures des 08-16 et 08-23.**

### 5) Pattern module-style pour les modules mockes — SAIN

`tests/test_architecture_invariants.py::UiApiPatchableImportTests` couvre les
cibles `cinesort.ui.api.*`. Les couches `app` / `infra` / `domain` restent tenues
par la relecture ; je l'ai refaite sur les **55 cibles distinctes** de
`patch("cinesort.(app|infra|domain).…")` relevees dans `tests/`.

Le cas qui pouvait mordre est instructif. Trois tests patchent
`cinesort.infra.network_utils.get_local_ip` / `build_dashboard_url` — le module
**source** —, et `rest_server.py:37` importe ces deux symboles en
`from … import`, forme ou le patch ne s'appliquerait pas. Mais le consommateur
reellement exerce est `cinesort_api.py`, qui fait **`import
cinesort.infra.network_utils as _network_utils_mod`** avec le commentaire
« NB : module-style pour permettre `patch("cinesort.infra.network_utils.X")` »
(l. 25 et 1127). Le pattern est donc respecte **et sa raison est ecrite au point
d'appel** — exactement ce que le corpus appelle un index de recherche.

Le seul KO historique, `infra.log_context.normalize_log_level_setting`, n'est
plus qu'une **mention en docstring** (`test_composite_score_toggle.py:140`) :
aucun `patch()` reel ne le vise. #1022 est fermee.

**Les 5 points ne produisent plus de findings depuis quatre runs.** Cf. la
section « Tendance ».

---

## Finding 1 — [severite 3 / RELIABILITY+UX] « Reprendre » consomme la capacite qu'il annonce

> Suivi : **issue #1226**. Pas de PR : le correctif change un contrat que la
> suite de tests grave aujourd'hui comme le comportement attendu — c'est un
> arbitrage.

Ce finding vient de la piste laissee mot pour mot par le transverse du 08-23 :
*« inventorier les capacites annoncees par un ecran et chercher qui d'autre peut
les retirer. Deux candidates non instruites ce jour : la reprise d'un run
(`resume`) […] »*. La reponse est plus nette que la question : **c'est le bouton
lui-meme qui retire la capacite.**

### La chaine, maillon par maillon

| # | ou | ce qui se passe |
|---|---|---|
| 1 | `run_control_support.save_for_later` | « 💾 Enregistrer le run » pose `SAVED`. Sa docstring distingue *« une pause cafe »* d'un *« operateur reviendra plus tard »* : la promesse est de **survivre a la session** |
| 2 | — | l'utilisateur ferme l'app. `JobRunner` et `RunState` meurent |
| 3 | `views/historique.js:669` | « ↻ Reprendre ce run », rendu **inconditionnellement**, navigue vers `/traitement#run-<id>` |
| 4 | `run_flow_support.py:1009-1068` | `_get_status_impl` a une **branche DB-only** pour les runs hors memoire : elle rend `status: "SAVED"` |
| 5 | `views/traitement.js:564,638` | `isPaused` vrai ⇒ le bouton **« ▶ Reprendre »** s'affiche |
| 6 | `run_control_support._reprendre_le_run` | `mark_run_resumed` ⇒ `UPDATE runs SET status='RUNNING', paused_at=NULL` ; puis `api._get_run(run_id)` rend `None`, **donc aucun signaling** ; retour `{"ok": True, "status": "RUNNING"}` |
| 7 | `views/traitement.js:1890` | toast **« Run repris. »**, `type: "success"` |

### Ce que l'utilisateur perd

- le run **sort** de `list_pending_runs` (`WHERE status IN ('PAUSED','SAVED','AWAITING_VALIDATION')`) ;
- il n'est **plus resumable** : `RUNNING` ∉ `_RESUMABLE_DB_STATES` ;
- `paused_at` est **efface** — l'horodatage qui ordonnait cette liste ;
- l'ecran annonce « En cours », progression figee, polling perpetuel.

L'asymetrie est le cœur : `pause_run` porte le commentaire *« si le run n'est
plus en memoire (apres redemarrage app), pas de signaling — l'etat DB est
suffisant »*, et **c'est vrai pour une pause**. Pour une reprise, non :
`resume_run` est la seule des trois routes qui pretend **demarrer** quelque
chose. Chaque maillon est correct isolement ; c'est la jonction qui ment.

### Ce qui borne la gravite — mesure, pas suppose

- **aucun fichier n'est touche.** La perte porte sur une capacite. Severite 3, pas 4 ;
- **c'est recuperable** : `RUNNING` ∈ `_PAUSABLE_DB_STATES`, donc « 💾 Enregistrer
  le run » reste affiche (`isRunning`) et repasse le run en `SAVED` ;
- **aucun blocage des routes destructives.** `_refus_si_run_actif`
  (`reset_support.py:558`) itere `api._runs` **en memoire** et teste
  `rs.running` : un `RUNNING` fantome en base ne bloque ni `reset_database` ni
  `reset_all_user_data`. **J'ai verifie ce point precisement parce qu'il aurait
  fait passer le finding en severite 4.**

### Verification adversaire

1. **Deja corrige ?** Non — les sept maillons sont lus sur `main` a `3fca5ff`.
2. **La garde existe ailleurs ?** Non, et c'est le plus notable :
   `test_phase4_traitement_endpoints.py::test_resume_run_brings_back_to_running`
   exerce **exactement** ce scenario — son `_StubApi._get_run` rend **toujours
   `None`** (l. 265-266) — et **assert que c'est un succes**. Le comportement
   n'est pas un oubli : il est **grave comme attendu**.
3. **Chemin inatteignable ?** Non : branche DB-only explicite, bouton
   inconditionnel.

Et le corpus ne l'avait jamais frole : `grep -rn "resume_run\|mark_run_resumed"
docs/internal/audits/` rend **zero** occurrence.

### Une extension que j'ai cru tenir, et qui tombe

`accueil.js:154` rend « ▶ Reprendre la validation » vers la meme URL. Mais son
`showResume` vaut `status === "AWAITING_VALIDATION"` (l. 139), etat que
`_RESUMABLE_DB_STATES` **exclut deliberement** (fix H13, commentaire a l'appui)
et pour lequel `isPaused` est faux : aucun bouton « ▶ Reprendre » ne s'affiche.
**L'accueil ne mene donc pas au defaut** — seul l'Historique y mene.

---

## Finding 2 — [severite 2 / RELIABILITY] Le miroir SQL des decisions avalait ses refus

> Suivi : **PR #1224**. Finding `8dfa8aa5` du **2026-08-22**, verifie present ce
> jour et jamais corrige.

`DecisionsRepository.set_decision` signale ses **deux** refus **par retour**, pas
par exception (`repositories/decisions.py:143-152`) : `film_id` vide, et
`decision` hors des trois valeurs. `_mirror_decisions_to_sql` l'appelait **en
position d'instruction** : les deux disparaissaient sans trace, et la ligne
n'atteignait jamais `film_decisions_v2`.

Empile dessus, le repli du `except` :

```python
# On force malgre tout decision=DECISION_REJECTED pour eviter
# le silence complet (ce code branch est defensif).
_ = DECISION_REJECTED
```

Affectation morte sous un commentaire qui annonce l'inverse : elle ne force rien,
et le silence etait complet.

**Ce qui n'est pas touche, et pourquoi.** Le miroir reste best-effort *par
conception* — `validation.json` demeure la source primaire, la shape de retour
est preservee (AC-2, backward compat absolue). Le correctif **lit** le retour et
journalise ; il ne fait pas echouer `save_validation`.

Cliquets consultes **avant** d'ecrire, et c'est ce qui a valide le geste :
`test_lazy_imports_bounded` compte les **nœuds** `ImportFrom`
(`_LazyImportCounter.visit_ImportFrom`), pas les alias — retirer un symbole de
l'import tardif laisse donc le compte par couche inchange. Et les six `MagicMock`
de `test_save_validation_backward_compat.py` rendent tous `{"ok": True}` ; le
seul `side_effect` est une `sqlite3.OperationalError` que l'`except` existant
rattrape deja.

---

## Finding 3 — [severite 2 / UX+SECURITY] Deux audits fournissent le jeton par un canal mort

> Suivi : **PR #1225**.

Le 2026-08-31, #1207 a deplace le jeton de boot de la **query** vers le
**fragment**, et `app.js` a cesse de lire la query **du tout**. **Deux harnais
n'ont pas suivi** :

```
tests/test_axe_dashboard.py:49                  audit a11y WCAG 2.2, 6 routes
tests/visual/test_responsive_viewports.py:69    captures + debordements, 10 viewports
```

Tous deux appellent encore `page.goto(f"{DASHBOARD_URL}?ntoken={self.token}&native=1")`.

**Pourquoi rien ne l'a signale**, et c'est le cœur :

1. `requireAuth()` (`core/router.js:286-289`) rend **`true`** en loopback via
   `_isNativeMode` (hostname `127.0.0.1`). Les vues se rendent donc — mais
   **sans Bearer**, donc peuplees d'erreurs 401 ;
2. les deux harnais sont `skipUnless(CINESORT_API_TOKEN)`, donc **skippes en
   CI**. La rupture n'etait visible que par un humain lisant un rapport faux.

Consequence propre aux captures : sur des ecrans vides, `scrollWidth` ne depasse
jamais `clientWidth`. **La detection de debordement ne pouvait plus rien
trouver** — dix viewports rendant un vert sans avoir rien observe.

C'est la classe de defaut que `test_axe_dashboard.py` documente **deja avoir
payee**, quinze lignes plus haut : la route `/validation`, jamais enregistree,
« auditait donc une page vide, sans que rien ne le signale ». Un garde avait ete
pose pour les **routes** (`test_axe_routes_existent.py`), aucun pour
l'**authentification**.

**Le canal retenu n'est pas le fragment**, et le choix est documente ailleurs :
`tests/e2e_dashboard/conftest.py:402-407` explique, mesure a l'appui, qu'avec
`ntoken` dans l'URL `app.js` appelle `setToken()` **puis** purge par
`history.replaceState`, ce qui decale le demarrage et fait tomber deux tests de
minuterie. La forme vivante est `sessionStorage` via `add_init_script` — et
`sessionStorage`, pas `localStorage`, parce que `getToken()` le lit en priorite.

**Le garde ajoute inspecte l'AST**, pas les lignes : un garde ligne-par-ligne
mordrait les docstrings qui *decrivent* le defaut, dont les deux miennes. Lecon
explicite de #1207. Il porte trois contre-epreuves (il voit au moins un `.goto` ;
il attrape la forme fautive ; il laisse passer le fragment) — sans quoi une
regression de l'extracteur rendrait « zero coupable », le pire des verts.

---

## Findings 4 et 5 — [severite 1] Deux documentations restees sur l'ancien monde

**4.** `save_validation`, dans le support **et** dans la facade, affirme au
present : *« la transition `deferred -> accepted` consulte les locks via
`DecisionsRepository.upgrade_deferred_to_accepted` (AC-3) »*. Le miroir passe en
realite par `set_decision`, qui ne consulte aucun lock.

**Ce que j'ai failli signaler a tort, et qui a ete ecarte** : la methode
`upgrade_deferred_to_accepted` (118 L, inscrite au cliquet de taille) n'a
**aucun appelant de production**. J'allais l'ouvrir en « code mort » — **sa
propre docstring le consigne deja**, explicitement : « la methode n'a
aujourd'hui aucun appelant de production (grep : docstrings + tests) », avec la
limite TOCTOU qu'un futur cablage devra traiter. C'est le piege « chercher le
garde avant d'en ecrire un », dans sa variante la plus economique : le garde
etait *dans le code lui-meme*. Seules les **deux docstrings consommatrices**
sont fautives, parce qu'elles, elles affirment le contraire.

Aucune tentative de cabler AC-3 : ce serait un changement de comportement sur un
chemin qui touche aux decisions de l'utilisateur.

**5.** Trois commentaires d'`app.py` decrivent encore `?ntoken=` en query, et
deux pointent `app.js:75-112` ou `_detectNativeBoot` n'est plus. Meme motif que
le `print` corrige par #1207 : « un message qui decrit une URL que le code ne
construit plus envoie chercher le defaut au mauvais endroit ».

---

## Verifications negatives — ne pas les re-instruire

Chacune a coute du temps ce jour ; les consigner evite de le repayer.

- **Le motif « `_state` apres `await` » de #1195 est SATURE.** Le lot du 08-31 a
  corrige deux modales ; j'ai verifie les deux autres modules qui posent
  `_state = null` (`views/doublons.js`, `views/bibliotheque.js`). Les deux sont
  **exemplaires** : `if (!_state) return;` apres chaque `await`, `if (_state)`
  dans les `catch`/`finally`, gardes documentees par des audits de mai 2026
  (DUP-1, 2026-05-24, 2026-05-30). Rien a ajouter.
- **`tests/e2e/conftest.py` et `tests/e2e_dashboard/conftest.py` sont sains** sur
  le sujet du finding 3 : le premier s'authentifie par le **formulaire de login**
  (`page.fill("#loginToken", token)`), le second par **`sessionStorage`**. Seuls
  les deux harnais nommes utilisaient la query.
- **`test_unified_ui_contracts.py:38`** (`assertIn("ntoken=", app_py)`) reste
  vert apres #1207 parce que `#ntoken=` contient `ntoken=`. Son **commentaire**
  parle encore de query string, mais l'assertion ne ment pas : elle n'a jamais
  porte sur le canal. Laisse tel quel.
- **Le `RUNNING` fantome du finding 1 ne bloque aucune route destructive** :
  `_refus_si_run_actif` lit la memoire, pas la base. Verifie explicitement.
- **`accueil.js` ne mene pas au finding 1** : son `showResume` est reserve a
  `AWAITING_VALIDATION`.
- **`upgrade_deferred_to_accepted` sans appelant** : deja consigne dans sa propre
  docstring (issue #768). Pas un finding.

---

## Statistiques

- Zones auditees : `cinesort/ui/api` (dont `run_control_support`,
  `run_flow_support`, `reset_support`, les 6 facades), `cinesort/infra/db/repositories`
  (les 13 modules, inventaire des methodes publiques et de leurs appelants),
  `web/dashboard` (`app.js`, `core/router.js`, `views/{traitement,historique,accueil,doublons,bibliotheque}.js`),
  `app.py`, et `tests/` (contrats, cliquets, harnais Playwright).
- Techniques de l'etape 2.5 employees : **(B)** field usage tracing (sur le jeton
  de boot, et sur les methodes de repository) ; **(C)** user journey matrix sur
  `pause → fermeture → reprise` ; **(G)** methodes de facade atteignables.
- Findings retenus : **5** (1 de severite 3, 2 de severite 2, 2 de severite 1).
- **Self-critique — 6 findings supprimes avant redaction :**
  - **2 deja gardes** : `upgrade_deferred_to_accepted` sans appelant (sa propre
    docstring le dit) et le motif `_state` apres `await` dans les deux vues
    (gardes depuis mai 2026) ;
  - **1 imagine** : j'ai d'abord ecrit que les harnais du finding 3 atterrissaient
    sur `/login`. **Faux** — `requireAuth()` rend `true` en loopback. Les vues se
    rendent, mais en 401. La conclusion tient, la description aurait ete fausse ;
  - **1 chemin inatteignable** : l'extension du finding 1 a l'ecran d'accueil ;
  - **1 sans consequence** : le `RUNNING` fantome bloquant les resets (il ne les
    bloque pas) ;
  - **1 idiomatique** : `test_unified_ui_contracts.py:38`, dont seul le
    commentaire est perime.
- PR ouvertes : **3** — #1224 (code), #1225 (code + garde), celle-ci (documentaire).
- Issues ouvertes : **2** — #1226 (finding 1) et la synthese du jour.
- Findings deja connus, non re-signales : lazy imports intra-`ui/api` (**#779**),
  methodes de facade sans appelant JS (`TRI_ROUTES_ORPHELINES.md`), les six
  bascules de notifications et les quatre de nettoyage (transverse du 08-23,
  toutes deux inscrites comme dette dans `tests/test_contract_settings.py`).

## Tendance

Compare au 2026-08-23 (dernier transverse) : les 5 points du prompt restent
propres, pour la **cinquieme** fois consecutive. Ils ne produisent plus de
findings depuis quatre runs — mais le point 1 a change de nature : son cliquet
**contraint desormais la forme des correctifs** (cf. les 8+/8− d'`app.py`), ce
qui en fait un outil actif plutot qu'une verification passive.

Le 08-16 avait deplace la cible sur « qui est proprietaire d'un reglage » ; le
08-23 sur « qui est proprietaire d'une CAPACITE ». Ce run la deplace d'un cran
encore : **quand une donnee change de canal, qui reste sur l'ancien ?** Les
findings 3 et 5 sont exactement cela pour le jeton de boot ; le finding 1 en est
la variante temporelle — la capacite « reprendre » traverse une frontiere de
session, et le code ne sait pas qu'il l'a franchie.

Cette methode a un rendement mesurable : elle se lance depuis un `git log` des
commits recents, et elle a produit **3 des 5 findings** en partant de #1207 et
#1195 — sans lire une seule fois un module « au hasard ».

**Piste pour le prochain transverse**, dans la meme veine, et non instruite ici :
le message de #1207 nomme lui-meme ce qu'il n'a pas prouve — *« les quatre
artefacts WebView2 qui portaient le jeton (`History`, `Top Sites`, `Favicons`,
`Local Storage/leveldb`) relevent du NAVIGATEUR, pas du protocole : un navigateur
stocke l'URL complete, fragment compris. […] Ce lot ferme la fuite SERVEUR avec
certitude ; la fuite CLIENT reste a mesurer. »* C'est un blocage **materiel**, pas
analytique : il faut demarrer l'application de bureau sous Windows et rebalayer
`%LOCALAPPDATA%` par la VALEUR du jeton, sans perimetre choisi (la premiere sonde
de 2026-08-26 avait rendu **0** pour avoir exclu les dossiers `cache`). Le
re-auditer par lecture ne produira rien — comme `a19mi002`, qui attend une sortie
MediaInfo reelle depuis le 2026-08-19.

Seconde piste, plus accessible : la sonde « ecrit / jamais lu » **sur les
repositories**, que le run du 09-05 signalait comme non encore passee. Je l'ai
amorcee (inventaire des methodes publiques des 13 modules et de leurs appelants)
et elle n'a rendu qu'un seul cas — `upgrade_deferred_to_accepted`, deja consigne.
Le rendement de cet angle est donc **plus faible qu'annonce** : les repositories
sont, eux, bien cables. C'est une information utile en soi, et elle epargne une
passe complete au prochain run.
