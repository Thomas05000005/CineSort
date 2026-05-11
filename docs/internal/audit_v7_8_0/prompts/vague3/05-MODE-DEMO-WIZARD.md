# V3-05 — Mode démo wizard (1ère ouverture)

**Branche** : `feat/demo-mode-wizard`
**Worktree** : `.claude/worktrees/feat-demo-mode-wizard/`
**Effort** : 1 jour
**Priorité** : 🟠 IMPORTANT (premier-run pour 2000 nouveaux users)
**Fichiers concernés** :
- `cinesort/ui/api/demo_support.py` (nouveau — génération données mock)
- `cinesort/ui/api/cinesort_api.py` (endpoint `start_demo_mode`)
- `web/dashboard/views/demo-wizard.js` (nouveau)
- `web/dashboard/index.html` (overlay wizard)
- `web/dashboard/styles.css` (style wizard)
- `web/dashboard/app.js` (détection 1er run)
- `tests/test_demo_mode.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/demo-mode-wizard .claude/worktrees/feat-demo-mode-wizard audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-demo-mode-wizard

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le système démo. Aucune modif des
vues métier ou de la logique scan/apply.

---

## CONTEXTE

Premier-run problème : un utilisateur installe CineSort, ouvre l'app, vide. Il doit
configurer ses roots, lancer un scan, attendre, comprendre les colonnes... beaucoup de
friction avant de voir un résultat.

**Solution** : si pas de scan effectué (`run_count == 0` && `roots vides`) → proposer
un **wizard mode démo** qui :
1. Crée 15 films fictifs en BDD avec scores variés (Premium / Bon / Moyen / Mauvais)
2. Crée 1 run fictif marqué `is_demo: true`
3. Navigue l'utilisateur sur la vue Bibliothèque pour qu'il voit immédiatement le
   résultat
4. Bandeau "Mode démo actif — pour ton vrai usage, configure tes dossiers dans
   Paramètres"
5. Bouton "Sortir du mode démo" qui supprime les données fictives

---

## MISSION

### Étape 1 — Lire les modules

- `cinesort/ui/api/cinesort_api.py` (voir comment exposer endpoints)
- `cinesort/ui/api/dashboard_support.py` (voir get_dashboard pour comprendre format)
- `cinesort/infra/db/sqlite_store.py` + mixins (voir comment créer rows/runs)
- `tests/e2e/create_test_data.py` (réutiliser logique 15 films mock)

### Étape 2 — Backend `demo_support.py`

Crée `cinesort/ui/api/demo_support.py` :

```python
"""V3-05 — Mode démo wizard (données fictives pour first-run)."""
from __future__ import annotations
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 15 films fictifs représentatifs
DEMO_FILMS = [
    {"title": "Inception", "year": 2010, "tmdb_id": 27205, "tier": "Premium", "score": 92, "resolution": "2160p", "video_codec": "hevc", "audio_codec": "truehd", "channels": 8, "bitrate": 25000},
    {"title": "Interstellar", "year": 2014, "tmdb_id": 157336, "tier": "Premium", "score": 95, "resolution": "2160p", "video_codec": "hevc", "audio_codec": "atmos", "channels": 8, "bitrate": 30000},
    {"title": "The Dark Knight", "year": 2008, "tmdb_id": 155, "tier": "Premium", "score": 89, "resolution": "1080p", "video_codec": "hevc", "audio_codec": "truehd", "channels": 6, "bitrate": 18000},
    {"title": "Pulp Fiction", "year": 1994, "tmdb_id": 680, "tier": "Bon", "score": 78, "resolution": "1080p", "video_codec": "h264", "audio_codec": "ac3", "channels": 6, "bitrate": 12000},
    {"title": "The Matrix", "year": 1999, "tmdb_id": 603, "tier": "Bon", "score": 75, "resolution": "1080p", "video_codec": "h264", "audio_codec": "dts", "channels": 6, "bitrate": 11000},
    {"title": "Fight Club", "year": 1999, "tmdb_id": 550, "tier": "Bon", "score": 72, "resolution": "1080p", "video_codec": "h264", "audio_codec": "ac3", "channels": 6, "bitrate": 10000},
    {"title": "Forrest Gump", "year": 1994, "tmdb_id": 13, "tier": "Bon", "score": 70, "resolution": "1080p", "video_codec": "h264", "audio_codec": "aac", "channels": 6, "bitrate": 9000},
    {"title": "The Godfather", "year": 1972, "tmdb_id": 238, "tier": "Moyen", "score": 62, "resolution": "720p", "video_codec": "h264", "audio_codec": "ac3", "channels": 2, "bitrate": 5000},
    {"title": "Goodfellas", "year": 1990, "tmdb_id": 769, "tier": "Moyen", "score": 60, "resolution": "720p", "video_codec": "h264", "audio_codec": "ac3", "channels": 2, "bitrate": 4500},
    {"title": "Casablanca", "year": 1942, "tmdb_id": 289, "tier": "Moyen", "score": 56, "resolution": "720p", "video_codec": "h264", "audio_codec": "aac", "channels": 2, "bitrate": 3500},
    {"title": "Old Movie SD", "year": 1985, "tmdb_id": None, "tier": "Mauvais", "score": 42, "resolution": "480p", "video_codec": "xvid", "audio_codec": "mp3", "channels": 2, "bitrate": 1500},
    {"title": "Bad Encode", "year": 2018, "tmdb_id": None, "tier": "Mauvais", "score": 38, "resolution": "1080p", "video_codec": "h264", "audio_codec": "aac", "channels": 2, "bitrate": 800},
    {"title": "Sample Trailer", "year": 2020, "tmdb_id": None, "tier": "Mauvais", "score": 25, "resolution": "720p", "video_codec": "h264", "audio_codec": "aac", "channels": 2, "bitrate": 2000},
    {"title": "Cam Rip", "year": 2022, "tmdb_id": None, "tier": "Mauvais", "score": 15, "resolution": "480p", "video_codec": "h264", "audio_codec": "aac", "channels": 2, "bitrate": 1000},
    {"title": "Avatar", "year": 2009, "tmdb_id": 19995, "tier": "Premium", "score": 88, "resolution": "2160p", "video_codec": "hevc", "audio_codec": "atmos", "channels": 8, "bitrate": 28000},
]


def is_demo_active(api) -> bool:
    """True si une run avec is_demo: true est présente."""
    store = api._get_store()
    try:
        with store.conn:  # adapter au pattern réel
            cur = store.conn.execute("SELECT COUNT(*) FROM runs WHERE config_json LIKE '%\"is_demo\":true%'")
            return (cur.fetchone()[0] or 0) > 0
    except Exception:
        return False


def start_demo_mode(api) -> dict:
    """Crée 1 run fictif + 15 films + scores. Retourne le run_id créé."""
    if is_demo_active(api):
        return {"ok": False, "error": "Mode démo déjà actif"}

    store = api._get_store()
    run_id = f"demo_{int(time.time())}"

    # Insertion run + rows + quality_reports
    # ⚠ Adapter aux signatures réelles du store
    config = {"is_demo": True, "root": "C:/DemoMovies"}
    cfg_json = json.dumps(config)

    try:
        store.create_run(run_id=run_id, root="C:/DemoMovies", started_at=time.time(),
                         status="completed", config_json=cfg_json)
        for film in DEMO_FILMS:
            row_id = f"{run_id}_{film['title'].lower().replace(' ', '_')}"
            store.insert_plan_row(run_id=run_id, row_id=row_id, **_film_to_row(film))
            store.insert_quality_report(run_id=run_id, row_id=row_id, **_film_to_quality(film))
        logger.info("V3-05 : mode démo créé (run_id=%s)", run_id)
        return {"ok": True, "run_id": run_id, "count": len(DEMO_FILMS)}
    except Exception as e:
        logger.exception("V3-05 : échec création démo")
        return {"ok": False, "error": str(e)}


def stop_demo_mode(api) -> dict:
    """Supprime tous les runs is_demo + rows + quality_reports liés."""
    store = api._get_store()
    try:
        with store.conn:
            # Récupérer les run_id démo
            cur = store.conn.execute("SELECT run_id FROM runs WHERE config_json LIKE '%\"is_demo\":true%'")
            demo_runs = [r[0] for r in cur.fetchall()]
            for rid in demo_runs:
                store.conn.execute("DELETE FROM quality_reports WHERE run_id = ?", (rid,))
                store.conn.execute("DELETE FROM plan_rows WHERE run_id = ?", (rid,))  # adapter nom table
                store.conn.execute("DELETE FROM runs WHERE run_id = ?", (rid,))
        logger.info("V3-05 : mode démo supprimé (%d runs)", len(demo_runs))
        return {"ok": True, "removed": len(demo_runs)}
    except Exception as e:
        logger.exception("V3-05 : échec suppression démo")
        return {"ok": False, "error": str(e)}


def _film_to_row(film: dict) -> dict:
    """Convertit un film démo en kwargs pour insert_plan_row."""
    return {
        "title": film["title"],
        "year": film["year"],
        "tmdb_id": film.get("tmdb_id"),
        "path": f"C:/DemoMovies/{film['title']} ({film['year']}).mkv",
        "proposed_path": f"C:/DemoMovies/{film['title']} ({film['year']})/{film['title']} ({film['year']}).mkv",
        "confidence": 95 if film.get("tmdb_id") else 0,
        "warning_flags": "[]",
        # ⚠ Compléter selon signature réelle de insert_plan_row
    }


def _film_to_quality(film: dict) -> dict:
    return {
        "score": film["score"],
        "tier": film["tier"],
        "resolution": film["resolution"],
        "video_codec": film["video_codec"],
        "audio_codec": film["audio_codec"],
        "channels": film["channels"],
        "bitrate": film["bitrate"],
        # ⚠ Compléter selon signature réelle
    }
```

⚠ **Adapter aux vraies signatures** : `insert_plan_row`, `insert_quality_report`,
`create_run` peuvent avoir des noms différents. Lire le store d'abord.

### Étape 3 — Endpoints

Dans `cinesort_api.py`, exposer 3 méthodes publiques :

```python
def start_demo_mode(self) -> dict:
    """V3-05 — Active le mode démo (15 films fictifs)."""
    from cinesort.ui.api.demo_support import start_demo_mode
    return start_demo_mode(self)

def stop_demo_mode(self) -> dict:
    """V3-05 — Désactive le mode démo (supprime les données fictives)."""
    from cinesort.ui.api.demo_support import stop_demo_mode
    return stop_demo_mode(self)

def is_demo_mode_active(self) -> dict:
    """V3-05 — True si mode démo actif."""
    from cinesort.ui.api.demo_support import is_demo_active
    return {"data": is_demo_active(self)}
```

### Étape 4 — Wizard frontend

Crée `web/dashboard/views/demo-wizard.js` :

```javascript
// V3-05 — Wizard mode démo (1er run)
import { apiPost } from "../core/api.js";

export async function showDemoWizardIfFirstRun(settings, globalStats) {
  const noRoots = !settings.roots || settings.roots.length === 0;
  const noRuns = !globalStats || (globalStats.total_runs || 0) === 0;
  if (!noRoots || !noRuns) return; // pas premier run

  const isActive = (await apiPost("is_demo_mode_active")).data;
  if (isActive) return; // déjà en mode démo

  _renderWizardOverlay();
}

function _renderWizardOverlay() {
  const overlay = document.createElement("div");
  overlay.className = "demo-wizard-overlay";
  overlay.innerHTML = `
    <div class="demo-wizard-card">
      <h2>👋 Bienvenue dans CineSort</h2>
      <p>Tu n'as pas encore configuré tes dossiers de films.</p>
      <p>Tu peux <strong>tester l'app avec 15 films fictifs</strong> pour voir comment ça marche, sans rien toucher à tes vrais fichiers.</p>
      <div class="demo-wizard-actions">
        <button class="btn btn--primary" id="btnStartDemo">Tester avec 15 films démo</button>
        <button class="btn" id="btnSkipDemo">Configurer mes dossiers</button>
      </div>
      <p class="text-muted">Tu pourras désactiver le mode démo à tout moment depuis l'écran d'accueil.</p>
    </div>
  `;
  document.body.appendChild(overlay);

  document.getElementById("btnStartDemo").addEventListener("click", async () => {
    const res = await apiPost("start_demo_mode");
    if (res.ok) {
      overlay.remove();
      window.location.hash = "#/library";
      window.location.reload();
    } else {
      alert("Erreur : " + (res.error || "inconnue"));
    }
  });

  document.getElementById("btnSkipDemo").addEventListener("click", () => {
    overlay.remove();
    window.location.hash = "#/settings";
  });
}

export async function renderDemoBanner() {
  const isActive = (await apiPost("is_demo_mode_active")).data;
  if (!isActive) return;

  const banner = document.createElement("div");
  banner.className = "demo-banner";
  banner.innerHTML = `
    <span>🎬 Mode démo actif — données fictives. Configure tes vrais dossiers dans <a href="#/settings">Paramètres</a>.</span>
    <button class="btn btn--small" id="btnStopDemo">Sortir du mode démo</button>
  `;
  document.body.insertBefore(banner, document.body.firstChild);

  document.getElementById("btnStopDemo").addEventListener("click", async () => {
    if (!confirm("Supprimer toutes les données démo ?")) return;
    const res = await apiPost("stop_demo_mode");
    if (res.ok) window.location.reload();
  });
}
```

### Étape 5 — Hook au boot

Dans `web/dashboard/app.js`, après le chargement des settings :

```javascript
import { showDemoWizardIfFirstRun, renderDemoBanner } from "./views/demo-wizard.js";
// ...
const settings = (await apiPost("get_settings")).data || {};
const stats = (await apiPost("get_global_stats")).data || {};
await showDemoWizardIfFirstRun(settings, stats);
await renderDemoBanner();
```

### Étape 6 — Style CSS

```css
/* V3-05 — Demo wizard */
.demo-wizard-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(8px);
}
.demo-wizard-card {
  background: var(--surface-elevated);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-lg);
  padding: 2.5rem;
  max-width: 540px;
  text-align: center;
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.demo-wizard-card h2 {
  margin: 0 0 1rem 0;
  color: var(--accent);
}
.demo-wizard-actions {
  display: flex;
  gap: 1rem;
  justify-content: center;
  margin: 2rem 0 1rem 0;
}
.demo-banner {
  background: var(--accent-warning);
  color: var(--bg-primary);
  padding: 0.75rem 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  font-weight: 500;
  z-index: 9000;
  position: sticky;
  top: 0;
}
.demo-banner a { color: inherit; text-decoration: underline; }
```

### Étape 7 — Tests

Crée `tests/test_demo_mode.py` :

```python
"""V3-05 — Mode démo backend + structure UI."""
from __future__ import annotations
import unittest
from pathlib import Path
import sys; sys.path.insert(0, '.')


class DemoModeBackendTests(unittest.TestCase):
    def test_demo_films_count(self):
        from cinesort.ui.api.demo_support import DEMO_FILMS
        self.assertEqual(len(DEMO_FILMS), 15)

    def test_demo_tiers_balanced(self):
        from cinesort.ui.api.demo_support import DEMO_FILMS
        tiers = {f["tier"] for f in DEMO_FILMS}
        # Au moins 3 tiers représentés
        self.assertGreaterEqual(len(tiers), 3)

    def test_functions_exposed(self):
        from cinesort.ui.api.demo_support import (
            is_demo_active, start_demo_mode, stop_demo_mode
        )
        self.assertTrue(callable(is_demo_active))
        self.assertTrue(callable(start_demo_mode))
        self.assertTrue(callable(stop_demo_mode))


class DemoModeFrontendTests(unittest.TestCase):
    def setUp(self):
        self.wizard = Path("web/dashboard/views/demo-wizard.js").read_text(encoding="utf-8")
        self.css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.app_js = Path("web/dashboard/app.js").read_text(encoding="utf-8")

    def test_wizard_exports(self):
        self.assertIn("showDemoWizardIfFirstRun", self.wizard)
        self.assertIn("renderDemoBanner", self.wizard)

    def test_styles_present(self):
        self.assertIn(".demo-wizard-overlay", self.css)
        self.assertIn(".demo-banner", self.css)

    def test_app_imports_wizard(self):
        self.assertIn("demo-wizard.js", self.app_js)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_demo_mode -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 9 — Commits

- `feat(api): demo_support module with 15 fictional films (V3-05)`
- `feat(api): expose start/stop/is_active demo endpoints`
- `feat(dashboard): demo wizard overlay + persistent banner`
- `test(demo): backend + frontend structural tests`

---

## LIVRABLES

Récap :
- 15 films démo en BDD (Premium / Bon / Moyen / Mauvais)
- Wizard overlay au 1er run si pas de roots ni runs
- Bannière persistante en mode démo
- Bouton "Sortir du mode démo" (cleanup BDD)
- 0 régression
- 4 commits sur `feat/demo-mode-wizard`
