# -*- coding: utf-8 -*-
"""Un format HDR non reconnu n'est pas du SDR.

Le defaut
---------
`composite_score_v2._score_hdr` est une chaine de `if` qui reconnait HDR10,
HDR10+ et les profils Dolby Vision 5 / 8.1 / 8.2 / 8.4. TOUT LE RESTE tombait
dans son `return 60.0, 0.3` final — la branche SDR.

Mesure du 2026-08-31, avec les cles que `_normalize_ffprobe` produit REELLEMENT
(`hdr_type`, `dv_present`, `dv_profile`) :

    HLG                -> 60, confiance 0.3   le probe portait 75
    DV profil 7        -> 60, confiance 0.3   le probe portait 95
    DV profil inconnu  -> 60, confiance 0.3   le probe portait 75

LA CONFIANCE EST LE PIRE DES DEUX. `0.3` annonce au composite « cette dimension
n'est pas vraiment pertinente ici, ne la prends pas au serieux » — alors que le
probe l'avait mesuree et rangee juste a cote, dans `hdr_quality_score` et
`dv_quality_score`. Une note fausse se corrige ; une confiance fausse fait taire
la dimension entiere.

C'est le motif « `.get(cle, 0)` confond INCONNU et PIRE » du comparateur de
doublons, transpose a une chaine de `if` sans clause finale honnete : l'absence
de connaissance y produisait un jugement au lieu d'un refus de trancher.

Ce que ce lot ne fait PAS
-------------------------
Il ne recalibre rien. Sur chacun des cas que `_score_hdr` traite deja, le code
est d'accord avec le bareme canonique (HDR10 85, DV 5 80, DV 8.1 100) ou en
diverge DELIBEREMENT — SDR a 60 « neutre » plutot que 40, parce que l'absence de
HDR n'est pas un defaut, et HDR10 sans metadonnees a 75 via son drapeau plutot
que 50. Ces choix restent.

Une premiere lecture de ce dossier annoncait « 7 cas sur 10 divergent » : le
chiffre venait de fixtures INVENTEES (une cle `hlg` qui n'existe nulle part, et
un harnais qui ecrasait les drapeaux en meme temps que la note). Le vrai defaut
est un TROU, pas un desaccord de calibrage.
"""

from __future__ import annotations

import unittest

from cinesort.domain.perceptual.composite_score_v2 import _score_hdr
from cinesort.domain.perceptual.constants import DV_QUALITY_SCORE, HDR_QUALITY_SCORE


class _VideoSansHdr10Plus:
    """`_score_hdr` ne lit qu'un attribut sur l'objet video ; le reste vient du probe."""

    has_hdr10_plus_detected = False


def _note(video_probe: dict) -> tuple[float, float, list[str]]:
    return _score_hdr(_VideoSansHdr10Plus(), {"video": video_probe})


class UnFormatNonReconnuNEstPasDuSdrTests(unittest.TestCase):
    def test_le_HLG_n_est_plus_note_comme_du_SDR(self) -> None:
        note, confiance, _drapeaux = _note({"hdr_type": "hlg"})

        self.assertEqual(note, float(HDR_QUALITY_SCORE["hlg"]))
        self.assertEqual(confiance, 1.0, "une dimension mesuree ne doit pas s'annoncer incertaine")

    def test_le_profil_DV_7_n_est_plus_note_comme_du_SDR(self) -> None:
        note, confiance, _drapeaux = _note({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": "7"})

        self.assertEqual(note, float(DV_QUALITY_SCORE["7"]))
        self.assertEqual(confiance, 1.0)

    def test_un_profil_DV_INCONNU_vaut_unknown_et_non_SDR(self) -> None:
        """Un profil que le depot ne connait pas encore doit valoir « Dolby
        Vision, profil non repertorie » — pas « pas de HDR du tout ». C'est la
        difference entre ignorer et juger.
        """
        note, confiance, _drapeaux = _note({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": "9.9"})

        self.assertEqual(note, float(DV_QUALITY_SCORE["unknown"]))
        self.assertEqual(confiance, 1.0)

    def test_les_valeurs_viennent_du_BAREME_et_ne_sont_pas_recopiees(self) -> None:
        """Contre-epreuve de la source. Si les trois notes etaient ecrites en
        dur dans `_score_hdr`, elles cesseraient de suivre le bareme le jour ou
        il bouge — et on aurait remplace un trou par une seconde verite.
        """
        self.assertEqual(_note({"hdr_type": "hlg"})[0], float(HDR_QUALITY_SCORE["hlg"]))
        for profil in ("7", "unknown"):
            attendu = float(DV_QUALITY_SCORE[profil])
            sonde = profil if profil != "unknown" else "profil-absent-du-bareme"
            with self.subTest(profil=profil):
                note, _c, _f = _note({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": sonde})
                self.assertEqual(note, attendu)


class LesCasDEJATraitesNeBougentPasTests(unittest.TestCase):
    """CONTRE-EPREUVE DU PERIMETRE. Sans elle, un correctif qui aurait tout
    bascule sur le bareme canonique passerait les tests ci-dessus — et aurait
    deplace le score de TOUTE la bibliotheque au lieu de fermer un trou.
    """

    def test_le_SDR_reste_neutre_et_peu_confiant(self) -> None:
        """60 et non 40 : l'absence de HDR n'est pas un defaut, et la confiance
        de 0.3 est le mecanisme qui le dit au composite. Ce choix est
        anterieur a ce lot et il est conserve.
        """
        note, confiance, _drapeaux = _note({"hdr_type": "sdr"})

        self.assertEqual(note, 60.0)
        self.assertEqual(confiance, 0.3)

    def test_les_formats_reconnus_gardent_leur_note(self) -> None:
        attendus = {
            "hdr10 valide": ({"hdr_type": "hdr10", "hdr10": True, "max_cll": 1000, "max_fall": 400}, 85.0),
            "hdr10 sans metadonnees": ({"hdr_type": "hdr10", "hdr10": True}, 75.0),
            "hdr10+": ({"hdr_type": "hdr10_plus", "hdr10_plus": True}, 95.0),
            "dv 5": ({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": "5"}, 80.0),
            "dv 8.1": ({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": "8.1"}, 100.0),
            "dv 8.2": ({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": "8.2"}, 100.0),
            "dv 8.4": ({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": "8.4"}, 100.0),
        }
        for nom, (probe, attendu) in attendus.items():
            with self.subTest(cas=nom):
                self.assertEqual(_note(probe)[0], attendu)

    def test_les_DRAPEAUX_survivent_au_correctif(self) -> None:
        """`dv_profile_5` et `hdr_metadata_missing` alimentent des ajustements
        du composite. Une reecriture de la chaine de `if` qui les perdrait
        changerait le score sans qu'aucune note ne bouge — un mutant que la
        seule verification des notes laisserait passer.
        """
        _n, _c, drapeaux_dv5 = _note({"hdr_type": "dolby_vision", "dv_present": True, "dv_profile": "5"})
        _n2, _c2, drapeaux_meta = _note({"hdr_type": "hdr10", "hdr10": True})

        self.assertIn("dv_profile_5", drapeaux_dv5)
        self.assertIn("hdr_metadata_missing", drapeaux_meta)

    def test_video_absente_rend_toujours_le_neutre_absolu(self) -> None:
        note, confiance, drapeaux = _score_hdr(None, None)

        self.assertEqual((note, confiance, drapeaux), (50.0, 0.0, []))


if __name__ == "__main__":
    unittest.main()
