"""GATE AUDIT 2026-06-11 (R4-P1) — le reglage workers survit au flux UI REEL.

Bug R3c residuel (confirme par la verification totale) : le fix 191b916 lisait
l'alias perceptual_workers_count en fallback, MAIS l'UI POST l'objet settings
ENTIER (echo du GET, parametres.js L1785) qui contient TOUJOURS la cle canonique
perceptual_workers (via _LITERAL_DEFAULTS). La canonique perimee primait donc
sur la saisie -> 8 saisi, 0 persiste. En plus le GET n'exposait jamais l'alias
-> le champ UI affichait toujours le defaut au lieu de la valeur persistee.

Fix R4-P1 a la racine : la cle du champ UI (parametres.js) devient la CANONIQUE
perceptual_workers. Ce GATE simule le flux UI REEL en extrayant la cle du champ
directement depuis parametres.js : GET complet -> edition de CETTE cle -> save
de l'objet entier -> relecture. Rouge avant (cle = alias jamais lu en presence
de l'echo canonique), vert apres.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PARAMETRES_JS = _REPO_ROOT / "web" / "dashboard" / "views" / "parametres.js"


def _ui_workers_field_key() -> str:
    """Extrait la cle reelle du champ 'Workers paralleles' depuis parametres.js."""
    src = _PARAMETRES_JS.read_text(encoding="utf-8")
    m = re.search(r'key:\s*"([a-z_]+)"[^\n]*Workers parall', src)
    assert m, "champ 'Workers paralleles' introuvable dans parametres.js"
    return m.group(1)


class PerceptualWorkersUiRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_ui_workers_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = CineSortApi()
        self.api._state_dir = self._sd

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_ui_field_key_is_canonical(self) -> None:
        """La cle du champ UI doit etre la canonique (celle du GET et du moteur).

        Toute autre cle casse le round-trip : le POST de l'objet entier contient
        l'echo canonique du GET qui prime sur la saisie.
        """
        self.assertEqual(
            _ui_workers_field_key(),
            "perceptual_workers",
            "parametres.js doit utiliser la cle canonique perceptual_workers "
            "(l'alias *_count n'est jamais renvoye par le GET -> echo perime prime).",
        )

    def test_full_ui_flow_get_edit_save_persists(self) -> None:
        """Flux UI REEL : GET complet -> edition du champ (cle extraite du JS)
        -> save de l'objet ENTIER -> la valeur saisie persiste."""
        key = _ui_workers_field_key()
        full = self.api.settings.get_settings()
        self.assertIsInstance(full, dict)
        # L'UI POST l'objet entier ; root/state_dir requis par save.
        full["root"] = str(self._root)
        full["state_dir"] = str(self._sd)
        full[key] = 8  # edition utilisateur du champ workers
        saved = self.api.settings.save_settings(full)
        self.assertTrue(saved.get("ok"), saved)

        after = self.api.settings.get_settings()
        self.assertEqual(
            int(after.get("perceptual_workers") or 0),
            8,
            f"la saisie UI (cle {key!r}=8) doit persister dans perceptual_workers "
            f"apres save de l'objet settings entier (echo GET inclus).",
        )

    def test_ui_field_value_visible_in_get(self) -> None:
        """Round-trip affichage : la cle du champ UI doit FIGURER dans le GET,
        sinon _renderField retombe sur le default JS au lieu de la valeur persistee."""
        key = _ui_workers_field_key()
        full = self.api.settings.get_settings()
        self.assertIn(
            key,
            full,
            f"le GET doit exposer la cle {key!r} du champ UI (round-trip affichage).",
        )

    def test_legacy_alias_alone_still_accepted(self) -> None:
        """Compat REST legacy : un payload PARTIEL avec l'alias seul persiste."""
        saved = self.api.settings.save_settings(
            {"root": str(self._root), "state_dir": str(self._sd), "perceptual_workers_count": 5}
        )
        self.assertTrue(saved.get("ok"), saved)
        after = self.api.settings.get_settings()
        self.assertEqual(int(after.get("perceptual_workers") or 0), 5)


if __name__ == "__main__":
    unittest.main()
