"""F01 : un ceiling de hierarchie doit VERROUILLER le reste de la boucle.

Bug d'origine (reproduit a HEAD 529fcd0) : ``apply_tier_hierarchy`` appliquait
chaque dimension cumulativement sur ``current_tier`` sans memoriser les
plafonds deja rencontres. Les floors des dimensions suivantes (hdr, audio,
release_group) re-promouvaient donc AU-DESSUS du plafond, contredisant la doc
du module (tiers_helpers.py:442-443 : "un fichier 720p ne peut PAS finir en
Platinum meme avec audio premium").

Ce fichier est autonome (nouveau fichier) : la classe complete
``tests/test_tier_hierarchy_floors.py`` reste inchangee, elle ne teste ceilings
et floors qu'en ISOLATION - c'est precisement l'interaction qui manquait.
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import (
    compute_quality_score,
    default_quality_profile,
)
from cinesort.domain.tiers_helpers import (
    apply_tier_hierarchy,
    default_hierarchy_config,
)


def _cfg_on(**overrides):
    cfg = default_hierarchy_config()
    cfg["enabled"] = True
    cfg.update(overrides)
    return cfg


class HierarchyCeilingLockTests(unittest.TestCase):
    """Le plafond rencontre sur une dimension borne toutes les suivantes."""

    def test_ceiling_locks_later_audio_floor(self):
        # 720p -> ceiling Silver (defaut TRaSH), puis audio truehd_atmos ->
        # floor Gold (defaut TRaSH). Le floor ne doit PAS repasser au-dessus.
        tier, applied = apply_tier_hierarchy(
            "Gold",
            {"resolution_label": "720p", "audio_codec": "truehd_atmos"},
            _cfg_on(),
        )
        self.assertEqual(tier, "Silver")
        # L'audit trail conserve bien la decision de plafonnement.
        self.assertTrue(
            any(d["type"] == "ceiling" and d["dimension"] == "resolution" for d in applied),
            f"la decision ceiling doit rester tracee, applied={applied}",
        )

    def test_ceiling_locks_user_group_floor(self):
        # Cas exact documente comme impossible (tiers_helpers.py:442-443) :
        # un 720p ne peut pas finir Platinum via un group_floor utilisateur.
        cfg = _cfg_on()
        cfg["group_floors"]["framestor"] = "Platinum"
        tier, _ = apply_tier_hierarchy(
            "Gold",
            {"resolution_label": "720p", "release_group": "FraMeSToR"},
            cfg,
        )
        self.assertEqual(tier, "Silver")

    def test_ceiling_sans_changement_verrouille_quand_meme(self):
        # Entree Bronze : le ceiling 720p (Silver) ne MODIFIE pas le tier, donc
        # il ne produit aucune entree d'audit trail. Le verrou doit malgre tout
        # etre pose (sinon le group floor Platinum passe).
        cfg = _cfg_on()
        cfg["group_floors"]["framestor"] = "Platinum"
        tier, _ = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "720p", "release_group": "FraMeSToR"},
            cfg,
        )
        self.assertEqual(tier, "Silver")

    def test_ceiling_sd_verrouille_le_floor_hdr(self):
        # SD -> ceiling Bronze ; dolby_vision -> floor Gold. Bronze gagne.
        tier, _ = apply_tier_hierarchy(
            "Gold",
            {"resolution_label": "SD", "hdr": "dolby_vision"},
            _cfg_on(),
        )
        self.assertEqual(tier, "Bronze")

    def test_ceilings_multiples_se_cumulent_au_plus_strict(self):
        # Deux ceilings sur la meme dimension resolution ne peuvent pas
        # coexister sur un meme fichier ; on verifie plutot que le verrou
        # retient le plus STRICT quand la config en pose un plus bas.
        cfg = _cfg_on()
        cfg["resolution_ceilings"]["720p"] = "Bronze"
        tier, _ = apply_tier_hierarchy(
            "Platinum",
            {"resolution_label": "720p", "audio_codec": "truehd_atmos"},
            cfg,
        )
        self.assertEqual(tier, "Bronze")


class HierarchyNonRegressionTests(unittest.TestCase):
    """Assertions qui doivent rester VERTES des deux cotes de la mutation."""

    def test_floor_2160p_probe_promeut_toujours(self):
        # Aucun ceiling en jeu : le floor doit continuer a promouvoir.
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "2160p", "resolution_source": "probe"},
            _cfg_on(),
        )
        self.assertEqual(tier, "Gold")
        self.assertEqual(applied[0]["dimension"], "resolution")
        self.assertEqual(applied[0]["type"], "floor")

    def test_floors_cumulatifs_sans_ceiling(self):
        # Sans ceiling, les floors des dimensions suivantes s'appliquent
        # toujours (on ne veut PAS d'un "break apres la 1re decision").
        cfg = _cfg_on()
        cfg["group_floors"]["framestor"] = "Platinum"
        tier, _ = apply_tier_hierarchy(
            "Bronze",
            {
                "resolution_label": "2160p",
                "resolution_source": "probe",
                "release_group": "FraMeSToR",
            },
            cfg,
        )
        self.assertEqual(tier, "Platinum")

    def test_default_off_reste_no_op_strict(self):
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "720p", "audio_codec": "truehd_atmos"},
            None,
        )
        self.assertEqual(tier, "Bronze")
        self.assertEqual(applied, [])


class CeilingExigeUneResolutionCONNUETests(unittest.TestCase):
    """Revue adversaire R1 (HIGH) : le verrou ne doit pas s'armer sur une
    resolution NON MESUREE.

    ``quality_score._resolution_label`` rend le couple ATTRAPE-TOUT
    ``("SD", "unknown")`` des que le probe n'a pas les dimensions ET que le nom
    ne porte aucun token de resolution - cas NOMINAL sur un probe PARTIAL
    ('Resolution video incomplete') ou avec ``probe_backend='none'``. Ce n'est
    pas une resolution SD, c'est une resolution INCONNUE. Le ceiling
    ``SD -> Bronze`` s'armait dessus et, depuis le verrou F01, retrogradait
    DEFINITIVEMENT un vrai UHD Dolby Vision de 3 tiers.
    """

    def test_resolution_unknown_n_arme_aucun_ceiling(self):
        tier, applied = apply_tier_hierarchy(
            "Gold",
            {
                "resolution_label": "SD",
                "resolution_source": "unknown",
                "hdr": "dolby_vision",
                "audio_codec": "truehd_atmos",
            },
            _cfg_on(),
        )
        self.assertEqual(tier, "Gold", f"applied={applied}")
        self.assertEqual(
            [d for d in applied if d["dimension"] == "resolution"],
            [],
            f"aucune regle de resolution ne doit se declencher, applied={applied}",
        )

    def test_resolution_unknown_ne_verrouille_pas_le_floor_hdr(self):
        # Entree Reject (score bas parce que le probe n'a rien mesure) : le
        # floor Dolby Vision doit pouvoir promouvoir, comme avant F01.
        tier, _ = apply_tier_hierarchy(
            "Reject",
            {
                "resolution_label": "SD",
                "resolution_source": "unknown",
                "hdr": "dolby_vision",
            },
            _cfg_on(),
        )
        self.assertEqual(tier, "Gold")

    def test_e2e_uhd_dv_au_probe_partial_n_est_pas_retrograde(self):
        # Chemin de production complet : profil hierarchie ON, vrai UHD Dolby
        # Vision + TrueHD Atmos 25 Mb/s dont le probe rend PARTIAL (width/height
        # manquants) et dont le nom ne porte aucun token de resolution.
        prof = default_quality_profile()
        prof["tier_hierarchy"]["enabled"] = True
        res = compute_quality_score(
            normalized_probe={
                "probe_quality": "PARTIAL",
                "video": {
                    "codec": "hevc",
                    "bitrate": 25000000,
                    "bit_depth": 10,
                    "hdr_dolby_vision": True,
                },
                "audio_tracks": [{"codec": "truehd atmos", "channels": 8, "bitrate": 4000000}],
            },
            profile=prof,
            folder_name="Le Grand Bleu (1988)",
            release_name="Le Grand Bleu (1988).mkv",
        )
        detected = res["metrics"]["detected"]
        # La fixture doit bien emprunter le chemin attrape-tout, sinon le test
        # ne prouve rien (garde anti-faux-vert).
        self.assertEqual(detected.get("resolution"), "SD")
        self.assertEqual(detected.get("resolution_source"), "unknown")
        self.assertEqual(res["tier"], "Gold", f"reasons={res['reasons']}")


class CeilingSurResolutionCONNUENonRegressionTests(unittest.TestCase):
    """Assertions qui doivent rester VERTES des deux cotes de la mutation."""

    def test_ceiling_sd_MESURE_plafonne_toujours(self):
        # Une vraie SD mesuree par le probe garde son plafond Bronze.
        tier, _ = apply_tier_hierarchy(
            "Gold",
            {
                "resolution_label": "SD",
                "resolution_source": "probe",
                "hdr": "dolby_vision",
            },
            _cfg_on(),
        )
        self.assertEqual(tier, "Bronze")

    def test_ceiling_720p_name_fallback_plafonne_toujours(self):
        # Le ceiling declaratif (label lu dans le NOM) reste actif : on n'a pas
        # exige `resolution_source == "probe"`, qui aurait desarme ce garde.
        tier, _ = apply_tier_hierarchy(
            "Gold",
            {
                "resolution_label": "720p",
                "resolution_source": "name_fallback",
                "audio_codec": "truehd_atmos",
            },
            _cfg_on(),
        )
        self.assertEqual(tier, "Silver")


class FloorBorneAuditTrailTests(unittest.TestCase):
    """Revue adversaire R1 (LOW) : un floor neutralise par le verrou doit
    laisser une trace, et cette trace doit porter le floor DEMANDE."""

    def _cfg_framestor_platinum(self):
        cfg = _cfg_on()
        cfg["group_floors"]["framestor"] = "Platinum"
        return cfg

    def test_floor_integralement_neutralise_laisse_une_trace(self):
        tier, applied = apply_tier_hierarchy(
            "Silver",
            {"resolution_label": "720p", "release_group": "FraMeSToR"},
            self._cfg_framestor_platinum(),
        )
        self.assertEqual(tier, "Silver")
        entries = [d for d in applied if d["dimension"] == "release_group"]
        self.assertEqual(len(entries), 1, f"applied={applied}")
        self.assertEqual(entries[0]["type"], "floor_capped")
        self.assertEqual(entries[0]["from"], "Silver")
        self.assertEqual(entries[0]["to"], "Silver")

    def test_l_entree_porte_le_floor_DEMANDE_et_le_plafond(self):
        # Avant : 'floor (release_group=framestor): Bronze -> Silver', alors que
        # le floor configure vaut Platinum -> libelle trompeur.
        _, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "720p", "release_group": "FraMeSToR"},
            self._cfg_framestor_platinum(),
        )
        entry = [d for d in applied if d["dimension"] == "release_group"][0]
        self.assertEqual(entry["type"], "floor_capped")
        self.assertEqual(entry["requested"], "Platinum")
        self.assertEqual(entry["ceiling"], "Silver")
        self.assertEqual(entry["to"], "Silver")

    @staticmethod
    def _e2e_profile(*, hierarchy: bool):
        # Seuil Silver abaisse a 42 (profil utilisateur legitime) pour que le
        # tier pondere de ce 720p tombe EXACTEMENT sur Silver, c'est-a-dire sur
        # le tier que la hierarchie va rendre elle aussi. Sans ce calage le
        # tier bougerait (Bronze -> Silver) et le gate consommateur laisserait
        # passer les raisons meme non corrige : le test serait un FAUX VERT.
        prof = default_quality_profile()
        prof["tiers"]["silver"] = 42
        if hierarchy:
            prof["tier_hierarchy"]["enabled"] = True
            prof["tier_hierarchy"]["group_floors"]["framestor"] = "Platinum"
        return prof

    @staticmethod
    def _e2e_score(prof):
        return compute_quality_score(
            normalized_probe={
                "probe_quality": "FULL",
                "video": {"codec": "hevc", "width": 1280, "height": 720, "bitrate": 6000000},
                "audio_tracks": [{"codec": "truehd", "channels": 8, "bitrate": 3000000, "language": "en"}],
            },
            profile=prof,
            folder_name="Film (2020)",
            release_name="Film.2020.720p.BluRay.TrueHD.7.1.x265-FraMeSToR.mkv",
        )

    def test_e2e_le_floor_borne_est_explique_meme_a_tier_CONSTANT(self):
        sans = self._e2e_score(self._e2e_profile(hierarchy=False))
        avec = self._e2e_score(self._e2e_profile(hierarchy=True))
        # Garde anti-faux-vert : la fixture DOIT etre a tier constant, sinon
        # elle n'exerce pas le gate de quality_score.
        self.assertEqual(
            avec["tier"],
            sans["tier"],
            "fixture invalide : le tier doit etre INCHANGE par la hierarchie",
        )
        borne = [r for r in avec["reasons"] if "floor borne" in r]
        self.assertTrue(
            borne,
            f"le floor Platinum a ete borne a Silver sans AUCUNE explication : reasons={avec['reasons']}",
        )
        self.assertIn("Platinum", borne[0])
        self.assertIn("Silver", borne[0])


class FloorAuditTrailNonRegressionTests(unittest.TestCase):
    """Assertions qui doivent rester VERTES des deux cotes de la mutation."""

    def test_floor_libre_garde_le_type_floor_historique(self):
        # Sans plafond, la forme de l'entree ne change pas (contrat des
        # consommateurs : quality_score construit son libelle dessus).
        _, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "2160p", "resolution_source": "probe"},
            _cfg_on(),
        )
        self.assertEqual(
            applied,
            [{"dimension": "resolution", "type": "floor", "value": "2160p_probe", "from": "Bronze", "to": "Gold"}],
        )

    def test_ceiling_effectif_reste_type_ceiling(self):
        _, applied = apply_tier_hierarchy(
            "Gold",
            {"resolution_label": "720p"},
            _cfg_on(),
        )
        self.assertEqual(
            [d["type"] for d in applied],
            ["ceiling"],
            f"applied={applied}",
        )


if __name__ == "__main__":
    unittest.main()
