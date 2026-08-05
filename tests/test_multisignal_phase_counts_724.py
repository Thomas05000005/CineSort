"""#724 — `phase_counts["fuzzy_title"]` ignorait le travail de la Pass 1.

La Phase B fait deux choses distinctes :
  - Pass 1 : elle ABSORBE des candidats dans des groupes deja crees par la
    Phase A (`group_match.members.append(...)`), sans creer de groupe ;
  - Pass 2 : elle CREE de nouveaux groupes avec les candidats restants.

Le compteur ne retenait que `len(groups_b)`, c'est-a-dire la Pass 2. Or les
augmentations de la Pass 1 ne sont visibles nulle part ailleurs :
`phase_counts["strict_metadata"]` est fige AVANT que la Phase B ne tourne, et
`len(result.groups)` ne bouge pas quand un groupe grossit. Le contrat annonce
par `MultiSignalResult` est pourtant « nombre de groupes crees ou augmentes ».

Consequence concrete du chiffre faux : sur une bibliotheque ou la Phase B ne
fait qu'absorber (aucun nouveau groupe), le log rendait `fuzzy_title=0` — la
lecture naturelle etant « cette phase ne sert a rien, on peut la desactiver »
alors qu'elle venait de rattacher des doublons. C'est la mesure qui etait
fausse, pas le regroupement.

Ces tests verrouillent la GRANDEUR mesuree, pas seulement sa presence : on
compte des GROUPES augmentes, pas des ajouts (deux candidats absorbes par le
meme groupe valent 1).
"""

from __future__ import annotations

import base64
import struct
import unittest
from typing import List

from cinesort.domain.duplicate_multi_signal import (
    PHASE_AUDIO_FINGERPRINT,
    PHASE_FUZZY_TITLE,
    PHASE_STRICT_METADATA,
    MultiSignalCandidate,
    group_by_multi_signal,
)

_AB = [PHASE_STRICT_METADATA, PHASE_FUZZY_TITLE]


def _encode_fp(ints: List[int]) -> str:
    """Encode une liste d'entiers 32-bit en base64 (compat fpcalc)."""
    return base64.b64encode(struct.pack(f"<{len(ints)}I", *ints)).decode("ascii")


class FuzzyCountIncludesPhaseAAugmentationsTests(unittest.TestCase):
    def test_augmenting_one_phase_a_group_is_counted(self) -> None:
        """r1+r2 forment un groupe Phase A ; r3 (ordre des mots different,
        annee +1) est absorbe par ce groupe sans qu'aucun groupe soit cree."""
        cands = [
            MultiSignalCandidate(item_id="r1", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="r2", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="r3", title="Lord of the Rings The", year=2002),
        ]
        result = group_by_multi_signal(cands, phases=_AB)

        # Pre-conditions : le chemin Pass 1 est REELLEMENT emprunte (sinon le
        # compteur serait a 0 pour une raison sans rapport avec le correctif).
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].phase, PHASE_STRICT_METADATA)
        self.assertEqual(set(result.groups[0].members), {"r1", "r2", "r3"})

        self.assertEqual(result.phase_counts[PHASE_FUZZY_TITLE], 1)
        self.assertEqual(result.phase_counts[PHASE_STRICT_METADATA], 1)

    def test_two_candidates_absorbed_by_the_same_group_count_one(self) -> None:
        """La grandeur mesuree est un nombre de GROUPES, pas d'ajouts."""
        cands = [
            MultiSignalCandidate(item_id="r1", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="r2", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="r3", title="Lord of the Rings The", year=2002),
            MultiSignalCandidate(item_id="r4", title="Rings of the Lord The", year=2000),
        ]
        result = group_by_multi_signal(cands, phases=_AB)

        self.assertEqual(len(result.groups), 1)
        self.assertEqual(set(result.groups[0].members), {"r1", "r2", "r3", "r4"})
        self.assertEqual(result.phase_counts[PHASE_FUZZY_TITLE], 1)

    def test_two_distinct_groups_augmented_count_two(self) -> None:
        cands = [
            MultiSignalCandidate(item_id="a1", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="a2", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="a3", title="Lord of the Rings The", year=2002),
            MultiSignalCandidate(item_id="b1", title="Pirates of the Caribbean", year=2003),
            MultiSignalCandidate(item_id="b2", title="Pirates of the Caribbean", year=2003),
            MultiSignalCandidate(item_id="b3", title="Caribbean of the Pirates", year=2004),
        ]
        result = group_by_multi_signal(cands, phases=_AB)

        self.assertEqual(len(result.groups), 2)
        self.assertEqual(result.phase_counts[PHASE_STRICT_METADATA], 2)
        self.assertEqual(result.phase_counts[PHASE_FUZZY_TITLE], 2)

    def test_created_and_augmented_are_summed(self) -> None:
        """1 groupe Phase A augmente + 1 groupe cree ex nihilo par la Pass 2."""
        cands = [
            MultiSignalCandidate(item_id="a1", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="a2", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="a3", title="Lord of the Rings The", year=2002),
            MultiSignalCandidate(item_id="c1", title="Pirates of the Caribbean", year=2003),
            MultiSignalCandidate(item_id="c2", title="Caribbean of the Pirates", year=2004),
        ]
        result = group_by_multi_signal(cands, phases=_AB)

        phases_of_groups = sorted(g.phase for g in result.groups)
        self.assertEqual(phases_of_groups, [PHASE_FUZZY_TITLE, PHASE_STRICT_METADATA])
        self.assertEqual(result.phase_counts[PHASE_STRICT_METADATA], 1)
        self.assertEqual(result.phase_counts[PHASE_FUZZY_TITLE], 2)


class NonRegressionTests(unittest.TestCase):
    """Le correctif ne doit rien ajouter la ou la Phase B n'augmente rien."""

    def test_pass_two_only_still_counts_created_groups(self) -> None:
        cands = [
            MultiSignalCandidate(item_id="r1", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="r2", title="Lord of the Rings The", year=2002),
        ]
        result = group_by_multi_signal(cands, phases=_AB)

        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].phase, PHASE_FUZZY_TITLE)
        self.assertEqual(result.phase_counts[PHASE_STRICT_METADATA], 0)
        self.assertEqual(result.phase_counts[PHASE_FUZZY_TITLE], 1)

    def test_no_fuzzy_match_leaves_the_counter_at_zero(self) -> None:
        cands = [
            MultiSignalCandidate(item_id="r1", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="r2", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="x1", title="Totalement Autre Chose", year=1998),
        ]
        result = group_by_multi_signal(cands, phases=_AB)

        self.assertEqual(result.phase_counts[PHASE_FUZZY_TITLE], 0)

    def test_phase_b_disabled_reports_no_fuzzy_key(self) -> None:
        cands = [
            MultiSignalCandidate(item_id="r1", title="The Lord of the Rings", year=2001),
            MultiSignalCandidate(item_id="r2", title="Lord of the Rings The", year=2002),
        ]
        result = group_by_multi_signal(cands, phases=[PHASE_STRICT_METADATA])

        self.assertNotIn(PHASE_FUZZY_TITLE, result.phase_counts)

    def test_phase_c_counter_stays_its_own_created_groups(self) -> None:
        """Sonde de non-contamination : le compteur de la Phase C ne doit pas
        heriter des augmentations de la Phase B.

        Le pipeline complet tourne, la Phase B augmente 1 groupe (fuzzy_title=1)
        et la Phase C cree 1 groupe a partir de deux titres sans rapport que
        seul le fingerprint rapproche. Un compteur C qui vaudrait 2 trahirait
        une fuite de `augmented_a`. Assertion non triviale des deux cotes : les
        deux compteurs valent 1, mais pour des raisons differentes."""
        fp = _encode_fp([0xDEADBEEF, 0x12345678, 0xCAFEBABE, 0xFEEDFACE])
        result = group_by_multi_signal(
            [
                MultiSignalCandidate(item_id="r1", title="The Lord of the Rings", year=2001),
                MultiSignalCandidate(item_id="r2", title="The Lord of the Rings", year=2001),
                MultiSignalCandidate(item_id="r3", title="Lord of the Rings The", year=2002),
                MultiSignalCandidate(item_id="f1", title="Movie VOSTFR", year=2020, audio_fingerprint=fp),
                MultiSignalCandidate(item_id="f2", title="Film VF", year=2020, audio_fingerprint=fp),
            ],
            phases=[PHASE_STRICT_METADATA, PHASE_FUZZY_TITLE, PHASE_AUDIO_FINGERPRINT],
        )
        # Pre-condition : la Phase C a REELLEMENT cree un groupe.
        phase_c_groups = [g for g in result.groups if g.phase == PHASE_AUDIO_FINGERPRINT]
        self.assertEqual(len(phase_c_groups), 1)
        self.assertEqual(set(phase_c_groups[0].members), {"f1", "f2"})

        self.assertEqual(result.phase_counts[PHASE_FUZZY_TITLE], 1)
        self.assertEqual(result.phase_counts[PHASE_AUDIO_FINGERPRINT], 1)


if __name__ == "__main__":
    unittest.main()
