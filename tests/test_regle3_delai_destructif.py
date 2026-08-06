"""Regle projet n3 : le delai de confirmation ne doit plus dependre de l'appelant.

MESURE du 2026-08-06 sur les 19 sites d'appel de `dangerConfirmModal` — QUATRE
conventions coexistaient pour un meme `countdownSeconds` :

    graduee (n<=30 -> 0, n>50 -> 3, interpolation entre)   2 sites
    ternaire `n > 50 ? 3 : 0`                              4 sites
    fixe 3, quel que soit le volume                        8 sites
    rien passe -> 0                                        3 sites

Le dernier groupe contient `processing.js` « Lancer l'apply », qui renomme et
deplace N films sur le disque : ni liste, ni delai, quel que soit N.

Une regle appliquee de quatre facons differentes n'est pas une regle. Le seuil
vit desormais DANS la modale ; les appelants qui passent une valeur explicite
gardent exactement leur comportement.

Ces tests lisent le source JS — c'est assume et borne : ils n'assertent que sur
la PRESENCE d'une cle passee a un appel, pas sur une mise en forme. Le
comportement de la modale, lui, est eprouve par les tests Playwright.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_WEB = Path("web/dashboard")
_MODAL = _WEB / "components" / "modal.js"


def _source(chemin: Path) -> str:
    return chemin.read_text(encoding="utf-8")


class SeuilDansLaModaleTests(unittest.TestCase):
    def test_le_helper_gradue_est_EXPORTE_par_la_modale(self) -> None:
        """Tant qu'il vit dans une vue, chaque vue peut en avoir sa version."""
        self.assertIn("export function gradedCountdownSeconds", _source(_MODAL))

    def test_le_defaut_est_DERIVE_et_non_zero(self) -> None:
        """`countdownSeconds = 0` en defaut est ce qui rendait les 3 sites muets."""
        source = _source(_MODAL)

        self.assertNotIn("countdownSeconds = 0", source, "le defaut a zero seconde est revenu")
        self.assertIn("countdownSeconds = null", source)
        self.assertIn("gradedCountdownSeconds(nbElements)", source)

    def test_la_regle_utilisateur_est_RESPECTEE_au_dela_de_50(self) -> None:
        """> 50 elements -> 3 s, sans interpolation. Une version anterieure
        rendait 1 s ou 2 s entre 51 et 99 et violait la regle."""
        source = _source(_MODAL)
        bloc = source[source.index("export function gradedCountdownSeconds") :][:600]

        self.assertIn("if (n > 50) return 3;", bloc)
        self.assertIn("if (n <= 30) return 0;", bloc)


class SitesDestructifsTests(unittest.TestCase):
    """Le site le plus destructif du depot ne passait rien du tout."""

    def test_lancer_l_apply_passe_un_nombre_d_elements(self) -> None:
        source = _source(_WEB / "views" / "processing.js")
        debut = source.index('title: "Lancer l\'apply ?"')
        bloc = source[debut : debut + 900]

        self.assertIn("itemCount:", bloc, "l'apply reel ne dit toujours pas combien de films il touche")

    def test_aucun_site_ne_passe_un_countdown_NEGATIF_ou_absurde(self) -> None:
        """Garde de coherence sur les valeurs explicites qui restent."""
        for chemin in sorted(_WEB.rglob("*.js")):
            for m in re.finditer(r"countdownSeconds:\s*(-?\d+)", _source(chemin)):
                valeur = int(m.group(1))
                self.assertGreaterEqual(valeur, 0, f"{chemin}: countdownSeconds negatif")
                self.assertLessEqual(valeur, 10, f"{chemin}: countdownSeconds absurde ({valeur} s)")


if __name__ == "__main__":
    unittest.main()
