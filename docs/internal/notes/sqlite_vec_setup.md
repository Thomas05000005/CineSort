# sqlite-vec setup (V3.3 scaffold)

Procedure pour integrer l'extension SQLite `sqlite-vec` (kNN vector
search) dans CineSort. Etat actuel : SCAFFOLD uniquement, dll non
encore bundle, feature flag `similar_films` OFF par defaut.

## Contexte

- Bounded context : recherche de films similaires via embeddings
  perceptuels (signature visuelle, distincte du quality score).
- Backend : `sqlite-vec` (extension C native, MIT, repo
  https://github.com/asg017/sqlite-vec).
- Storage : table plate `vec_films_hash` (migration 032) + virtual
  table `vec_films_hash_idx` (HNSW, creee a runtime).
- Code : `cinesort/infra/vector_search/sqlite_vec_adapter.py`,
  `cinesort/ui/api/similar_films_facade.py`.

## Memoires applicables

- Subprocess direct ffprobe : non applicable ici (extension C native
  chargee via `sqlite3.load_extension`).
- PAS DE BUNDLE DL au 1er usage : la dll vec0 DOIT etre dans le bundle
  PyInstaller, +120MB accepte.
- Backward compat ABSOLUE : migration 032 ne fait que `CREATE TABLE
  IF NOT EXISTS`, aucune modification de schema existant.
- perceptual != quality : ces embeddings n'entrent PAS dans le
  quality_profile ni le global_score.

## Etape 1 : telecharger vec0.dll (Windows)

1. Aller sur https://github.com/asg017/sqlite-vec/releases
2. Telecharger `sqlite-vec-<version>-loadable-windows-x86_64.tar.gz`
3. Extraire `vec0.dll` (taille ~500 KB)
4. Placer dans `vendor/sqlite-vec/vec0.dll` a la racine du repo
   (cree le dossier si necessaire)
5. NE PAS commit la dll : ajouter `vendor/sqlite-vec/*.dll` au
   `.gitignore` si pas deja present

Version pinnee recommandee : derniere release stable au moment du
bundle V3.3 (verifier les changelogs pour les ruptures d'API).

## Etape 2 : verifier en dev

```powershell
# Depuis la racine du repo
python -c "import sqlite3; c = sqlite3.connect(':memory:'); c.enable_load_extension(True); c.load_extension(r'vendor\sqlite-vec\vec0'); print(c.execute('SELECT vec_version()').fetchone())"
```

Resultat attendu : tuple `('v0.x.y',)`. Si erreur :
- `AttributeError: enable_load_extension` : Python compile sans
  `--enable-loadable-sqlite-extensions`. Recompiler ou utiliser
  python.org build officiel (qui l'active par defaut).
- `OperationalError: unable to load DLL` : verifier le chemin et que
  la dll n'est pas bloquee par Windows (clic droit > Proprietes >
  Debloquer).

## Etape 3 : integration PyInstaller

Modifier `CineSort.spec` (ou equivalent) pour inclure vec0.dll dans le
bundle :

```python
binaries=[
    ('vendor/sqlite-vec/vec0.dll', 'sqlite_vec'),
    # ... autres binaires (ffprobe, mediainfo, ...)
]
```

Puis adapter `SqliteVecAdapter._default_extension_path()` pour resoudre
le chemin dans le bundle PyInstaller :

```python
import sys
if getattr(sys, 'frozen', False):
    base = Path(sys._MEIPASS) / "sqlite_vec"
else:
    base = Path("vendor") / "sqlite-vec"
return base / "vec0.dll"
```

## Etape 4 : index HNSW a runtime

La migration 032 cree uniquement la table plate `vec_films_hash`.
L'index HNSW (virtual table `vec0`) doit etre cree a runtime par
`SqliteVecAdapter.create_vec_table()` une fois l'extension chargee :

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_films_hash_idx
USING vec0(embedding float[256]);
```

Le `float[256]` correspond a `SqliteVecAdapter.EMBEDDING_DIM_DEFAULT`.
Si la dimension evolue en V3.4+, prevoir une migration de donnees
(rebuild des embeddings + DROP/CREATE virtual table).

## Etape 5 : activer le feature flag

Une fois la dll bundle et l'integration testee :

```python
# cinesort/ui/api/similar_films_facade.py
SIMILAR_FILMS_FEATURE_FLAG: bool = True
```

Et brancher la facade dans `CineSortApi.__init__` :

```python
self.similar_films = SimilarFilmsFacade(self)
```

## Test plan V3.3

- [ ] vec0.dll telechargee et placee dans `vendor/sqlite-vec/`
- [ ] Verification dev : `vec_version()` retourne une version
- [ ] Migration 032 appliquee sur base PRE-EXISTANTE (memoire
      feedback_sqlite_migration_test_existing_db) et base fraiche
- [ ] PyInstaller spec mis a jour, dll bundle dans dist/CineSort/
- [ ] `SqliteVecAdapter.create_vec_table()` cree la virtual table
- [ ] `add_embedding(film_id, vec)` insere/update sans erreur
- [ ] `knn_search(query, k=10)` retourne 10 voisins tries
- [ ] Feature flag ON : endpoint `find_similar_films` retourne payload
      success
- [ ] Feature flag OFF (regression check) : endpoint retourne payload
      degradation `feature_flag_disabled` sans crash

## References

- Repo upstream : https://github.com/asg017/sqlite-vec
- Doc API : https://alexgarcia.xyz/sqlite-vec/
- Memoire CineSort : `project_cinesort.md`,
  `feedback_cinesort_design.md`,
  `feedback_sqlite_migration_test_existing_db.md`
- Migration : `cinesort/infra/db/migrations/032-vector-search-tables.sql`
- Adapter : `cinesort/infra/vector_search/sqlite_vec_adapter.py`
- Facade : `cinesort/ui/api/similar_films_facade.py`
