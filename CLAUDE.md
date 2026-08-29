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
uvx ruff@0.16.3 check .
uvx ruff@0.16.3 format --check .

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
`/api/<methode>` renvoient **410 Gone** (`rest_server.py:1341`), avec un message
qui guide vers la facade. Ce fichier a longtemps dit 404 : un 410 se distingue
d'un 404 pour un client, et `docs/internal/CLAUDE.md:190` disait deja 410.

## Pieges qui ont deja coute cher

**`ruff --fix` en aveugle CASSE le depot.** `cinesort/app/plan_support.py` et
`cinesort/domain/probe_models.py` sont des modules de **re-export** : leurs
symboles prives, consommes par les tests, ne sont pas dans `__all__`, donc F401
les supprime. Mesure : 37 re-exports effaces, 2 fichiers de tests ne collectaient
plus, et pytest s'arretait AVANT d'executer quoi que ce soit — un « 0 echec »
trompeur sur une batterie amputee. Les deux modules sont en `per-file-ignores`.

**ruff est epingle EXACTEMENT** (`ruff==0.16.3`) en **5 endroits** qui doivent
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
3. **Le `WinError 5` est MITIGE et son issue est CLOSE (#965, PR #969 fusionnee
   le 2026-08-05)** — mais la cause profonde reste inconnue. Distinguer les deux,
   ce paragraphe a longtemps presente le defaut comme ouvert et a corriger :

   - **corrige** : `renommer_avec_reprise` (`app/move_journal.py`) rend **0 echec
     sur 25** la ou `main` nu en donnait 8/20. Bras alternes : 10/20 contre 0/20,
     Fisher `p ~ 0,0003`. Il ne se reproduit plus a 33 % : il ne se reproduit plus.
   - **toujours inconnu** : **QUEL** handle. La fenetre se compte en microsecondes
     — la seule presence d'une enveloppe Python autour de `Path.rename` suffisait
     deja a faire disparaitre l'echec. La reprise ferme la consequence, pas la
     question, et elle ne masque rien : un verrou REEL epuise les paliers et
     l'exception d'origine remonte.

   Deja ECARTE PAR LA MESURE, ne pas y revenir : la saturation de `%TEMP%`
   (10/30 a vide contre 6/30 sature, `p = 0,38`) ; un cycle de references
   (`gc.collect()` force : 3/25 contre 4/25) ; `sha1_quick` (ferme son handle via
   `with`) et les deux `os.scandir` (fermes en `finally`).

   **Si la signature revient MALGRE la reprise**, c'est un verrou *persistant* —
   une bete differente — et il faut rouvrir #965 avec cette information.

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
atteignait la couche de persistance. Aucune erreur, aucun avertissement : le fichier reste
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

**UNE ISOLATION DE TEST SE VERIFIE — LA VARIABLE PEUT N'ETRE LUE PAR PERSONNE.**
Le smoke test PyInstaller posait `CINESORT_STATE_DIR` « pour ne pas polluer ».
Cette variable n'est lue **nulle part** sous `cinesort/` : l'etat se resout par
`%LOCALAPPDATA%/CineSort` (`infra/state.py:default_state_dir`). Le test demarrait
donc l'application **packagee** sur l'etat REEL de l'utilisateur — vraie base
SQLite, vrais reglages, vraie racine de bibliotheque. Un `grep` de la variable
dans le code de PRODUCTION coute cinq secondes et tranche.

L'ampleur n'etait pas celle qu'une premiere sonde montrait. Une sentinelle qui
surveillait 4 fichiers temoins a nomme **3** tests ; le garde qui compte TOUTE
entree creee en a nomme **130** — le cache de sonde vit sous
`default_state_dir()/cache/probe`. `tests/_etat_reel_guard.py` redirige
desormais `LOCALAPPDATA` pour toute la session et **attribue** au lieu
d'interdire (meme parti que `tests/_temp_leak_guard.py` pour `%TEMP%`). Corriger
les 3 sites n'aurait rien regle : le depot compte **338** `CineSortApi()` nus
dans **144** fichiers.

Trois pieges de cette famille, tous payes le 2026-08-15 :

- **`terminate()` ne tue pas un bundle *onefile*.** `Popen` demarre le
  BOOTLOADER, qui lance l'application dans un processus ENFANT. L'enfant
  survivait et gardait `.cinesort.lock`, donc l'execution suivante sortait sur
  « Another CineSort instance is already running » — un echec **un tour sur
  deux, parfaitement alterne**. Un motif alterne n'est jamais du hasard : c'est
  un etat partage entre executions. Remede : `taskkill /T`, par chemin absolu
  **et litteral** (une variable fait perdre a l'analyse la preuve que la
  commande est fixe).
- **Un test peut ne passer QUE parce qu'il reutilise un etat provisionne.** Une
  fois reellement isole, l'exe ne demarrait plus : en `--api` le serveur refuse
  sans jeton, et il sort en code 1 avec stdout, stderr **et** journal vides
  (build sans console).
- **Rediriger `LOCALAPPDATA` casse Playwright**, qui range ses navigateurs sous
  `%LOCALAPPDATA%\ms-playwright` : 52 tests `[chromium]` en **ERROR at setup**,
  donc invisibles dans un grep `FAILED`. Le compte le disait au chiffre pres
  (9071 au lieu de 9121). D'ou `PLAYWRIGHT_BROWSERS_PATH` fige avant la
  redirection.

**L'ASCENDANCE MENT SUR CE DEPOT — IL FUSIONNE EN SQUASH.** Le SHA d'une branche
n'entre jamais dans `main` : `git branch --merged`, `git log main..branche` et
`git cherry` la declarent donc **non fusionnee** meme quand son travail est
livre. Le 2026-08-15, 104 branches distantes sur 105 presentaient cette
signature — 1 commit devant `main`, PR **CLOSED** et non MERGED. La lecture
evidente (« 104 branches mortes ») etait fausse dans les DEUX sens :

- **59 d'entre elles etaient l'unique exemplaire** de 117 rapports d'audit
  absents de `main` (2026-05-25 au 2026-08-02). Les supprimer aurait detruit
  trois mois d'historique — le motif exact de #990, ou 8 des 9 retraits proposes
  avaient ete refutes ;
- **4 portent un correctif de code toujours absent** de `main` et qui s'y
  applique encore proprement, dont deux de securite (voir « Branches conservees »).

Le seul controle qui tranche est le **CONTENU**, jamais l'ascendance : comparer
les blobs **en binaire** (`read_text` decode en cp1252 et plante sur un rapport
accentue ; une comparaison en mode texte a rendu « 0/117 identiques » la ou le
binaire en rend **117/117**), et pour un correctif, tester s'il **s'annule** sur
`main` (`git apply --check -R`). `git cherry` ne suffit pas non plus quand un
commit melange le correctif ET son rapport : le patch-id diffère alors meme si le
code a ete repris — il a rendu « 42 non appliques » la ou le test par fichier en
trouve 3 deja presents.

**Les processus de session survivent des JOURS.** Six `python.exe` tournaient
depuis 3 a 5 jours — deux `http.server`, et surtout deux boucles d'entretien de
la cascade du 2026-08-04, campagne close depuis. L'une d'elles appelle
`gh pr update-branch` : elle agissait **encore seule sur le depot**. Tout demon
lance en session doit avoir une condition d'arret, et une fin de campagne doit
inclure son extinction. Un `Get-Process python` en debut de session longue les
revele — ils tiennent aussi des handles. (Cette piste visait le `WinError 5` du
point 3, desormais mitige : elle ne vaut plus que si la signature revient.)

**UN SECRET EN PROSE ECHAPPE A GITLEAKS, ET LE SCRUBBER EST BORGNE SUR
`ntoken=`.** Le 2026-08-26 : le jeton Bearer REST **actif** de l'utilisateur
etait en clair dans `docs/internal/BILAN_ITER4_2026-06-08.md:272` et
`BILAN_ITER13_2026-06-08.md:1174`, suivis a HEAD d'un depot **PUBLIC**, depuis
67 jours. Trois gardes verts l'ont laisse passer, chacun pour une raison propre :

- **gitleaks ne l'a jamais vu.** Le secret est ecrit en prose entre backticks,
  sans operateur d'affectation — la regle generique en exige un. Il n'etait
  **pas** dans `.gitleaksignore` : ce n'etait donc pas une exemption assumee mais
  une **non-detection**. Un fichier d'exemptions fait croire que ce qui n'y
  figure pas a ete examine.
- **`log_scrubber.py:41` ne redige pas `ntoken=`.** Son motif porte un `\b` en
  amont, ajoute deliberement « pour eviter de matcher `mytoken=` ». Or le boot
  desktop passe le jeton sous ce nom exact (`app.py:846`), et
  `rest_server.py:543` journalise la ligne de requete brute. Demonstration avec
  la regex reelle : `?token=X` -> redige, `?ntoken=X` -> **intact**. La
  precaution anti-faux-positif d'une garde est ce qui aveugle l'autre.
- **DEUX des SEPT checks REQUIS ne pouvaient pas echouer** : `bandit.yml` et
  `mypy.yml` finissaient par `|| true`. **Lire la COMMANDE d'un check requis,
  jamais son nom dans la liste.** Corrige le 2026-08-29 par un cliquet sur le
  COMPTE (33 findings bandit, 70 erreurs mypy) : la montee echoue, la baisse
  aussi — un gain non verrouille se reperd.

  Ce paragraphe a longtemps dit **TROIS**, en comptant `pip-audit.yml:87`. FAUX,
  et la facon dont l'erreur a survecu compte plus que l'erreur : verifier que la
  chaine `continue-on-error` EXISTE dans un fichier ne dit pas ce qu'elle
  GOUVERNE. `pip-audit.yml` a un job et trois etapes ; les deux audits de
  PRODUCTION tournent en `--strict` et bloquent, seul celui des dependances de
  DEV est exempte. **Un `grep` qui trouve la chaine attendue confirme la
  presence, jamais la portee.**

**Un secret en query string fuit cote CLIENT.** Sur 129 889 fichiers balayes
sous `%LOCALAPPDATA%/CineSort`, **24** portaient la valeur : 6 `settings.json.bak*`,
13 sauvegardes SQLite, le journal, et **4 artefacts WebView2** (`History`,
`Top Sites`, `Favicons`, `Local Storage/leveldb`). Chiffrer le stockage (DPAPI
sur `rest_api_token_secret`, SEC-2) ne dit RIEN sur le transit. Et trois de ces
sauvegardes sont hors rotation pour un caractere : `SETTINGS_BACKUP_PREFIX` vaut
`.bak.` et elles s'appellent `.bak_ITER7_pre`.

(Ma premiere sonde avait rendu **0** : j'avais exclu les dossiers `cache` et
limite les extensions. Chercher un secret par sa VALEUR, sans perimetre choisi.)

**UN RUN DE WORKFLOW PEUT EXISTER SANS JAMAIS TOURNER.** Le 2026-08-26, sept PR
etaient BLOCKED avec **0 des 7 checks requis** — non pas rouges, **absents**.
Leurs 10 a 44 runs existaient, parques en `conclusion=action_required`.
Discriminant mesure : le **`triggering_actor` du push**. L'evenement `opened` a
pour acteur `claude[bot]` et demarre ; chaque `synchronize` suivant a pour acteur
`github-actions[bot]` et se fait parquer.

Trois pieges de lecture, tous payes ce jour-la :

- **`mergeable: MERGEABLE` ne parle QUE des conflits de fichiers**, jamais des
  checks. Lire `mergeStateStatus`.
- **`gh pr checks` dedoublonne les check-runs cote client**, et
  `statusCheckRollup.state` rend `SUCCESS` interroge seul et `FAILURE` interroge
  avec `contexts(first:100)` — **sur le meme commit**. Seul le rendu HTML a
  tranche.
- **Une premiere lecture accusait le NOMBRE DE COMMITS** et se verifiait 15/15…
  sur un echantillon CHOISI (les PR >= #1124). Elargi, il rend sept
  contre-exemples (#1099, #1104…). Le remede qu'elle dictait — squasher, ou
  fermer/rouvrir — visait le mauvais mecanisme. **La cause racine reste non
  mesuree** : l'API n'expose pas le reglage d'approbation.

**`stale.yml` porte `delete-branch: true`** (30 j -> stale, +7 j -> close). Cinq
des sept PR gelees sont des rapports d'audit qui n'existent QUE sur leur branche
— le motif exact de #1089. `exempt-pr-labels` contient deja `blocked` : poser ce
label est la parade.

### Le triangle : annonce / journal / disque

Quatre defauts de la MEME forme sur la semaine du 2026-08-13 au 2026-08-19 :
*ce que l'application annonce n'est pas ce qu'elle a fait* (#1103, #1097, #1099,
#1062). `cinesort/app/verdicts.py` pose l'invariant generique qui manquait.

**Ce qu'il couvre REELLEMENT : #1103 seul.** La premiere redaction annoncait
« deux defauts sur quatre » — c'etait faux, et le detail compte : le payload de
#1062 portait `errors: 300`, il etait HONNETE, c'est l'ecran qui ne lisait que
`deleted` ; #1099 tronquait le plan AVANT l'apply ; #1097 est l'ecran des
reglages. Ne pas rouvrir ce chantier en croyant ces trois-la gardes.

Quatre choses a savoir avant d'y toucher :

1. **Deux journaux, et il en faut deux.** `apply_operations` (SQLite, `op_type`
   en MAJUSCULES) dit ce qui a BOUGE ; `apply_audit.jsonl` (`event` en
   minuscules) voit les ECHECS de l'apply. Brancher une seule source rend
   l'instrument muet sur la moitie du probleme — c'est arrive : la premiere
   version cherchait une cle `error` qui n'existe dans NI l'une NI l'autre.
   Quinze tests verts, tous leurs mutants morts, zero detection.
2. **#1103 se voit sans lire le disque.** Le plan prevoyait une photo
   avant/apres ; `_snapshot_tree` hache chaque fichier, impensable sur une
   bibliotheque. Le mecanisme etait geometrique — un dossier PARTAGE entre
   plusieurs lignes du plan — donc une comparaison de chemins suffit, et elle
   reste vraie APRES coup, quand la source n'existe plus. Un second controle,
   la GRANULARITE (`op_type` dit FICHIER, destination est un DOSSIER), attrape
   l'autre moitie : contrairement a ce que j'avais d'abord ecrit, l'`op_type`
   de #1103 N'ETAIT PAS honnete — l'issue dit `QUARANTINE_FILE`.
3. **Un invariant peut etre correct et INATTEIGNABLE.**
   `succes_annonce_malgre_des_echecs` ne peut pas se declencher : les trois
   `audit_logger.error` d'`apply_core` incrementent tous `res.errors` juste
   avant, et `append_apply_operation` n'a aucun parametre d'erreur. Il est
   conserve en defense en profondeur et ETIQUETE comme tel dans le module. Ne
   pas le presenter comme le cœur du dispositif.
4. **Le cliquet est la vraie garantie.** `test_cliquet_couverture_triangle.py`
   compte les routes destructives — methodes de facade portant `dry_run` **ou**
   `confirmation`, relevees a l'AST — qui echappent au verdict. Le marqueur
   `confirmation` a ete ajoute apres coup : sans lui, `reset_all_user_data`, qui
   efface TOUTES les donnees, etait hors du denominateur. Marge zero.

**Trois pieges de methode, tous payes dans ce chantier :**

- **La FORME IMAGINEE.** J'ai invente la forme d'une donnee quatre fois (cle
  `error` inexistante ; `conflict(kind=)` qui n'existe pas ; quatre compteurs de
  deplacement sur DIX-HUIT ; `res.quarantined` compare a une population
  disjointe). Chaque fois, mes propres tests me la resservaient et la mutation
  tuait proprement. Parade : faire produire la fixture par le code de PRODUCTION
  (`ApplyAuditLogger` -> `read_apply_audit`), et poser un test de DERIVE sur
  toute liste recopiee depuis un dataclass.
- **Toute reecriture INVALIDE la batterie de mutation qui la precede.** Le
  correctif de performance a rendu un helper MORT ; ses cinq assertions
  restaient vertes, et la batterie jouee avant validait donc du code mort.
- **Tester la decision ne dit RIEN du site d'appel.** Trois fois de suite, un
  mutant qui supprimait un appel a survecu. Il faut executer le VRAI corps de la
  fonction appelante, et eprouver aussi ses ARGUMENTS (passer `rows=()` au lieu
  de `rows=rows` laissait la batterie entiere verte).

**Ou l'incoherence atterrit** : `payload["verdict"]` n'est lu par AUCUN ecran —
pas plus que `journal_warning` ni `undo_available`, poses par des correctifs
anterieurs pour la meme raison. Le canal qui atteint reellement l'utilisateur est
le CENTRE DE NOTIFICATIONS, seul a survivre a la fermeture de l'ecran d'apply.
Un test (`LeVerdictNAtteintAUCUNEcranTests`) CONSTATE l'absence de lecteur cote
front, pour que le jour ou un ecran le lira, quelqu'un vienne mettre ce constat
a jour au lieu de le decouvrir.

**`same-site` N'EST PAS UNE FRONTIERE SUR `127.0.0.1`.** Le « site » au sens
Fetch Metadata est le domaine enregistrable : **le port n'en fait pas partie**.
Mesure au navigateur reel (2026-08-29, deux serveurs locaux 18801/18802) : une
image demandee a un AUTRE PORT porte `Sec-Fetch-Site: same-site`, jamais
`cross-site`. `_poster_trusted_caller` acceptait `same-site` : tout autre service
web tournant sur la machine de l'utilisateur etait donc FIABLE, avec `force=1` et
le fetch TMDb — et pouvait lire le cache de jaquettes id par id, donc enumerer la
bibliotheque. La valeur qui porte la meme frontiere qu'`_allowed_origin` (lequel,
lui, contraint le port) est **`same-origin`**.

Deux corollaires payes le meme jour :

- **un repli par IP annule un durcissement d'en-tete.** Exiger `same-origin` sans
  toucher au `return self._client_ip() in _LOCAL_CLIENT_IPS` laissait un
  navigateur `same-site` en loopback redevenir fiable. Des qu'un `Sec-Fetch-Site`
  est present, l'appelant EST un navigateur et se prononce lui-meme. C'est
  l'ECRITURE DU TEST qui l'a revele, pas la lecture ;
- **une preuve qui enumere les cas qu'on avait en tete n'est pas une preuve.**
  Le diagnostic d'origine (`docs/internal/r8/r8_f3_poster_trusted_diff.py`, que
  nul workflow ne lance) testait `same-origin` et `cross-site` — les deux
  extremes d'un en-tete qui a QUATRE valeurs. Celle du milieu ouvrait le trou.

**UN CORRECTIF DE SECURITE PEUT INTRODUIRE UN ReDoS, ET AUCUN TEST NE LE VERRA.**
Le 2026-08-29, boucher le scrubber sur `ntoken=` demandait de retirer un `\b`.
Prefixer le motif par `[\w-]*` pour englober le nom complet du parametre rend une
sortie **strictement identique** — et fait passer 40 000 caracteres sans
correspondance de **0,91 ms a 24 338 ms**. Cette version a bloque la batterie des
12 fichiers lies : 371 s de CPU pour 439 s ecoulees, sans terminer.

Les quatre variantes de motif etaient fonctionnellement VERTES : seule une mesure
de TEMPS pouvait les separer. Quand un motif s'applique a de l'entree controlee
par l'appelant — une ligne de requete, un nom de fichier —, sa complexite fait
partie de sa surface d'attaque. Et **un test qui n'en finit pas ressemble a un
test lent** : la difference se lit au compteur CPU, pas au chronometre.

**`.get(cle, 0)` CONFOND « INCONNU » ET « PIRE ».** Dans le comparateur de
doublons, `_video_codec_rank_value` rendait 0 pour tout codec absent d'une table
de dix etiquettes — donc SOUS `xvid` (1). Mesure : `vc1`, `mpeg2video`, `vp9`,
`prores`, `wmv3` rendaient tous 0, et le verdict d'un Blu-ray VC-1 25 Mbps 21 Go
contre un DivX 1,5 Mbps 1,3 Go etait **« Garder B, archiver A »**, les deux debits
affiches juste a cote. La fonction savait pourtant rendre `None` — elle le faisait
deja pour un codec VIDE. Sur un chemin qui deplace des fichiers, l'absence de
connaissance doit produire un refus de trancher, pas un jugement.

**LE DEPOT STOCKE DU LF** (`core.autocrlf=true`, aucun `.gitattributes`) : la
copie de travail est en CRLF, l'index en LF. La discipline binaire sur les fins de
ligne protege donc la COPIE DE TRAVAIL, jamais le commit — `git add` normalise de
toute facon. Le controle qui prouve qu'une edition est locale est le
**`git diff --numstat` identique avec et sans `--ignore-cr-at-eol`**.

Et ce controle **ne voit pas** une insertion qui coupe une fonction en deux :
inserer entre deux lignes rend « N ajoutees, **0 retiree** » alors que le test
voisin a perdu une assertion (vecu le 2026-08-29). Meme famille que « ne jamais
inserer entre un decorateur et sa fonction ». Le garde qui mord est un controle
**AST** : comparer, avant/apres, le nombre d'instructions du corps de chaque
fonction preexistante.

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
ne bouge pas). Seuil de couverture CI : **75 %**. Perimetre CI : **9279 tests**
(`passed`, mesure de la CI sur `main` fusionne le 2026-08-16 ; s'y ajoutent
20 skipped, 2 xfailed et 1635 subtests). Ce nombre se remesure, il ne se recopie
pas — et il se remesure **par la meme commande**, sinon on compare un compte
d'items (`--collect-only`) a un compte de `passed`.

Le TOTAL d'items vaut **9276** (`--collect-only -q`, mesure du 2026-08-26 ; il
disait 9140 le 2026-08-16, donc il n'est pas « stable », il croit). La
repartition passed/skipped **depend de
la machine** : plusieurs `skipUnless` portent sur l'environnement (`fpcalc.exe`
present, `CINESORT_API_TOKEN` pose, rapport Lighthouse deja genere, symlinks
sur Windows non eleve). Un ecart de quelques unites entre deux postes ne signale
donc rien — c'est l'ecart sur le TOTAL qu'il faut regarder.

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

**ET UNE PR OUVERTE PEUT DEJA PORTER LE CORRECTIF.** Le 2026-08-29, un lot a
reimplemente `sqlite3.Error` sur `cinesort_api.py::log_api_exception`... que la
PR #1128, ouverte depuis huit jours, corrigeait deja — et mieux : elle traitait
aussi `_find_run_row` et `quality_audit_support._recompute_worker`, avec un
fichier de test dedie de 260 lignes. Le merge a produit un conflit sur la ligne
exacte, et la branche a du ceder.

La regle « re-mesurer avant de coder, y compris sur une issue ouverte » existait
deja (voir juste en dessous). Il lui manquait sa variante la plus couteuse : les
PR EN COURS. Avant d'attaquer un constat de la file de travail,
`gh pr list --search "<mot-cle du defaut>"` coute dix secondes.

**TROIS ISSUES OUVERTES ETAIENT DEJA CORRIGEES** — #984, #972, #1002. Mesurees
avant d'ecrire une ligne : la garde d'unicite de #984 existe
(`run_id_est_utilise` interroge les tables filles), le commentaire faux de #972
est devenu un predicat nomme, et la fixture `scan_actif` de #1002 existe et
explique meme pourquoi elle n'a pris aucune des deux directions proposees. Avec
le contrat CSS de la veille, cela fait **quatre** implementations redondantes
evitees en deux jours. **Re-mesurer avant de coder, y compris sur une issue
ouverte.**

### Lot du 2026-08-16 — 5 PR, et le prompt de l'audit repare

**#1096 — le prompt du bot d'audit annulait sa propre regle.** En tete : « au
plus 3 PR, 5 issues ». **1360 lignes plus loin**, a l'etape ou le bot ouvre :
« PAS DE LIMITE [...] ouvre 50 PRs [...] cree 200 issues ». Le bot obeit au
DERNIER lu — voila le backlog de 177 PR et 248 issues. Chercher les
contradictions INTERNES d'un prompt avant ses faits perimes.

Trois « REGLES ABSOLUES » etaient par ailleurs IMPOSSIBLES : elles exigeaient
`ruff`, `pytest`, `git fetch`, `gh api`, tous absents du runner ou de
`--allowedTools`. Une regle absolue impossible apprend que les regles absolues
sont decoratives. Et deux faits faux DESARMAIENT les gardes : « la CI est rouge
sur main, ne t'en sers pas comme critere » et « ~22 echecs pre-existants ».

Ajoute : le CADRE D'EXECUTION (le « multi-agent interieur » du document etait
une alternance de personas — `grep -c Task` = 0), la MEMOIRE des audits passes,
et la VERIFICATION ADVERSAIRE. Mesure du premier run sous le nouveau prompt :
budget respecte (1 PR + 1 issue), une section « findings ECARTES » dont un que
le bot se refute lui-meme, et une section « ce que cet audit N'A PAS couvert ».

**#1098 — trois correctifs jamais repris**, dormants depuis mai-juin parce que
le squash-merge rend l'ascendance illisible (cf. le piege plus haut). Dont deux
de securite : les plugins TIERS ne recoivent plus `PYTHONPATH`/`PYTHONHOME`, et
`CORS='*'` + `0.0.0.0` n'est plus silencieux. **5/5 mutants.**

**#1097 — l'ecran Parametres effacait des reglages qu'il ne possede pas.** Meme
famille que le piege du 2026-08-15 : la garde du backend etait CORRECTE mais
INATTEIGNABLE, parce que `apply_settings_defaults` injecte toujours les cles et
que l'ecran re-POSTe son instantane fige. Le remede ne remplace pas la garde, il
la rend atteignable. Non uniforme : `ffprobe_path` est un VRAI champ de l'ecran,
le filtrer aurait remplace un defaut par un autre. **4/4 mutants**, dont le
contre-test qui le prouve.

**#1099 — deux reecritures de `plan.jsonl` effacaient les lignes illisibles**,
donc le TEMOIN de la perte : le plan redevenait syntaxiquement parfait, plus
rien ne rougissait, et l'apply s'executait sur N-1 films avec `errors: 0`.
Trouve par le bot. Deux defauts que son runner ne POUVAIT pas voir ont ete
corriges a la main : formatage et handler d'exception redondant.

**TROIS ANALYSEURS, TROIS MARQUES.** `# noqa` couvre ruff, `# nosec` couvre
bandit, `# nosemgrep` couvre semgrep. Poser l'une ne fait pas taire les autres,
et le signalement change de LIBELLE a chaque fois — ce qui donne l'illusion d'un
nouveau defaut alors que c'est le meme appel vu par un outil de plus. Quatre
iterations perdues sur un seul `subprocess.run`.

**UN MUTANT SURVIVANT SE QUALIFIE AVANT DE CONCLURE.** La batterie sur #1099 a
d'abord rendu « 1 tue sur 3 » — de quoi refuser la PR. Faux : l'un etait
EQUIVALENT par construction (une seconde garde rend le meme resultat avant toute
ecriture), l'autre visait du code couvert AILLEURS (7 tests rougissent sur les
21 fichiers concernes). Bilan reel : correctement eprouve.

### Lot du 2026-08-15 — 3 PR

- **#1080** le simulateur de profil **reimplementait** la derivation de tier au
  lieu de deleguer a `tiers_helpers.determine_tier`. Sur des profils que
  `validate_quality_profile` ACCEPTE :

  ```
  bronze = 0        score 10 -> simulateur "Reject",   production "Bronze"
  70/70/55/40       score 70 -> simulateur "Gold",     production "Platinum"
  ```

  Or `parametres.js` ORDONNE d'utiliser la simulation avant d'activer un profil.
  Sa grille de repli etait la grille **pre-v1.5.5** (85/68/54/30), celle qu'un
  test interdit deja cote frontend : le correctif n'avait ete pose que d'un
  cote. Balayage : 42 sites la portent encore, **38 sont des tests** qui
  l'exercent pour la retrocompatibilite et 3 des commentaires. **2/2 mutants.**
- **#1083** deux defauts des regles custom, et surtout **deux essais de
  correction qui ont chacun ETEINT une garde existante** — cf. le piege
  ci-dessous.

**UNE GARDE PEUT EN AVEUGLER UNE AUTRE EN S'EXECUTANT AVANT ELLE.** Le
2026-08-15, `validate_quality_profile` laissait passer `custom_rules` sans les
valider, en deleguant PAR COMMENTAIRE. Six chemins d'ecriture l'appellent, un
seul appliquait la delegation. Poser la garde au point commun paraissait evident.
Deux essais, deux gardes tuees :

1. **Ajouter les erreurs a `errs`.** `compute_quality_score` fait
   `if not ok: return _build_invalid_profile_result(...)` : une seule regle
   inutilisable mettait **TOUS les films a 0** (mesure : 0 au lieu de 46), ce qui
   annulait #723, dont le principe est de refuser la VALEUR en preservant le
   score.
2. **Ecarter les regles fautives dans le validateur.** Plus doux, et pire :
   `save_quality_profile` lit `custom_rules` **APRES** lui. Elles avaient disparu,
   sa propre verification ne voyait plus rien, et son refus cessait de
   fonctionner — en silence.

Le twist : une garde n'a pas besoin d'en supprimer une autre pour la tuer. Il lui
suffit de s'executer **avant** elle et de lui retirer sa matiere.

Trois contre-feux :

- avant de poser une garde a un point de passage partage, lister ses appelants et
  lire **ce que chacun fait du resultat** — `if not ok:` veut dire « refuse »
  chez l'un et « degrade tout » chez l'autre ;
- se demander qui lit la meme donnee **apres** ce point, et si la normaliser la
  lui retire ;
- souvent le bon endroit n'est pas le point commun mais **le seul appelant qui
  manque la garde** (ici `set_active_profile`, un sur six, designe par la mesure
  — `import_recyclarr_yaml` ne porte AUCUNE `custom_rules`).

Les trois echecs de cette PR ont ete dits par la suite **complete**, jamais par
les tests du domaine : deux tests de bout en bout d'une AUTRE issue, le cliquet
d'imports lazy (16 pour un plafond de 15 — le commentaire affirmant qu'un import
en tete creerait un cycle etait faux, ce fichier importe deja `custom_rules`) et
le gabarit de fonction.

### Rangement du depot (2026-08-15) — 3 PR

Le but etait de rendre les audits FUTURS moins couteux, pas de gagner des octets.

**Ou vivent les rapports d'audit** — desormais tous dans
`docs/internal/audits/` : les rapports en `claude/AAAA-MM-JJ-*.md`, leurs
constats en `findings/AAAA-MM-JJ-*.jsonl`. **172 fichiers**, dont **117
rapatries par #1085** depuis les branches qui en etaient l'unique exemplaire.
Ils sont donc cherchables d'un seul `grep` — avant, une recherche dans `main`
n'en voyait que le tiers.

**#1086** retire du suivi 29 Mo regenerables : le rapport visuel
`tests/e2e/visual_report.html` (6,4 Mo, que `test_15_visual_catalog.py`
reconstruit des qu'il manque) et 44 captures de maquette (22,4 Mo). Les 2
`.html` de `docs/design-mockup/` sont **gardes** : ils pesent ~0 et deux audits
les citent comme preuve (`v6.html` porte la seule definition des variables
`--glass-*` du depot). Cela n'allege PAS `.git` — les blobs restent dans
l'historique ; le gain porte sur l'arbre de travail, donc sur chaque worktree.

**#1087** borne la retention des artefacts CI. `windows-ci.yml` etait le seul
des cinq workflows sans `retention-days` : il retombait sur le defaut du depot
(90 j) la ou ses freres tiennent 3 a 30 j, d'ou **51,6 Go** dormants
(245 runs x 216 Mo) pour un build de diagnostic. Aligne sur 7 j, comme
l'artefact frere `CineSort-exe` de `ci.yml` qui porte le MEME binaire.

**Le stock ne se resorbe pas tout seul** : a la cadence mesuree (~5 Go/jour de
`windows-build-artifacts`), meme une retention a 7 jours laisse un regime
permanent d'environ **36 Go**. Si ce poste redevient genant, la variable a
regarder est le NOMBRE de runs, pas la duree.

Remesure du 2026-08-26 : **41,05 Go vivants** sur 1 892 artefacts, dont 39,61 Go
pour 188 `windows-build-artifacts`. Le chiffre ci-dessus tient donc. **Et la
retention n'est PAS retroactive** : elle est fixee A L'UPLOAD. Les artefacts
anterieurs a #1087 gardent leurs 90 jours quoi qu'on regle aujourd'hui — la
majeure partie de ces 39,6 Go date du 9 au 15 aout et vivra jusqu'a mi-novembre.
Aucun reglage ne les touchera ; seule une suppression explicite le ferait.
(Une revue automatisee a rendu ici « 3,18 Go », faux d'un facteur 13, et a
propose de corriger ce paragraphe : c'est LUI qui avait raison. Remesurer avant
de « corriger » un chiffre qui derange.)

**`git branch -r` MENT sur ce poste** : il rend **620** refs remote-tracking
locales pour **63** branches reellement presentes sur `origin`
(`git ls-remote --heads origin | wc -l`, 2026-08-26). Les refs perimees ne sont
jamais elaguees. Toute remesure du rangement ci-dessous faite avec `git branch -r`
compte donc dix fois trop — `git fetch --prune` d'abord, ou interroger `origin`.

**Branches conservees.** 105 -> 41 distantes, 444 -> 84 locales. Ce qui reste
n'est pas du residu : **4 branches portent un correctif absent de `main`** et
qui s'y applique encore — `fix/audit-2026-05-30-core-min-vs-sorted`,
`fix/audit-2026-06-20-radarr-sync-tmdb-defensif`,
`sec/audit-cors-warning-2026-05-26`,
`sec/audit-plugin-env-pythonpath-2026-05-25`. **35 autres sont indecidables**
(`main` a diverge depuis) et demandent un examen un par un, plus
`loop/correction-2026-06` (855 fichiers, chantier a part). Voir le piege
« l'ascendance ment sur ce depot ».

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
**Dix-neuf** modules depassent 1 000 lignes (dont **onze** au-dela de 1 500),
et pas seulement dans `ui/api/` et `app/` — mesure du 2026-08-26, contre « neuf,
tous dans ui/api et app » ecrit ici. Les FONCTIONS sont bornees par un cliquet
depuis #778 ; les MODULES ne le sont par rien, et aucun n'a diminue. Le plan
associe est
`docs/internal/audit_v7_8_0/REMEDIATION_PLAN_v7_8_0.md`.

`tests/test_doc_consistency.py` verifie que cette section reste presente et que
ce fichier ne revendique pas de note de sante inventee. Il lit **`/CLAUDE.md`**,
pas `docs/internal/CLAUDE.md` : une refonte de ce fichier qui supprime ces
references fait echouer la CI — c'est arrive le 2026-08-03, ou la creation de ce
fichier a transforme 4 tests jusque-la **skippes** (la racine n'avait pas de
`CLAUDE.md`) en 4 echecs sur `main`.
