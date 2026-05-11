# V1-04 — Fix accent "Rester connecté" + audit accents login

**Branche** : `fix/accent-rester-connecte`
**Worktree** : `.claude/worktrees/fix-accent-rester-connecte/`
**Effort** : 15 min
**Priorité** : 🔴 BLOQUANT (visible au 1er écran)
**Fichiers concernés** :
- `web/dashboard/index.html` (ligne ~43)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE avant TOUT)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b fix/accent-rester-connecte .claude/worktrees/fix-accent-rester-connecte audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/fix-accent-rester-connecte fix/accent-rester-connecte
cd .claude/worktrees/fix-accent-rester-connecte

pwd && git branch --show-current && git status
```

⚠ Cette mission a **probablement déjà été faite** (commit `6932f69` sur la branche).
Vérifie : `git log --oneline | head -3`. Si le commit existe → mission déjà OK,
signale "déjà fait" à l'orchestrateur et termine.

À partir de maintenant : tout dans ce worktree.

---

## RÈGLES GLOBALES

PROJET : CineSort, FR francophone.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/dashboard/index.html`.

---

## MISSION

Sur la page login du dashboard distant, la checkbox affiche "Rester connecte" sans accent.
Avec 2000 users francophones, c'est visible immédiatement et nuit à l'image de polish.

### Étape 1 — Localiser

Lis `web/dashboard/index.html`. Cherche `Rester connect`. Vérifie l'accent manquant.

### Étape 2 — Fixer

Remplace `Rester connecte` par `Rester connecté`.

### Étape 3 — Audit accents page login complète

Vérifie le reste de la section login (lignes ~30-50) pour d'autres accents manquants :
- `Cle` → `Clé`
- `Acces` → `Accès`
- `Memoriser` → `Mémoriser`
- `Reglages` → `Réglages`
- `Connexion echouee` → `Connexion échouée`

⚠ NE PAS toucher les attributs HTML (id, class, name). Uniquement texte visible utilisateur.

### Étape 4 — Vérifications

```bash
python -c "from html.parser import HTMLParser; HTMLParser().feed(open('web/dashboard/index.html', encoding='utf-8').read())"
.venv313/Scripts/python.exe -m unittest tests.test_dashboard_shell -v 2>&1 | tail -5
```

### Étape 5 — Commit

`fix(ui): restore French accents in dashboard login form`

---

## LIVRABLES

Récap :
- "Rester connecte" → "Rester connecté" : OK
- Autres accents corrigés : liste les
- Tests : 0 régression
- 1 commit sur `fix/accent-rester-connecte`
