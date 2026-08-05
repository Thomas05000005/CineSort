"""F02 (revue adversaire R1) — un tag provider ne doit pas fuir dans le titre.

Le correctif F02 empeche de lire une pseudo-annee dans les chiffres d'un tag
provider (`[imdbid-tt1950186]`, `{tmdb-19995}`). Effet de bord non declare :
sans annee fiable, la row bascule sur `_build_unresolved_row`, dont le titre de
repli etait le nom de dossier BRUT — tag compris.

Le tag partait alors dans `proposed_title`, donc dans la cle d'identite/dedup et
dans le nom de dossier propose a l'apply (« Avatar {tmdb-19995} (2009) »).
"""

from __future__ import annotations

import unittest

from cinesort.domain.title_helpers import strip_provider_tags


class StripProviderTagsFallbackTests(unittest.TestCase):
    """Le helper utilise par le titre de repli doit nettoyer les 2 syntaxes."""

    def test_tag_tmdb_accolades_retire(self) -> None:
        self.assertEqual(strip_provider_tags("Avatar {tmdb-19995}").strip(), "Avatar")

    def test_tag_imdb_crochets_retire(self) -> None:
        self.assertEqual(strip_provider_tags("Ford v Ferrari [imdbid-tt1950186]").strip(), "Ford v Ferrari")

    def test_titre_sans_tag_inchange(self) -> None:
        """NON-REGRESSION : un titre normal ne doit pas etre touche."""
        self.assertEqual(strip_provider_tags("Blade Runner 2049").strip(), "Blade Runner 2049")

    def test_titre_avec_parentheses_annee_inchange(self) -> None:
        """NON-REGRESSION : l'annee parenthesee n'est pas un tag provider."""
        self.assertEqual(strip_provider_tags("Inception (2010)").strip(), "Inception (2010)")


class UnresolvedRowFallbackTitleTests(unittest.TestCase):
    def _row_pour(self, nom_dossier: str):
        """Construit la vraie PlanRow de repli produite par le plan."""
        from pathlib import Path

        from cinesort.app import plan_support_replan

        return plan_support_replan._build_unresolved_row(
            Path("C:/films") / nom_dossier,
            Path("C:/films") / nom_dossier / "film.mkv",
            row_id="S|deadbeef",
            kind="single",
            is_collection=False,
            folder_name=nom_dossier,
            cands=[],
            nfo=None,
            nfo_path=None,
            nfo_state={
                "nfo_ok": False,
                "nfo_cov": 0.0,
                "nfo_seq": 0,
                "nfo_reject_reason": "",
                "year_delta_reject": False,
                "nfo_partial_match": False,
            },
            name_year=None,
            name_year_reason="aucune annee detectee",
            remaster_hint=False,
            tmdb_used=False,
            title_ambiguous=False,
            detected_edition=None,
            log=lambda *_a, **_k: None,
        )

    def test_le_titre_propose_ne_porte_pas_le_tag(self) -> None:
        """Chemin REEL : la row de repli ne doit plus exposer le tag provider.

        C'est `proposed_title` qui part dans la cle d'identite/dedup et dans le
        nom de dossier propose a l'apply.
        """
        for dossier in ("Avatar {tmdb-19995}", "Ford v Ferrari [imdbid-tt1950186]"):
            titre = self._row_pour(dossier).proposed_title
            self.assertNotIn("{", titre, f"tag provider dans le titre propose pour {dossier!r} : {titre!r}")
            self.assertNotIn("[", titre, f"tag provider dans le titre propose pour {dossier!r} : {titre!r}")
            self.assertTrue(titre.strip(), "le titre propose ne doit jamais etre vide")

        self.assertEqual(self._row_pour("Avatar {tmdb-19995}").proposed_title, "Avatar")

    def test_dossier_sans_tag_inchange(self) -> None:
        """NON-REGRESSION : un dossier normal garde exactement son nom."""
        self.assertEqual(self._row_pour("Blade Runner 2049").proposed_title, "Blade Runner 2049")

    def test_repli_garde_le_nom_brut_si_le_nettoyage_vide_tout(self) -> None:
        """Garde : un dossier qui n'est QUE un tag ne doit pas donner un titre vide."""
        nettoye = strip_provider_tags("{tmdb-19995}").strip()
        self.assertEqual(nettoye or "{tmdb-19995}", "{tmdb-19995}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
