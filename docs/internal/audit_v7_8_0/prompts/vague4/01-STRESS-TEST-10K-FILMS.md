# V4-01 — Stress test 10 000 films (perf + crash + UI tient)

**Branche** : `test/stress-10k-films`
**Worktree** : `.claude/worktrees/test-stress-10k-films/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable (100% scriptable)
**Fichiers concernés** :
- `tests/stress/test_10k_films.py` (nouveau)
- `tests/stress/generate_demo_library.py` (nouveau — générateur)
- `audit/results/v4-01-stress-results.md` (nouveau — rapport)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b test/stress-10k-films .claude/worktrees/test-stress-10k-films audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/test-stress-10k-films

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `tests/stress/` + le rapport markdown.
Aucune modif des modules métier.

REGLE NO-DESTRUCTION : tu travailles sur une **DB temporaire** (tempdir), pas la
vraie DB CineSort de l'utilisateur.

---

## CONTEXTE

CineSort est conçu pour des bibliothèques personnelles (~100-1000 films). Mais certains
power users ont des collections de **10 000+ films** (ratio cinéphiles obsessifs). On
doit valider que :
1. Le scan termine sans crasher
2. La DB SQLite ne devient pas illisiblement lente
3. L'UI dashboard charge sans freeze
4. La RAM reste raisonnable (< 1 GB pic)
5. Les opérations critiques (`get_dashboard`, `library_filtered`) restent < 2s

---

## MISSION

### Étape 1 — Générateur de données mock

Crée `tests/stress/generate_demo_library.py` :

```python
"""V4-01 — Génère N films fictifs en BDD pour stress test.

Usage: python tests/stress/generate_demo_library.py 10000 /tmp/test.db
"""
from __future__ import annotations
import argparse
import logging
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from cinesort.infra.db.connection import connect_sqlite
from cinesort.infra.db.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Pools réalistes
RESOLUTIONS = ["480p", "720p", "1080p", "1440p", "2160p"]
VIDEO_CODECS = ["h264", "hevc", "av1", "vp9", "mpeg4"]
AUDIO_CODECS = ["aac", "ac3", "eac3", "dts", "dts-hd ma", "truehd", "atmos"]
TIERS = ["Premium", "Bon", "Moyen", "Mauvais"]
TIER_WEIGHTS = [0.20, 0.40, 0.30, 0.10]  # distribution réaliste


def generate_films(n: int, db_path: Path) -> dict:
    """Génère N films fictifs. Retourne stats {duration_s, total_films}."""
    t0 = time.perf_counter()
    store = SQLiteStore(str(db_path.parent))  # adapter au constructor réel
    run_id = f"stress_{int(time.time())}"

    # Run unique
    store.create_run(run_id=run_id, root="C:/StressMovies", started_at=time.time(),
                     status="completed", config_json='{"is_stress": true}')

    for i in range(n):
        title = f"Film stress {i:05d}"
        year = random.randint(1950, 2025)
        tier = random.choices(TIERS, weights=TIER_WEIGHTS, k=1)[0]
        score = {"Premium": random.randint(85, 100), "Bon": random.randint(68, 84),
                 "Moyen": random.randint(54, 67), "Mauvais": random.randint(20, 53)}[tier]
        store.insert_plan_row(
            run_id=run_id,
            row_id=f"{run_id}_{i:05d}",
            title=title, year=year,
            path=f"C:/StressMovies/{title} ({year}).mkv",
            proposed_path=f"C:/StressMovies/{title} ({year})/{title} ({year}).mkv",
            confidence=random.randint(0, 100),
            warning_flags="[]",
        )
        store.insert_quality_report(
            run_id=run_id, row_id=f"{run_id}_{i:05d}",
            score=score, tier=tier,
            resolution=random.choice(RESOLUTIONS),
            video_codec=random.choice(VIDEO_CODECS),
            audio_codec=random.choice(AUDIO_CODECS),
            channels=random.choice([2, 6, 8]),
            bitrate=random.randint(800, 30000),
        )

        if i % 1000 == 0 and i > 0:
            logger.info("Inséré %d films... (%.1fs)", i, time.perf_counter() - t0)

    store.conn.commit()
    duration = time.perf_counter() - t0
    return {"duration_s": duration, "total_films": n, "run_id": run_id}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, default=10000)
    parser.add_argument("db_path", type=str, default="/tmp/stress.db")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists(): db_path.unlink()

    stats = generate_films(args.count, db_path)
    print(f"\n✅ Généré {stats['total_films']} films en {stats['duration_s']:.1f}s")
    print(f"   DB : {db_path} ({db_path.stat().st_size / 1024 / 1024:.1f} MB)")
```

⚠ **Adapter** `SQLiteStore`, `create_run`, `insert_plan_row`, `insert_quality_report`
aux vraies signatures du store CineSort. Lire `cinesort/infra/db/sqlite_store.py`
+ ses mixins pour confirmer.

### Étape 2 — Test stress

Crée `tests/stress/test_10k_films.py` :

```python
"""V4-01 — Stress test 10 000 films : perf + RAM + UI."""
from __future__ import annotations
import gc
import os
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

sys.path.insert(0, ".")


class Stress10kTests(unittest.TestCase):
    """⚠ Skip par défaut. Lancer avec : CINESORT_STRESS=1 python -m unittest tests.stress.test_10k_films -v"""

    @classmethod
    def setUpClass(cls):
        if os.environ.get("CINESORT_STRESS") != "1":
            raise unittest.SkipTest("Stress test : set CINESORT_STRESS=1 to run")

        cls.tmpdir = tempfile.mkdtemp(prefix="cinesort_stress_")
        cls.db_path = Path(cls.tmpdir) / "stress.db"

        # Génération
        from tests.stress.generate_demo_library import generate_films
        cls.gen_stats = generate_films(10000, cls.db_path)

    def test_dashboard_loads_under_2s(self):
        from cinesort.ui.api.dashboard_support import get_global_stats
        # Construire une fake api/store sur la DB temp (adapter pattern)
        # ...
        t0 = time.perf_counter()
        # res = get_global_stats(api)
        # ⚠ Adapter selon les vraies signatures
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 2.0, f"get_global_stats trop lent : {elapsed:.2f}s sur 10k films")

    def test_library_filter_under_2s(self):
        from cinesort.ui.api.library_support import get_library_filtered
        t0 = time.perf_counter()
        # res = get_library_filtered(api, filters={"tier": "Premium"})
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 2.0, f"library_filtered trop lent : {elapsed:.2f}s sur 10k films")

    def test_ram_pic_under_1gb(self):
        tracemalloc.start()
        from cinesort.ui.api.dashboard_support import get_global_stats
        # Simuler 10 chargements consécutifs
        # for _ in range(10): get_global_stats(api)
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")
        peak_mb = sum(s.size for s in top_stats) / 1024 / 1024
        tracemalloc.stop()
        self.assertLess(peak_mb, 1024, f"Pic RAM > 1 GB : {peak_mb:.1f} MB")

    def test_db_size_under_100mb(self):
        size_mb = self.db_path.stat().st_size / 1024 / 1024
        self.assertLess(size_mb, 100, f"DB > 100 MB sur 10k films : {size_mb:.1f} MB")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
```

⚠ **Adapter** les imports `get_global_stats`, `get_library_filtered`, `library_support`
+ les patterns d'instanciation api/store aux vraies signatures.

### Étape 3 — Lance le test et collecte résultats

```bash
CINESORT_STRESS=1 .venv313/Scripts/python.exe -m unittest tests.stress.test_10k_films -v 2>&1 | tee /tmp/stress_output.log
```

### Étape 4 — Rapport résultats

Crée `audit/results/v4-01-stress-results.md` avec :

```markdown
# V4-01 — Résultats stress test 10 000 films

**Date** : YYYY-MM-DD
**Machine de test** : Windows 11, RAM, CPU model

## Génération données
- Films : 10 000
- Durée génération : XX.X s
- Taille DB SQLite : XX MB

## Performance UI
| Endpoint | Temps observé | Seuil | Verdict |
|---|---|---|---|
| `get_global_stats` | XX ms | < 2 s | ✅/❌ |
| `get_library_filtered` (tier=Premium) | XX ms | < 2 s | ✅/❌ |
| `get_dashboard` | XX ms | < 2 s | ✅/❌ |

## RAM
- Pic observé : XX MB (sur 10 chargements consécutifs)
- Seuil : < 1 GB → ✅/❌

## DB
- Taille finale : XX MB
- Seuil : < 100 MB → ✅/❌

## Verdict global
✅ READY POUR PUBLIC RELEASE / ❌ Optimisations nécessaires : (lister)
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m ruff check tests/stress/ 2>&1 | tail -2
CINESORT_STRESS=1 .venv313/Scripts/python.exe -m unittest tests.stress.test_10k_films -v 2>&1 | tail -10
```

### Étape 6 — Commits

- `test(stress): generator for N fictional films via SQLite (V4-01)`
- `test(stress): 10k films perf + RAM + DB size assertions`
- `docs(audit): stress test results v4-01`

---

## LIVRABLES

- `tests/stress/generate_demo_library.py`
- `tests/stress/test_10k_films.py` (skip par défaut, opt-in via env)
- `audit/results/v4-01-stress-results.md` avec verdict
- 0 régression suite tests
- 3 commits sur `test/stress-10k-films`
