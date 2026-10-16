"""Basculer `scan_max_workers` sur « auto » ne remet plus la valeur manuelle a 1.

LE DEFAUT. `set_scan_max_workers_payload` ecrivait, dans les DEUX modes :

    data["scan_max_workers_value"] = _normalize_scan_max_workers_value(value)

Or `_applyScanMaxWorkers` (`web/dashboard/views/parametres.js`) ne transmet
`value` QUE pour le mode manuel :

    const payload = { mode: String(mode || "auto") };
    if (mode === "manual") payload.value = Number(value);

`value` valait donc `None` en mode auto, que le normalisateur rend `1`.

    reglage manuel 16 workers, puis bascule sur "auto"
      -> scan_max_workers_value : 16 -> 1
      -> retour en "manual" : le panneau affiche 1

La docstring du setter promettait pourtant « valeur conservee si presente et
valide » : elle decrivait une lecture de l'EXISTANT la ou le code lisait le
PARAMETRE. C'est la famille « une docstring qui decrit l'INVERSE du code ».

CE DEFAUT ETAIT MASQUE PAR UN AUTRE, ET C'EST CE QUI LE REND NOUVEAU. Avant
#1097, l'ecran Parametres rejouait `scan_max_workers_value` a chaque autosave
depuis son instantane d'ouverture : il restaurait donc la valeur ecrasee, par
accident. En retirant ce rejeu (`_CLES_POSSEDEES_AILLEURS`), #1097 a laisse
l'ecrasement visible. Le finding `t16sav03` du 2026-08-16 portait sur l'autre
mecanisme — le rejeu — et il est bien corrige ; celui-ci vit dans le backend.

CE QUE CES TESTS DISTINGUENT. Le silence de l'appelant et sa demande explicite :
une `value` fournie reste souveraine meme en mode auto, seul le silence fait
reprendre l'existant. Un correctif qui ignorerait `value` en mode auto serait
aussi faux que l'original.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.ui.api import settings_support


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_bascule_auto_")
        self.state_dir = Path(self._tmp.name)
        # Etat de depart : l'utilisateur a choisi 16 workers en manuel.
        rendu = settings_support.set_scan_max_workers_payload(self.state_dir, "manual", 16)
        # ANCRAGE. Sans cette assertion, « la valeur n'a pas ete perdue » ne
        # prouverait rien : il faut d'abord qu'elle ait ete posee.
        self.assertTrue(rendu.get("ok"), rendu)
        self.assertEqual(self._valeur_sur_disque(), 16, "la valeur manuelle de depart n'a pas ete persistee")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _valeur_sur_disque(self) -> int:
        """Relit par le code de PRODUCTION."""
        return int(settings_support.read_settings(self.state_dir).get("scan_max_workers_value") or 0)

    def _mode_sur_disque(self) -> str:
        return str(settings_support.read_settings(self.state_dir).get("scan_max_workers_mode") or "")


class LaBasculeEnAutoConserveLaValeurManuelleTests(_Base):
    """LE test de cette correction."""

    def test_passer_en_auto_sans_valeur_ne_remet_pas_a_1(self) -> None:
        rendu = settings_support.set_scan_max_workers_payload(self.state_dir, "auto")

        self.assertTrue(rendu.get("ok"))
        self.assertEqual(
            self._valeur_sur_disque(),
            16,
            "la bascule sur « auto » a remis la valeur manuelle a 1",
        )

    def test_le_payload_rendu_annonce_la_valeur_conservee(self) -> None:
        """L'ecran recopie `data.value` dans son etat : le payload doit etre juste.

        Sans ceci, le panneau afficherait 1 alors que le disque porte 16 — un
        ecart entre ce que l'application annonce et ce qu'elle a fait.
        """
        rendu = settings_support.set_scan_max_workers_payload(self.state_dir, "auto")

        self.assertEqual(rendu.get("value"), 16)

    def test_la_bascule_AGIT_bien_sur_le_mode(self) -> None:
        """ANCRAGE. Un setter devenu inerte rendrait les tests ci-dessus verts."""
        settings_support.set_scan_max_workers_payload(self.state_dir, "auto")

        self.assertEqual(self._mode_sur_disque(), "auto")

    def test_un_aller_retour_manuel_auto_manuel_preserve_la_valeur(self) -> None:
        """Le parcours reel de l'utilisateur qui essaie les deux modes."""
        settings_support.set_scan_max_workers_payload(self.state_dir, "auto")

        rendu = settings_support.get_scan_max_workers_payload(self.state_dir)

        self.assertEqual(rendu["value"], 16)
        self.assertEqual(rendu["mode"], "auto")


class UneValeurEXPLICITEResteSouveraineTests(_Base):
    """L'AUTRE SENS : ignorer `value` en mode auto serait aussi faux.

    Seul le SILENCE de l'appelant fait reprendre l'existant.
    """

    def test_une_valeur_fournie_en_mode_auto_est_ecrite(self) -> None:
        settings_support.set_scan_max_workers_payload(self.state_dir, "auto", 4)

        self.assertEqual(self._valeur_sur_disque(), 4)

    def test_une_valeur_hors_plage_fournie_en_mode_auto_est_clampee(self) -> None:
        """Le mode auto reste tolerant — c'est le mode manuel qui refuse."""
        settings_support.set_scan_max_workers_payload(self.state_dir, "auto", 999)

        self.assertEqual(self._valeur_sur_disque(), settings_support._SCAN_MAX_WORKERS_MAX)

    def test_un_booleen_est_traite_comme_un_silence(self) -> None:
        """`True` est un `int` en Python : le laisser passer donnerait 1 worker.

        C'est exactement la valeur que ce correctif existe pour ne plus ecrire
        par accident, donc le bool doit valoir silence, pas « 1 ».
        """
        settings_support.set_scan_max_workers_payload(self.state_dir, "auto", True)

        self.assertEqual(self._valeur_sur_disque(), 16)


class SansValeurPrealableLeDefautResteUnTests(unittest.TestCase):
    """Sur un etat vierge, la bascule en auto doit toujours rendre le defaut.

    La correction ne doit pas inventer de valeur quand il n'y en a jamais eu.
    """

    def test_etat_vierge_rend_le_defaut(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cinesort_bascule_vierge_") as tmp:
            state_dir = Path(tmp)

            rendu = settings_support.set_scan_max_workers_payload(state_dir, "auto")

            self.assertTrue(rendu.get("ok"))
            self.assertEqual(rendu.get("value"), settings_support._DEFAULT_SCAN_MAX_WORKERS_VALUE)


class LeModeManuelRefuseToujoursUneValeurAbsenteTests(_Base):
    """CONTRE-TEST : la correction ne doit pas assouplir le mode manuel.

    Le refus de `value` absente en manuel est delibere et documente sur place
    (« eviter qu'un payload UI casse retombe silencieusement sur 1 ») : reprendre
    l'existant la aussi aurait masque un client defectueux.
    """

    def test_manuel_sans_valeur_refuse_encore(self) -> None:
        rendu = settings_support.set_scan_max_workers_payload(self.state_dir, "manual")

        self.assertFalse(rendu.get("ok"))
        self.assertEqual(self._valeur_sur_disque(), 16, "un refus ne doit rien ecrire")

    def test_manuel_avec_valeur_hors_plage_refuse_encore(self) -> None:
        rendu = settings_support.set_scan_max_workers_payload(self.state_dir, "manual", 999)

        self.assertFalse(rendu.get("ok"))
        self.assertEqual(self._valeur_sur_disque(), 16)


if __name__ == "__main__":
    unittest.main()
