# V3-09 — Reset all data UI (bouton Paramètres)

**Branche** : `feat/reset-all-data-ui`
**Worktree** : `.claude/worktrees/feat-reset-all-data-ui/`
**Effort** : 2-3h
**Priorité** : 🟠 IMPORTANT (RGPD-friendly + désinstallation propre)
**Fichiers concernés** :
- `cinesort/ui/api/reset_support.py` (nouveau)
- `cinesort/ui/api/cinesort_api.py` (endpoint `reset_all_user_data`)
- `web/dashboard/views/settings-v5.js` (bouton danger zone)
- `web/dashboard/styles.css` (style zone danger)
- `tests/test_reset_all_data.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/reset-all-data-ui .claude/worktrees/feat-reset-all-data-ui audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-reset-all-data-ui

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le système reset. Aucune modif des
opérations métier scan/apply.

REGLE SAFETY : opération destructive — confirmation double + détail explicite des
actions effectuées.

---

## CONTEXTE

Aujourd'hui pour réinitialiser CineSort, l'utilisateur doit :
1. Trouver le dossier `%LOCALAPPDATA%\CineSort\` (peu user-friendly)
2. Le supprimer manuellement
3. Comprendre ce qui est gardé / supprimé

**Solution** : bouton "Réinitialiser toutes mes données" dans la section Danger Zone
des Paramètres. Avec :
- Confirmation typée ("Tape RESET pour confirmer")
- Liste explicite de ce qui sera supprimé
- Création d'un backup avant suppression (sécurité)

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/ui/api/settings_support.py` (voir comment localiser le dossier user data)
- `cinesort/infra/db/backup.py` (voir le helper backup déjà existant)
- `cinesort/ui/api/cinesort_api.py` (pattern d'expose endpoint)

### Étape 2 — Backend `reset_support.py`

Crée `cinesort/ui/api/reset_support.py` :

```python
"""V3-09 — Reset all user data (avec backup de sécurité)."""
from __future__ import annotations
import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def reset_all_user_data(api, confirmation_text: str) -> dict:
    """V3-09 — Réinitialise toutes les données utilisateur.

    Étapes :
    1. Vérifier que confirmation_text == "RESET"
    2. Créer un backup ZIP du dossier user-data complet
    3. Supprimer : DB SQLite, settings.json, runs/, cache TMDb, perceptual reports
    4. Préserver : logs (utiles pour debug si reset cause un problème)

    Returns:
        {ok: bool, backup_path: str, removed: list[str], error: str?}
    """
    if confirmation_text != "RESET":
        return {"ok": False, "error": "Confirmation invalide (attendu 'RESET')"}

    state_dir = api._get_state_dir() if hasattr(api, "_get_state_dir") else None
    if not state_dir or not Path(state_dir).exists():
        return {"ok": False, "error": "Dossier user-data introuvable"}

    state_path = Path(state_dir)
    backup_path = state_path.parent / f"cinesort_backup_before_reset_{int(time.time())}.zip"

    try:
        # 1. Backup sécurité
        logger.info("V3-09 : création backup avant reset → %s", backup_path)
        shutil.make_archive(str(backup_path).replace(".zip", ""), "zip", root_dir=str(state_path))

        # 2. Suppression sélective (préserve logs/)
        removed = []
        for item in state_path.iterdir():
            if item.name == "logs":
                continue  # préserver logs
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            removed.append(item.name)

        logger.warning("V3-09 : reset complet effectué (%d items supprimés). Backup : %s", len(removed), backup_path)
        return {
            "ok": True,
            "backup_path": str(backup_path),
            "removed": removed,
        }
    except Exception as e:
        logger.exception("V3-09 : échec reset")
        return {"ok": False, "error": str(e)}


def get_user_data_size(api) -> dict:
    """V3-09 — Retourne la taille du dossier user-data (pour affichage UI)."""
    state_dir = api._get_state_dir() if hasattr(api, "_get_state_dir") else None
    if not state_dir or not Path(state_dir).exists():
        return {"size_mb": 0, "items": 0}

    total = 0
    items = 0
    for f in Path(state_dir).rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
                items += 1
            except Exception:
                pass
    return {
        "size_mb": round(total / (1024 * 1024), 2),
        "items": items,
    }
```

⚠ Adapter `_get_state_dir` au vrai nom dans `CineSortApi`. Lire d'abord pour confirmer.

### Étape 3 — Endpoints

```python
def reset_all_user_data(self, confirmation: str) -> dict:
    """V3-09 — Reset toutes les données user (avec backup)."""
    from cinesort.ui.api.reset_support import reset_all_user_data
    return reset_all_user_data(self, confirmation)

def get_user_data_size(self) -> dict:
    """V3-09 — Taille actuelle du user-data."""
    from cinesort.ui.api.reset_support import get_user_data_size
    return {"data": get_user_data_size(self)}
```

### Étape 4 — UI section Danger Zone

Dans `web/dashboard/views/settings-v5.js`, ajouter (en bas, après tous les groupes) :

```javascript
function _renderDangerZone() {
  return `
    <section class="danger-zone">
      <h2>⚠ Zone de danger</h2>
      <div class="danger-card">
        <h3>Réinitialiser toutes mes données</h3>
        <p>Supprime ta base de données, tes paramètres, l'historique des runs, les caches TMDb et les analyses perceptuelles.</p>
        <p><strong>Préservé</strong> : tes fichiers vidéo (jamais touchés), les logs (debug).</p>
        <p class="text-muted">Un backup ZIP automatique est créé avant la suppression dans le dossier parent.</p>
        <p id="userDataSizeInfo" class="text-muted">Données actuelles : ...</p>
        <button class="btn btn--danger" id="btnOpenResetDialog">Réinitialiser…</button>
      </div>
    </section>
  `;
}

async function _openResetDialog() {
  const sizeInfo = (await apiPost("get_user_data_size")).data || {};
  const sizeMb = sizeInfo.size_mb || 0;
  const items = sizeInfo.items || 0;

  const confirm1 = prompt(
    `Tu vas supprimer ${items} fichiers (${sizeMb} MB) de données utilisateur.\n\n` +
    `Tape exactement "RESET" pour confirmer (ou Annuler pour abandonner) :`
  );
  if (confirm1 !== "RESET") {
    if (confirm1 !== null) alert("Mauvaise confirmation. Reset annulé.");
    return;
  }

  if (!confirm("DERNIÈRE CHANCE : continuer le reset ?\n(un backup sera créé avant la suppression)")) return;

  const res = await apiPost("reset_all_user_data", { confirmation: "RESET" });
  if (res.ok) {
    alert(`Reset terminé.\n\nBackup créé : ${res.backup_path}\n\nL'application va se rafraîchir.`);
    window.location.reload();
  } else {
    alert("Erreur : " + (res.error || "inconnue"));
  }
}

// Wire-up dans la vue settings
document.getElementById("btnOpenResetDialog")?.addEventListener("click", _openResetDialog);

// Au boot vue settings, charger la taille
apiPost("get_user_data_size").then(({ data }) => {
  const el = document.getElementById("userDataSizeInfo");
  if (el && data) el.textContent = `Données actuelles : ${data.items} fichiers (${data.size_mb} MB)`;
});
```

### Étape 5 — CSS

```css
/* V3-09 — Danger zone */
.danger-zone {
  margin-top: 3rem;
  padding-top: 2rem;
  border-top: 2px dashed var(--accent-danger);
}
.danger-zone h2 {
  color: var(--accent-danger);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.danger-card {
  background: rgba(239, 68, 68, 0.05);
  border: 1px solid var(--accent-danger);
  border-radius: var(--radius-md);
  padding: 1.5rem;
  margin-top: 1rem;
}
.btn--danger {
  background: var(--accent-danger);
  color: white;
  border: none;
}
.btn--danger:hover {
  background: #DC2626;
}
```

### Étape 6 — Tests

```python
"""V3-09 — Reset all user data backend."""
from __future__ import annotations
import unittest
from pathlib import Path
import tempfile
import json
import sys; sys.path.insert(0, '.')


class ResetBackendTests(unittest.TestCase):
    def test_reset_requires_correct_confirmation(self):
        from cinesort.ui.api.reset_support import reset_all_user_data

        class FakeApi:
            def _get_state_dir(self): return tempfile.mkdtemp()

        out = reset_all_user_data(FakeApi(), "wrong")
        self.assertFalse(out["ok"])
        self.assertIn("invalide", out["error"].lower())

    def test_reset_with_correct_confirmation(self):
        from cinesort.ui.api.reset_support import reset_all_user_data

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "userdata"
            state.mkdir()
            (state / "settings.json").write_text(json.dumps({"x": 1}))
            (state / "logs").mkdir()
            (state / "logs" / "app.log").write_text("log content")

            class FakeApi:
                def _get_state_dir(self): return str(state)

            out = reset_all_user_data(FakeApi(), "RESET")
            self.assertTrue(out["ok"])
            self.assertIn("settings.json", out["removed"])
            # Logs préservés
            self.assertNotIn("logs", out["removed"])
            self.assertTrue((state / "logs" / "app.log").exists())
            # Backup créé
            backup = Path(out["backup_path"])
            self.assertTrue(backup.exists())

    def test_get_user_data_size(self):
        from cinesort.ui.api.reset_support import get_user_data_size

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "userdata"
            state.mkdir()
            (state / "f1.txt").write_text("a" * 1024)  # 1KB
            (state / "f2.txt").write_text("b" * 2048)  # 2KB

            class FakeApi:
                def _get_state_dir(self): return str(state)

            out = get_user_data_size(FakeApi())
            self.assertEqual(out["items"], 2)
            self.assertGreater(out["size_mb"], 0)


class ResetFrontendTests(unittest.TestCase):
    def test_settings_has_danger_zone(self):
        js = Path("web/dashboard/views/settings-v5.js").read_text(encoding="utf-8")
        self.assertIn("danger-zone", js)
        self.assertIn("RESET", js)

    def test_css_danger_styles(self):
        css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.assertIn(".danger-zone", css)
        self.assertIn(".btn--danger", css)


if __name__ == "__main__":
    unittest.main()
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_reset_all_data -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 8 — Commits

- `feat(api): reset_all_user_data with safety backup (V3-09)`
- `feat(dashboard): danger zone with reset button + double confirmation`
- `style(dashboard): danger zone visual + danger button variant`
- `test(reset): backend reset_support tests + frontend structural`

---

## LIVRABLES

Récap :
- Endpoint `reset_all_user_data(confirmation)` qui exige "RESET" exact
- Backup ZIP automatique avant suppression
- Logs préservés (pour debug si problème)
- Endpoint `get_user_data_size` pour afficher l'impact
- UI Danger Zone visible mais isolée
- Double confirmation (texte + dialog)
- 0 régression
- 4 commits sur `feat/reset-all-data-ui`
