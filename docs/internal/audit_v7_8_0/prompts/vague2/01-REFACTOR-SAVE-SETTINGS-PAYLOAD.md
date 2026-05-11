# V2-01 — Refactor save_settings_payload (complexité F=81 → ≤15)

**Branche** : `refactor/save-settings-payload-split`
**Worktree** : `.claude/worktrees/refactor-save-settings-payload-split/`
**Effort** : 2 jours
**Priorité** : 🔴 MAJEUR (audit ID-CODE-001 — fonction la plus complexe du projet)
**Fichiers concernés** :
- `cinesort/ui/api/settings_support.py` (uniquement save_settings_payload + helpers extraits)
- `tests/test_settings_payload.py` (existant, à enrichir)
- éventuellement `tests/test_settings_section_helpers.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b refactor/save-settings-payload-split .claude/worktrees/refactor-save-settings-payload-split audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/refactor-save-settings-payload-split

pwd && git branch --show-current && git status
```

À partir de maintenant : tout dans ce worktree. PAS de `git checkout` autre.

---

## RÈGLES GLOBALES

PROJET : CineSort, app desktop Windows Python 3.13.
TA BRANCHE : `refactor/save-settings-payload-split`
EXIGENCE QUALITÉ MAXIMALE :
- Ne fais pas confiance au prompt — vérifie chaque hypothèse
- Lis `audit/report.md` + `audit/lot2_security_robustness_code.md` pour contexte
- Lance les tests AVANT et APRÈS — zéro régression tolérée
- Ruff check + format à la fin
- Commits granulaires (1 par helper extrait)

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT settings_support.py + tests listés.

---

## CONTEXTE

L'audit a montré que `save_settings_payload` (settings_support.py:883) a une **complexité
cyclomatique de 81** (rapport radon = `F`). C'est la fonction la plus complexe du projet
entier. Plus de 80 chemins indépendants → bug-prone, dur à tester exhaustivement, dur à
maintenir.

Avec 2000 users, cette fonction est appelée à chaque save settings → toute régression
silencieuse passe en prod immédiatement.

---

## MISSION

### Étape 1 — Recherche obligatoire

WebSearch :
- "refactor function high cyclomatic complexity Python 2025 best practices"
- "Extract Method pattern Python settings handler"

Note les patterns recommandés.

### Étape 2 — Comprendre le code actuel

Lis `cinesort/ui/api/settings_support.py` complètement (1221 lignes). Identifie :
- La fonction `save_settings_payload` (ligne ~883)
- Les sections logiques internes (probablement 9-15 sections, chacune correspondant à un
  groupe de settings : essentiel, tmdb, analyse video, renommage, jellyfin, nettoyage,
  notifications, plex, radarr, surveillance, email, plugins, api rest, apparence, perceptuel)

Mesure la complexité actuelle :
```bash
.venv313/Scripts/python.exe -m radon cc cinesort/ui/api/settings_support.py -s -n D | grep save_settings_payload
```

### Étape 3 — Lance les tests existants AVANT (baseline)

```bash
.venv313/Scripts/python.exe -m unittest tests.test_settings_payload tests.test_settings_backup -v 2>&1 | tail -10
```

Capture le baseline : N tests passent, X failures.

### Étape 4 — Refactor

Extrais des helpers privés `_save_section_<group>(payload, current) -> dict` :
- `_save_section_essential(payload, current)` (root, state_dir)
- `_save_section_tmdb(payload, current)` (tmdb_enabled, tmdb_api_key, tmdb_timeout_s)
- `_save_section_analysis(payload, current)` (subtitle_detection_enabled, etc.)
- `_save_section_naming(payload, current)` (naming_preset, templates)
- `_save_section_jellyfin(payload, current)`
- `_save_section_plex(payload, current)`
- `_save_section_radarr(payload, current)`
- `_save_section_cleanup(payload, current)`
- `_save_section_notifications(payload, current)`
- `_save_section_perceptual(payload, current)`
- `_save_section_watch(payload, current)` (watch folder)
- `_save_section_email(payload, current)`
- `_save_section_plugins(payload, current)`
- `_save_section_rest_api(payload, current)`
- `_save_section_appearance(payload, current)` (theme, animation, etc.)
- `_save_section_update(payload, current)` (cf V1-13)

Chaque helper :
- Prend payload (dict input user) + current (dict actuel)
- Modifie current en place ou retourne current modifié
- Complexité < 15

`save_settings_payload` devient un dispatcher de ~40-60 lignes :

```python
def save_settings_payload(payload):
    current = read_settings()
    current = _save_section_essential(payload, current)
    current = _save_section_tmdb(payload, current)
    # ... ligne par section
    current = _validate_complete(current)
    write_settings(current)
    return current
```

### Étape 5 — Tests

Lance les tests existants APRÈS le refactor :
```bash
.venv313/Scripts/python.exe -m unittest tests.test_settings_payload tests.test_settings_backup -v 2>&1 | tail -10
```

**Doit être identique au baseline** (zéro régression).

Bonus : crée `tests/test_settings_section_helpers.py` avec un test isolé par helper
(15-16 tests, un par section) pour figer le comportement.

### Étape 6 — Vérification complexité

```bash
.venv313/Scripts/python.exe -m radon cc cinesort/ui/api/settings_support.py -s -n D
```

`save_settings_payload` doit être ≤ B (15) après refactor.

### Étape 7 — Vérifications finales

```bash
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
.venv313/Scripts/python.exe -m ruff format --check . 2>&1 | tail -2
```

### Étape 8 — Commits

3-5 commits granulaires :
1. `refactor(settings): extract _save_section_essential + _save_section_tmdb`
2. `refactor(settings): extract _save_section_analysis + _save_section_naming`
3. `refactor(settings): extract _save_section_<integrations> (jellyfin/plex/radarr)`
4. `refactor(settings): extract _save_section_<misc> (cleanup/notif/perceptual/watch/email/plugins/rest/appearance)`
5. `refactor(settings): simplify save_settings_payload to dispatcher (F=81 → B=15)`

Bonus : `test(settings): add isolated tests for 15 section helpers`

---

## LIVRABLES

Récap court (≤15 lignes) :
- save_settings_payload complexité avant/après (F=81 → ?)
- Nombre de helpers extraits
- Tests : 0 régression
- 3-5 commits sur `refactor/save-settings-payload-split`
