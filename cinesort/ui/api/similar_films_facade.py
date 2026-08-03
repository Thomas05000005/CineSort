"""SimilarFilmsFacade : endpoint scaffold pour la recherche de films similaires (V3.3).

Bounded context : "Similar films" (vector kNN via sqlite-vec).
Strategie : feature flag `similar_films` DESACTIVE par defaut. Tant que
la dll vec0 n'est pas integree au bundle PyInstaller (cf
docs/internal/notes/sqlite_vec_setup.md), tous les endpoints retournent
un payload d'erreur structure explicite (pas de crash).

Memoires :
    - PAS de bundle DL au 1er usage : la dll vec0 DOIT etre dans le
      bundle, +120MB accepte.
    - perceptual != quality : les embeddings ici sont des "perceptual
      hashes" reduits (signature visuelle), DISTINCTS du quality score.
    - Code robuste aux binaires absents : si vec0.dll absent,
      VectorSearchUnavailableError est rattrape et un payload de
      degradation est retourne.

Architecture (import-linter) : cinesort.ui.api peut importer
cinesort.infra.vector_search (ui -> infra OK).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Feature flag global. Mettre True une fois vec0.dll bundle (V3.3 runtime).
SIMILAR_FILMS_FEATURE_FLAG: bool = False


def _feature_disabled_payload(reason: str = "feature_flag_disabled") -> Dict[str, Any]:
    """Payload de degradation lorsque la feature `similar_films` est OFF.

    Forme stable pour les call sites UI : { ok: False, reason: str,
    results: [] }. La compat ascendante avec le futur shape success
    sera assuree en V3.3 runtime.
    """
    return {
        "ok": False,
        "reason": reason,
        "results": [],
    }


class SimilarFilmsFacade:
    """Facade bounded context Similar Films (scaffold V3.3, flag OFF).

    Args:
        api: Instance CineSortApi parent (delegation helpers internes).
            Pour le scaffold, l'instance n'est pas encore utilisee mais
            est conservee pour symetrie avec les autres facades.
    """

    def __init__(self, api: Any) -> None:
        self._api = api

    # ---------- Status / introspection ----------

    def get_similar_films_status(self) -> Dict[str, Any]:
        """Retourne l'etat de la feature `similar_films`.

        Forme : { enabled: bool, extension_loaded: bool, reason: str|None }
        Toujours sur (ne tente PAS de charger la dll si flag OFF).
        """
        return {
            "enabled": SIMILAR_FILMS_FEATURE_FLAG,
            "extension_loaded": False,
            "reason": (None if SIMILAR_FILMS_FEATURE_FLAG else "feature_flag_disabled"),
        }

    # ---------- Endpoint scaffold ----------

    def find_similar_films(
        self,
        film_id: int,
        k: int = 10,
    ) -> Dict[str, Any]:
        """Recherche les k films les plus similaires a `film_id` (kNN cosine).

        Args:
            film_id: PK du film de reference (INTEGER).
            k: Nombre max de voisins a retourner (>= 1).

        Returns:
            Si feature flag OFF :
                { ok: False, reason: "feature_flag_disabled", results: [] }
            Si feature flag ON mais vec0.dll absente :
                { ok: False, reason: "extension_unavailable", results: [] }
            Sinon (V3.3 runtime) :
                { ok: True, results: [{film_id, distance}, ...] }
        """
        if not SIMILAR_FILMS_FEATURE_FLAG:
            return _feature_disabled_payload("feature_flag_disabled")

        # V3.3 runtime : delegation a SqliteVecAdapter.knn_search().
        # Scaffold : pas de chargement ni d'appel reel pour ne pas
        # impacter les utilisateurs avec flag OFF.
        return _feature_disabled_payload("not_implemented_yet")

    def compute_film_embedding(
        self,
        film_id: int,
        force_recompute: bool = False,
    ) -> Dict[str, Any]:
        """Calcule et persiste l'embedding d'un film (scaffold).

        Args:
            film_id: PK du film cible.
            force_recompute: Si True, recalcul meme si deja present.

        Returns:
            { ok: bool, reason: str|None, embedding_dim: int|None }
        """
        if not SIMILAR_FILMS_FEATURE_FLAG:
            return {
                "ok": False,
                "reason": "feature_flag_disabled",
                "embedding_dim": None,
            }
        return {
            "ok": False,
            "reason": "not_implemented_yet",
            "embedding_dim": None,
        }

    def batch_compute_embeddings(
        self,
        film_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Batch compute pour une liste de film_id (None = tous les films).

        Forme degradation : { ok: False, reason: str, processed: 0,
        skipped: 0, errors: [] }.
        """
        if not SIMILAR_FILMS_FEATURE_FLAG:
            return {
                "ok": False,
                "reason": "feature_flag_disabled",
                "processed": 0,
                "skipped": 0,
                "errors": [],
            }
        return {
            "ok": False,
            "reason": "not_implemented_yet",
            "processed": 0,
            "skipped": 0,
            "errors": [],
        }
