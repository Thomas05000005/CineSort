"""GATE AUDIT 2026-06-11 (R3c) — `perceptual_workers_count` de l'UI persiste enfin.

Avant : l'UI (settings perceptual) envoie UNIQUEMENT `perceptual_workers_count`.
`_save_section_perceptual` ne lisait que `perceptual_workers` -> tombait sur le
defaut 0 (= auto) ; en parallele `_save_section_advanced` lisait bien l'alias
mais avec un clamp incoherent [1..32] PUIS etait ecrase par la section
perceptual (dispatcher : advanced L1911 avant perceptual L1918).
Resultat : l'utilisateur fixe 8 workers -> 0 (auto) persiste, reglage ignore.

Apres : `_save_section_perceptual` lit `perceptual_workers` puis bascule sur
`perceptual_workers_count` en fallback, avec le clamp canonique [0..16]
(0 = auto). `_save_section_advanced` ne traite plus ce champ (source unique).
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.settings_support import (
    _save_section_advanced,
    _save_section_perceptual,
)


class PerceptualWorkersPersistTests(unittest.TestCase):
    # --- Le coeur du GATE : l'alias UI doit etre lu ---
    def test_ui_alias_count_persists(self) -> None:
        section = _save_section_perceptual({"perceptual_workers_count": 8})
        self.assertEqual(
            section["perceptual_workers"],
            8,
            "perceptual_workers_count=8 (envoye par l'UI) doit persister 8, pas 0.",
        )

    def test_zero_means_auto(self) -> None:
        self.assertEqual(
            _save_section_perceptual({"perceptual_workers_count": 0})["perceptual_workers"],
            0,
        )

    def test_clamp_canonique_16(self) -> None:
        self.assertEqual(
            _save_section_perceptual({"perceptual_workers_count": 20})["perceptual_workers"],
            16,
        )
        self.assertEqual(
            _save_section_perceptual({"perceptual_workers_count": -5})["perceptual_workers"],
            0,
        )

    def test_canonical_key_still_wins(self) -> None:
        # AUDIT 2026-06-11 (R4-P1) : la canonique prime — et c'est desormais le
        # contrat CORRECT car la cle du champ UI (parametres.js) EST la canonique
        # perceptual_workers. L'alias *_count n'est plus qu'un fallback legacy
        # pour payloads partiels REST. Cf test_perceptual_workers_ui_roundtrip_v77
        # pour le GATE du flux UI reel (GET complet -> edition -> save).
        section = _save_section_perceptual({"perceptual_workers": 4, "perceptual_workers_count": 99})
        self.assertEqual(section["perceptual_workers"], 4)

    def test_default_absent_is_auto(self) -> None:
        self.assertEqual(_save_section_perceptual({})["perceptual_workers"], 0)

    # --- Source unique : advanced ne doit plus produire le champ ---
    def test_advanced_no_longer_owns_workers(self) -> None:
        section = _save_section_advanced({"perceptual_workers_count": 8})
        self.assertNotIn(
            "perceptual_workers",
            section,
            "_save_section_advanced ne doit plus gerer perceptual_workers "
            "(sinon double source + clamp [1..32] incoherent).",
        )


if __name__ == "__main__":
    unittest.main()
