"""SqliteVecAdapter : wrapper sur l'extension SQLite `sqlite-vec` (V3.3 scaffold).

Pattern : adapter infra autour de la dll C `vec0.dll` (Windows) bundlee
dans dist/CineSort.exe via PyInstaller --add-binary. Le chargement de
l'extension est LAZY (premiere methode appelee), pour eviter le cout
si la feature flag `similar_films` est OFF.

API publique :
    - load_extension(conn)             : charge vec0.dll dans la connection
    - create_vec_table()               : cree vec_films_hash (idempotent)
    - add_embedding(film_id, vec)      : insert/update un embedding
    - knn_search(query_vec, k)         : top-k voisins par similarite cosine

Memoires :
    - subprocess direct > wrappers Python : ici extension C native, pas
      de subprocess (sqlite3.enable_load_extension natif).
    - Code robuste aux binaires absents : si vec0.dll absent, lever
      VectorSearchUnavailableError EXPLICITE (pas crash silencieux).
    - PAS de bundle DL au 1er usage : la dll vec0 DOIT etre dans le
      bundle PyInstaller (cf sqlite_vec_setup.md, accepte +120MB).

Architecture (import-linter) : ce module est en cinesort/infra/, peut
importer cinesort.infra.errors mais PAS cinesort.app / cinesort.ui /
cinesort.domain.

V3.3 status : SCAFFOLD uniquement. Aucun appel runtime tant que la
feature flag `similar_films` n'est pas activee (cf
similar_films_facade.py, feature_flag=disabled par defaut).
"""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


class VectorSearchUnavailableError(RuntimeError):
    """Levee si vec0.dll est absent ou ne peut etre charge."""


class SqliteVecAdapter:
    """Adapter sur l'extension sqlite-vec (lazy load, kNN cosine).

    Args:
        conn: Connection sqlite3 ouverte (typiquement issue de
            cinesort.infra.db.connection.get_connection).
        extension_path: Chemin optionnel vers vec0.dll. Si None, recherche
            dans `_default_extension_path()` (a cote de l'exe bundlee).
        embedding_dim: Dimension attendue pour les embeddings (defaut 256).
            Garde-fou : add_embedding rejette les vecteurs de taille
            differente.
    """

    EMBEDDING_DIM_DEFAULT: int = 256
    VEC_TABLE_NAME: str = "vec_films_hash"

    def __init__(
        self,
        conn: sqlite3.Connection,
        extension_path: Optional[Path] = None,
        embedding_dim: int = EMBEDDING_DIM_DEFAULT,
    ) -> None:
        self._conn = conn
        self._extension_path = extension_path or self._default_extension_path()
        self._embedding_dim = embedding_dim
        self._loaded: bool = False

    # ---------- Lazy load ----------

    @staticmethod
    def _default_extension_path() -> Path:
        """Chemin par defaut vers vec0.dll (a cote du bundle PyInstaller).

        Convention bundle : `dist/CineSort/vec0.dll` ou, en dev, a la
        racine du repo dans `vendor/sqlite-vec/vec0.dll`.
        Cf docs/internal/notes/sqlite_vec_setup.md.
        """
        # SCAFFOLD : path resolution definitive faite en V3.3 runtime,
        # ici on retourne un placeholder qui sera valide par load_extension.
        return Path("vendor") / "sqlite-vec" / "vec0.dll"

    def load_extension(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """Charge vec0.dll dans la connection (idempotent).

        Args:
            conn: Connection cible. Si None, utilise self._conn.

        Raises:
            VectorSearchUnavailableError: si vec0.dll absent ou si
                enable_load_extension echoue (Python compile sans support
                extensions).
        """
        target = conn or self._conn
        if self._loaded and conn is None:
            return

        if not self._extension_path.exists():
            raise VectorSearchUnavailableError(
                f"vec0.dll introuvable : {self._extension_path}. "
                "Cf docs/internal/notes/sqlite_vec_setup.md pour l'installation."
            )

        try:
            target.enable_load_extension(True)
            target.load_extension(str(self._extension_path))
            target.enable_load_extension(False)
        except sqlite3.OperationalError as exc:
            raise VectorSearchUnavailableError(f"Echec chargement sqlite-vec : {exc}") from exc
        except AttributeError as exc:
            # Python compile sans --enable-loadable-sqlite-extensions
            raise VectorSearchUnavailableError(
                "Python ne supporte pas les extensions SQLite chargeables "
                "(recompiler avec --enable-loadable-sqlite-extensions)."
            ) from exc

        if conn is None:
            self._loaded = True

    # ---------- Schema ----------

    def create_vec_table(self) -> None:
        """Cree la table vec_films_hash si absente (idempotent).

        Note : la table SQL plate est creee par la migration 032
        (vec_films_hash : film_id, embedding BLOB). Cette methode peut
        creer en plus une VIRTUAL TABLE `vec0` indexee, qui n'est PAS
        dans la migration (necessite l'extension chargee a runtime).
        """
        self.load_extension()
        # SCAFFOLD : creation virtual table vec0 (HNSW) a faire en V3.3.
        # Forme attendue :
        #     CREATE VIRTUAL TABLE IF NOT EXISTS vec_films_hash_idx
        #     USING vec0(embedding float[256])
        # Voir docs/internal/notes/sqlite_vec_setup.md section "Index HNSW".
        raise NotImplementedError("create_vec_table : a implementer en V3.3 runtime (virtual table vec0).")

    # ---------- CRUD embeddings ----------

    def add_embedding(self, film_id: int, vec: Sequence[float]) -> None:
        """Insere ou met a jour l'embedding d'un film.

        Args:
            film_id: PK dans la table films (INTEGER).
            vec: Vecteur d'embedding (typiquement issue d'un modele
                perceptual hash + reduction dimensionnelle).

        Raises:
            ValueError: si len(vec) != self._embedding_dim.
            VectorSearchUnavailableError: si extension non chargee.
        """
        if len(vec) != self._embedding_dim:
            raise ValueError(f"Dimension embedding invalide : {len(vec)} (attendu {self._embedding_dim}).")
        self.load_extension()
        # SCAFFOLD : la serialisation float32 little-endian est la forme
        # attendue par sqlite-vec. Implementation runtime en V3.3.
        _blob = struct.pack(f"<{len(vec)}f", *vec)
        raise NotImplementedError("add_embedding : a implementer en V3.3 runtime (INSERT OR REPLACE).")

    def knn_search(
        self,
        query_vec: Sequence[float],
        k: int = 10,
    ) -> List[Tuple[int, float]]:
        """Recherche les k voisins les plus proches (similarite cosine).

        Args:
            query_vec: Vecteur de requete (meme dim que embedding_dim).
            k: Nombre de voisins a retourner (max).

        Returns:
            Liste de tuples (film_id, distance) tries par distance
            croissante (plus proche en premier).

        Raises:
            ValueError: si len(query_vec) != self._embedding_dim.
            VectorSearchUnavailableError: si extension non chargee.
        """
        if len(query_vec) != self._embedding_dim:
            raise ValueError(f"Dimension query invalide : {len(query_vec)} (attendu {self._embedding_dim}).")
        if k <= 0:
            raise ValueError(f"k doit etre > 0 (recu {k}).")
        self.load_extension()
        # SCAFFOLD : implementation runtime en V3.3.
        # Forme attendue :
        #     SELECT film_id, distance FROM vec_films_hash_idx
        #     WHERE embedding MATCH ? AND k = ?
        #     ORDER BY distance
        raise NotImplementedError("knn_search : a implementer en V3.3 runtime (vec0 MATCH operator).")
