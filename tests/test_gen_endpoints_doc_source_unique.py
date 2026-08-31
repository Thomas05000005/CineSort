"""Le generateur de `docs/api/ENDPOINTS.md` doit lire la MEME source que le dispatcher.

Constats d'audit couverts (lot « endpoints », 2026-08-31) :

- #22 / #32 — `scripts/gen_endpoints_doc.py::_collect_methods` reimplementait la
  seule « Pass 1 » de `rest_server._get_api_methods` (methodes directes sur
  `CineSortApi`). Or Pass 1 est DESACTIVEE par defaut depuis P0 #233 : la
  reimplementation rendait **0** methode quand le dispatcher en servait **172**
  (Pass 2 = walk des 6 facades). La surface REST etait encodee deux fois et les
  deux copies avaient diverge.
- #23 — la meme notion « nombre d'endpoints REST » portait des valeurs
  divergentes livrees a l'utilisateur : `docs/api/ENDPOINTS.md:8` annoncait
  « Total endpoints publics : 1 » (un seul bloc, `POST /api/test_reset`) quand
  le serveur journalisait 172 routes au demarrage.
- #24 — les 10 exemples curl « endpoints critiques » de la doc publique visaient
  tous des routes que le dispatcher ne sert pas (`/api/start_plan` au lieu de
  `/api/run/start_plan`, ...).
- #30 / #38 — la docstring annoncait « 8 categories metier » pour 9 listes, et
  un garde « la generation echoue avec un warning si trop d'orphelins » qui
  n'existait nulle part dans le fichier.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from cinesort.infra.rest_server import _get_api_methods
from cinesort.ui.api.cinesort_api import CineSortApi
from scripts import gen_endpoints_doc as gen

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC = _REPO_ROOT / "docs" / "api" / "ENDPOINTS.md"


class SourceUniqueTests(unittest.TestCase):
    """#22 / #32 : une seule fonction decrit la surface REST."""

    def test_collect_methods_rend_exactement_les_routes_du_dispatcher(self) -> None:
        api = CineSortApi()
        attendu = set(_get_api_methods(api))
        obtenu = set(gen._collect_methods(api))
        self.assertEqual(
            obtenu,
            attendu,
            f"le generateur voit {len(obtenu)} routes, le dispatcher en sert {len(attendu)}",
        )

    def test_le_dispatcher_sert_bien_des_routes_de_facade(self) -> None:
        """Garde-fou anti-test-vide : si le dispatcher rendait 0 route, le test
        ci-dessus serait vert sans rien prouver."""
        routes = _get_api_methods(CineSortApi())
        self.assertGreater(len(routes), 100)
        self.assertTrue(any("/" in name for name in routes))


class DocCommitteeTests(unittest.TestCase):
    """#23 : le nombre annonce dans la doc committee doit etre le nombre servi."""

    def test_total_annonce_dans_la_doc_egale_le_nombre_de_routes_servies(self) -> None:
        contenu = _DOC.read_text(encoding="utf-8")
        trouve = re.search(r"\*\*Total endpoints publics\*\*\s*:\s*(\d+)", contenu)
        self.assertIsNotNone(trouve, "ligne 'Total endpoints publics' introuvable dans la doc")
        assert trouve is not None
        annonce = int(trouve.group(1))
        reel = len(_get_api_methods(CineSortApi()))
        self.assertEqual(annonce, reel, f"la doc annonce {annonce} endpoints, le dispatcher en sert {reel}")

    def test_la_doc_documente_un_bloc_par_route_servie(self) -> None:
        contenu = _DOC.read_text(encoding="utf-8")
        rendus = re.findall(r"^#### `POST /api/([^`]+)`", contenu, flags=re.MULTILINE)
        routes = set(_get_api_methods(CineSortApi()))
        self.assertEqual(
            set(rendus),
            routes,
            f"{len(routes - set(rendus))} routes servies sans bloc, {len(set(rendus) - routes)} blocs sans route",
        )
        # Un nom present dans deux categories dupliquerait le bloc sans que la
        # comparaison d'ensembles ci-dessus ne le voie.
        self.assertEqual(len(rendus), len(routes), "au moins une route est documentee deux fois")


class RenvoisVersLaDocTests(unittest.TestCase):
    """#23 : aucun autre document ne doit RECOPIER le nombre d'endpoints.

    `docs/MANUAL.md` et `docs/TROUBLESHOOTING.md` renvoyaient tous deux vers
    `docs/api/ENDPOINTS.md` en annoncant « 98 endpoints », quand la doc pointee
    en annoncait 1 et le dispatcher en servait 172. Un renvoi ne doit pas porter
    le chiffre : il doit renvoyer a l'endroit qui le calcule.
    """

    def test_aucun_renvoi_vers_endpoints_md_ne_porte_de_compte_en_dur(self) -> None:
        fautifs: list[str] = []
        for chemin in sorted((_REPO_ROOT / "docs").rglob("*.md")):
            if chemin == _DOC or "internal" in chemin.parts:
                continue
            for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
                if "ENDPOINTS.md" in ligne and re.search(r"\b\d+\s+endpoints", ligne, flags=re.IGNORECASE):
                    fautifs.append(f"{chemin.relative_to(_REPO_ROOT).as_posix()}:{numero} : {ligne.strip()}")
        self.assertEqual(fautifs, [], "\n".join(fautifs))


class DonneesCurateesTests(unittest.TestCase):
    """#24 / #38 : le garde annonce doit exister ET mordre."""

    def test_les_donnees_curatees_du_depot_sont_a_jour(self) -> None:
        routes = _get_api_methods(CineSortApi())
        problemes = gen._verifier_donnees_curatees(routes)
        self.assertEqual(problemes, [], "\n".join(problemes))

    def test_chaque_exemple_curl_vise_une_route_servie(self) -> None:
        routes = _get_api_methods(CineSortApi())
        inconnus = [ex["method"] for ex in gen._EXAMPLES if ex["method"] not in routes]
        self.assertEqual(
            inconnus,
            [],
            f"{len(inconnus)}/{len(gen._EXAMPLES)} exemples curl visent une route absente",
        )


class DocstringTests(unittest.TestCase):
    """#30 : la docstring annoncait 8 categories pour 9 listes."""

    def test_le_nombre_de_categories_annonce_est_le_nombre_reel(self) -> None:
        doc = gen.__doc__ or ""
        trouve = re.search(r"(\d+)\s+categories metier", doc)
        self.assertIsNotNone(trouve, "la docstring n'annonce plus de nombre de categories")
        assert trouve is not None
        self.assertEqual(int(trouve.group(1)), len(gen._CATEGORIES))


if __name__ == "__main__":
    unittest.main()
