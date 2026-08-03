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
uvx ruff@0.15.22 check .
uvx ruff@0.15.22 format --check .

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

Contrats (identifiants exacts, utiles pour lire un echec CI) :
`domain_pure` — domain n'importe ni app, ni infra, ni ui.
`infra_bounded` — infra n'importe ni app, ni ui.
`app_bounded` — app n'importe pas ui.

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

**ruff est epingle EXACTEMENT** (`ruff==0.15.22`) en **4 endroits** qui doivent
rester synchrones : `pyproject.toml`, `requirements-dev.txt`,
`.pre-commit-config.yaml` (rev du hook) et `uv.lock`. Trois versions differentes
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
qui deplacent des dossiers sous charge. Un echec isole sur la chaine apply/undo
en suite complete, qui passe en isolation, est presque toujours cela.

## Conventions

**Titre de PR** — types autorises : `feat fix docs ci refactor test chore perf
build style revert deps sec rel`. Un autre type fait echouer un check
**obligatoire**. `sec` = correctif de securite (CWE identifie), `rel` = fiabilite
(ecriture atomique, fsync, course entre ecrivains).

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

## Etat

Version **1.5.2-beta** (les jalons se marquent par des tags `+build`, la version
ne bouge pas). Seuil de couverture CI : **75 %**. Perimetre CI : ~6660 tests.

Le bot d'audit quotidien tourne en Opus 5 et est **borne par un budget
d'ouverture** (`.github/audit-prompt.md`) : au plus 3 PR et 5 issues par
execution, zero au-dela de 150 elements ouverts. Sans cette borne il avait
produit un backlog de 177 PR et 248 issues.

Detail et historique : `docs/internal/CLAUDE.md` et
`docs/internal/CLAUDE_HISTORY.md`.
