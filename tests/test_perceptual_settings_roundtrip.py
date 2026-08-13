"""Ce que la sauvegarde ACCEPTE, la lecture doit le RENDRE.

POURQUOI CE FICHIER EXISTE. `_save_section_perceptual` borne
`perceptual_skip_percent` a **[0, 20]** : zero est une valeur legale, et elle a
un sens precis — « n'ignore ni le debut ni la fin du film pour choisir les
frames ». Elle se persistait correctement. Mais `_build_settings_dict`, cote
lecture, faisait :

    "skip_percent": int(settings.get("perceptual_skip_percent") or 5)

`0 or 5` vaut `5`. Le reglage revenait donc a 5 % a chaque lecture, et les trois
appelants (`extract_representative_flames`, la comparaison, le batch) sautaient
5 % du film que l'utilisateur avait explicitement demande de ne pas sauter.

Le piege est nomme dans `settings_support.py` lui-meme, avec CE reglage en
exemple :

    # Hotfix sentinel : pattern `int(payload.get(k) or DEFAULT)` ecrase 0 [...]
    # Or l'utilisateur peut legitimement vouloir 0 (ex: perceptual_skip_percent).

Le correctif d'alors n'a ete applique qu'au chemin d'ECRITURE
(`_coerce_int_with_default`). Le chemin de LECTURE est reste sur `or`.

CE QUE CE TEST EPROUVE. Il ne verifie pas un reglage : il verifie l'INVARIANT
qui relie les deux bouts. Pour chaque reglage perceptuel numerique, il demande a
la sauvegarde sa valeur MINIMALE legale (en lui soumettant une valeur sous la
borne, le clamp rend le minimum), puis exige que la lecture rende EXACTEMENT
cette valeur. Aucun minimum n'est ecrit en dur ici : les deux ensembles sont
derives du code de production, donc le test suit les bornes si elles bougent, et
il attrapera le prochain `or DEFAULT` pose sur un reglage dont 0 est legal.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.perceptual_support import _build_settings_dict
from cinesort.ui.api.settings_support import _save_section_perceptual

#: cle persistee -> cle exposee au runtime, pour les reglages NUMERIQUES bornes.
_NUMERIQUES = {
    "perceptual_timeout_per_film_s": "timeout_per_film_s",
    "perceptual_frames_count": "frames_count",
    "perceptual_skip_percent": "skip_percent",
    "perceptual_dark_weight": "dark_weight",
    "perceptual_audio_segment_s": "audio_segment_s",
    "perceptual_comparison_frames": "comparison_frames",
    "perceptual_comparison_timeout_s": "comparison_timeout_s",
}

#: Valeur soumise pour obtenir le minimum : sous toute borne inferieure connue,
#: donc le clamp de la sauvegarde rend le plancher REEL, quel qu'il soit.
_SOUS_LA_BORNE = -1


class UneValeurSauvegardableEstUneValeurRelisibleTests(unittest.TestCase):
    def test_le_minimum_legal_de_chaque_reglage_survit_a_la_relecture(self) -> None:
        """LE test qui aurait attrape `skip_percent`.

        Il derive le minimum de la sauvegarde elle-meme : si une borne change,
        le test suit ; si un `or DEFAULT` reapparait a la lecture, il rougit.
        """
        persiste = _save_section_perceptual({k: _SOUS_LA_BORNE for k in _NUMERIQUES})
        runtime = _build_settings_dict(persiste)

        for cle_persistee, cle_runtime in _NUMERIQUES.items():
            with self.subTest(reglage=cle_persistee):
                attendu = persiste[cle_persistee]
                self.assertEqual(
                    runtime[cle_runtime],
                    attendu,
                    f"« {cle_persistee} » se persiste a {attendu!r} mais se relit "
                    f"{runtime[cle_runtime]!r} : la valeur choisie par l'utilisateur "
                    "est remplacee par le defaut a chaque lecture",
                )

    def test_zero_est_une_valeur_legale_de_skip_percent_et_le_reste(self) -> None:
        """Le cas concret : 0 % veut dire « analyse le film en entier »."""
        persiste = _save_section_perceptual({"perceptual_skip_percent": 0})
        self.assertEqual(persiste["perceptual_skip_percent"], 0, "la sauvegarde ne borne plus a 0")
        self.assertEqual(
            _build_settings_dict(persiste)["skip_percent"],
            0,
            "0 % de skip demande explicitement se relit autrement : les frames "
            "seront choisies en sautant le debut et la fin du film",
        )


if __name__ == "__main__":
    unittest.main()
