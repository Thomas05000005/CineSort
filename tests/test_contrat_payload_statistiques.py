"""Les cles que le backend EMET, epinglees pour la vue qui les lit.

POURQUOI CE FICHIER EXISTE. La vue Statistiques lisait `g.group || g.name ||
g.key` pour nommer une ligne du tableau « Scores ». Or `get_scoring_rollup`
emet **`group_name`** — aucune des trois. Chaque ligne du tableau se serait
affichee « — », c'est-a-dire l'ecran entier vide de sens.

Le test de la vue ne l'a pas vu parce qu'il INVENTAIT `group` dans son
echantillon. Une fixture qui ne vient pas de la production ne prouve que la
coherence du test avec lui-meme : les deux cotes etaient d'accord sur une cle
qui n'existe nulle part.

CE QUE CES TESTS EPROUVENT. Ils appellent le VRAI backend et epinglent le nom
des cles. Si une route renomme un champ, ils rougissent ici — a l'endroit ou la
cause est lisible — plutot que de laisser un ecran se vider en silence.

Ils n'epinglent QUE les cles que la vue consomme reellement : epingler la forme
entiere ferait rougir ce fichier a chaque enrichissement du payload, et un test
qui rougit pour de bonnes nouvelles finit par etre desactive.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi

#: Ce que `web/dashboard/views/statistiques.js` lit dans chaque reponse.
_LU_PAR_LA_VUE = {
    "library/get_scoring_rollup": {
        "racine": ("ok", "groups"),
        # `_rendreRollup` : g.group_name, g.count, g.avg_score
        "element": ("group_name", "count", "avg_score"),
        "liste": "groups",
    },
    "library/get_library_podiums": {
        "racine": ("ok", "total_films", "release_groups", "codecs", "sources"),
        # `_podium` : e.name, e.count
        "element": ("name", "count"),
        "liste": "release_groups",
    },
    "library/get_library_timeline": {
        "racine": ("ok", "source", "months"),
        # `_rendreTimeline` : m.month, m.count
        "element": ("month", "count"),
        "liste": "months",
    },
}


class LesClesDuBackendSontCELLESQueLaVueLitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_stats_payload_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp / "state"  # type: ignore[attr-defined]
        self.api._state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _appeler(self, route: str) -> dict:
        _facade, methode = route.split("/", 1)
        return getattr(self.api.library, methode)() or {}

    def test_les_cles_RACINE_sont_presentes(self) -> None:
        """Une bibliotheque vide suffit : ces cles doivent exister meme sans film,
        sinon la vue lit `undefined` la ou elle attend une liste."""
        for route, attendu in _LU_PAR_LA_VUE.items():
            with self.subTest(route=route):
                rep = self._appeler(route)
                self.assertTrue(rep.get("ok"), f"{route} a echoue : {rep}")
                manquantes = [c for c in attendu["racine"] if c not in rep]
                self.assertEqual(
                    manquantes,
                    [],
                    f"{route} n'emet plus {manquantes} — la vue lit ces cles",
                )

    def test_le_rollup_nomme_ses_groupes_group_name(self) -> None:
        """LE cas qui a coute l'ecran.

        La cle est verifiee sur la DOCUMENTATION EXECUTABLE de la fonction — sa
        propre construction — plutot que sur un echantillon : une bibliotheque
        vide ne rend aucun groupe, donc aucun element a inspecter.
        """
        import inspect

        from cinesort.ui.api import library_support

        source = inspect.getsource(library_support)
        self.assertIn(
            '"group_name"',
            source,
            "get_scoring_rollup ne construit plus `group_name` : la vue Statistiques "
            "affichera « — » sur chaque ligne du tableau Scores",
        )
        for absente in ('"group":', '"key":'):
            self.assertNotIn(
                f"groups.append({{\n                {absente}",
                source,
                f"le rollup emet desormais {absente} : la vue lit `group_name`",
            )

    def test_la_timeline_rend_bien_une_liste_de_mois_datee(self) -> None:
        rep = self._appeler("library/get_library_timeline")

        self.assertIsInstance(rep.get("months"), list)
        self.assertIn(
            str(rep.get("source") or ""),
            {"jellyfin", "filesystem", "mixed"},
            "la vue traduit `source` en une phrase ; une valeur inconnue n'affiche rien",
        )


if __name__ == "__main__":
    unittest.main()
