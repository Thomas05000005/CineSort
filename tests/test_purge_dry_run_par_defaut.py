"""Une route de purge exposee en REST ne doit pas supprimer sur un corps VIDE.

Les deux methodes de purge de la quarantaine sont atteignables en
`POST /api/run/purge_quarantine_bucket[_all]`. Leur `dry_run` valait **False**
par defaut : un appel sans aucun parametre supprimait donc des fichiers de
l'utilisateur.

Sur une frontiere destructive, l'omission doit produire l'APERCU, jamais l'effet.
Les appelants dont le travail EST de supprimer le disent maintenant
explicitement — c'est un parametre visible en review, plus un defaut invisible.

CE QUE CE CORRECTIF NE FAIT PAS : rendre la purge impossible. Le cron TTL et le
bouton « Vider maintenant » fonctionnent exactement comme avant.
"""

from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

from cinesort.ui.api.facades.run_facade import RunFacade


class DefautDesRoutesDePurgeTests(unittest.TestCase):
    def test_purge_par_ttl_previsualise_par_defaut(self) -> None:
        defaut = inspect.signature(RunFacade.purge_quarantine_bucket).parameters["dry_run"].default

        self.assertIs(defaut, True, "un POST au corps vide supprime des fichiers")

    def test_purge_totale_previsualise_par_defaut(self) -> None:
        defaut = inspect.signature(RunFacade.purge_quarantine_bucket_all).parameters["dry_run"].default

        self.assertIs(defaut, True, "un POST au corps vide vide toute la quarantaine")


class LesAppelantsLegitimesRestentEXPLICITESTests(unittest.TestCase):
    """Contre-epreuve : basculer le defaut ne doit pas rendre la purge inoperante.

    Le cron TTL s'appuyait sur le defaut. Sans ce parametre explicite, il
    deviendrait un no-op SILENCIEUX et la quarantaine croitrait sans borne — un
    correctif de securite qui casse la fonction qu'il protege.
    """

    def test_le_cron_TTL_demande_explicitement_la_suppression(self) -> None:
        source = Path("cinesort/app/quarantine_ttl.py").read_text(encoding="utf-8")
        appels = re.findall(r"api\.run\.purge_quarantine_bucket\(([^)]*)\)", source)

        self.assertTrue(appels, "l'appel du cron a disparu ou change de forme")
        for args in appels:
            self.assertIn("dry_run=False", args, f"le cron ne supprimerait plus rien : purge_quarantine_bucket({args})")

    def test_l_UI_demande_explicitement_la_suppression(self) -> None:
        source = Path("web/dashboard/views/parametres.js").read_text(encoding="utf-8")

        self.assertIn(
            "purge_quarantine_bucket_all",
            source,
            "le bouton « Vider maintenant » a disparu",
        )
        self.assertRegex(
            source,
            r'purge_quarantine_bucket_all"\s*,\s*\{\s*dry_run:\s*false',
            "le bouton « Vider maintenant » ne demande plus la suppression : il previsualiserait",
        )


if __name__ == "__main__":
    unittest.main()
