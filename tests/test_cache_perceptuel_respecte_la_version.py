"""Un rapport perceptuel d'une version ANTERIEURE n'est pas un cache valide.

Le defaut
---------
`PERCEPTUAL_ENGINE_VERSION` existait, etait documentee mot pour mot « c'est ce
qui permet de distinguer un rapport calcule avec les regles precedentes d'un
rapport recalcule apres correctif », etait posee sur chaque `PerceptualResult`
(`composite_score.py:349`) et persistee dans `metrics_json` via `to_dict()`...
et n'etait RELUE NULLE PART. Mesure du 2026-08-31 : `grep -rn
PERCEPTUAL_ENGINE_VERSION` rend trois lignes — la definition et deux ecritures.
Aucune lecture.

Consequence : le bump 1.0 -> 1.1 du 2026-08-03 (trous spectraux AAC rendus
operants, confiances DRC et fake-4K plafonnees, verdict « Faux 4K » plus leve)
n'a rafraichi AUCUN rapport deja en base. Et l'analyse en masse
(`analyze_perceptual_batch`) appelle `get_perceptual_report` film par film :
une bibliotheque melangeait donc en silence des verdicts 1.0 et 1.1 dans le
meme classement de tiers.

C'est EXACTEMENT le defaut de #1172 / #1186, sur l'autre moteur. Le moteur de
qualite, lui, compare bien sa version au cache-hit
(`quality_report_support.py:396`, `existing_rules_version == str(
SCORING_RULES_VERSION)`) : c'est ce precedent qui tranche ici.

Le repli, et pourquoi il n'est pas facultatif
---------------------------------------------
Exiger la bonne version SANS repli transformerait un rapport servi en ERREUR
pour tout film dont le media a bouge — une regression de disponibilite
introduite par un correctif de fraicheur. Le precedent fait le meme choix
(`stale_existing`, `quality_report_support.py:398`). Le rapport perime reste
servi quand le recalcul est impossible, mais il le DIT :
`perceptual_engine_stale`.

Ce que ces tests distinguent
---------------------------
`ok` et `cache_hit` valent True dans les DEUX chemins — le vrai cache-hit et le
repli. Les assertions portent donc sur `api._get_run`, qui n'est atteint
qu'APRES le bloc de cache : c'est le seul observable qui separe « servi sans
regarder plus loin » de « on a tente de recalculer ».

Sans cette precaution le test serait complaisant, et il l'a ete : en l'etat,
`test_cache_hit_returns_existing` (tests/test_perceptual_orchestration.py) reste
VERT alors qu'il passe desormais par le repli et non par le cache — mesure faite
avant d'ecrire ce fichier. Il est corrige dans le meme lot.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from cinesort.domain.perceptual.constants import PERCEPTUAL_ENGINE_VERSION
from cinesort.ui.api.perceptual_support import get_perceptual_report
from tests.test_perceptual_orchestration import _mock_api

_FFMPEG = mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")


def _api_avec_rapport(version_du_rapport):
    """API mockee dont le store rend un rapport portant `version_du_rapport`.

    `version_du_rapport=None` simule un rapport ANTERIEUR a l'introduction du
    champ : le cas le plus courant en base chez un utilisateur de longue date.
    """
    metrics = {"global_score": 80, "global_tier": "excellent"}
    if version_du_rapport is not None:
        metrics["version"] = version_du_rapport
    api = _mock_api()
    store = mock.MagicMock()
    store.perceptual.get_perceptual_report.return_value = {
        "run_id": "run1",
        "row_id": "r1",
        "global_score": 80,
        "global_tier": "excellent",
        "visual_score": 78,
        "audio_score": 82,
        "metrics": metrics,
        "settings_used": {},
        "ts": 1.0,
    }
    # `tempfile.gettempdir()` plutot qu'un "/tmp" litteral : ce chemin n'est
    # jamais ecrit (le recalcul echoue avant), mais un repertoire temporaire
    # code en dur est signale comme tel par l'analyse statique (B108, releve
    # par Codacy sur ce lot), et "/tmp" n'existe pas sous Windows — il rendait
    # la fixture trompeuse en plus d'etre signale.
    api._find_run_row.return_value = ({"state_dir": tempfile.gettempdir()}, store)
    return api


class LeCachePerceptuelRespecteLaVersionTests(unittest.TestCase):
    def test_la_version_COURANTE_est_un_vrai_cache_hit(self) -> None:
        """Contre-epreuve indispensable : sans elle, un correctif qui refuserait
        TOUT cache passerait les autres tests de ce fichier.
        """
        api = _api_avec_rapport(PERCEPTUAL_ENGINE_VERSION)

        with _FFMPEG:
            resultat = get_perceptual_report(api, "run1", "r1")

        self.assertTrue(resultat["ok"])
        self.assertTrue(resultat["cache_hit"])
        self.assertNotIn("perceptual_engine_stale", resultat)
        api._get_run.assert_not_called()

    def test_une_version_ANTERIEURE_n_est_pas_un_cache_hit(self) -> None:
        api = _api_avec_rapport("1.0")

        with _FFMPEG:
            resultat = get_perceptual_report(api, "run1", "r1")

        api._get_run.assert_called_once_with("run1")
        self.assertTrue(resultat.get("perceptual_engine_stale"))

    def test_un_rapport_SANS_version_est_traite_comme_perime(self) -> None:
        """Les rapports anterieurs a l'introduction du champ ne le portent pas.
        `"" != "1.1"` : ils doivent etre recalcules eux aussi, sinon le
        correctif ne toucherait que les bases recentes.
        """
        api = _api_avec_rapport(None)

        with _FFMPEG:
            resultat = get_perceptual_report(api, "run1", "r1")

        api._get_run.assert_called_once_with("run1")
        self.assertTrue(resultat.get("perceptual_engine_stale"))

    def test_le_repli_ne_transforme_pas_un_rapport_servi_en_ERREUR(self) -> None:
        """La regression que le correctif aurait introduite sans repli.

        Le recalcul est impossible ici (le plan mocke ne contient pas la ligne).
        Avant, l'utilisateur recevait un rapport ; il doit continuer a en
        recevoir un, avec son contenu intact et le drapeau qui dit sa
        peremption.
        """
        api = _api_avec_rapport("1.0")

        with _FFMPEG:
            resultat = get_perceptual_report(api, "run1", "r1")

        self.assertTrue(resultat["ok"])
        self.assertEqual(resultat["perceptual"]["global_score"], 80)
        self.assertEqual(resultat["perceptual"]["perceptual_engine_version_attendue"], PERCEPTUAL_ENGINE_VERSION)
        self.assertIn("version anterieure", resultat["message"])

    def test_force_ignore_le_cache_QUELLE_QUE_SOIT_la_version(self) -> None:
        """Le correctif ne doit pas rendre `force` inoperant sur un rapport a
        jour : c'est le seul moyen pour l'utilisateur de reanalyser.
        """
        api = _api_avec_rapport(PERCEPTUAL_ENGINE_VERSION)

        with _FFMPEG:
            get_perceptual_report(api, "run1", "r1", {"force": True})

        api._get_run.assert_called_once_with("run1")


if __name__ == "__main__":
    unittest.main()
