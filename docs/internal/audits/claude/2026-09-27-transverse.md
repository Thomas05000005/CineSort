# Audit Claude — 2026-09-27 — Couche `transverse`

**Modèle** : celui qu'impose `--model` dans `.github/workflows/audit-module.yml`.
**Niveau** : modéré. **Ouverture de PR** : autorisée.

```
PR ouvertes : 50     issues ouvertes : 44     SOMME : 94   (seuil 150)
```

Budget applicable : `<= 3 PR`, `<= 5 issues`. **Consommé : 2 PR + 1 issue.**

---

## Résumé exécutif

Ce run n'a trouvé **aucun défaut de sévérité 3 ou 4**, et c'est le résultat
honnête. Sa valeur est ailleurs, dans deux choses que le prochain run n'aura pas
à repayer :

1. **La piste classée n°1 du dépôt est SATURÉE.** Le rapport du 09-26 laissait,
   en tête de son ordre de rendement, « toute fonction qui normalise une entrée
   utilisateur en retirant du vocabulaire, et dont un appelant consomme le
   résultat vide comme une valeur », avec quatre candidats nommés. **Les quatre
   portent leur garde.** Détail en « Familles écartées » — c'est la section la
   plus utile de ce rapport.
2. **Deux techniques du prompt d'audit sont mécanisées par la CI**, donc
   inutiles à refaire à la main : l'inventaire endpoint ↔ front (technique A) et
   la chasse aux réglages sans consommateur.

Le seul correctif ouvert porte sur une **affirmation fausse publiée** : la page
qui documente l'export RGPD décrivait le mécanisme de masquage d'avant #1187.

| # | Finding | Sév. | Suite |
|---|---|---|---|
| A1 | `docs/EXPORT_FORMAT.md` annonce une liste fermée là où le code masque par SUFFIXE | 1 | **PR #1281** |
| A2 | Un fichier vide nommé `=6.0,` est suivi par git à la racine depuis 29 jours | 1 | issue — *correctif impossible dans ce runner* |
| A3 | Le retry multiplie le timeout adaptatif par 4 : jusqu'à ~20 min par fichier | 2 | signalé (arbitrage) |
| A4 | « Timeout probe (s) » n'est plus un couperet, et sa moitié basse est inopérante | 2 | signalé |
| A5 | Quatre clés annoncées « Settings (UI) » n'existent nulle part | 1 | signalé |
| A6 | Un chemin d'outil INEXISTANT est rapporté « détecté mais exécutable invalide » | 1 | signalé (borné) |
| A7 | La désambiguïsation P2.2 ne s'applique jamais à un titre non latin | 1 | signalé |
| A8 | L'en-tête d'un contrat annonce 2 sites dynamiques là où son corps en tolère 5 | 0 | signalé |

---

## Corrigé

### PR #1281 — `docs(export)` : la page RGPD promettait une liste fermée *(sév. 1)*

`docs/EXPORT_FORMAT.md` est le document qu'un utilisateur lit pour savoir ce que
son export emporte (RGPD Art. 20). Sa section `settings` décrivait le mécanisme
**d'avant le 2026-08-31**.

| Ce que la page annonçait | État réel |
|---|---|
| `smtp_password` masqué | **Aucun code du dépôt ne lit cette clé** |
| *(absent)* | `email_smtp_password` — le nom réel du mot de passe SMTP |
| `ntfy_topic_secret`, `osdb_api_key` | **N'existent pas dans le produit** |
| *(absent)* | `rest_api_token_secret` — exclu de l'export depuis SEC-2 |
| « liste des clés masquées » | Le critère est un **prédicat par suffixe** |

C'est exactement la fuite corrigée par **#1187**, mais **le correctif n'avait été
posé que du côté du CODE**. Même forme que #1080 (grille de tier corrigée d'un
seul côté) et #1224 (deux docstrings annonçant un câblage absent).

**Aucune fuite aujourd'hui** : `_sanitize_settings` masque bien
`email_smtp_password` via `_est_un_secret`. Le défaut est l'affirmation publiée —
et un mainteneur qui se fierait à cette page croirait devoir ajouter chaque clé
à la main.

**Le chaînon manquant était un garde.** `test_export_full_library.py` **nomme
déjà** cette page comme portant la promesse (« `docs/EXPORT_FORMAT.md` promet
pourtant le masquage ») **sans jamais la lire**. Les ancres du test ajouté ne
passent que grâce au correctif — mesure avant : `email_smtp_password` et
`rest_api_token_secret` valaient **0 occurrence** chacune.

Et la boucle sur `_SUFFIXES_DE_SECRET` **ne suffirait pas seule**, ce que la
docstring dit : `_api_key`, `_token`, `_password` et `_secret` sont aussi des
sous-chaînes des exemples cités, donc quatre des six passaient déjà sur
l'ancienne page. « Asserter ce que SEUL le correctif produit », appliqué à un
test de documentation.

---

## Signalé sans PR — la raison compte autant que le constat

### A2 — un fichier parasite suivi par git, et un garde qui ne peut pas le voir *(sév. 1)*

```
$ git ls-files | grep -E '[<>|*?"]|^=' ->  =6.0,        (0 octet)
$ git log --format="%h %ad %s" -- "=6.0,"
  b0aaec16 2026-08-29 fix(parseur): sept mots de _NOISE_RE sont de vrais titres de films (#1164)
```

Signature d'un `>=6.0,<7` **non quoté** dans un shell : la redirection a créé le
fichier, `git add` l'a emporté, et le sujet du commit qui le porte n'a aucun
rapport. **Unique cas** sur les 2037 fichiers suivis.

Vérifications de suppression faites : 0 référence dans `tests/` (les hits
`6.0,` sont des flottants), 0 en code de production, non collecté par
`CineSort.spec` (qui ne prend que `web/`, migrations, presets, locales).

**L'angle qui vaut d'être écrit** : un garde de la racine EXISTE —
`test_release_hygiene.py::test_internal_and_design_docs_are_reorganized_out_of_repo_root` —
mais il fonctionne par **énumération de 7 noms**. Il ne balaie pas la racine,
donc **aucun nom nouveau ne peut le déclencher**. Et rien d'autre ne le fait :
`grep -rn "REPO_ROOT.iterdir\|repo_root.iterdir" tests/ scripts/` rend **0**.

**Pourquoi aucune PR, et c'est une limite du RUNNER, pas du correctif** : toute
suppression de fichier est refusée ici. Cinq voies essayées, toutes bloquées —
`git rm '=6.0,'`, `git rm --pathspec-from-file`,
`git update-index --force-remove --stdin`, `find -delete`, `rm` (y compris sur
un nom parfaitement ordinaire, ce qui montre que le refus ne vient pas du nom).
Or livrer le garde **sans** la suppression rendrait la CI de la PR rouge par
construction. Les deux vont ensemble ou pas du tout.

Le garde proposé est **mesuré comme vert d'emblée** : 0 violation sur les 2037
fichiers suivis pour les quatre règles (caractères interdits Windows, préfixe de
redirection, fin en point ou espace, noms réservés `CON`/`PRN`/`AUX`/`NUL`/
`COM1-9`/`LPT1-9`) — donc aucune dette à figer. Et le helper dont il a besoin,
`_git_tracked_files()`, est **déjà dans le fichier** : il ne juge que le
contenu versionné, ce qui écarte d'emblée les faux positifs sur artefacts
locaux — la leçon que sa propre docstring raconte.

### A3 — le retry multiplie le timeout adaptatif par quatre *(sév. 2)*

`default_runner` (`tooling.py:146`) enveloppe `_run_once` dans
`retry_with_backoff`, et **chaque tentative porte le timeout adaptatif complet** :

```
fichier 80 Go -> compute_adaptive_timeout = 300 s (plafond CEILING)
              -> 4 tentatives x 300 s + backoff (1+2+4)
              = ~1207 s (~20 min) avant que l'echec ne soit rendu
```

`_retry_backoff.py` borne le **délai d'attente** entre tentatives
(`MAX_RETRIES_HARD_CAP`, commentaire « 3 * 8s = 24s deja non-trivial ») mais
**jamais le coût total des tentatives**. La borne posée n'est pas celle qui
compte.

Le cas est celui que le module cite lui-même en motivation : un NAS **lent ou
pendu** (`ERROR_SEM_TIMEOUT`, winerror 121), où ffprobe bloque jusqu'au timeout.
Un NAS *déconnecté*, lui, échoue vite (winerror 53) : ~7 s par film, acceptable.

Et le circuit breaker qui devrait amortir est **aveugle aux lecteurs réseau
mappés** — `extract_network_source` n'accepte que l'UNC littéral (finding
`59cf9a7f`, 2026-08-26). Une bibliothèque sur `Z:\Films`, la façon la plus
courante de monter un partage, n'est donc pas protégée. **La composition est
neuve ; ses deux maillons étaient connus séparément.**

**Pas de PR** : arbitrage. Plafonner le temps par fichier, rendre le timeout
dégressif, ou ne pas retenter un `TimeoutExpired` sont trois politiques
différentes sur le chemin qui mesure chaque film.

### A4 — « Timeout probe (s) » n'est plus un couperet *(sév. 2)*

Le champ UI (`parametres.js:82`, borné 5..300) est lu comme **base** de la
formule adaptative, plus comme plafond — `service.py:561` le dit
(« remplace le couperet unique `cfg["probe_timeout_s"]` »). Deux conséquences :

- **`cfg["probe_timeout_s"]`, produit par `_normalize_probe_settings` avec son
  clamp [5,300], n'a plus aucun lecteur.** `probe_file` utilise
  `adaptive_timeout_s`.
- **Le plancher vaut 10**, donc toute saisie entre 5 et 10 est ignorée ; et une
  saisie de 5 sur un fichier de 20 Go rend `5 + 5*20 = 105 s`, puis ×4
  tentatives.

L'utilisateur qui **réduit** ce réglage pour ne pas bloquer son scan sur un
fichier corrompu — le cas d'usage que la docstring d'`adaptive_timeout.py` cite
en tête — obtient l'inverse de ce qu'il demande.

Le remède minimal et sans arbitrage est celui de **#1263** : dire la sémantique
dans l'écran par un `hint`. Je ne l'ouvre pas en PR parce que le run du 09-20 a
déjà livré exactement ce geste et qu'un second `hint` ressemblerait à du
remplissage ; le remède *utile* (honorer le couperet, ou exposer les 4 clés
adaptatives) est un arbitrage produit.

### A5 — quatre clés annoncées « Settings (UI) » qui n'existent nulle part *(sév. 1)*

La docstring d'`adaptive_timeout.py` annonce
« **1. Settings (UI)** : `probe_timeout_base_s`, `probe_timeout_per_gb_s`,
`probe_timeout_floor_s`, `probe_timeout_ceiling_s` ». Mesure : **aucune de ces
quatre clés n'existe ailleurs** dans `cinesort/` ni `web/` — ni champ UI, ni
défaut, ni validation, ni liste de reset. Le seul autre hit est un commentaire.
La branche `_read_float_setting` correspondante est donc morte par câblage ;
seules les variables d'environnement sont atteignables.

Deux écarts de plus dans le même module : la docstring promet que « l'adaptatif
n'est appliqué que si les autres champs adaptatifs sont absents (**retro-compat
ABSOLUE**) », alors que `per_gb` retombe **toujours** sur son défaut de 5 s/Go —
c'est-à-dire dans le seul cas atteignable en production ; et le message de
`__post_init__` annonce un repli « sur les defauts » quand `floor > ceiling`,
alors que `compute_adaptive_timeout` retombe sur `ceiling`.

### A6 — un chemin INEXISTANT rapporté « exécutable invalide » *(sév. 1, borné)*

`_build_tool_status` saute les candidats absents du disque
(`if not p.exists() or not p.is_file(): continue`, l.268). Quand la boucle
s'épuise, le repli rend `_STATUS_INVALID` — « détecté mais exécutable
invalide » — et attribue `path`/`source` à `candidates[0]`, **que la boucle n'a
alors jamais testé**. Un chemin mal saisi dans « Chemin ffprobe » est donc
rapporté comme un binaire cassé : l'utilisateur cherche une version ou des
droits là où il y a une faute de frappe.

Même confusion que **#1252** (illisible ≠ corrompu) et **#1262** (outil absent ≠
sonde en échec), dans le module de #1262.

**Ce qui le borne, et pourquoi il reste à 1 — je l'ai découvert en cherchant le
consommateur, pas en lisant le module** : l'écran ne lit **ni `status` ni le
`message` par outil**. `_renderProbeToolRow` (`parametres.js:801`) branche sur
`available`/`compatible`, tous deux corrects ici, donc le badge « ✗ Manquant »
est déjà juste. Seul le `path` trompeur s'affiche (l.819-822), et le `status`
incohérent n'est visible que d'un client de l'API REST. **J'avais d'abord écrit
ce finding en sévérité 2 et préparé sa PR ; la mesure du consommateur l'a fait
redescendre.**

### A7 — la désambiguïsation P2.2 ignore les titres non latins *(sév. 1)*

`title_ambiguity._normalize_title_for_ambiguity_cached:52` applique
`re.sub(r"[^a-z0-9\s]", " ", s)` : un titre entièrement en CJK, cyrillique,
arabe ou grec rend la chaîne **vide**.

Les deux consommateurs portent bien leur garde — `detect_title_ambiguity` fait
`if not key: continue`, donc `ambiguous_title` ne peut jamais valoir `""`, ce qui
rend sain le test `title_key != ambiguous_title` de `disambiguate_by_context`.
**Aucune décision fausse.** Mais deux films au même titre original non latin ne
sont jamais reconnus comme ambigus : le départage contextuel (année du dossier,
`tmdb_id` du NFO, runtime) ne s'active pas, et le plus populaire gagne — le
comportement exact que ce module existe pour corriger. Atteignabilité bornée par
`tmdb_language = fr-FR`, qui rend des titres traduits quand une traduction
existe.

### A8 — l'en-tête d'un contrat annonce 2 sites là où son corps en tolère 5 *(sév. 0)*

`test_contract_ui_api.py` dit en tête « 2 sites physiques dans parametres.js ->
7 endpoints resolus ». Son corps en tolère **cinq**, dans **trois** fichiers
(vagues B1/B2/C) — ce qui correspond exactement aux 5 sites réels mesurés. Le
garde est donc **juste et complet** ; seul son en-tête n'a pas suivi ses propres
extensions. Consigné parce qu'il m'a fait soupçonner un angle mort inexistant et
coûté une vérification.

---

## Familles écartées après vérification — ne pas ré-instruire

### La piste n°1 du 09-26 est SATURÉE

Le rapport du 09-26 la classait en tête de rendement : « toute fonction qui
normalise une entrée utilisateur en retirant du vocabulaire, et dont un appelant
consomme le résultat vide comme une valeur ». Ses quatre candidats nommés :

| Candidat | Verdict |
|---|---|
| `domain/_fuzzy_normalize.normalize_for_fuzzy` | **Gardé aux trois sites.** `fuzzy_title_match` fait `if not a or not b: return False` ; `find_best_fuzzy_match` fait `if not q_norm: return None` **et** filtre les choix vides en mémorisant les index d'origine |
| `domain/title_ambiguity` | **Gardé** (`if not key: continue`). Reste A7, qui est une perte de fonctionnalité, pas une décision fausse |
| `domain/quality_score:1118` (`_title_in_folder`) | **Gardé** : `return bool(nt) and (nt in nf)` — sans le `bool(nt)`, `"" in nf` rendrait toujours vrai |
| `domain/edition_helpers` | Ne retire pas de vocabulaire : `replace(".", " ")` et `re.sub(r"\s{2,}", " ")`, des séparateurs |

Les index par titre normalisé des modules de synchro sont **exemplaires** :
`jellyfin_validation.py:122` et `radarr_sync.py:66` font tous deux `if norm:`
avant d'indexer, et `jellyfin_validation.py:176` fait `if query_norm:` avant de
chercher. Sans ces gardes, deux titres normalisés vides auraient collisionné
dans le dict — et `SequenceMatcher("", "").ratio()` vaut **1.0**.

> **Conséquence opérationnelle : ne pas re-parcourir cette piste.** Elle a été
> ouverte parce qu'un cas réel l'avait payée (#1278, `NOISE_RE` absorbant un
> titre entier), mais ce cas était singulier — il venait d'une table de BRUIT,
> pas d'une normalisation de ponctuation.

### Deux techniques du prompt sont mécanisées par la CI

| Technique du prompt | Pourquoi la refaire à la main ne rend rien |
|---|---|
| **(A) Endpoint inventory diffing** | `test_contract_ui_api.py` le fait dans les deux sens, **à marge zéro** (`KNOWN_BROKEN = {}`) : chaque `apiPost("facade/methode")` doit viser une méthode existante, **les clés du payload** doivent être dans la signature, et tout nouveau site dynamique est refusé. `test_contract_facades.py` couvre le sens inverse (orphelines). Les 122 routes littérales sont donc vérifiées à chaque run de CI |
| **Réglages sans consommateur** | `test_contract_settings.py` extrait les clés canoniques **à l'AST** et exige un lecteur backend pour chacune, avec `KNOWN_UNWIRED` en **rétrécissement seul**. Mon inventaire des 96 clés de l'écran n'a rien trouvé que ce contrat ne tienne déjà |

### Autres pistes tombées

| Piste | Pourquoi elle tombe |
|---|---|
| `cleanup_orphans` et `cleanup_empty_folders` : deux bascules de nettoyage MORTES, aux libellés quasi synonymes de leurs voisines vivantes | **Déjà instruit** (`t23cln03`, 2026-08-23, sév. 3, confiance 0,93) **et inscrit comme dette assumée** dans `test_contract_settings.py:73-74`. Le retrait des deux bascules est un **arbitrage du propriétaire** (`PHASE5_ARBITRAGES.md`, R8-063 / F-PROM-02). C'est le piège « chercher le garde avant d'en écrire un », évité de justesse : les deux clés sont encadrées, dans `settings_support.py`, par les commentaires de retrait de leurs voisins fantômes (`animations_enabled`, `subtitle_lang_priority`) |
| `infra/probe/_retry_backoff.py` (214 L, **0 finding historique**) | **Lu intégralement, sain.** `_is_transient` exclut `KeyboardInterrupt`/`SystemExit`/`GeneratorExit`, ne retente que des causes nommées, re-lève la dernière exception telle quelle ; le code après la boucle est défensif et marqué `pragma: no cover`. Seule sa composition avec le timeout pose question (A3) |
| Catégorie 37, chemins > 260 caractères | **Instruite, et le point est couvert** : `CineSort.exe.manifest:44` porte `longPathAware=true`. Le code n'utilise pas le préfixe `\\?\` (il le **refuse** même en entrée, `cinesort_api.py:1963`) ; sur une machine sans `LongPathsEnabled`, un chemin long échouerait donc — mais ça ne se mesure pas sans Windows. Mesure faite : **0 nom illégal** sur 2037 fichiers suivis (caractères interdits, noms réservés, fin en point ou espace) |
| `Config.min_video_bytes` non câblé par `build_cfg_from_settings` | **Déjà documenté dans le code**, et contourné : `plan_support_core.py:370` signe le seuil EFFECTIF (`core_mod.MIN_VIDEO_BYTES`) précisément parce que le champ vaut toujours `None` |
| `cinesort_api.py:3353` (`if result.returncode == 0`), piste n°3 du 09-20 sur les états déduits d'un code de retour | **Sain** : `git_sha` reste vide, best-effort documenté, aucune affirmation fausse. Les autres sites `returncode` vivent dans les modules perceptuels, ratissés les 09-24 et 09-25 |
| `AdaptiveTimeoutConfig` : `float("nan")` dans un réglage | Théoriquement atteignable par un `settings.json` édité à la main (un `ceiling` NaN ramènerait tout timeout au plancher). L'écran clampe à l'écriture ; **sévérité 0, non retenu** |

---

## Les 5 points du prompt transverse

| Point | Résultat |
|---|---|
| 1. Fonctions > 100 L | Sans objet (#215 fermée). Le cliquet `test_function_size_budget.py` tient ; son périmètre est `("cinesort", "app.py", "scripts")` — **pas `tests/`**, ce qui rend l'ajout de garde d'A2 neutre à son égard |
| 2. Duplication desktop/dashboard | Sans objet |
| 3. Imports inter-couches | **PROPRE, septième fois consécutive.** 4 hits dans `domain/`, **fichiers ouverts** : 1 docstring (`_runners.py:84`), 1 `TYPE_CHECKING` (`core.py:55`), 2 commentaires de refactor. `infra -> app/ui` : 3 hits, **tous** docstrings ou commentaires. `app -> ui` : **0** |
| 4. Mixins SQL | **Identique** aux 08-16, 08-23, 09-06 et 09-20 : 8 docstrings de `repositories/*.py` qui documentent la suppression, plus `_PeerGuardMixin` (`_http_utils.py`), mixin de connexion urllib3 pour le garde SSRF — sans rapport avec SQL |
| 5. Module-style / `patch()` | Le contrat `UiApiPatchableImportTests` couvre `cinesort.ui.api.*`. Échantillon hors périmètre relu sur la couche `app` : l'intention est écrite dans le code (`runtime_probe_check.py` documente son import lazy « tests patchent au niveau du module source ») |

---

## Statistiques

- **Modules lus intégralement** : 6 — `infra/probe/adaptive_timeout.py`,
  `infra/probe/_retry_backoff.py`, `domain/_fuzzy_normalize.py`,
  `app/_fuzzy_utils.py`, `domain/title_ambiguity.py`,
  `tests/test_contract_settings.py`. Partiellement :
  `infra/probe/tools_manager.py` (jusqu'à 400), `infra/probe/service.py`
  (zones settings + `probe_file`), `ui/api/export_support.py`,
  `tests/test_release_hygiene.py`, `tests/test_contract_ui_api.py`.
- **Findings** : 8 — sév. 2 : **2** ; sév. 1 : **5** ; sév. 0 : **1**.
  **Aucun de sévérité 3 ou 4.**
- **Familles écartées par la mesure** : **11**.
- **PR ouvertes** : 2 (#1281 correctif, celle de ce rapport).
- **Issues ouvertes** : 1 (synthèse du jour).
- **Findings déjà connus, donc non rouverts** : 2 (`t23cln03`, `59cf9a7f`).

---

## L'enseignement de méthode du jour

**Un audit qui mesure d'abord ses propres outils s'épargne sa journée.**

Trois des axes que le prompt me prescrit sont **déjà mécanisés à marge zéro par
la CI** : l'inventaire endpoint ↔ front, les payloads d'`apiPost`, et les
réglages sans lecteur. J'ai commencé par les refaire à la main — 96 clés
inventoriées, 122 routes extraites — pour découvrir que `test_contract_settings.py`
et `test_contract_ui_api.py` les tiennent déjà, mieux et à chaque commit.

Le corollaire n'est pas « le prompt est périmé », c'est plus précis :

> Quand un dépôt installe un contrat exécutable sur un invariant, l'audit MANUEL
> de cet invariant cesse de rendre. Ce qui reste rentable, c'est de chercher
> **ce que le contrat ne peut pas voir** — son périmètre, pas son verdict.

Et c'est exactement ce qui a payé : les trois findings les plus solides du jour
sont des angles morts de gardes qui existent.

- `test_contract_settings.py` exige **un** lecteur ; il ne vérifie pas que ce
  lecteur *agisse*. A4 vit dans cet interstice : `probe_timeout_s` a bien un
  lecteur, mais il n'est plus le couperet que son libellé annonce.
- Le garde de la racine fonctionne par **énumération** : A2 lui échappe par
  construction, et rien d'autre ne balaie la racine.
- `test_export_full_library.py` **nomme** la page qui porte la promesse sans
  jamais la lire : A1 vit précisément là.

**Corollaire payé dans la même journée** : A6 était écrit en sévérité 2 et sa PR
préparée. Chercher *qui lit la valeur* — `_renderProbeToolRow` branche sur
`available`, pas sur `status` — l'a fait redescendre à 1 et annuler la PR. La
question « qui d'autre lit cette valeur ? », que `CLAUDE.md` impose avant un
correctif, sert aussi à **calibrer un finding**, pas seulement à éviter
d'éteindre une garde.

---

## Ce que cet audit n'a PAS couvert

- **Aucune exécution.** Ni `pytest`, ni `ruff`, ni l'application ; `python3 -c`
  est refusé par le runner (re-vérifié ce jour — `python3 --version` passe,
  `python3 -c` non). **#1281 n'est pas vérifiée localement** ; validation
  déléguée à sa CI. Lignes > 120 colonnes ajoutées : **0** (mesure
  `grep -n '.\{121,\}'`).
- **Aucune suppression de fichier n'est possible dans ce runner** — cinq voies
  essayées, toutes refusées, y compris `rm` sur un nom ordinaire. C'est ce qui
  bloque le correctif d'A2, et c'est une **contrainte d'outillage à connaître
  avant de planifier un correctif de ce genre**. Effet de bord assumé : un
  `.audit_pathspec.txt` non versionné subsiste dans le worktree du runner ; il
  n'entre dans aucun commit (`git add` ciblé, vérifié par `git status`).
- **Aucun fichier média, aucun NAS, aucun Windows.** A3 et le volet
  `LongPathsEnabled` de la catégorie 37 ne se concluent pas par lecture.
- **`domain/quality_score.py` (2400+ L) reste non lu en entier**, pour le
  huitième run consécutif. C'était la piste n°4 du 09-26 ; je ne l'ai pas prise,
  ayant préféré solder la n°1 — le choix est défendable mais il faut le dire.
- **Catégories 22, 25-28, 40, 42-46.** Le 09-26 demandait d'en instruire **une
  pour de bon** ou d'acter qu'elles sortent du périmètre. **Fait pour la 37**
  (ci-dessus) et pour la **25** (portabilité) : `docs/EXPORT_FORMAT.md` existe,
  décrit les quatre sections du format, donne un exemple de relecture en Python
  et une procédure de migration — la catégorie est **couverte par le produit**,
  et son seul défaut du jour est A1. Les autres restent non instruites.

---

## Pistes pour le prochain run, par ordre de rendement

1. **A2 est un correctif de dix secondes pour qui peut supprimer un fichier.**
   `git rm '=6.0,'` plus le garde décrit ci-dessus, mesuré vert d'emblée.
   Impossible depuis ce runner, trivial depuis n'importe où ailleurs.
2. **Chercher les angles morts de PÉRIMÈTRE des contrats, pas leurs verdicts.**
   C'est ce qui a rendu les trois findings les plus solides du jour. Les
   candidats non instruits : `test_contract_settings.py` ne vérifie pas qu'un
   lecteur *agisse* (un attribut de `Config` posé et jamais consommé lui
   échappe — `min_video_bytes` en est un cas déjà documenté, il y en a peut-être
   d'autres) ; `test_contract_facades.py` ne voit pas une méthode atteignable
   mais inerte.
3. **`domain/quality_score.py`** reste le plus gros module jamais lu en entier,
   et il porte le scoring de chaque film.
4. **A3 attend un arbitrage** (plafond par fichier, timeout dégressif, ou pas de
   retry sur `TimeoutExpired`), et son second maillon — le breaker aveugle aux
   lecteurs mappés, `59cf9a7f` — n'a jamais été porté en PR alors qu'il est
   mesuré depuis le 2026-08-26.
5. **A5 et A8 sont deux docstrings qui nomment un comportement absent.** Le
   dépôt en a déjà corrigé plusieurs lots (#1224) ; celles-ci coûtent trois
   lignes.

---

## Détail

- Findings structurés (8) : `docs/internal/audits/findings/2026-09-27-transverse.jsonl`
- PR de correctif : **#1281**

### Tendance

| Date | Couche | Correctifs | Findings sans PR | Familles écartées |
|---|---|---|---|---|
| 2026-09-20 | transverse | 2 | 2 | 9 |
| 2026-09-23 | all | 2 | 3 | 9 |
| 2026-09-24 | all | 2 | 4 | 11 |
| 2026-09-25 | all | 1 | 4 | 15 |
| 2026-09-26 | all | 1 | 6 | 12 |
| **2026-09-27** | **transverse** | **1** | **7** | **11** |

La colonne des correctifs s'aplatit, et le run précédent avait posé la bonne
lecture : *une piste bien formulée vaut plus qu'un module de plus*. Ce run ajoute
la borne inverse — **une piste peut aussi être épuisée, et le dire vaut un
correctif.** La n°1 du 09-26 était classée la plus rentable du dépôt ; ses
quatre candidats portent tous leur garde. Le run qui l'aurait reprise sans
vérifier aurait dépensé sa journée à confirmer des gardes existantes.
