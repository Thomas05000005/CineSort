# Audit Claude - 2026-09-20 - Couche transverse

**Modele** : celui impose par `--model` dans `.github/workflows/audit-module.yml`, effort maximal.
**Niveau** : modere. **Ouverture de PR** : true.

## Budget d'ouverture

```
PR ouvertes : 37     issues ouvertes : 39     SOMME : 76   (seuil 150)
```

Budget applicable : `<= 3 PR`, `<= 5 issues`. **Consomme : 3 PR + 1 issue (la synthese).**

Les PR ouvertes ont ete interrogees avant d'ecrire (`gh pr list --search "probe"`), pas
supposees — la regle qui a paye trois fois au run du 09-19.

## Resume executif

Un seul fil, tire d'un bout a l'autre : **une decision structurante prise en lisant un
texte destine a l'humain.** C'est la piste n°3 laissee par le rapport du 2026-09-19
(« tout message qui AFFIRME une cause merite la meme lecture »), generalisee en motif
cherchable : `if "<phrase>" in str(message).lower()`.

Le depot en compte **huit sites**. Deux portent une decision qui change le comportement
produit ; les six autres classent des flags internes ou des libelles. Les deux premiers
sont les findings du jour.

| # | Severite | Sujet | Sort |
|---|---|---|---|
| **A1** | **3 (BUG)** | Un outil ABSENT masquait l'echec de sonde de l'autre : probe classee PARTIAL, cap Silver contourne | **PR #1262** |
| **A2** | 2 (QUALITY) | Placeholder des extensions video : 9 entrees pour un defaut effectif de 15, sur un champ RESTRICTIF | **PR #1263** |
| A3 | 2 (QUALITY) | `year_conflict_folder_file` : la branche « remaster » est le conflit le PLUS large et ne pose pas le flag critique | signale, arbitrage produit |
| A4 | 1 (STYLE) | Quatre champs probe de la Vague K ecrits, testes, **jamais lus** en production | signale |

## Le fil du jour, et pourquoi il rend

Le motif `"<phrase>" in str(x).lower()` a ete cherche sur tout `cinesort/`. Il rend
**8 sites**. Le tri n'est pas la quantite mais la **portee de la decision** :

| Site | Ce qui est decide | Verdict |
|---|---|---|
| `probe/_normalize_merge.py:239` | `probe_quality` -> score + cap de tier | **A1, defaut reel** |
| `domain/core.py:1595` | flag `_AUTO_CRITICAL_WARNINGS` | **A3, trou de branche** |
| `infra/db/sqlite_store.py:1327` | `no such table` dans `str(exc)` | ecarte : message SQLite stable et anglais, usage courant |
| `domain/codec_ranks.py:169` | detection `atmos` dans un titre | ecarte : c'est bien un titre de piste, pas un message |
| `domain/librarian.py:233`, `quality_score.py:1954`, `perceptual/grain_analysis.py:205` | flags / warnings internes | ecartes : identifiants, pas de la prose |
| `ui/api/demo_support.py:228` | slug de nom de fichier demo | ecarte : sans rapport |

Cinq sites sur huit sont sains **par nature** : ce qu'ils lisent est un identifiant, pas
une phrase. La distinction utile n'est donc pas « ne jamais tester une sous-chaine »,
c'est **« ne jamais deduire un etat d'un texte ecrit pour etre lu »**.

## A1 — Un outil ABSENT masquait l'echec de sonde de l'autre *(sev. 3)* — PR #1262

`_determine_quality` deduisait la cause d'un echec de probe de la presence du mot
« manquant » dans les messages :

```python
if any("manquant" in str(m).lower() for m in normalized.messages):
    reasons.append("Analyse partielle: outil manquant.")
    normalized.probe_quality = PROBE_QUALITY_PARTIAL
```

En mode `auto` — **le defaut** — les deux causes coexistent des qu'un seul outil est
absent, et c'est `service.py` lui-meme qui pose le message de l'absent :

```
["ffprobe manquant (mode auto).",                    <- outil ABSENT
 "MediaInfo echec (code 1): File is not readable"]   <- sonde ECHOUEE
```

`raw_mediainfo` et `raw_ffprobe` valent tous deux `None`, mais « manquant » l'emporte :
la probe est classee **PARTIAL** alors qu'**aucune metadonnee n'a pu etre lue**.

### Ou ca atterrit

`probe_quality` n'est pas un libelle : il pondere le score (`domain/quality_score.py`).

| | PARTIAL (observe) | FAILED (attendu) |
|---|---|---|
| `extras_sub` | +4 | -18 |
| mode metadata strict | -6 | -10 |
| cap de tier | *aucun* | **plafonne a Silver** |

22 points d'ecart (26 en mode strict), et surtout le contournement du cap Silver, dont
le commentaire (`quality_score.py:2850`) enonce exactement l'invariant brise :

> « Decision senior conservatrice. Applique APRES custom rules pour etre la **derniere
> autorite** : aucune regle / aucun bonus de nom ne peut certifier un tier eleve si on
> n'a pas verifie le fichier (probe FAILED) »

**Un fichier que personne n'a pu lire pouvait donc etre certifie Gold ou Platinum**, sur
la seule foi de son nom. Cote ecran, `library_support.py:773` derive `quality_unavailable`
du seul `FAILED` : la ligne s'affiche avec un score et un tier normaux.

### Ce qui rend le correctif sur, et court

**Le predicat correct existait deja dans le meme fichier.**
`ProbeService._is_tool_definitely_unavailable`, ecrit pour le circuit breaker, ne classe
« tool unavailable » que si aucun binaire n'est lancable — et un commentaire voisin
(`service.py:636`) enonce meme la distinction que `_determine_quality` ratait :

> Distinguer : « tool unavailable » (transient) / « file corrupted » (persistent :
> ffprobe a tourne mais a echoue)

Le depot **savait** faire la distinction, et s'en servait pour decider du cache — jamais
pour decider de la qualite. `probe_file` transmet desormais la reponse. Le parametre est
optionnel : omis, le comportement historique est conserve a l'identique.

Seules **deux lignes** de la table de verite changent (un outil absent + l'autre qui
echoue, dans les deux sens) ; les sept autres combinaisons sont inchangees.

### Cliquets, et celui qui a failli passer

Deux cliquets a marge zero mordaient ce correctif :

- `test_function_size_budget` : `probe_file` **204 -> 211** (remesure a l'AST) ;
- `test_normalize_probe_signature_unchanged` : il compare le set **exact** des parametres
  de `normalize_probe`. Ajouter un kwarg optionnel le faisait rougir.

Le second n'est pas sorti d'une recherche de cliquets — il est sorti de la lecture
integrale du fichier de test voisin. **Chercher les cliquets par leur nom ne suffit
pas** : celui-ci ne porte ni « contract », ni « budget », ni « cliquet » dans son nom,
il s'appelle `test_probe_normalize_split_imports_v77.py`. Ce qui l'a revele est la
question « quels tests nomment le symbole que je modifie ? », posee sur les trois
symboles, ce qui a rendu 19 fichiers relus.

## A2 — Le placeholder des extensions video *(sev. 2)* — PR #1263

Champ vide, l'ecran Parametres affiche `.mkv;.mp4;.avi;.mov;.m4v;.wmv;.flv;.webm;.ts`
(**9**). Le defaut reellement applique par `resolve_video_exts` est
`VIDEO_EXTS_DEFAULT | VIDEO_EXTS_ALL`, soit **15**.

Absentes : **`.m2ts`** (Blu-ray), **`.vob`** et **`.iso`** (DVD), `.mpg`, `.mpeg`,
`.ogv` — les six sont celles des **sources physiques**.

Ce qui rend l'ecart couteux : le champ est **RESTRICTIF** depuis le 2026-08-03, et le
durcissement le dit lui-meme (« un champ nomme Extensions video ACCEPTEES qui ne sait
pas refuser une extension est un perimetre en trompe-l'oeil »). Toute saisie REMPLACE le
defaut. Le placeholder ne s'affiche que quand le champ est vide — donc exactement sur
une installation qui n'a jamais touche ce reglage. Le recopier pour y ajouter une
extension sort les Blu-ray et les DVD du perimetre de scan, **sans message**.

Le correctif **n'enumere pas** les 15 : une liste en dur dans l'ecran rejouerait la
divergence que `tests/test_constantes_divergentes_audit_20260806.py` verrouille cote
backend — un fichier qui existe precisement parce que deux copies d'une meme table
avaient derive en silence. Le placeholder dit la **semantique** du champ vide.

**Honnetete sur la portee** : le declencheur est une action utilisateur plausible mais
non certaine. Severite 2, pas 3.

## A3 — La branche « remaster » ne pose pas le flag critique *(sev. 2, signale sans PR)*

`_warning_flags_from_analysis` (`domain/core.py:1595`) pose
`year_conflict_folder_file` — membre de `_AUTO_CRITICAL_WARNINGS`
(`ui/api/run_read_support.py:17`) — si la raison contient la phrase francaise
`"conflit dossier/fichier"`.

Or `infer_name_year` (`domain/title_helpers.py`) a **deux** branches de conflit :

```python
if remaster_hint and abs(folder_paren - video_paren) >= 3:
    return (min(...), "annee de sortie deduite (conflit parenthese + indice remaster)", True)
return (video_paren, f"conflit dossier/fichier ({folder_paren} vs {video_paren}), ...", ...)
```

La premiere est le conflit **le plus large** (>= 3 ans d'ecart) et ne contient pas la
sous-chaine : elle ne produit donc **aucun** avertissement critique, la ou un conflit
d'un an en produit un.

**Pourquoi c'est defendable** : quand un indice de remaster est present, le conflit est
*explique* (edition 2019 d'un film de 2001), et l'app retient deliberement `min()`,
l'annee de sortie originale — ce qui est le bon choix. Flagger tous les remasters
noierait l'utilisateur.

**Pourquoi ca reste un finding** : `REMASTER_HINT_RE` ne detecte pas que des remasters.
Il couvre `extended`, `director's cut`, `final cut`, `special edition`,
`collector's edition`, `redux`, `anniversary` — des tags d'**edition** omnipresents dans
les noms de release. Un dossier `Dune (2021) Extended` contenant par erreur
`Dune (1984).mkv` retient donc **1984**, en silence et sans flag — et `Dune 1984/2021`
est l'exemple que le code cite lui-meme pour `title_ambiguity`.

**Pas de PR** : poser le flag dans les deux branches est un arbitrage produit (plus de
validations manuelles contre moins d'annees fausses), et le prompt interdit d'ouvrir une
PR qui en depend. Ce que le code ne dit nulle part, en revanche, c'est que cette
exclusion est **voulue** : rien, a `core.py:1595`, n'indique qu'une seconde branche de
conflit existe et est deliberement exclue.

## A4 — Quatre champs probe ecrits, testes, jamais lus *(sev. 1, signale sans PR)*

`NormalizedProbe` porte depuis la Vague K quatre champs dont la docstring annonce la
raison d'etre : « permettre la generation d'un fichier NFO complet ».

| Champ | Ecrit par | Lu en production |
|---|---|---|
| `chapters` | `_normalize_merge.py:115` | **0** |
| `container_encoder` | `_normalize_merge.py:111` | **0** |
| `container_creation_time` | `_normalize_merge.py:113` | **0** |
| `container_format_long` | `_normalize_merge.py:107` | **0** |

Le generateur de NFO existe — `export_support.py:327`,
`_build_nfo_xml(title, year, original_title, tmdb_id, imdb_id)` — et ne prend **que** des
metadonnees d'identification : aucune donnee technique. La promesse de la Vague K n'a
jamais ete cablee. Seuls des tests les exercent (`test_probe_normalize_complete.py`).

**Pas de PR** : cabler (enrichir le NFO) ou retirer sont deux decisions opposees.
`test_contract_dead_symbols` ne peut pas le voir — `USE_ROOTS` inclut `tests/`
deliberement, angle mort que le fichier documente lui-meme.

## Les 5 points du prompt transverse

| Point | Resultat |
|---|---|
| 1. Fonctions > 100 L par ROI | Sans objet (#215 fermee). Le cliquet `test_function_size_budget` tient ; A1 l'a fait monter de 204 a 211 sur `probe_file`, ligne de diff visible en review |
| 2. Duplication desktop/dashboard | Sans objet — arborescence unique |
| 3. Imports inter-couches | **PROPRE, sixieme passage consecutif.** 4 hits, **fichiers ouverts** : `_runners.py:84` (docstring), `core.py:55` (`TYPE_CHECKING`), et deux COMMENTAIRES de refactor (`duplicate_multi_signal.py:151`, `core.py:1975`). Aucun import reel. `infra -> app/ui` et `app -> ui` : **0 hit** |
| 4. Repository pattern / mixins SQL | **Identique** aux mesures des 08-16, 08-23 et 09-06 : 11 occurrences = 8 docstrings qui documentent la suppression + `_PeerGuardMixin` (garde SSRF urllib3, 3 lignes), sans rapport avec SQL |
| 5. Imports module-style des cibles `patch()` | Echantillon cible sur le cas a RISQUE : `patch("cinesort.app.plan_support.replan_single_row")` vise un module de **re-export**, et le consommateur fait `from ... import ...`. **Sain** — l'import est lazy (`library_actions_support.py:793`), donc re-evalue a l'appel et le mock s'applique. Et un remontage en tete ferait **rougir** le test, pas passer silencieusement : la faute est auto-detectee ici |

## Ecarte apres verification — ne pas re-instruire

| Piste | Pourquoi elle tombe |
|---|---|
| `_determine_quality` : les DEUX outils absents rendent PARTIAL alors que rien n'est mesure | **Deliberé et fige** par `test_probe_auto.py:114` (`which_fn` rend `None`, `spy.calls == []`). Distinguer « pas d'outil » de « echec de mesure » est un choix, pas un oubli — A1 ne le touche pas |
| Les deux tests voisins qui attendent PARTIAL sur un echec de sonde | **Non concernes** : MediaInfo y **reussit** (`raw_json.mediainfo` est un dict), ils passent par `any_raw`, branche non modifiee |
| `sqlite_store.py:1327` : `no such table` cherche dans `str(exc)` | Message SQLite **stable et anglais**, produit par la lib et non par l'app. Pas de la prose traduisible |
| `resolve_ui_variant` rend toujours `"stable"` (condition morte) | **Deliberé et documente** : l'UI `next` est archivee, `resolve_ui_policy_notice` porte le message de repli |
| `_log_video_parity` : divergence codec/bitrate entre backends loggee en INFO, jamais exposee | Choix **ecrit** dans la docstring (« on flag pour analyse offline pas pour alerter l'user ») |
| Le log `extensions video RESTREINTES` s'affiche aussi quand la liste est ELARGIE | Vrai mais **cosmetique** (log INFO interne, `explicit != default_exts` sans direction). Severite 0, non retenu |
| `probe_files` echapperait au correctif A1 | Non : elle delegue a `probe_file` (`service.py:804`). Les deux seuls appels a `normalize_probe` sont `service.py:489` et `:623` |
| `_degraded_source_payload` change de comportement avec A1 | Non : il ne passe pas le nouveau parametre, garde le repli historique, et son message (« probe non tente ») ne contient pas « manquant » — FAILED avant comme apres, conformement a sa docstring |
| 11 tests assertent `probe_quality: "PARTIAL"` | Tous le **fournissent en entree** du scoring ; aucun ne traverse `_determine_quality` |

## Ce que cet audit n'a PAS couvert

- **Aucune execution.** `python3` est refuse par le runner (re-verifie ce jour) : ni
  pytest, ni ruff, ni l'application. **PR #1262 et #1263 non verifiees localement**,
  validation deleguee a leur CI. Formatage tenu a la main ; lignes > 120 colonnes
  ajoutees cote Python : **0**.
- **Aucun fichier media reel.** A1 se lit entierement dans le code ; le test injecte
  l'echec au niveau du **runner**, la ou la production le subit.
- **Categories 22-28 et 40-46** (truck factor, SBOM/CRA, signature Authenticode,
  onboarding, dark patterns) : examen produit, pas lecture de code.
- **Techniques cross-couche (A)-(G)** : seule **(B)** (column/field usage tracing) a ete
  jouee, sur la zone probe — elle a rendu A4. **(F) CLI vs GUI parity** a ete ouverte
  puis refermee : la CLI se reduit a `--api`, `--port`, `--public`, `--dev`, `--ui`
  (parse a la main dans `app.py`), sans equivalent attendu a l'ecran. Rendement nul,
  **inutile de la reprendre**.
- **La fuite CLIENT du jeton** reste a mesurer (blocage materiel, cf. #1228).

## Pistes pour le prochain run, par ordre de rendement

1. **Le reste de la zone probe est encore vierge.** A1 est le **premier** finding jamais
   ouvert sur `infra/probe/` (0 en 557 findings historiques) et il etait de severite 3.
   `adaptive_timeout`, `_retry_backoff`, `_source_circuit_breaker`, `disk_cache`,
   `auto_install` n'ont toujours ete lus par personne — et ils sont sur le chemin qui
   **mesure** les fichiers dont tout le scoring depend.
2. **A4 le jour d'un enrichissement du NFO** : les quatre champs sont deja calcules,
   `_build_nfo_xml` est le seul site a etendre.
3. **Le motif d'A1 a une forme symetrique non exploree** : un etat structure deduit d'un
   **code de retour** plutot que d'un message (`rc != 0` traite comme cause unique).
   Meme question, autre support.
4. **A3 attend un arbitrage**, pas une mesure. Le trancher demande de savoir si
   l'utilisateur prefere plus de validations manuelles ou moins d'annees fausses.

## Statistiques

- Modules audites : **~25 lus integralement** (chaine probe complete, `domain/core.py`
  partiel, `title_helpers`, `settings_support` partiel, `parametres.js` partiel), sur un
  perimetre transverse.
- Findings totaux : **4** retenus (1 sev. 3, 2 sev. 2, 1 sev. 1) + **9 familles ecartees**
  apres verification.
- Self-critique : **6 findings supprimes** — 3 idiomatiques (sous-chaines sur des
  identifiants, pas de la prose), 1 deja delibere et fige par un test (les deux outils
  absents), 1 de severite 0 (log directionnel), 1 refute par lecture (`probe_files`
  echapperait au correctif).
- Issues creees : **1** (synthese du jour).
- PR ouvertes : **3** — #1262, #1263, et celle qui porte ce rapport.
- Findings deja connus (dedup) : **0 doublon** — `gh pr list --search "probe"` et
  `gh issue list --search "probe_quality"` interroges avant ecriture.

## Tendance

Audit transverse precedent : **2026-09-06** (#1228) — 2 correctifs, 1 finding sans PR,
7 pistes ecartees. Aujourd'hui : 2 correctifs, 2 findings sans PR, 9 familles ecartees.

Stable en volume. Le changement est ailleurs : le run du 09-19 concluait que « le facteur
limitant de ce depot n'est plus la detection » (trois pistes deja portees par des PR
ouvertes). Ce run n'a rencontre **aucun doublon** — parce qu'il est alle dans la zone que
557 findings historiques n'avaient jamais touchee. **La surface vierge, quand elle est
sur un chemin de decision, rend encore de la severite 3.**
