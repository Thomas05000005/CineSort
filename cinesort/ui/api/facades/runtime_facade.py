"""RuntimeFacade : bounded context Runtime / Help (spec 12-aide.md).

Cf docs/internal/design/refonte_2026_05_17/screens/12-aide.md.

4 endpoints exposes pour l'ecran Aide :
    - get_diagnostic : bloc texte complet (version, Python, DB, integrations...)
    - get_recent_logs : N dernieres lignes du log courant (cap a 1000)
    - get_doc : lecture d'un markdown whiteliste (anti path traversal)
    - search_docs : recherche full-text dans les docs publiques

Strategie : meme pattern Strangler Fig + Adapter que les autres facades.
Les methodes existent EN PARALLELE sur CineSortApi via `_X_impl()` pour
preserver la backward-compat 100%. Cette facade delegue simplement.

Usage frontend :
    api.runtime.get_diagnostic()
    api.runtime.get_recent_logs(limit=100)
    api.runtime.get_doc("user-guide")
    api.runtime.search_docs("score V2")
"""

from __future__ import annotations

from typing import Any, Dict

from cinesort.ui.api.facades._base import _BaseFacade


class RuntimeFacade(_BaseFacade):
    """Bounded context Runtime/Help : diagnostic, logs, docs (spec ecran 12)."""

    def get_diagnostic(self) -> Dict[str, Any]:
        """Retourne le diagnostic complet pour le bouton "Copier diagnostic".

        Cf CineSortApi._get_diagnostic_impl pour la doc complete.
        """
        return self._api._get_diagnostic_impl()

    def get_recent_logs(self, limit: int = 100) -> Dict[str, Any]:
        """Lit les N dernieres lignes du log courant (cap a 1000).

        Cf CineSortApi._get_recent_logs_impl pour la doc complete.
        """
        return self._api._get_recent_logs_impl(limit)

    def get_doc(self, file: str) -> Dict[str, Any]:
        """Retourne le contenu markdown brut d'un document whiteliste.

        Cf CineSortApi._get_doc_impl pour la doc complete. Tout chemin
        contenant `..` ou doc_id inconnu est rejete (category="validation").
        """
        return self._api._get_doc_impl(file)

    def search_docs(self, query: str) -> Dict[str, Any]:
        """Recherche full-text dans tous les documents whitelistes.

        Cf CineSortApi._search_docs_impl pour la doc complete.
        """
        return self._api._search_docs_impl(query)
