# -*- coding: utf-8 -*-
"""Changer les regles perceptuelles SANS bumper la version rend le correctif INVISIBLE.

Le defaut, et pourquoi il devient couteux MAINTENANT
----------------------------------------------------
`PERCEPTUAL_ENGINE_VERSION` ne servait a rien : elle etait ecrite dans chaque
rapport et relue nulle part. Un changement de regle sans bump n'avait donc
aucune consequence — il n'y avait rien a tromper.

Depuis que le cache perceptuel exige la version courante
(`perceptual_support.py`, meme campagne), la version DECIDE si un rapport est
recalcule. Un changement de regle sans bump laisse alors servir des rapports de
l'ancienne formule EN CROYANT LES AVOIR RAFRAICHIS — c'est-a-dire pire qu'avant,
parce que le correctif de fraicheur donne une fausse assurance.

C'est exactement l'enchainement de #1172 / #1186 sur le moteur de qualite. Ce
fichier generalise le cliquet de #1186 au moteur perceptuel.

Pourquoi une EMPREINTE, et pas une lecture du source
-----------------------------------------------------
Il n'existe aucun moyen d'observer « les regles ont change » depuis le source :
la modification peut vivre dans n'importe laquelle des lignes de
`composite_score.py`, `composite_score_v2.py`, `audio_perceptual.py` ou
`mel_analysis.py`. Ce qu'on peut observer, c'est le COMPORTEMENT sur un corpus
fige (`tests/_corpus_perceptuel.py`).

Le cliquet est BIDIRECTIONNEL :

  - le comportement change sans bump  -> l'empreinte inscrite ne correspond plus ;
  - la version est bumpee sans entree -> aucune empreinte a comparer.

Ce n'est pas un test de non-regression : rien n'interdit de changer les regles.
Il interdit de le faire SILENCIEUSEMENT.

SEPT surfaces, parce qu'une seule aurait menti
----------------------------------------------
Les trois raisons citees par le bump 1.0 -> 1.1 vivent dans TROIS modules
differents. Une empreinte posee sur le seul `build_perceptual_result` n'en
aurait couvert aucune :

    #660 trous spectraux AAC   -> mel_analysis.detect_aac_holes
    #752 confiance DRC         -> audio_perceptual.classify_drc
    #804 confiance fake 4K     -> composite_score_v2
    #813 verdict « Faux 4K »   -> composite_score.detect_cross_verdicts

D'ou une empreinte PAR SURFACE : le message d'echec nomme alors celle qui a
bouge, au lieu de dire « quelque chose a change quelque part ».

LA SEPTIEME SURFACE (`hdr`) A ETE AJOUTEE APRES COUP, ET SON ABSENCE ETAIT UN
ANGLE MORT. Le lot qui a ferme le trou HLG / DV 7 / DV inconnu de `_score_hdr`
n'a change AUCUNE des six empreintes existantes : `composite_v2` est appele avec
`normalized_probe={}`, donc `_score_hdr` y prend toujours la branche SDR. Le
cliquet variait, couvrait dix cas, et ne gardait rien de la regle corrigee. Un
corpus qui VARIE n'est pas un corpus qui COUVRE — c'est la lecon de plus, apres
les trois inerties de sa redaction initiale.

Ce que ce cliquet NE couvre pas
--------------------------------
  - Les fonctions qui exigent un vrai fichier media (`analyze_video_frames`,
    `analyze_loudnorm`, `analyze_astats`) : elles pilotent des subprocess
    ffmpeg. Leur SORTIE alimente les surfaces ci-dessus, donc un changement de
    seuil y reste visible ; un changement dans l'extraction elle-meme, non.
  - `compute_global_score_v2` est appele avec `normalized_probe={}` : il rend
    donc des scores plus bas qu'en usage reel (un « mastering reference » y
    tombe en `bronze`). Le corpus n'est pas REALISTE, il est DETERMINISTE — la
    seule propriete dont une empreinte a besoin.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any, Dict

from cinesort.domain.perceptual.constants import PERCEPTUAL_ENGINE_VERSION
from tests._corpus_perceptuel import VERDICTS_CROISES_ATTENDUS, verdicts

#: Empreinte du comportement, PAR VERSION et PAR SURFACE.
#:
#: Pour bumper : changer `PERCEPTUAL_ENGINE_VERSION`, lancer ce test, recopier
#: les empreintes que le message d'echec affiche, et dire dans `constants.py`
#: CE QUI a change. Recopier une empreinte sans avoir lu le diff qu'elle
#: recouvre est le seul usage de ce fichier qui le rende inutile.
#:
#: PURGER `__pycache__` AVANT DE MESURER (ou lancer avec `-B` et
#: `PYTHONDONTWRITEBYTECODE=1`). Python invalide son bytecode sur le couple
#: (mtime, TAILLE) de la source : editer une constante de `-70.0` en `-65.0` ne
#: change pas la taille, et si la restauration retombe dans la meme seconde,
#: le `.pyc` MUTE est juge valide. Vecu en ecrivant ce fichier : une empreinte
#: a ete inscrite depuis la valeur mutee, `constants.py` portant pourtant
#: l'original sur disque et `git status` etant propre. Le cliquet passait alors
#: au vert sur la mutation qu'il devait attraper — un instrument casse ne rend
#: pas d'erreur, il rend un chiffre propre.
EMPREINTES: Dict[str, Dict[str, str]] = {
    "1.2": {
        "composite_v1": "9af3071f8085ad499869e8acef9b9cb3553f399d989b0365b2487c90e3add4da",
        "drc": "267aa75cc1dfe558a5160f544d238f5f026c60f27e6eb7568908c6ea9c197225",
        "audio_score": "9266ec38ce90ad82ec4a86546d309392380592716ea83e0b4acdf7b388eac664",
        "mel_scores": "00beba2083f05d4c16301fa8a794be3c978389faaaecb82c643c1ac0cbc4870b",
        "aac_holes": "2201737ec70ce2c50d822633f9d6616e0b18263fec350f24c25b6314fb233d2b",
        "composite_v2": "9cd19ce24a04d704e23f2edb6c1025650ad562ed8b2b816a1dee63e1b7878656",
        "hdr": "fc83d6f38b72748de98136695b19786c37549ee51755f8c0d7adf8664bb38b0f",
    },
    "1.1": {
        "composite_v1": "9af3071f8085ad499869e8acef9b9cb3553f399d989b0365b2487c90e3add4da",
        "drc": "267aa75cc1dfe558a5160f544d238f5f026c60f27e6eb7568908c6ea9c197225",
        "audio_score": "9266ec38ce90ad82ec4a86546d309392380592716ea83e0b4acdf7b388eac664",
        "mel_scores": "00beba2083f05d4c16301fa8a794be3c978389faaaecb82c643c1ac0cbc4870b",
        "aac_holes": "2201737ec70ce2c50d822633f9d6616e0b18263fec350f24c25b6314fb233d2b",
        "composite_v2": "9cd19ce24a04d704e23f2edb6c1025650ad562ed8b2b816a1dee63e1b7878656",
    },
}


def _canonique(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False)


def _empreinte(cas: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonique(cas).encode("utf-8")).hexdigest()


def _empreintes_mesurees() -> Dict[str, str]:
    return {surface: _empreinte(cas) for surface, cas in verdicts().items()}


class CliquetDeVersionPerceptuelleTests(unittest.TestCase):
    def test_la_version_COURANTE_a_une_empreinte(self) -> None:
        """Le sens « bumpe sans entree ». Sans ce test, bumper la version
        suffirait a rendre le cliquet muet : il n'aurait plus rien a comparer,
        et l'absence de comparaison passerait pour un succes.
        """
        self.assertIn(
            PERCEPTUAL_ENGINE_VERSION,
            EMPREINTES,
            f"PERCEPTUAL_ENGINE_VERSION vaut {PERCEPTUAL_ENGINE_VERSION!r} et n'a aucune empreinte inscrite. "
            "Ajouter une entree a EMPREINTES avec les valeurs mesurees, et dire dans constants.py CE QUI a change.",
        )

    def test_le_COMPORTEMENT_correspond_a_la_version(self) -> None:
        """Le sens « change sans bump ». Le message nomme la surface qui bouge."""
        attendues = EMPREINTES.get(PERCEPTUAL_ENGINE_VERSION, {})
        mesurees = _empreintes_mesurees()

        divergentes = {
            surface: (mesure, attendues.get(surface))
            for surface, mesure in mesurees.items()
            if attendues.get(surface) != mesure
        }

        self.assertEqual(
            divergentes,
            {},
            "Le comportement perceptuel a change sans que "
            f"PERCEPTUAL_ENGINE_VERSION ({PERCEPTUAL_ENGINE_VERSION}) bouge.\n"
            + "\n".join(
                f"  {surface} : mesure {mesure} / inscrit {inscrit}"
                for surface, (mesure, inscrit) in divergentes.items()
            )
            + "\n\nDeux issues, et une seule est correcte selon le cas :\n"
            "  - le changement est VOULU  -> bumper la version, ajouter une entree a EMPREINTES,\n"
            "    et ecrire dans constants.py ce qui change pour l'utilisateur ;\n"
            "  - le changement est FORTUIT -> c'est une regression, et ce test vient de l'attraper.",
        )

    def test_les_empreintes_inscrites_couvrent_TOUTES_les_surfaces(self) -> None:
        """Une surface ajoutee au corpus mais oubliee dans EMPREINTES ne serait
        comparee a rien. `attendues.get(surface)` rendrait None, donc different
        de la mesure — mais seulement parce que le test precedent compare dans
        ce sens-la. Cette assertion le dit franchement plutot que par accident.
        """
        inscrites = set(EMPREINTES.get(PERCEPTUAL_ENGINE_VERSION, {}))
        mesurees = set(_empreintes_mesurees())

        self.assertEqual(mesurees - inscrites, set(), "surface(s) du corpus sans empreinte inscrite")
        self.assertEqual(inscrites - mesurees, set(), "empreinte(s) inscrite(s) pour une surface disparue")

    def test_chaque_surface_VARIE(self) -> None:
        """LA LECON DE CE LOT. Une premiere version du corpus mesurait
        `audio_score = 0` sur les dix cas — `compute_audio_score` rend `None`
        des que `track_index < 0`, et le defaut du champ est -1. L'empreinte
        aurait ete parfaitement stable... et parfaitement inutile : elle aurait
        fige une constante, pas un comportement.

        Un cliquet inerte est indiscernable d'un cliquet sain tant qu'on ne le
        mute pas. Ce test exige que chaque surface produise au moins deux
        verdicts DISTINCTS sur son corpus.
        """
        pauvres = {}
        for surface, cas in verdicts().items():
            distincts = {_canonique(valeur) for valeur in cas.values()}
            if len(distincts) < 2:
                pauvres[surface] = len(distincts)

        self.assertEqual(
            pauvres,
            {},
            f"Surface(s) INERTE(S) : {pauvres}. Un corpus dont toutes les entrees rendent le meme verdict "
            "fige une constante, pas un comportement — son empreinte ne bougera jamais.",
        )

    def test_les_DIX_verdicts_croises_sont_exerces(self) -> None:
        """Deuxieme controle de non-inertie, sur la couverture cette fois.

        `test_chaque_surface_VARIE` verifie qu'une surface n'est pas constante ;
        il ne dit rien de ce qu'elle ATTEINT. Sans cette assertion, on pourrait
        retirer la moitie des cas de `CAS_COMPOSITE_V1`, recopier la nouvelle
        empreinte, et le cliquet continuerait de passer pour complet — en ayant
        cesse de garder cinq regles.
        """
        obtenus = set()
        for cas in verdicts()["composite_v1"].values():
            obtenus.update(cas["verdicts"])

        self.assertEqual(
            VERDICTS_CROISES_ATTENDUS - obtenus,
            set(),
            "verdict(s) croise(s) que le corpus n'exerce plus : leur regle n'est plus gardee",
        )
        self.assertEqual(
            obtenus - VERDICTS_CROISES_ATTENDUS,
            set(),
            "verdict(s) croise(s) inconnu(s) : un verdict a ete ajoute au produit sans entrer dans la liste",
        )

    def test_l_empreinte_DEPEND_du_verdict(self) -> None:
        """Contre-epreuve du hachage lui-meme : si `_empreinte` ignorait son
        argument, tous les tests ci-dessus passeraient pour toujours.
        """
        self.assertNotEqual(_empreinte({"a": 1}), _empreinte({"a": 2}))
        self.assertEqual(_empreinte({"a": 1, "b": 2}), _empreinte({"b": 2, "a": 1}))

    def test_le_corpus_est_DETERMINISTE(self) -> None:
        """Deux appels doivent rendre la meme chose. Un `ts`, une graine
        aleatoire ou un parcours de `set` non trie suffirait a rendre le
        cliquet rouge une execution sur deux — et a le faire desactiver.
        """
        self.assertEqual(_empreintes_mesurees(), _empreintes_mesurees())


if __name__ == "__main__":
    unittest.main()
