"""Un score de 0 est le PIRE fichier, pas une absence de donnee.

`should_propose_upgrade` filtrait sur `score > 0 and score < 54`. Le `> 0`
n'excluait pas une valeur manquante — `get_quality_report` fait
`int(row["score"])`, la cle est toujours la — mais bien la NOTE 0, c'est-a-dire
le bas de l'echelle `[0, 100]` que `quality_score._clamp_0_100` garantit.

Le seul film que Radarr ne se voyait donc JAMAIS proposer en upgrade par le
critere du score etait le plus mauvais de la bibliotheque. Meme famille que
#1216 (« `.get(cle, 0)` confond inconnu et pire »), prise par l'autre bout :
ici c'est « le pire » qui etait traite comme « inconnu ».

CE QUE CHAQUE TEST PROUVE
-------------------------
Le fichier de reference porte un encodage SAIN (1080p, 12 000 kbps, hevc) :
`analyze_encode_quality` n'emet aucun flag et le codec n'est pas obsolete. Les
deux autres criteres de `should_propose_upgrade` sont donc MUETS, et seul le
critere du score peut repondre — « asserter ce que SEUL le correctif produit ».
"""

from __future__ import annotations

import unittest
from typing import Any, Dict

from cinesort.app.radarr_sync import get_upgrade_candidates, should_propose_upgrade
from cinesort.domain.encode_analysis import analyze_encode_quality

_MONITORED: Dict[str, Any] = {"monitored": True, "row_id": "r1"}
# Encodage sain : aucun flag d'encode, codec moderne. Verifie par un test
# ci-dessous plutot que suppose.
_DETECTED_SAIN: Dict[str, Any] = {"height": 1080, "bitrate_kbps": 12000, "video_codec": "hevc"}


def _rapport(score: Any = 70, *, avec_cle_score: bool = True) -> Dict[str, Any]:
    """Rapport qualite realiste sur un fichier dont l'ENCODAGE est irreprochable."""
    rapport: Dict[str, Any] = {
        "tier": "Silver",
        "reasons": [],
        "metrics": {"detected": dict(_DETECTED_SAIN)},
    }
    if avec_cle_score:
        rapport["score"] = score
    return rapport


class LeFichierDeReferenceNeutraliseLesAutresCriteresTests(unittest.TestCase):
    """Sans ca, les tests ci-dessous pourraient passer pour une autre raison."""

    def test_l_encodage_de_reference_n_emet_aucun_flag(self) -> None:
        self.assertEqual(analyze_encode_quality(_DETECTED_SAIN), [])

    def test_un_score_sain_ne_propose_rien(self) -> None:
        self.assertFalse(should_propose_upgrade(_MONITORED, _rapport(70)))


class UnScoreDeZeroEstUneNoteTests(unittest.TestCase):
    """`0` doit declencher l'upgrade ; `absent` ne doit pas trancher."""

    def test_un_score_de_zero_propose_un_upgrade(self) -> None:
        """ROUGE sans le correctif : `score > 0` refusait le pire fichier."""
        self.assertTrue(should_propose_upgrade(_MONITORED, _rapport(0)))

    def test_un_rapport_sans_cle_score_ne_propose_rien(self) -> None:
        """CONTRE-TEST, vert des deux cotes : l'absence ne devient pas un oui.

        C'est ce qui distingue le correctif d'un simple `score < 54` : un
        rapport muet sur le score laisse les autres criteres decider.
        """
        self.assertFalse(should_propose_upgrade(_MONITORED, _rapport(avec_cle_score=False)))

    def test_un_score_nul_sur_un_film_non_suivi_reste_refuse(self) -> None:
        """CONTRE-TEST, vert des deux cotes : le garde `monitored` prime toujours."""
        self.assertFalse(should_propose_upgrade({"monitored": False, "row_id": "r1"}, _rapport(0)))

    def test_le_seuil_reste_exclusif(self) -> None:
        """CONTRE-TEST, vert des deux cotes : la borne haute n'a pas bouge."""
        self.assertFalse(should_propose_upgrade(_MONITORED, _rapport(54)))
        self.assertTrue(should_propose_upgrade(_MONITORED, _rapport(53)))

    def test_un_score_illisible_ne_leve_plus(self) -> None:
        """Durcissement annexe, PAS un contre-test.

        `int("indisponible" or 0)` levait une `ValueError` qui remontait jusqu'a
        `get_radarr_status` et emportait tout le rapport Radarr. On rend
        desormais « on ne sait pas », comme pour une cle absente.
        """
        self.assertFalse(should_propose_upgrade(_MONITORED, _rapport("indisponible")))

    def test_un_score_flottant_garde_son_verdict(self) -> None:
        """NON-REGRESSION : l'ancien code tolerait les types numeriques larges."""
        self.assertTrue(should_propose_upgrade(_MONITORED, _rapport(12.5)))


class LeSiteDAppelRemonteLeFilmAZeroTests(unittest.TestCase):
    """Eprouver la decision ne dit rien du site d'appel : on joue la chaine.

    `get_upgrade_candidates` est ce que `get_radarr_status` rend a l'ecran. Un
    mutant qui supprimerait l'appel a `should_propose_upgrade`, ou lui passerait
    le mauvais rapport, doit mourir ici.
    """

    def test_le_film_a_zero_apparait_dans_les_candidats(self) -> None:
        report = {"matched": [{**_MONITORED, "title": "Le Pire Fichier", "year": 2001}]}
        candidats = get_upgrade_candidates(report, {"r1": _rapport(0)})

        self.assertEqual([c["title"] for c in candidats], ["Le Pire Fichier"])
        # Le score remonte tel quel : l'ecran doit pouvoir afficher « 0 ».
        self.assertEqual(candidats[0]["score"], 0)

    def test_un_film_sain_reste_hors_des_candidats(self) -> None:
        """CONTRE-TEST : le site d'appel ne promeut pas tout le monde."""
        report = {"matched": [{**_MONITORED, "title": "Fichier Sain", "year": 2001}]}

        self.assertEqual(get_upgrade_candidates(report, {"r1": _rapport(70)}), [])


if __name__ == "__main__":
    unittest.main()
