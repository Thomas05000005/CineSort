"""T-DOM-1 : une penalite ANNONCEE a l'utilisateur et jamais appliquee.

Dans `_score_video`, branche « debit video non detecte » :

    if bitrate_kbps is None:
        video_sub -= 8
        if resolution_rank >= 2160 and release_4k_light_hint and toggles[...]:
            is_4k_light = True
            add_reason(-4, "4K Light probable (tag release) sans debit mesure")
        add_reason(-8, "Debit video non detecte")

`add_reason` n'ecrit QUE dans `reasons` et `factors` — ce que l'utilisateur lit.
`video_sub` ne bouge que de -8. Le -4 part donc a l'affichage sans jamais toucher
le score. Mesure du 2026-08-29 sur un 2160p tagge « 4KLight » sans debit :
toggle ON -> 37, toggle OFF -> 37, difference NULLE, et la ligne « -4 4K Light
probable » bien presente dans les raisons.

Deux consequences, pas une :
1. le reglage `enable_4k_light` est INERTE sur ce chemin ;
2. l'explication de score MENT — meme famille que le triangle annonce/journal
   du lot T-PROD, ou ce qu'on affiche n'est pas ce qu'on a fait.

La branche `elif` juste en dessous, elle, applique bien `video_sub -= penalty` —
et porte le commentaire « Hotfix coherence (2026-06-04) : aligner add_reason
delta sur l'increment reel applique a video_sub ». Le defaut avait donc deja ete
corrige ICI MEME, dans la branche voisine, et manque dans celle-ci.
"""

from __future__ import annotations

import copy
import unittest

from cinesort.domain.quality_score import compute_quality_score, default_quality_profile

SONDE_4K_SANS_DEBIT = {
    "width": 3840,
    "height": 2160,
    "video_codec": "hevc",
    "bitrate": None,
    "duration": 7200,
    "audio_tracks": [{"codec": "eac3", "channels": 6, "language": "fre", "bitrate": 640}],
    "subtitle_tracks": [],
}
RELEASE_TAGGEE = "Film.2020.2160p.4KLight.HDR.x265-GROUP"


class LaPenaliteAnnonceeEstAppliqueeTests(unittest.TestCase):
    def _score(self, actif: bool) -> dict:
        prof = copy.deepcopy(default_quality_profile())
        prof["toggles"]["enable_4k_light"] = actif
        return compute_quality_score(
            normalized_probe=copy.deepcopy(SONDE_4K_SANS_DEBIT),
            profile=prof,
            release_name=RELEASE_TAGGEE,
        )

    def test_le_reglage_change_reellement_le_score(self) -> None:
        actif, inactif = self._score(True), self._score(False)
        self.assertLess(
            actif["score"],
            inactif["score"],
            "`enable_4k_light` est INERTE sur le chemin « debit non detecte » : "
            f"ON={actif['score']} et OFF={inactif['score']}. Le reglage existe, "
            "l'utilisateur le voit, et il ne fait rien.",
        )

    def test_la_penalite_affichee_correspond_a_l_ecart_reel(self) -> None:
        """Le chiffre montre doit etre celui applique — sinon l'explication ment."""
        actif, inactif = self._score(True), self._score(False)
        # La penalite vit dans `reasons` — la liste que l'utilisateur LIT.
        # Il n'y a pas de cle `factors` au niveau du payload : `explanation` est
        # une vue ponderee et filtree, et cette ligne-la n'y figure meme pas.
        annonce = sum(int(str(r).split(maxsplit=1)[0]) for r in (actif.get("reasons") or []) if "4K Light" in str(r))
        self.assertNotEqual(annonce, 0, "aucune penalite 4K Light annoncee : le temoin est muet")

        # La comparaison porte sur le SOUS-SCORE video, pas sur le score final.
        # `add_reason` annonce un delta de sous-score ; le total applique ensuite
        # la ponderation (video 60 %), si bien qu'un -4 annonce vaut -2 au bout.
        # Comparer les deux echelles serait mesurer deux choses differentes.
        def sous(r: dict) -> int:
            return int(((r.get("metrics") or {}).get("subscores") or {})["video"])

        self.assertEqual(
            sous(actif) - sous(inactif),
            annonce,
            f"l'utilisateur lit {annonce:+d} et le sous-score video bouge de {sous(actif) - sous(inactif):+d}.",
        )

    def test_le_reglage_peut_faire_basculer_le_PALIER(self) -> None:
        """Ce n'est pas cosmetique : sur ce cas mesure, Bronze devient Reject.

        Le palier est ce que l'utilisateur voit en premier, et ce sur quoi les
        regles de tri s'appuient. Inerte, le reglage ne changeait rien ;
        applique, il fait basculer le verdict.
        """
        self.assertEqual(self._score(False)["tier"], "Bronze")
        self.assertEqual(self._score(True)["tier"], "Reject")

    def test_sans_le_tag_release_rien_ne_change(self) -> None:
        """Temoin : la penalite ne doit pas s'appliquer a tout 4K sans debit."""
        prof_on = copy.deepcopy(default_quality_profile())
        prof_on["toggles"]["enable_4k_light"] = True
        prof_off = copy.deepcopy(prof_on)
        prof_off["toggles"]["enable_4k_light"] = False
        sans_tag = "Film.2020.2160p.HDR.x265-GROUP"
        a = compute_quality_score(
            normalized_probe=copy.deepcopy(SONDE_4K_SANS_DEBIT), profile=prof_on, release_name=sans_tag
        )
        b = compute_quality_score(
            normalized_probe=copy.deepcopy(SONDE_4K_SANS_DEBIT), profile=prof_off, release_name=sans_tag
        )
        self.assertEqual(a["score"], b["score"], "penalite appliquee sans tag release")


if __name__ == "__main__":
    unittest.main()
