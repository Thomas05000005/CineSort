# -*- coding: utf-8 -*-
"""Changer les regles de scoring SANS bumper la version rend le correctif INVISIBLE.

Le defaut
---------
`quality_report_support.py:396` decide un CACHE HIT sur
`existing_rules_version == str(SCORING_RULES_VERSION)`, et l'analyse en masse
passe `reuse_existing=True` par defaut (`quality_support.py:30`). Un rapport
deja persiste n'est donc PAS recalcule tant que la version ne bouge pas.

Mesure du 2026-08-31 : le commit 0d3c9c25 (#1172) a change QUATRE regles —
plancher de tier desarme sur les dimensions issues du nom, canaux inventes
(6/2) remplaces par 0 avec `channels_source="unknown"`, garde anti-double-
comptage Atmos passee au codec canonique, taille de fichier lue depuis
`container_size_bytes` — et n'a PAS bumpe. Le dernier bump (3 -> 4) datait de
2c22bc98 (#1165), la PR PRECEDENTE, qui avait pourtant bumpe pour exactement
cette raison. Sur le meme film, le scoring passait de Gold a Reject, et
`scoring_rules_version` valait 4 DES DEUX COTES : en production, plus personne
ne voyait la difference.

Trois fichiers de tests citaient deja `SCORING_RULES_VERSION`. Aucun ne gardait
l'invariant : le comportement change => la version change.

Ce que ce test fait, et pourquoi c'est une EMPREINTE
----------------------------------------------------
Il n'existe aucun moyen d'observer « les regles ont change » depuis le code
source : la modification peut vivre dans n'importe laquelle des ~2500 lignes de
`quality_score.py`. Ce qu'on peut observer, c'est le COMPORTEMENT — le verdict
rendu sur un corpus fige.

Le cliquet est donc BIDIRECTIONNEL, comme celui de bandit :

- le comportement change sans bump  -> l'empreinte inscrite ne correspond plus ;
- la version est bumpee sans entree -> aucune empreinte a comparer.

Dans les deux cas le message dit quoi faire. Ce n'est pas un test de
non-regression : rien n'interdit de changer les regles. Il interdit de le faire
SILENCIEUSEMENT.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any, Dict, List

from cinesort.domain.quality_score import (
    SCORING_RULES_VERSION,
    compute_quality_score,
    default_quality_profile,
)

#: Corpus fige. Chaque cas exerce un axe DIFFERENT, et les quatre regles
#: changees par #1172 y sont representees. Les valeurs sont inventees et
#: deterministes : aucun acces disque, aucun horodatage.
_CORPUS: List[tuple] = [
    (
        "nom menteur, aucune piste audio",
        {
            "normalized_probe": {
                "probe_quality": "FULL",
                "video": {
                    "width": 1920,
                    "height": 1080,
                    "codec": "h264",
                    "bitrate": 1_200_000,
                    "bit_depth": 8,
                },
                "audio_tracks": [],
                "subtitles": [],
            },
            "release_name": "Film.2020.1080p.WEB-DL.TrueHD.Atmos.7.1-MENTEUR.mkv",
        },
    ),
    (
        "lossless reel TrueHD 7.1",
        {
            "normalized_probe": {
                "probe_quality": "FULL",
                "video": {
                    "width": 3840,
                    "height": 2160,
                    "codec": "hevc",
                    "bitrate": 60_000_000,
                    "bit_depth": 10,
                },
                "audio_tracks": [{"codec": "truehd", "channels": 8, "language": "eng"}],
                "subtitles": [],
            },
            "release_name": "Film.2020.2160p.UHD.BluRay.TrueHD.Atmos.7.1-GRP.mkv",
        },
    ),
    (
        "aac stereo",
        {
            "normalized_probe": {
                "probe_quality": "FULL",
                "video": {
                    "width": 1280,
                    "height": 720,
                    "codec": "h264",
                    "bitrate": 3_000_000,
                    "bit_depth": 8,
                },
                "audio_tracks": [{"codec": "aac", "channels": 2, "language": "eng"}],
                "subtitles": [],
            },
            "release_name": "Film.2020.720p.WEB-DL.AAC2.0-GRP.mkv",
        },
    ),
    (
        "atmos sans truehd (double comptage)",
        {
            "normalized_probe": {
                "probe_quality": "FULL",
                "video": {
                    "width": 1920,
                    "height": 1080,
                    "codec": "h264",
                    "bitrate": 8_000_000,
                    "bit_depth": 8,
                },
                "audio_tracks": [{"codec": "eac3", "channels": 6, "language": "eng"}],
                "subtitles": [],
            },
            "release_name": "Film.2020.1080p.WEB-DL.DDP5.1.Atmos-GRP.mkv",
        },
    ),
    (
        "sans canaux dans le nom",
        {
            "normalized_probe": {
                "probe_quality": "FULL",
                "video": {
                    "width": 1920,
                    "height": 1080,
                    "codec": "h264",
                    "bitrate": 8_000_000,
                    "bit_depth": 8,
                },
                "audio_tracks": [],
                "subtitles": [],
            },
            "release_name": "Film.2020.1080p.BluRay.TrueHD.Atmos-GRP.mkv",
        },
    ),
    (
        "taille de conteneur presente",
        {
            "normalized_probe": {
                "probe_quality": "FULL",
                "container_size_bytes": 25_000_000_000,
                "video": {
                    "width": 3840,
                    "height": 2160,
                    "codec": "hevc",
                    "bitrate": 50_000_000,
                    "bit_depth": 10,
                },
                "audio_tracks": [{"codec": "dts", "channels": 6, "language": "eng"}],
                "subtitles": [],
            },
            "release_name": "Film.2020.2160p.UHD.BluRay.DTS-HD.MA.5.1-GRP.mkv",
        },
    ),
    (
        "probe FAILED, tout depuis le nom",
        {
            "normalized_probe": {
                "probe_quality": "FAILED",
                "video": {},
                "audio_tracks": [],
                "subtitles": [],
            },
            "release_name": "Film.2020.2160p.UHD.BluRay.TrueHD.Atmos.7.1-GRP.mkv",
        },
    ),
    (
        "petit fichier nomme 1080p",
        {
            "normalized_probe": {
                "probe_quality": "FULL",
                "video": {
                    "width": 700,
                    "height": 400,
                    "codec": "h264",
                    "bitrate": 600_000,
                    "bit_depth": 8,
                },
                "audio_tracks": [{"codec": "ac3", "channels": 6, "language": "eng"}],
                "subtitles": [],
            },
            "release_name": "Film.1965.1080p.BluRay.x264-GRP.mkv",
        },
    ),
]

#: Empreinte du corpus, PAR version de regles.
#:
#: Pour ajouter une entree apres un changement volontaire : lancer ce fichier,
#: le message d'echec porte l'empreinte mesuree. L'inscrire ici, en gardant les
#: precedentes — elles documentent l'historique et coutent une ligne.
_EMPREINTE_PAR_VERSION: Dict[int, str] = {
    5: "fa5ed2f7a52f7e716ac86430f345c6a7e177a1a783bbe86e0f2d5b38977a10ac",
}


def _verdicts() -> List[Dict[str, Any]]:
    sorties: List[Dict[str, Any]] = []
    for nom, kw in _CORPUS:
        res = compute_quality_score(
            profile=default_quality_profile(),
            folder_name="Film (2020)",
            expected_title="Film",
            expected_year=2020,
            film_year=2020,
            **kw,
        )
        detecte = (res.get("metrics") or {}).get("detected") or {}
        sorties.append(
            {
                "cas": nom,
                "score": res.get("score"),
                "tier": res.get("tier"),
                "resolution_source": detecte.get("resolution_source"),
                "audio_tracks_count": detecte.get("audio_tracks_count"),
                "channels_source": detecte.get("channels_source"),
            }
        )
    return sorties


def _empreinte(verdicts: List[Dict[str, Any]]) -> str:
    lignes = [json.dumps(v, sort_keys=True, ensure_ascii=False) for v in verdicts]
    return hashlib.sha256("\n".join(lignes).encode("utf-8")).hexdigest()


class LeComportementNePEUTPasChangerEnSilenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verdicts = _verdicts()

    def test_le_corpus_DISCRIMINE(self) -> None:
        """Garde anti-silence. Un corpus qui rendrait le meme tier partout —
        parce qu'une regle l'ecrase, ou parce que `compute_quality_score` leve
        et qu'on l'a avale — donnerait une empreinte stable qui ne mesure RIEN.
        On exige de la variete des deux cotes."""
        tiers = {v["tier"] for v in self.verdicts}
        scores = {v["score"] for v in self.verdicts}
        self.assertGreaterEqual(len(tiers), 3, f"corpus non discriminant : {tiers}")
        self.assertGreaterEqual(len(scores), 6, f"scores trop uniformes : {sorted(scores)}")
        self.assertTrue(all(isinstance(v["score"], int) for v in self.verdicts))

    def test_la_version_courante_a_une_EMPREINTE_inscrite(self) -> None:
        """Bumper sans inscrire laisserait le cliquet sans reference — il
        passerait au vert en ne comparant rien."""
        self.assertIn(
            SCORING_RULES_VERSION,
            _EMPREINTE_PAR_VERSION,
            f"SCORING_RULES_VERSION = {SCORING_RULES_VERSION} n'a pas d'empreinte inscrite. "
            f"Mesuree a l'instant : {_empreinte(self.verdicts)}",
        )

    def test_le_comportement_correspond_a_la_version_ANNONCEE(self) -> None:
        """LE test. Si le scoring a change, l'empreinte ne correspond plus — et
        le cache de production servirait un rapport perime sans que personne ne
        le voie."""
        attendue = _EMPREINTE_PAR_VERSION.get(SCORING_RULES_VERSION)
        if attendue is None:
            self.skipTest("couvert par test_la_version_courante_a_une_EMPREINTE_inscrite")
        mesuree = _empreinte(self.verdicts)
        self.assertEqual(
            mesuree,
            attendue,
            "les regles de scoring ont change sans que SCORING_RULES_VERSION bouge.\n"
            f"  version annoncee : {SCORING_RULES_VERSION}\n"
            f"  empreinte mesuree: {mesuree}\n"
            "Consequence en production : `quality_report_support.py` rend un CACHE HIT "
            "sur tout rapport deja persiste, et le changement reste INVISIBLE.\n"
            "Remede : incrementer SCORING_RULES_VERSION et inscrire l'empreinte "
            "ci-dessus dans _EMPREINTE_PAR_VERSION.",
        )


if __name__ == "__main__":
    unittest.main()
