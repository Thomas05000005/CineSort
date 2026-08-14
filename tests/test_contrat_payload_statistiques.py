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
        """LE cas qui a coute l'ecran — eprouve sur le PAYLOAD, pas sur le source.

        Version precedente : `inspect.getsource(library_support)` puis
        `assertIn('"group_name"', source)`. C'est la famille que `CLAUDE.md`
        proscrit, et les deux reproches se verifiaient ici :

        - elle serait restee VERTE si `group_name` etait devenue une cle morte
          ailleurs dans le module (la chaine y est, le rollup ne l'emet plus) ;
        - elle serait devenue ROUGE sur un simple renommage de variable interne.

        Son motif etait reel : une bibliotheque vide ne rend aucun groupe, donc
        aucun element a inspecter. La reponse n'est pas de lire le source, c'est
        de FOURNIR une row — au niveau ou la production la fabrique.
        `_build_library_rows` est le seul producteur de rows du rollup ; on
        l'intercepte la, et on lit ce que la vraie aggregation emet.
        """
        from cinesort.ui.api import library_support

        row = {
            "row_id": "r1",
            "title": "Dune",
            "year": 2024,
            "codec": "x265",
            # DERIVEE de la production, pas ecrite a la main : `_classify_resolution`
            # n'emet jamais « 2160p ». Meme discipline que
            # tests/test_statistiques_dimensions.py.
            "resolution": library_support._classify_resolution(3840, 2160),
            "grain_era_v2": "modern_digital",
            "tmdb_collection_name": "Dune (collection)",
            "score_v2": 88.0,
            "display_tier": "gold",
        }

        vrai_build = library_support._build_library_rows
        vrai_resolve = library_support._resolve_run_id
        library_support._build_library_rows = lambda *a, **k: [row]
        library_support._resolve_run_id = lambda *a, **k: "run-1"
        try:
            rep = library_support.get_scoring_rollup(self.api, by="franchise")
        finally:
            library_support._build_library_rows = vrai_build
            library_support._resolve_run_id = vrai_resolve

        groupes = rep.get("groups") or []
        self.assertTrue(groupes, f"le rollup ne rend aucun groupe sur une row complete : {rep}")

        attendu = _LU_PAR_LA_VUE["library/get_scoring_rollup"]["element"]
        manquantes = [c for c in attendu if c not in groupes[0]]
        self.assertEqual(
            manquantes,
            [],
            f"le rollup n'emet plus {manquantes} — la vue Statistiques affichera "
            f"« — » sur chaque ligne du tableau Scores. Emis : {sorted(groupes[0])}",
        )
        # ASSERTER LA VALEUR, PAS SEULEMENT LA PRESENCE : une cle presente mais
        # vide vide l'ecran tout autant.
        self.assertEqual(groupes[0]["group_name"], "Dune (collection)")

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
