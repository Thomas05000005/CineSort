# Audit Claude — 2026-08-23 — Couche transverse

**Modele** : celui impose par `--model` dans `.github/workflows/audit-module.yml`, effort
de raisonnement max. **Niveau** : modere. **Ouverture de PR** : oui.

## Budget d'ouverture

Mesure au demarrage, par `gh` :

```
gh pr list    --state open --limit 400  ->  10 PR ouvertes
gh issue list --state open --limit 400  ->  14 issues ouvertes
                                   SOMME =  24
```

Tres en dessous du plafond de 150 de `.github/audit-prompt.md`. Budget nominal :
au plus 3 PR, au plus 5 issues. **Consomme : 2 PR (une de code, une documentaire)
et 1 issue de synthese.**

> Le repere du prompt (110 PR + 195 issues au 2026-08-03) reste **perime**. Il se
> remesure, il ne se recopie pas.

## Contrainte d'execution

Comme les runs des 2026-08-09, 08-15 et 08-16, ce bac a sable **refuse toute
execution**. Mesure de ce run : `python3 --version` passe ; `python3 <fichier>`,
`python3 -m ast`, `pytest`, `ruff`, `node` sont tous refuses par la politique de
permissions. `git`, `gh`, la lecture et `grep` passent.

Consequences, ecrites pour que personne ne les deduise a tort :

- **tous les findings ci-dessous sont etablis par LECTURE**, pas par execution.
  Chaque affirmation porte son `fichier:symbole` ;
- les `id` du fichier de findings sont des **slugs lisibles**, pas les prefixes
  `sha256(...)[:8]` du schema : je ne pouvais pas les calculer. Meme convention
  que les runs des 08-15 et 08-16 ;
- la PR de code ouverte ce jour porte la mention exigee (« correctif non verifie
  localement, verification deleguee a la CI »).

Note utile pour la suite : `Node` etant refuse ici mais present en CI, le harnais
`tests/_jsexec.py` reste **ecrivable** depuis ce runner — c'est ce qui a permis
d'ouvrir une PR de code malgre la contrainte, en calquant les doublures sur un
test deja vert.

---

## Resume executif

Le finding du jour est un **quatrieme cote du triangle** « ce que l'application
annonce n'est pas ce qu'elle fait », et il porte sur la seule chose que
l'utilisateur ne peut pas refaire a la main : **revenir en arriere**.

| # | Severite | Persona | Finding | Suite |
|---|---|---|---|---|
| 1 | 3 BUG | UX / RELIABILITY | « Supprimer ce run » detruit le journal d'undo, sous une modale qui annonce « **Aucune modification sur les fichiers vidéo du disque** ». Le bouton « ↺ Annuler l'apply » est rendu **juste au-dessus**, pour le meme run. | **PR #1136** |
| 2 | 2 QUALITY | UX | Le **centre de notifications** — seul canal qui survit a la fermeture d'un ecran — n'est garde par **aucun** des 6 reglages de la section « Notifications ». Ils ne gardent que le toast Windows. | Issue |
| 3 | 3 BUG | UX | Section « Nettoyage » : 4 bascules cote a cote, **2 mortes** aux libelles quasi-synonymes des 2 vivantes. Le sens dangereux (« decocher ne protege pas ») n'est ecrit nulle part. | Issue (arbitrage) |
| 4 | 1 STYLE | ARCHITECT | Le repli pywebview de `_v5_helpers.js` est **mort par construction** : il cherche un attribut Python nomme `"facade/methode"`. | Rapport |

Rien de severite 4. Aucun secret expose, aucune violation d'architecture, aucun
appel JS vers un endpoint inexistant.

**Les findings 2 et 3 sont deja inscrits comme dette**, et je le dis avant de les
decrire : c'est le piege « chercher le garde avant d'en ecrire un », dans sa
variante la plus couteuse — publier « aucun test ne voit ca » sans avoir cherche.
Ce qui est neuf, dans les deux cas, est **le sens de la consequence**, pas le
constat statique.

---

## Les 5 points du prompt transverse

### 1) Fonctions > 100 L par ROI — SANS OBJET

Issue **#215 fermee le 2026-08-06**. Le prompt la decrit encore comme ouverte
(correction demandee par les rapports des 08-09 et 08-16, **toujours pas
appliquee** au prompt). Le cliquet vivant est `tests/test_function_size_budget.py`.

### 2) Duplication desktop/dashboard — SANS OBJET

`web/dashboard/` est le seul arbre JS. Confirme pour la quatrieme fois.

### 3) Imports inter-couches interdits — 0 VIOLATION

```
(from|import) cinesort.(app|infra|ui)  dans cinesort/domain/  -> 2 hits, 2 faux positifs
   cinesort/domain/core.py:55       -> sous `if TYPE_CHECKING:`, deja dans ignore_imports
   cinesort/domain/_runners.py:84   -> DANS UNE DOCSTRING (celle de `tracked_run`)
(from|import) cinesort.(app|ui)     dans cinesort/infra/      -> aucun
(from|import) cinesort.ui           dans cinesort/app/        -> aucun
```

Les deux fichiers ont ete **ouverts**, pas seulement grepes. C'est la quatrieme
consigne consecutive sur `_runners.py:84` : la ligne
`from cinesort.infra.subprocess_safety import tracked_run` existe litteralement,
dans la docstring qui documente l'import que le Service Locator a remplace.

> `lint-imports` n'a PAS pu etre execute. Cette verification est une lecture des
> imports, pas un passage du contrat.

### 4) Repository pattern — 0 MIXIN SQL RESIDUEL

`_[A-Za-z]+Mixin` sur `cinesort/` rend **11 occurrences dans 8 fichiers, aucune
pertinente** : 8 docstrings de `infra/db/repositories/*.py` qui documentent la
suppression, et 3 pour `_PeerGuardMixin` (`infra/_http_utils.py`), un mixin de
connexion urllib3 pour le garde SSRF. Identique a la mesure du 08-16.

### 5) Pattern module-style pour les modules mockes — GARDE PARTIEL, INCHANGE

`tests/test_architecture_invariants.py::UiApiPatchableImportTests` couvre les
cibles `cinesort.ui.api.*`. Les couches `app`/`infra`/`domain` restent tenues par
la relecture — verifiees saines le 08-16, aucune cible nouvelle depuis (le seul
KO connu, `infra.log_context.normalize_log_level_setting`, est deja dans #1022).

---

## Finding 1 — [severite 3 / UX+RELIABILITY] Supprimer un run detruit son undo, et la modale annonce l'inverse

C'est la valeur de ce run. Le mecanisme est un enchainement de quatre faits,
chacun correct isolement.

### Fait 1 — les deux boutons sont voisins, et un seul est conditionnel

`web/dashboard/views/historique.js`, section « Actions » de l'inspecteur :

```js
${isApply && status !== "UNDONE" ? `<button ... data-historique-action="undo-apply" ...>↺ Annuler l'apply</button>` : ...}
<button ... data-historique-action="delete-run" ...>🗑 Supprimer ce run</button>
```

`isApply` et `status` sont calcules **trois lignes plus haut**. Le bouton de
suppression, lui, ne les consulte pas : il est rendu **inconditionnellement**.

### Fait 2 — ce que la modale annonce

```js
consequence:
  "Le run + son plan + son log seront supprimés définitivement. " +
  "Aucune modification sur les fichiers vidéo du disque. Action NON réversible.",
```

### Fait 3 — ce que la suppression fait reellement

| Etape | Fichier | Effet |
|---|---|---|
| `delete-run` | `historique.js` | `apiPost("run/delete_run", { run_id })` |
| `delete_run` | `ui/api/history_support.py` | **aucune garde** : ni `dry_run`, ni verification qu'un undo est disponible. La docstring delegue explicitement : « Le frontend a deja affiche une modale de confirmation » |
| `delete_run` | `infra/db/repositories/run.py` | `DELETE FROM apply_batches WHERE run_id=?` — donc `apply_operations` par CASCADE — puis `DELETE FROM runs` |

### Fait 4 — l'undo devient impossible, deux fois

`apply_support.build_undo_preview_payload` :

1. `api._find_run_row(run_id)` — la ligne `runs` a disparu → « Run introuvable » ;
2. `store.apply.get_last_reversible_apply_batch(run_id)` — le batch a disparu.

La phrase « Aucune modification sur les fichiers vidéo du disque » est donc
**litteralement vraie et pratiquement trompeuse** : elle rassure exactement la ou
la perte a lieu. Ce qui est detruit n'est pas le contenu, c'est **la seule chose
qui permettait de revenir en arriere sur ce contenu**.

### Ce qui borne la gravite, et qu'il faut dire

- L'undo reel est de toute facon refuse au-dela de `UNDO_DEADLINE_SECONDS`
  (24 h, `domain/run_models.py`). La fenetre de perte est donc les **24 h qui
  suivent l'apply** — mais c'est precisement la fenetre pendant laquelle l'ecran
  **affiche** « ↺ Annuler l'apply ».
- **Aucun fichier video n'est detruit ni deplace.** La perte porte sur la
  REVERSIBILITE. D'ou severite 3, et non 4 comme #1066.

### Verification adversaire — pourquoi ce finding pourrait etre faux

Les trois formes du prompt, cherchees dans le code et dans le corpus :

1. **Deja corrige ?** Non — les quatre faits sont lus sur `main` (commit `2b07c04`).
2. **La garde existe ailleurs ?** Non, et c'est le point le plus verifie :
   - backend : `history_support.delete_run` n'a aucune verification d'undo ;
   - front : le bouton est inconditionnel ;
   - tests : `tests/test_phase5_historique_complete.py` et
     `test_phase3_4_historique.py` couvrent `delete-run`, mais uniquement le
     **cablage** (`assertIn('apiPost("run/delete_run"', js)`). Aucun ne regarde ce
     qui est annonce a l'utilisateur.
3. **Chemin inatteignable ?** Non : bouton rendu dans l'inspecteur de l'ecran
   Historique, pour tout run selectionne.

**Et pourquoi le corpus ne l'a pas deja dit.** Deux passages l'ont frole :

- le finding `9b2f60d4` (2026-08-09) **nomme la cascade** — « `delete_run` cascade
  sur `apply_batches`, donc sur `apply_operations` par FK CASCADE — le journal
  d'undo » — mais pour justifier la gravite de `cleanup_old_runs`, et il ecarte
  `delete_run` d'une ligne : « exige un run_id » ;
- la PR **#1003** (issue **#997**) l'ecarte pour le meme motif, avec un tableau
  explicite : « `run.delete_run` — erreur (run_id requis) → rien a faire ».

Les deux avaient raison **pour leur critere** : ils cherchaient les routes qui
agissent sur un POST au corps VIDE, c'est-a-dire la surface REST. `delete_run`
n'en fait pas partie. **Personne n'a examine la chaine UI** — l'utilisateur qui
clique deliberement, avec une modale qui lui dit qu'il ne risque rien.

### Remede applique, et celui qui ne l'est pas

**Applique (PR #1136)** : la modale dit la consequence. Le texte, seulement —
aucun bouton masque, aucune route refusee, aucun comportement modifie.

**Non applique, et c'est delibere** : refuser la suppression tant qu'un undo est
disponible (ou masquer le bouton) serait fail-closed et defendable. C'est un
**arbitrage produit** : il retire une capacite a l'utilisateur pour le proteger,
et le prompt d'audit interdit d'ouvrir une PR qui en depend.

Un troisieme remede est a **ecarter** : conditionner le texte a l'annulabilite.
Le handler ne dispose que du `run_id` ; retrouver le run imposerait une lecture
de `_runs` dans un chemin qui n'en a pas besoin, pour un gain nul — la phrase
inconditionnelle reste vraie pour un run sans apply, seulement sans objet.

---

## Finding 2 — [severite 2 / UX] Le canal qui atteint l'utilisateur n'est garde par aucun reglage

### Le constat statique est DEJA INSCRIT — je le dis avant de decrire

`tests/test_contract_settings.py`, liste `KNOWN_UNWIRED` :

```python
"notifications_enabled": "WRITE_ONLY - R8-069 : le gate desktop lit
                          desktop_notifications_enabled, ce toggle n'a plus aucun lecteur",
```

Et `docs/internal/verif_totale_2026_07/PHASE5_ARBITRAGES.md` le classe en
arbitrage en attente. Ecrire « aucun test ne voit ca » serait ici la faute exacte
de #1061.

### Ce qui est neuf : le sens de la consequence

L'ecran expose **six** bascules dans « Notifications desktop »
(`parametres.js`) :

| Bascule | Ce qu'elle garde REELLEMENT |
|---|---|
| `desktop_notifications_enabled` | le toast Windows (`show_balloon`) |
| `notifications_enabled` — « Activer les notifications **applicatives** » | **rien** |
| `notifications_scan_done`, `_apply_done`, `_undo_done`, `_errors` | le toast Windows uniquement |

Or `NotifyService.notify` (`cinesort/app/notify_service.py`) appelle le miroir
vers le centre de notifications **AVANT** le gate :

```python
hook = self._center_hook
if hook is not None:
    hook(event_type, title, body, level)   # <- inconditionnel

if not self._is_event_enabled(event_type):
    return
```

`self._center_hook` est pose **inconditionnellement** dans le constructeur de
`CineSortApi`, et `notifications_support.add_notification` n'a **aucune garde** :
elle ecrit directement dans le store.

Consequence : **toute** notification atteint le centre, quels que soient les six
reglages. Dix sites de production y aboutissent (apply, scan, watcher, erreurs
d'API, reconciliation de moves).

Le `/CLAUDE.md` dit lui-meme : « Le canal qui atteint reellement l'utilisateur est
le CENTRE DE NOTIFICATIONS, seul a survivre a la fermeture de l'ecran d'apply. »
**C'est donc le seul canal qui compte qui n'est garde par rien**, pendant que la
bascule dont le libelle le designe (« applicatives ») ne fait rien.

### Le piege du remede, mesure avant d'etre propose

Cabler naivement `notifications_enabled` sur le hook du centre **serait
nuisible** : son defaut est `False` (`_LITERAL_DEFAULTS`). Tous les utilisateurs
existants perdraient le centre de notifications du jour au lendemain, sans avoir
rien change.

C'est pourquoi ce finding part en issue et non en PR. Trois voies possibles, dont
deux impliquent un arbitrage :

1. **retirer la bascule morte** de l'ecran (elle ment) — le moins risque ;
2. **la cabler avec un defaut inverse** (`True`) — change la semantique d'une cle
   persistee, donc migration ;
3. **la cabler telle quelle** — a ecarter, cf. ci-dessus.

---

## Finding 3 — [severite 3 / UX] Quatre bascules de nettoyage, deux mortes, libelles quasi-synonymes

### Deja connu, et je le dis d'abord

R8-063 / F-PROM-02 : `docs/internal/baseline_r8/BASELINE_R8.md`, avec une capture
dediee (`captures/cap_phantom_config.py`), et **classe en arbitrage en attente**
dans `PHASE5_ARBITRAGES.md` et `PLAN_VERIF_TOTALE.md` (« Arbitrages Thomas
(bloques sans lui) : cleanup_orphans, ... cleanup_empty_folders »).

### Ce qui est neuf : le VOISINAGE, et le sens dangereux

Les quatre bascules sont dans **la meme section** « Nettoyage » de l'ecran
Bibliotheque (`parametres.js`), l'une sous l'autre :

| Ordre | Cle | Libelle | Etat |
|---|---|---|---|
| 1 | `cleanup_orphans` | « Nettoyer les fichiers orphelins **(sous-titres, .nfo, images)** » | **MORTE** |
| 2 | `cleanup_empty_folders` | « Supprimer les dossiers vides après apply » | **MORTE** |
| 3 | `move_empty_folders_enabled` | « Déplacer les dossiers vides vers _Vide » | vivante |
| 4 | `cleanup_residual_folders_enabled` | « Nettoyer fichiers résiduels **(.nfo, images, sous-titres)** » | vivante |

Les paires (1,4) et (2,3) sont des quasi-synonymes — **la meme parenthese, dans
un ordre different**. Vivantes : `build_cfg_from_settings` → `Config` →
`app/cleanup.py` et `app/apply_core.py`. Mortes : persistance seule
(`_save_section_advanced`), **zero lecteur** dans tout `cinesort/`.

La baseline decrit le sens « cocher ne supprime rien ». **Le sens inverse n'est
ecrit nulle part, et c'est le dangereux** : l'utilisateur qui veut ARRETER un
nettoyage decoche la bascule 1 ou 2, croit avoir coupe la fonction, et l'apply
continue de deplacer des fichiers via 3 et 4.

Pas de PR : l'arbitrage (retirer les deux mortes, ou les cabler) appartient au
proprietaire, et il est deja formule depuis juillet.

---

## Finding 4 — [severite 1 / ARCHITECT] Le repli pywebview de `_v5_helpers.js` est mort par construction

```js
// web/dashboard/views/_v5_helpers.js
if (typeof window !== "undefined" && window.pywebview?.api?.[method]) {
  const args = _kwargsToPositional(method, params);
  const res = await window.pywebview.api[method](...args);
```

`method` est la route au format `"facade/methode"` — `core/api.js` en fait
`` `${baseUrl()}/api/${method}` ``. Le repli cherche donc un attribut Python nomme
`"settings/save_settings"` : **aucun attribut Python ne peut porter un `/`**. La
condition est toujours fausse.

Second defaut empile, que le code admet lui-meme (« Ce helper est imparfait ») :
`_kwargsToPositional` fait `Object.values(params)`, dont l'ordre ne correspond a
aucune signature.

**Portee reelle** : un seul consommateur, `views/processing.js`. Et le chemin ne
se prend qu'en cas d'indisponibilite du REST local, qui est demarre en mode
desktop. C'est du **code mort trompeur** (il promet une resilience qu'il n'a
pas), pas un defaut atteignable — d'ou la severite 1 et l'absence d'issue.

---

## Piege d'outillage mesure ce jour — le titre de PR et le guillemet francais

La PR #1136 a d'abord ete ouverte sous le titre :

```
fix(ui): « Supprimer ce run » detruisait le journal d'undo en annoncant l'inverse
```

`Validate PR title` **a echoue**. La cause n'est ni le type ni la portee : le
`subjectPattern` de `.github/workflows/pr-title-lint.yml` vaut

```
^[A-Za-z0-9_À-ɏ].+$
```

Le sujet doit donc commencer par une lettre ou un chiffre. Le guillemet ouvrant
francais est **U+00AB**, en dessous de la plage `À-ɏ` ouverte pour les
accents : un titre qui commence par « ... » est recale.

**Mesure, pas deduction** : titre d'origine → `FAILURE` ; titre reecrit pour
commencer par une lettre → `SUCCESS`, sans autre changement.

Cela compte pour ce bot en particulier : il ecrit ses titres en francais et cite
volontiers l'ecran entre guillemets. Le check **ne bloque pas** la fusion (il ne
fait pas partie des 7 requis), mais le titre devient le message de commit au
squash et alimente Release Drafter — un titre recale y perd sa categorie.

Le commentaire en tete du workflow affirme d'ailleurs l'inverse (« Si non
conforme : la PR ne peut pas etre mergee (status check fail) ») ; c'est la meme
divergence entre la promesse et la protection de branche que le `/CLAUDE.md`
consigne deja.

## Verifications negatives — ne pas les re-instruire

Chacune a coute du temps ce jour ; les consigner evite de le repayer.

- **`_appliquer_les_sections` ne contredit pas `to_save = dict(existing_settings)`.**
  Sa docstring (« une cle que AUCUNE section ne reclame [...] disparait en
  silence ») parait contredire le merge read-modify-write. Elle parle de la valeur
  **ENTRANTE** : ce que le client POSTe sans section est ignore, l'existant est
  preserve. Docstring exacte, pas perimee.
- **Timeouts HTTP** : les 9 sites d'appel des clients TMDb / OMDb / Jellyfin /
  Plex / Radarr / Ollama passent tous `timeout=self.timeout_s`, y compris les
  quatre en appel multi-ligne. Aucun appel nu.
- **Routes REST fantomes par heritage** : `_BaseFacade` n'expose que `_api`
  (prive). Le dispatcher decouvre par `dir(facade)` en sautant les `_*` : aucune
  route ne nait de la classe de base.
- **`open_path`** : bien present en methode PUBLIQUE
  (`cinesort_api.py`), et volontairement dans `_EXCLUDED_METHODS` du REST parce
  qu'elle passe par le pont pywebview. Quatrieme audit a le confirmer.
- **Noms de parametres JS ↔ signatures de facade** : **deja garde**, et
  strictement — `tests/test_contract_ui_api.py` croise chaque cle de payload avec
  `inspect.signature` (« dispatch `method(**params)` ⇒ cle inconnue ⇒ TypeError ⇒
  400 »), et sa liste `KNOWN_BROKEN` est **VIDE**. J'allais ecrire cet audit a la
  main : le garde existait.
- **Migration jamais jouee (#983)** : gardee par
  `tests/test_aucune_migration_invisible_983.py`.
- **`purge_terminal_runs_locked(max_keep=...)`** : `max(1, int(max_keep or 1))`
  ressemble au motif de #1133 (`0` avale par un `or`), mais `max_keep` est une
  constante interne (50 runs EN MEMOIRE), pas un reglage utilisateur, et rien
  n'est supprime sur disque.
- **`cleanup_old_runs` pendant un run actif** : supprime par ANCIENNETE
  (`list_runs_older_than`), le run en cours n'est jamais dans la population.

---

## Statistiques

- Zones auditees : `cinesort/domain`, `cinesort/infra` (dont `rest_server`,
  clients HTTP, `db/repositories`), `cinesort/app`, `cinesort/ui/api` (+ les 6
  facades), `web/dashboard` (core, views, components), `tests/` (contrats,
  cliquets, baselines) et `docs/internal/` (baselines R8, arbitrages Phase 5).
- Techniques de l'etape 2.5 employees : **(A)** endpoint inventory diffing
  (litteral + dynamique) ; **(B)** field usage tracing sur les 6 cles de
  notifications et les 4 de nettoyage ; **(C)** user journey matrix sur
  apply → undo → suppression du run ; **(E)** notification coverage matrix.
- Findings retenus : **4** (2 de severite 3, 1 de severite 2, 1 de severite 1).
- Self-critique — **7 findings supprimes avant redaction** :
  - **2 deja gardes** : l'audit des noms de parametres JS↔facades
    (`test_contract_ui_api.py`, `KNOWN_BROKEN` vide) et les migrations invisibles
    (`test_aucune_migration_invisible_983.py`) ;
  - **2 imagines** : la docstring d'`_appliquer_les_sections` « perimee » (elle ne
    l'est pas) et les routes REST fantomes par `_BaseFacade` (aucune) ;
  - **1 idiomatique** : `max_keep or 1` lu comme une instance de #1133 ;
  - **1 chemin inatteignable** : `cleanup_old_runs` concurrent d'un run actif ;
  - **1 sans consequence** : les timeouts HTTP, tous presents.
- PR ouvertes : **2** — #1136 (code) et celle-ci (documentaire).
- Issues ouvertes : **1** (synthese du jour).
- Findings deja connus, non re-signales : troncature a 120 groupes (**#1127**,
  enrichi le 08-21), lazy imports intra-`ui/api` (**#779**), methodes de facade
  sans appelant JS (`TRI_ROUTES_ORPHELINES.md`).

## Tendance

Compare au 2026-08-16 (dernier transverse) : les 5 points du prompt restent
propres, pour la quatrieme fois consecutive. **Ils ne produisent plus de
findings** — trois runs de suite les ont trouves sains. Le rendement de l'audit
transverse est desormais ailleurs, et ce run le confirme : dans les **chaines
completes**, ou chaque maillon est correct et ou c'est la jonction qui ment.

Le 08-16 avait deplace la cible sur « qui est proprietaire d'un reglage ». Ce run
la deplace d'un cran de plus : **qui est proprietaire d'une CAPACITE**. L'undo
n'appartient a aucun ecran — il est promis par l'inspecteur de l'Historique et
detruit par le bouton d'a cote ; les notifications n'appartiennent a aucun
reglage — six bascules gardent un canal secondaire et laissent le principal
ouvert. Dans les deux cas, aucun module n'est fautif isolement.

Piste pour le prochain transverse, dans la meme veine : **inventorier les
capacites annoncees par un ecran et chercher qui d'autre peut les retirer.**
Deux candidates non instruites ce jour : la reprise d'un run (`resume`) et les
decisions de doublons — `delete_run` emporte aussi `duplicate_decisions`,
`film_decisions_v2` et `film_marked_for_deletion` (verifie dans
`_TABLES_PORTANT_RUN_ID`), et la modale ne parle que du « run + son plan + son
log ».

**Le raisonnement a mener y est plus fin qu'il n'y parait, et une verification de
ce jour le montre.** J'ai d'abord cru tenir une extension du finding 1 sur
`film_tmdb_overrides` — une correction TMDb manuelle est une intention de
l'utilisateur, et le code lui-meme pose ce critere pour `film_field_locks` : « un
verrou est une INTENTION DE L'UTILISATEUR, il doit survivre a la suppression du
run ». **Faux ici** : l'override est identifie par `(run_id, row_id)`
(`repositories/film_modal.py`), donc rattache au run PAR CONCEPTION — la ligne de
plan qu'il corrige n'existe plus apres la suppression. Le critere n'est pas « la
donnee vient-elle de l'utilisateur ? » mais « **a-t-elle encore un sens sans le
run ?** ». Le seul cas anormal connu (`film_field_locks`, `run_id` documente
« audit, optionnel ») a deja ete traite par `_TABLES_DETACHEES_AU_LIEU_D_ETRE_PURGEES`.

**Le critere se LIT, il ne se devine pas.** Une relecture de ce paragraphe a
d'abord voulu etendre le finding aux tables « de decision » par leur NOM, ce qui
est precisement le raisonnement que le paragraphe ci-dessus refute. La reponse
est dans le DDL : **`run_id` figure-t-il dans la cle d'identite de la ligne ?**
Si oui, la ligne n'existe pas hors du run et sa purge est correcte.

| table | identite (DDL de migration) | `delete_run` |
|---|---|---|
| `duplicate_decisions` | `PRIMARY KEY (run_id, group_key)` | purge — juste |
| `film_marked_for_deletion` | `UNIQUE(run_id, row_id)` | purge — juste |
| `film_tmdb_overrides` | `UNIQUE(run_id, row_id)` | purge — juste |
| `user_quality_feedback` | `run_id TEXT NOT NULL`, sans cle par film | purge — juste |
| `film_decisions_v2` | `UNIQUE(film_id, run_id)`, `run_id DEFAULT ''` | purge — juste ; les decisions GLOBALES (`run_id=''`) ne sont pas ciblees par `WHERE run_id=?` et survivent |
| `film_field_locks` | `UNIQUE(film_id, field_name)` — `run_id` HORS identite | detachee — juste |

Le paragraphe ci-dessus citait quatre tables ; il y en a **cinq** qui portent une
decision de l'utilisateur (`user_quality_feedback` manquait). Le verdict ne
change pour aucune : `_TABLES_PORTANT_RUN_ID` et
`_TABLES_DETACHEES_AU_LIEU_D_ETRE_PURGEES` classent les six correctement.

**Ce qui reste debout, et qui n'est pas une perte de donnees.** La modale
annonce « le run + son plan + son log ». L'utilisateur perd EN PLUS, legitimement
mais sans le savoir, ses decisions de doublons, ses marquages de suppression, ses
corrections TMDb et ses retours qualite. Le defaut est donc dans l'ANNONCE, pas
dans le comportement — meme famille que le finding 1, et meme famille que le
triangle annonce/journal du depot. A instruire avec la modale de #1136, dont
c'est le sujet ; il est nomme ici pour ne pas se perdre en « piste ».
