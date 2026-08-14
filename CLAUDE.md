# CineSort — contexte projet

<!--
Ce fichier est a la RACINE parce que c'est le seul emplacement charge
automatiquement (avec .claude/CLAUDE.md). Jusqu'au 2026-08-03 il vivait dans
docs/internal/CLAUDE.md : 570 lignes que personne ne chargeait jamais.

Regle de maintenance : viser < 200 lignes. Pour chaque ligne, se demander
« est-ce que la retirer ferait commettre une erreur ? » Sinon, la couper.
Un fichier gonfle fait IGNORER les instructions qu'il contient.
Ce qui est derivable du code n'a rien a faire ici. L'historique des sessions
est dans docs/internal/CLAUDE_HISTORY.md, l'etat detaille dans
docs/internal/CLAUDE.md.
-->

Application desktop Windows qui trie et renomme une bibliotheque de **films** :
scan, identification (NFO / TMDb / OMDb), score qualite, detection de doublons,
puis **apply** qui renomme et deplace des fichiers sur disque, avec undo.

Reponds en **francais**.

## Regles inviolables

1. **Ne JAMAIS renommer le fichier video.** Uniquement les DOSSIERS. Les noms de
   fichiers doivent rester synchrones avec les torrents, sinon le seeding casse.
   Tout template de nommage s'applique au nom de dossier.
2. **Ne jamais mutiler un titre.** Une heuristique qui *peut* amputer un titre
   doit etre abandonnee, pas iteree. Lecon acquise : 2 passes de revue sur une
   detection de pack TV ont produit 4 bugs de mutilation, chaque correctif
   ouvrant un nouveau trou (« Fahrenheit 451 » lu comme S04E51...).
3. **Actions destructives** : confirmation supplementaire avec la liste des
   elements, la consequence, et un delai de 3 s au-dela de 50 elements.
4. **`sqlite3.Error` n'herite PAS de `OSError`.** Un `except OSError` ne
   l'attrape pas. Ce piege a deja avorte des apply APRES un deplacement fait
   sur disque, laissant un etat mixte non annulable.

## Commandes

L'interpreteur du projet est **`.venv/Scripts/python.exe` (3.13)**. Le `python`
global est en 3.12 et produit des echecs massifs trompeurs.

```bash
# Tests — perimetre EXACT de la CI (ne pas ajouter --timeout, non installe)
./.venv/Scripts/python.exe -m pytest tests/ \
  --ignore=tests/e2e --ignore=tests/e2e_dashboard --ignore=tests/e2e_desktop \
  --ignore=tests/manual --ignore=tests/live --ignore=tests/stress -q

# Lint et formatage — la version EXACTE compte (cf. section Pieges)
uvx ruff@0.16.1 check .
uvx ruff@0.16.1 format --check .

# Contrats d'architecture (l'executable, PAS `python -m importlinter`)
./.venv/Scripts/lint-imports.exe

# Lancer le REST sans interface (localhost ; --public pour ouvrir au LAN)
./.venv/Scripts/python.exe app.py --api --port 18642

# Build EXE (exige .venv313)
build_windows.bat
```

La suite complete prend ~9-12 min en local, ~22 min en CI. Cibler ses tests.

## Architecture

Quatre couches, **verrouillees par import-linter en CI** (`.importlinter`) :

```
ui/api/   6 facades (run, settings, quality, integrations, library, runtime)
   |      + modules *_support.py qui portent les use-cases
   v
app/      orchestration (apply_core, plan_support_*, jellyfin_sync...)
   v
domain/   metier pur (scoring, tiers, naming, matching, perceptual)
   v
infra/    I/O (SQLiteStore + 10 repositories, clients TMDb/Plex/Jellyfin/Radarr,
          serveur REST)
```

Contrats, libelles **exacts** tels qu'ils apparaissent dans un echec CI (ce sont
des phrases, pas des identifiants — cherchez-les tels quels dans `.importlinter`) :
`Domain ne doit importer ni app, ni infra, ni ui`
`Infra ne doit importer ni app, ni ui`
`App ne doit pas importer ui`

**Front** : `web/dashboard/` uniquement (ESM vanilla, aucun framework). Il n'y a
plus de `web/views/` ni `web/components/` de premier niveau — ne pas chercher de
duplication desktop/dashboard, elle n'existe plus.

**API REST** : `POST /api/<facade>/<methode>`. Les chemins historiques
`/api/<methode>` renvoient 404.

## Pieges qui ont deja coute cher

**`ruff --fix` en aveugle CASSE le depot.** `cinesort/app/plan_support.py` et
`cinesort/domain/probe_models.py` sont des modules de **re-export** : leurs
symboles prives, consommes par les tests, ne sont pas dans `__all__`, donc F401
les supprime. Mesure : 37 re-exports effaces, 2 fichiers de tests ne collectaient
plus, et pytest s'arretait AVANT d'executer quoi que ce soit — un « 0 echec »
trompeur sur une batterie amputee. Les deux modules sont en `per-file-ignores`.

**ruff est epingle EXACTEMENT** (`ruff==0.16.1`) en **5 endroits** qui doivent
rester synchrones : `pyproject.toml`, `requirements-dev.txt`,
`.pre-commit-config.yaml` (rev du hook), `uv.lock` — et **CE FICHIER**, qui
porte la commande que tout le monde copie. Trois versions differentes
avaient coexiste : un developpeur formatait avec une version que la CI rejetait.
Le test `test_ruff_version_is_identical_everywhere` echoue si elles divergent.
Toute montee de version doit etre **deliberee**, avec le reformatage dans le
meme commit — sinon tout le depot devient non conforme du jour au lendemain.

**Les erreurs de setup pytest n'apparaissent PAS dans un grep `FAILED`.** Ce sont
des `ERROR at setup`. 46 tests `[chromium]` ont ainsi echoue en silence pendant
des mois. Toujours lire le resume complet, pas seulement les lignes `FAILED`.

**`VERSION` est duplique** dans le fichier `VERSION` et dans `pyproject.toml` :
les deux doivent bouger ensemble.

**Windows** : les verrous de fichiers (WinError 5/32) rendent instables les tests
qui deplacent des dossiers sous charge. **Cette phrase a longtemps servi de
fourre-tout** : deux causes MESUREES se cachaient derriere (issue #960), et
« rejouer en isolation » ne prouve rien contre elles — le test passe seul parce
qu'il ne subit plus la charge de ses voisins, pas parce qu'il est sain.

1. **`%TEMP%` sature** — defaut REEL, mais **PAS** la cause du `WinError 5`.
   La suite y laissait **259 dossiers par execution** et rien ne les purge
   (26 059 avaient ete trouves) ; la CI ne le voit jamais, runner neuf a chaque
   fois. `tests/_temp_leak_guard.py` compte desormais la fuite (il redirige
   `%TEMP%` vers un bac a sable) et fait echouer la session au-dela de la borne.

   Ce fichier a affirme qu'au-dela de quelques milliers d'entrees le renommage
   partait en `PermissionError [WinError 5]`. **Experience controlee (#965), une
   seule variable, bras alternes, dossier neuf a chaque tour :**

   ```
   %TEMP% VIDE   a chaque tour : 10/30 echecs (33 %)
   %TEMP% SATURE (7 000 dirs)  :  6/30 echecs (20 %)
   Fisher exact bilateral      : p = 0,38
   ```

   L'echec se produit donc dans un `%TEMP%` **parfaitement vide**, une fois sur
   trois, et l'ecart entre les deux bras n'est pas distinguable du hasard. La
   saturation n'est ni necessaire, ni demontree comme aggravante.

   Une premiere version de l'experience concluait l'inverse (2/12 contre 5/12) :
   son bras « vide » **se remplissait au fil des tours** — les deux echecs y sont
   tombes aux tours 6 et 10 — et les deux bras s'executaient l'un apres l'autre.
   Elle mesurait une saturation progressive, pas son absence.
2. **Les threads de fond de l'app survivent au test.** Ils continuent d'ecrire
   dans le `state_dir` du test, au point de le **recreer** juste apres le
   `rmtree` du `tearDown` (12 dossiers sur 13 pour `test_api_bridge_lot3.py`),
   et de tomber sur le dossier d'un test VOISIN en cours de renommage. Nettoyer
   le tmpdir d'un test qui a pilote l'API passe par
   `tests/_helpers.py::cleanup_test_tree`, qui joint ces threads d'abord.
3. **Le `WinError 5` lui-meme reste INEXPLIQUE (#965)** — et c'est la SEULE
   cause connue de cette signature. Il se reproduit a **33 %** dans un `%TEMP%`
   neuf et vide, sur `apply` (renommage d'un DOSSIER de film), y compris sur le
   garde anti-destruction de la racine de bibliotheque. Ce n'est donc ni un
   defaut d'`undo`, ni un effet de la charge, ni un effet de la saturation.

   Deja ecarte par lecture, ne pas y revenir : `sha1_quick` ferme son handle
   (`with`), et les deux `os.scandir` sans context manager sont fermes en
   `finally`. Reste a instrumenter quel handle est ouvert a l'instant du rename.

   **« Rejouer en isolation » ne prouve RIEN sur cette famille** : le meme
   fichier est vert seul et rouge en suite complete, et le cas de #965 est rouge
   *en* isolation. Attribuer un nouvel echec a l'une des causes 1 ou 2 demande
   une MESURE, pas une ressemblance — c'est en s'en dispensant que ce fichier
   avait affirme une causalite que l'experience a ensuite refutee.

**UNE SONDE PEUT ETRE JUSTE ET SON PERIMETRE FAUX.** Le 2026-08-13, une sonde
d'imbrication des connexions SQLite lancee sur les seuls **tests de
repositories** a rendu « profondeur maximale **1** ». Une conception de partage
de connexion en a ete tiree, ecrite dans le code et dans un message de commit.
La meme sonde sur le perimetre CI **complet** rend **2** (20 049 ouvertures) — et
la profondeur 2 est exactement le cas ou partager un handle **deplacerait les
frontieres de commit**, donc la durabilite d'une application qui deplace des
fichiers.

Deux contre-feux, tous deux payes ce jour-la :

- mesurer sur le perimetre **ou le comportement peut vivre**, pas sur celui qui
  est commode ;
- **capturer la PILE**, pas seulement le chiffre. Elle a nomme la source unique
  (`repositories/quality.py:get_global_tier_distribution`, une verification de
  schema faite sous une connexion deja ouverte — **1 site sur tout le depot**),
  la ou « profondeur 2 » obligeait a tout remesurer.

**NE JAMAIS INSERER ENTRE UN DECORATEUR ET SA FONCTION.** Le 2026-08-14, une
fonction d'aide posee juste au-dessus de `check_duplicates` s'est glissee SOUS
son `@requires_valid_run_id`. Le decorateur s'appliquait donc a l'aide, et
l'endpoint perdait TOUTE validation de son `run_id` — un identifiant arbitraire
atteignait la couche base. Aucune erreur, aucun avertissement : le fichier reste
syntaxiquement valide et l'aide, elle, marche.

Sept tests l'ont dit, et seulement parce que le nombre de verts a ete COMPARE a
celui de `main` (510) au lieu d'etre suppose. Apres toute insertion pres d'un
`def`, verifier que le decorateur qui le precedait le precede toujours.

**CHERCHER LE GARDE AVANT D'EN ECRIRE UN.** Le 2026-08-13, deux classes CSS
posees par le JS et definies nulle part (dont `.v5-help-fab`, le bouton flottant
d'aide, sans style depuis la premiere release publique). Sonde, cliquet, liste
d'exemptions et batterie de mutation ont ete ecrits pour les garder — et le
commit **comme la PR** affirmaient qu'« aucun test du depot ne pouvait le voir ».

**Faux.** `tests/test_contract_css.py` porte cet invariant depuis 2026-07, avec
une extraction plus large (`class=`, `cls:`, `querySelector`, `closest`,
`matches`) et une baseline de **197 entrees qui ne peut que RETRECIR**
(`tests/contract_baselines/css_used_undefined.json`). Les deux classes y
figuraient : pas invisibles, **inscrites comme dette acceptee**.

Le cout n'est pas le travail perdu mais l'**affirmation fausse publiee**, et un
second garde plus faible qui aurait dilue le vrai. Trois contre-feux : chercher
dans `tests/contract_baselines/` et `ls tests/ | grep -i contract` avant d'ecrire
un garde ; ne jamais ecrire « aucun test ne voit ca » sans l'avoir cherche ; et
**lancer la suite COMPLETE sur la branche**, pas ses propres tests plus `ruff` —
c'est ce qui avait ete saute, et le perimetre qu'on choisit soi-meme penche vers
ce qu'on attend, exactement comme le filtre `-k`.

**UNE COULEUR SE LIT AU RENDU, PAS DANS LE CSS.** `--surface-1` a `--surface-3`
valent **0,035 a 0,12 d'alpha** sur TOUS les themes : une regle qui les emploie
comme fond parait opaque a la lecture et rend un element translucide. Le fond
d'une surface qui doit masquer ce qu'il y a dessous s'ecrit
`var(--bg-base, #1a1a1a)` — c'est deja le correctif de `.duplicate-modal`, dont
le commentaire dit meme « verifier en runtime via Playwright getComputedStyle ».
Repris quand meme le 2026-08-13 (#1063). Et pour un etat de SURVOL, **superposer**
un voile (`inset` box-shadow) plutot que REMPLACER le fond, sinon l'element
devient plus transparent au survol qu'au repos.

Deux pieges de la mesure elle-meme, payes dans la foulee :

- **les themes s'appellent `studio` / `cinema` / `luxe`** (`[data-theme=...]`),
  pas `light` / `dark` : basculer sur un nom inexistant ne selectionne RIEN et
  rend quatre fois la meme valeur, ce qui ressemble a « stable sur tous les
  themes » ;
- **le cache du navigateur sert l'ancien CSS** et rend donc la mesure d'AVANT
  apres le correctif. Suffixer les liens par l'empreinte du fichier sur disque.

Enfin : **ne pas demarrer `app.py --api` pour une verification visuelle** — le
cron de purge TTL demarre avec, et il agit sur la bibliotheque REELLE. Charger
les feuilles declarees par `index.html` dans une page de controle suffit.

**UNE SONDE DE MUTATION QUI REECRIT LES FINS DE LIGNE.** `read_text()` normalise
`CRLF` -> `\n`, `write_text()` refait l'inverse : muter puis restaurer par ces
deux appels **reecrit le fichier entier** tout en satisfaisant son propre
`assert restaure == original` (comparaison sur du texte normalise). Signature :
`git status` montre le fichier modifie alors que `git diff --stat` est **vide**.
Consequences vecues : worktree « sale » qui fait abandonner la sonde suivante, et
ancres en `\n` qui ne matchent plus rien — 0 occurrence, donc AUCUNE mesure.
Travailler en **binaire**, avec la fin de ligne reelle du fichier :

```python
fin = b"\r\n" if brut.count(b"\r\n") > brut.count(b"\n") // 2 else b"\n"
ancre = texte.encode().replace(b"\n", fin)
```

C'est le compteur d'occurrences AVANT mutation qui l'a revele — sans lui la sonde
mutait zero ligne et rendait « 0 survivant », soit un faux vert.

**`dry_run=True` EST LE DEFAUT des routes de reinitialisation.** `reset_database`
et `reset_all_user_data` sont en apercu par defaut depuis le durcissement des
purges. Une mesure qui oublie `dry_run=False` ne mesure **rien** : elle observe un
chemin qui ne touche a aucun fichier, et conclut que tout va bien.

**LE CHECKOUT PRINCIPAL PEUT ETRE SUR UNE BRANCHE PERIMEE.** Une mesure du
comportement de `reset_database` a tourne dans le checkout principal du depot,
reste sur une branche **anterieure** a ce durcissement : elle portait sur du code
qui n'etait plus celui de `main`. Un worktree dit quelle branche il porte ; le
checkout porte la sienne — `git branch --show-current` avant toute mesure de
comportement.

(Et ce paragraphe a lui-meme rougi `test_release_hygiene.py` en nommant le chemin
absolu : **aucun chemin personnel dans le depot**, le garde l'interdit et son
jeton est code en dur, donc il rougit aussi sur le runner.)

**L'ESPACE DISQUE avant d'accuser son propre changement.** Le 2026-08-08, quatre
tests de `test_apply_disk_check_recursive_v796.py` ont echoue sur une branche
dont le diff ne touchait ni le disque ni l'apply. La cause etait dans le HELPER
de fixture, pas dans le code teste :

```
_sized(folder / "Extras" / "bonus.bin", 80 * MB)
    handle.truncate(size)
E   OSError: [Errno 28] No space left on device      <- 137 Mo libres sur 454 Go
```

Un echec environnemental porte le nom du test qu'il frappe, jamais celui de sa
cause. `df -h` coute une seconde et tranche ; sans lui, on « corrige » du code
sain. `Errno 28`, `WinError 5/32` et `ERR_NO_BUFFER_SPACE` sont tous des
epuisements de ressource — la meme famille, pas des defauts de logique.

Deux pieges de mesure rencontres en reparant :

- **La taille LOGIQUE ment sur les fichiers creux.** Les fixtures fabriquent
  leurs faux `.mkv` par `truncate()`, que NTFS laisse creux : une somme des
  `Length` annoncait **133 822 Go** dans un repertoire, sur un disque de 454 Go.
  Supprimer douze dossiers « de 38 Go » a rendu **0,05 Go**. La seule grandeur
  honnete est l'espace LIBRE mesure avant et apres.
- **Les worktrees s'accumulent en silence** : 212 sur cette machine, ~21 Go.
  `git worktree remove --force` puis `git worktree prune` ; retirer un worktree
  ne supprime PAS sa branche. Archiver `git diff HEAD` avant, la purge etant
  irreversible.

**Les processus de session survivent des JOURS.** Six `python.exe` tournaient
depuis 3 a 5 jours — deux `http.server`, et surtout deux boucles d'entretien de
la cascade du 2026-08-04, campagne close depuis. L'une d'elles appelle
`gh pr update-branch` : elle agissait **encore seule sur le depot**. Tout demon
lance en session doit avoir une condition d'arret, et une fin de campagne doit
inclure son extinction. Un `Get-Process python` en debut de session longue les
revele — ils tiennent aussi des handles, ce qui en fait une piste plausible,
non encore mesuree, pour le `WinError 5` du point 3.

## Conventions

**Titre de PR** — types autorises : `feat fix docs ci refactor test chore perf
build style revert deps sec rel`. `sec` = correctif de securite (CWE identifie),
`rel` = fiabilite (ecriture atomique, fsync, course entre ecrivains).
Un autre type fait rougir le check `PR title linter`, qui **ne bloque PAS** la
fusion : les 7 checks requis par la protection de branche sont `Lint, Tests,
Build` / `Analyze python` / `Analyze javascript-typescript` / `Scan secrets` /
`bandit scan` / `pip-audit` / `mypy check`, et le linter de titre n'en fait pas
partie (verifie 2026-08-03 ; quatre PR en `i18n(...)`, `ui-sec(...)` et
`chore+docs(...)` ont deja fusionne). Respecter la convention reste utile : elle
alimente le classement de Release Drafter.

**Erreurs d'API** : passer par `cinesort/ui/api/_responses.py:err()`, jamais un
`return {"ok": False}` nu.

**Deplacement de fichier** : passer par `cinesort.app.move_journal.atomic_move`
(journalise, donc annulable).

**Migrations SQLite** : ordre `CREATE TABLE` puis `CREATE INDEX`, `IF NOT EXISTS`
partout, idempotentes, et **testees sur une base PRE-EXISTANTE** — pas seulement
sur une base fraiche.

**Tests** : un correctif n'est prouve que si le test a ete vu **ROUGE** sans lui.
Casser le correctif (avec un compteur d'occurrences verifie), constater le rouge,
restaurer, verifier le contenu restaure, revoir le vert. Proscrire les tests qui
comparent une chaine de **code source** : ils tombent quand le code s'ameliore et
ne detectent rien quand il casse.

Quatre pieges de cette famille, chacun ayant produit un faux vert dans une
session qui appliquait pourtant la regle ci-dessus — les trois premiers mesures
le 2026-08-06, le quatrieme le 2026-08-13 :

1. **La panne doit etre injectee a la couche de PRODUCTION.** L'issue #901 avait
   ete fermee sur un test qui passait un `record_op` **qui leve** — forme absente
   du code reel, ou la closure attrape et avale. Le test sautait par-dessus le
   seul endroit ou le defaut vivait. Injecter au niveau du **store**, pas du
   callable.
2. **Un test qui verifie la PRESENCE d'une garde reste vert quand elle est
   neutralisee.** `if (false && condition)` contient toujours `condition` :
   asserter sur la chaine ne prouve rien. Exiger que la garde soit
   **atteignable** (premier terme = la vraie variable), et qu'aucune garde
   desactivee par une constante ne subsiste.
3. **UN MUTANT SURVIVANT N'EST PAS TOUJOURS UN TEST FAIBLE.** Trois survivants
   le meme jour, trois causes differentes, et une seule etait une faiblesse :

   - *argument supplementaire ignore par JS* — mutant EQUIVALENT par
     construction (la fonction ne prend plus de parametre) : remplacer le mutant ;
   - *ligne morte inseree AVANT la vraie* — mutant equivalent par erreur d'ancre :
     viser la ligne qui AGIT ;
   - *assertion satisfaite par une AUTRE source* — vraie faiblesse : « 2 » et
     « cinesort.db » figuraient aussi dans le message du backend, donc
     l'assertion ne prouvait pas le rendu qu'elle visait. **Asserter ce que SEUL
     le correctif produit.**

   Et une quatrieme cause, la plus retorse : **le HARNAIS ne reproduisait pas la
   production**. Un faux DOM rendait eternellement le MEME noeud alors que
   `_refreshAll()` fait `root.innerHTML = ...` et le DETRUIT : deux correctifs du
   « message perdu » ont survecu a leur propre batterie tant que la racine
   factice ne remplacait rien.

4. **Un correctif peut ETEINDRE une garde existante.** Rendre `op_index` honnete
   (il comptait des tentatives) l'a mis a 0 sur un journal verrouille — or il
   servait de preuve « le disque a bouge » a l'alerte d'undo indisponible. Apres
   avoir change la semantique d'une valeur, **grep tous ses lecteurs** et
   asserter sur la **sortie utilisateur** (payload), pas seulement sur la valeur
   corrigee.

**Mesures** : `cProfile` ajoute son cout a CHAQUE appel — il fait paraitre couteux
ce qui est FREQUENT. Sur `connect_sqlite` il attribuait 49 us par `execute` la ou
la mesure directe en donne 1,5. Pour comparer deux variantes, A/B a **bras
alternes** sans profileur (cf. `scripts/mesure_cout_connexion.py`).

## Etat

Version **1.5.2-beta** (les jalons se marquent par des tags `+build`, la version
ne bouge pas). Seuil de couverture CI : **75 %**. Perimetre CI : **9041 tests**
(`passed`, suite complete sur `main` fusionne, mesure du 2026-08-13 ; s'y ajoutent
20 skipped, 2 xfailed et 1619 subtests). Ce nombre se remesure, il ne se recopie
pas — et il se remesure **par la meme commande**, sinon on compare un compte
d'items (`--collect-only`) a un compte de `passed`.

Le bot d'audit quotidien tourne en Opus 5 et est **borne par un budget
d'ouverture** (`.github/audit-prompt.md`) : au plus 3 PR et 5 issues par
execution, zero au-dela de 150 elements ouverts. Sans cette borne il avait
produit un backlog de 177 PR et 248 issues.

### Campagne de remise en etat (2026-08-06) — 7 PR, 5 issues

Plan complet et arbitrages : `docs/internal/TRI_ROUTES_ORPHELINES.md` pour la
vague 3.1 ; le reste vit dans les PR. Ce qui compte pour une session suivante :

- **#982** #901 rouverte : la closure de production AVALAIT l'echec, et
  `op_index` comptait des tentatives — donc `undo_available` mentait.
- **#985** migration 021 : une ligne `errors` orpheline bloquait le demarrage
  **definitivement**. Le correctif est le marqueur `disable_fk`, PAS un filtre —
  le meme SQL est rejoue par `_bootstrap_schema_latest` a chaque auto-reparation,
  et filtrer y detruisait le journal d'erreurs (refute par la passe N26).
- **#988** regle n3 : le seuil vit desormais DANS `dangerConfirmModal`. Quatre
  conventions coexistaient sur 19 sites ; « Lancer l'apply » ne passait ni liste
  ni delai.
- **#989** undo : `UNDONE_NONE` ne consomme plus l'annulation ; le refus du garde
  anti-echappement n'avorte plus le batch (type DEDIE, pas `RuntimeError` nu —
  sinon le rollback atomique ne part plus) ; conflits exposes en donnee ;
  pre-check d'espace sur les DEUX volumes ; cliquet de couverture par module.
- **#990** tri des 60 methodes de facade orphelines : 42 a cabler, et **8 des 9
  retraits proposes ont ete refutes**.
- **#991** durcissement : `dry_run=True` par defaut sur les purges (un POST au
  corps vide supprimait), cle TMDb jetee sur profil neuf, `db_local_guard`
  aveugle aux lecteurs reseau mappes, cliquet sur 68 `except OSError` a risque.
- **#993** politique Compensate : un fichier modifie ne bloque plus la
  restauration des autres.

### Campagne vagues B3 / C / D / E (2026-08-13) — 10 PR, plan A→E SOLDE

- **#1046-#1048** vague D : simulateur de profil, builder de regles custom,
  reglages fins. Sept defauts corriges AVANT fusion, dont trois trouves par revue
  adversaire et quatre par mutation ; **17/17 mutants tues**.
- **#1053** derniere methode B3 : `settings.reset_all_user_data` etait
  INATTEIGNABLE — le backend exige que l'utilisateur TAPE « RESET », et aucune
  modale n'avait de champ de saisie. Trois defauts de la famille « un echec
  devient un succes silencieux » corriges au passage : reset PARTIEL affiche en
  VERT, cle `error` jetee, cache non invalide (la premiere autosave RECREAIT
  `settings.json`). **23/23 mutants.**
- **#1054** instrument de #924 : etat reseau capture a l'instant de l'echec. Le
  hook ne regardait que la phase `call` alors que #924 echoue au **setup** ; et
  `connect_ex` sur un socket a timeout etiquetait « REFUSE » un `WSAEWOULDBLOCK`
  — les deux hypotheses que #924 doit justement separer.
- **#1055** `_close_infra` etait APPELE mais N'EXISTAIT PAS (`hasattr` toujours
  faux, et le test qui le « prouvait » definissait sa propre fausse api). A/B :
  sans lui, un reset laissait `user_version 0` et **21 tables manquantes**, et
  `get_dashboard` repondait quand meme `ok: True`. Purger ne suffisait pas : une
  **barriere** gele la reconstruction pendant tout le wipe, et les deux routes
  REFUSENT tant qu'un run tourne — le `JobRunner` cache est le SEUL verrou
  d'exclusion du depot. **13/13 mutants.**
- **#1056** le retry REST ne couvrait pas `TimeoutError` : trois executions de CI
  rougies le meme jour, sur trois PR aux diffs sans rapport, alors que les memes
  tetes etaient vertes en local.
- **#1057** vague E etape 1 : une connexion par requete REST. **50 -> 25
  connexions**, 35 a 47 % de gain selon la charge, frontieres de commit
  **inchangees**.
- **#1060** vague E **etape 2, la derniere du plan** : la portee du RUN, la ou
  vivent les 60 003 connexions du scan. A/B a bras alternes sur un job de
  400 acces : **407 -> 8 connexions**, mediane 508,8 -> 18,2 ms. Le x28 est un
  **MAJORANT** (job synthetique, lectures pures) ; la reference honnete reste le
  x8,2 mesure sur un scan reel, et la grandeur robuste est le COMPTE.

  Ce qui rend l'etape sure n'est PAS une propriete de SQLite : une connexion de
  run vit des **minutes**, et sous Windows un handle ouvert empeche de SUPPRIMER
  le fichier. C'est le refus « un traitement est en cours » des deux routes
  destructives qui la rend acceptable — `tests/test_portee_du_run.py` eprouve
  cette COMPOSITION, pas seulement le partage. Chaque `_managed_conn` garde son
  `with conn:` : aucune transaction entre deux appels, frontieres de commit
  inchangees. **4/4 mutants**, dont celui qui a montre qu'assertir « en cours »
  ne distinguait PAS le refus du verrou de fichier (les deux messages le
  contiennent).
- **#1059** le mot a taper etendu a la purge du bucket `_review`, et le CRITERE
  ecrit dans la docstring de `dangerConfirmModal` : perte irrecuperable par
  l'application **et** portee non choisie par l'utilisateur.
- **#1049** un bouton de dimension mort par construction (`director` : la branche
  rendait `None` quoi qu'il arrive). Deux constats de revue retenus, **remedes
  corriges** : la sortie immediate proposee amputait le payload de `ok` et `by`,
  et « assouplir » l'extraction des DIMENSIONS l'aurait fait echouer plus
  SILENCIEUSEMENT — elle est donc devenue plus stricte, avec un message qui nomme
  la cause au lieu d'accuser la vue.
- **#1062** `purge_review_bucket_all` pose `ok: true` a la CONSTRUCTION de son
  payload et ne le rediscute jamais : ses echecs vivent dans `errors`. L'ecran ne
  lisant que `deleted`, une purge dont TOUS les fichiers ont resiste affichait
  « ✓ 0 fichier(s) supprimé(s) » en vert — juste apres avoir fait TAPER « VIDER ».
  Corrige cote ECRAN : mettre `ok` a faux des qu'`errors > 0` ferait passer pour
  un echec une purge ou 299 sur 300 sont partis. **4/4 mutants**, dont le
  contre-test « une purge reussie reste verte » verifie comme non satisfait par
  une autre source (l'inventaire ecrit lui aussi `--ok` dans une zone voisine).
- **#1061** deux classes CSS posees par le JS et definies nulle part —
  `.v5-help-fab`, monte a chaque demarrage du shell, et `.modal-open`. Baseline
  du contrat CSS : **197 -> 195**. Voir le piege « chercher le garde avant d'en
  ecrire un ».
- **#1063** suivi immediat : la regle de #1061 etait opaque **en lecture** et
  translucide **au rendu** (`--surface-2` -> `rgba(255,255,255,0.055)`). Cf. le
  piege « une couleur se lit au RENDU ».

### Depilage du backlog d'audit (2026-08-14) — 11 PR

Les trois PR du bot du jour, PUIS les constats que ses rapports precedents
avaient **verifies mais laisses sans PR**, faute de budget d'ouverture.

- **#1066 PERTE DE DONNEES**, et c'est la seule de ce niveau. La garde
  anti-jonction de #941 ne testait pas la RACINE transmise, or la production
  n'entre jamais par le bucket entier. Reproduit avec une vraie jonction
  Windows : l'ecran annonce **1 fichier**, l'application en supprime **4**, dont
  **3 dans la bibliotheque** — et rapporte `errors: 0`, un succes franc. La
  regle n3 exige une LISTE ; elle etait affichee, et fausse dans le sens
  permissif.

  En mutant ses TROIS gardes separement : `_purge_dir_recursive` a **quatre**
  appelants, pas trois. Les deux gardes ajoutees couvrent `iterdir()` ; les deux
  autres passent `root / sub` sans garde, et seule la garde du PARCOURS les
  protege — elle n'etait eprouvee par personne. Test ajoute, **3/3**.
- **#1067** un `cap_max` non numerique valait 0, donc un PLAFOND a 0 : score
  80 -> **0**, tier **Reject** (seuil < 25), et `motifs: []` — totalement muet.
  Le sac que l'utilisateur vide. **4/4 mutants.**
- **#1068** le lookahead « pas DVD » mordait `DV.DDP`, `DV.DTS-HD` : **3 des 4**
  formes reelles de release 4K perdaient leur Dolby Vision. Le lookahead
  RESTANT etait mort pour la meme raison — equivalence prouvee sur **15 561
  cas**, `\b` etant strictement plus fort. **3/3 mutants**, dans les deux
  directions (ne plus detecter, et detecter trop).
- **#1070 a #1075** les restes sans PR : un retour mort ET trompeur, deux
  homoglyphes cyrilliques (garde a ZERO exemption sur `cinesort/`), le repli
  d'etat RELATIF (`./CineSort` : lancer l'app d'ailleurs ouvrait silencieusement
  une AUTRE base, 133 sites d'appel), deux frontieres d'exception asymetriques,
  une docstring qui decrivait l'INVERSE du code, un test de contrat qui lisait
  le SOURCE, `delta_reject` qui comptait `|A \ B|` au lieu de `|A|` (mesure :
  **1 au lieu de 0**), et la moyenne de la courbe Qualite passee PAR FILM
  (30,0 -> 50,0 sur le scenario discriminant, soit Bronze -> Silver).
- **#1076** le scan gitleaks complet n'avait tourne qu'UNE fois, par accident.
  Relance : **56 detections, ZERO secret reel** — exemples `curl` de la doc,
  journaux de suites de tests, fixtures, et un NOM DE CLE de reglage signale par
  entropie. Desormais HEBDOMADAIRE, avec les 56 empreintes figees.
- **#1077** le nombre de groupes de doublons est desormais RANGE la ou il est
  deja calcule (l'ouverture de l'ecran Doublons) et non au scan, ou il couterait
  « ~1000 films + un parcours disque » (#406). L'absence vaut **INCONNU**, pas
  zero : l'ecran a trois etats.

**TROIS ISSUES OUVERTES ETAIENT DEJA CORRIGEES** — #984, #972, #1002. Mesurees
avant d'ecrire une ligne : la garde d'unicite de #984 existe
(`run_id_est_utilise` interroge les tables filles), le commentaire faux de #972
est devenu un predicat nomme, et la fixture `scan_actif` de #1002 existe et
explique meme pourquoi elle n'a pris aucune des deux directions proposees. Avec
le contrat CSS de la veille, cela fait **quatre** implementations redondantes
evitees en deux jours. **Re-mesurer avant de coder, y compris sur une issue
ouverte.**

**Constats d'audit ECARTES apres mesure** — ne pas les re-instruire :

- « transaction `pragma_history` laissee ouverte » : NE SE REPRODUIT PAS
  (3 scenarios, `in_transaction=False` et `BEGIN ok` a chaque fois) ;
- « les films ecartes partent en %LOCALAPPDATA% » : la quarantaine des NON
  APPROUVES reste sous `cfg.root`. Ce sont les bacs conflits / doublons /
  marques-pour-suppression qui sont ailleurs (6 sur 7, mesure) ;
- « ~14 PRAGMA par appel expliquent le cout de `connect_sqlite` » : les MEMES 8
  PRAGMA coutent **x139** sur un handle neuf. Ce n'est pas leur nombre —
  en retirer 6 sur 14 rend 1,7 %. Le gain est dans la REUTILISATION.

Ecarts entre les chiffres annonces et mesures : 78 -> 68 `except OSError`,
53 -> 60 routes orphelines. **Remesurer avant de coder.**

Detail et historique : `docs/internal/CLAUDE.md` et
`docs/internal/CLAUDE_HISTORY.md`.

## Dette technique connue

Les chiffres ci-dessous ne se recopient pas : ils se **remesurent**.

```bash
# Sur Windows, PYTHONIOENCODING=utf-8 est OBLIGATOIRE : le script plante sinon
# en ecrivant son propre rapport (UnicodeEncodeError cp1252 sur un caractere
# non-ASCII).
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/measure_codebase_health.py
```

Mesure du 2026-08-03 : **230 fichiers Python, 91 224 LOC**. Les regles ruff
tolerees (hors barriere CI) donnent la forme de la dette : `PLR2004` 394
(constantes magiques), `RUF100` 185 (noqa devenus inutiles), `C901` 168
(complexite), `PLR0913` 153 (trop de parametres), `BLE001` 41 (except nu).
Neuf modules depassent 1 000 lignes, tous dans `ui/api/` et `app/` — c'est la
que la refonte paie le plus. Le plan associe est
`docs/internal/audit_v7_8_0/REMEDIATION_PLAN_v7_8_0.md`.

`tests/test_doc_consistency.py` verifie que cette section reste presente et que
ce fichier ne revendique pas de note de sante inventee. Il lit **`/CLAUDE.md`**,
pas `docs/internal/CLAUDE.md` : une refonte de ce fichier qui supprime ces
references fait echouer la CI — c'est arrive le 2026-08-03, ou la creation de ce
fichier a transforme 4 tests jusque-la **skippes** (la racine n'avait pas de
`CLAUDE.md`) en 4 echecs sur `main`.
