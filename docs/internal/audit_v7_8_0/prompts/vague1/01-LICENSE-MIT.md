# V1-01 — Déposer LICENSE MIT

**Branche** : `fix/license-mit`
**Worktree** : `.claude/worktrees/fix-license-mit/`
**Effort** : 15 min
**Priorité** : 🔴 BLOQUANT publication
**Fichiers concernés** :
- `LICENSE` (nouveau)
- `pyproject.toml` (ajout champ license)
- `README.md` (mention license en fin de fichier)

---

## RÈGLES GLOBALES

PROJET : CineSort, app desktop Windows Python 3.13 + pywebview + SQLite
REPO PRINCIPAL : `C:\Users\blanc\projects\CineSort`
TON DOSSIER DE TRAVAIL : worktree dédié (Étape 0 ci-dessous)

CONTEXTE : 2000 utilisateurs en attente, publication GitHub Release prévue.

EXIGENCE QUALITÉ MAXIMALE :
- NE FAIS PAS confiance aveuglément à ce prompt — vérifie chaque hypothèse
- LIS les fichiers AVANT de modifier
- FAIS une recherche web si nécessaire (best practices 2025-2026)
- LANCE les tests existants AVANT et APRÈS ton changement
- COMMITS GRANULAIRES (préfixe feat/fix/docs/etc)
- TEXTE en FRANÇAIS pour UI / commentaires
- ZÉRO emoji sauf demandé

RÈGLE PARALLÉLISATION : tu travailles UNIQUEMENT sur les fichiers listés ci-dessus.
Si tu touches un fichier non listé → STOP et signale.

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE avant TOUT)

Le repo est partagé par 14 instances en parallèle. SANS WORKTREE, tes commits
tomberont sur la mauvaise branche (course HEAD entre instances). Cette étape
est non négociable.

```bash
cd /c/Users/blanc/projects/CineSort

# Si la branche n'existe pas encore :
git worktree add -b fix/license-mit .claude/worktrees/fix-license-mit audit_qa_v7_6_0_dev_20260428

# Si la branche existe déjà (instance précédente plantée) :
# git worktree add .claude/worktrees/fix-license-mit fix/license-mit

cd .claude/worktrees/fix-license-mit
```

**Vérifications obligatoires** :
```bash
pwd                          # doit afficher .../fix-license-mit
git branch --show-current    # doit afficher fix/license-mit
git status                   # working tree clean (sauf untracked audit/)
```

**À PARTIR DE MAINTENANT** : tous tes `git`, `Edit`, `Read`, `Write`, `Bash`
se font DANS ce worktree. NE FAIS JAMAIS `git checkout <autre-branche>`.
NE SORS JAMAIS du worktree pour faire un commit.

Cf `audit/prompts/_WORKTREE_SETUP.md` (présent dans le worktree) pour la doc complète.

---

## MISSION

L'app CineSort n'a aucun fichier LICENSE à la racine. Sans licence, par défaut
tous les droits sont réservés → personne ne peut légalement forker / contribuer /
distribuer. Bloquant pour la publication GitHub publique prévue.

### Étape 1 — Recherche

1. WebSearch : "MIT vs Apache-2.0 license desktop python app GitHub 2025-2026"
2. Lis https://choosealicense.com/ pour confirmer que MIT convient à un projet
   solo, permissif, open source
3. Confirme MIT ou justifie un autre choix

### Étape 2 — Créer le fichier LICENSE

Template MIT officiel SPDX :

```
MIT License

Copyright (c) 2026 <PROJECT_AUTHOR>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

⚠ Garde `<PROJECT_AUTHOR>` comme placeholder.

### Étape 3 — Mettre à jour pyproject.toml

Ajoute (ou complète) `[project]` :
```toml
[project]
name = "cinesort"
license = {text = "MIT"}
authors = [{name = "<PROJECT_AUTHOR>"}]
```

Vérifie : `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`

### Étape 4 — Mettre à jour README.md

Fin de README :
```markdown
## Licence

CineSort est distribué sous licence MIT. Voir le fichier [LICENSE](LICENSE)
pour le texte complet.
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -3
```

### Étape 6 — Commits

Commits granulaires depuis le worktree :
1. `feat(license): add MIT LICENSE file`
2. `chore(pyproject): declare MIT license in [project] metadata`
3. `docs(readme): add license section`

---

## LIVRABLES

Récap (≤15 lignes) :
- LICENSE créé : OK
- pyproject.toml mis à jour : OK
- README.md mention license : OK
- Tests : 0 régression
- Commits : liste les 3 SHA + branche `fix/license-mit`
