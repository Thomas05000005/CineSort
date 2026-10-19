"""Le TTL de quarantaine doit suivre le reglage COURANT, pas celui du boot.

`tests/test_zero_desactive_les_crons.py` a rendu la garde `days <= 0` du
demarreur ATTEIGNABLE — mais son perimetre est le SITE DE BOOT (`app.py`), et
sa docstring le dit : « le seul chemin qui relie le reglage a la garde ».

Il en restait un second, jamais eprouve : le cron tourne toutes les 24 h avec la
valeur capturee dans sa closure au demarrage. Un changement fait EN COURS DE
SESSION n'avait donc aucun effet avant le prochain lancement, alors que :

  - l'ecran annonce « 0 = désactivé » sans mentionner de redemarrage
    (`web/dashboard/views/parametres.js`, `min: 0`) ;
  - la sauvegarde PERSISTE bien l'entier 0 (`_save_section_advanced`, [0, 3650]) ;
  - `purge_review_bucket` sait deja rendre un no-op sur `days <= 0`.

Consequence : l'utilisateur qui desactive la purge pour garder ses fichiers, ou
qui allonge le TTL, voyait `_review/` purge a l'ANCIENNE valeur au cycle suivant
— des fichiers video, sur le SEUL chemin de suppression automatique du depot.

Ce fichier eprouve donc le CYCLE, pas la decision : les cas principaux passent
par `start_quarantine_ttl_cron`, dont `_worker` est le porteur du defaut. Un
test qui n'appellerait que `_ttl_du_cycle` resterait vert si l'appel disparaissait
du worker (piege documente dans `/CLAUDE.md`).
"""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from cinesort.app.quarantine_ttl import _ttl_du_cycle, start_quarantine_ttl_cron

#: Non nul, pour ne pas faire tourner le worker en boucle serree pendant le
#: `join`. La terminaison reste portee par la doublure (qui pose le stop), pas
#: par ce delai : le test n'est donc pas sensible au timing.
_INTERVALLE_TEST_S = 0.01


class _RunQuiEnregistre:
    """Doublure de `api.run` : journalise les appels, puis arme l'arret."""

    def __init__(self, appels: list, *, stop_apres: int = 2) -> None:
        self.appels = appels
        self.stop_apres = stop_apres
        self.au_premier_appel = None
        self.api = None  # pose par le test : la doublure doit voir le stop_event

    def purge_quarantine_bucket(self, ttl_days: int, dry_run: bool = True):
        self.appels.append((ttl_days, dry_run))
        if len(self.appels) == 1 and self.au_premier_appel is not None:
            self.au_premier_appel()
        if len(self.appels) >= self.stop_apres:
            stop = getattr(self.api, "_quarantine_ttl_stop", None)
            if isinstance(stop, threading.Event):
                stop.set()
        return {"ok": True, "deleted": 0}


class _BaseCycle(unittest.TestCase):
    """Outillage commun : monter un faux `api`, jouer deux cycles, tout arreter."""

    def _api(self, appels: list, etat: dict):
        """`api` complet : facade `run`, facade `settings` relue a chaque appel."""
        run = _RunQuiEnregistre(appels)
        api = SimpleNamespace(
            run=run,
            settings=SimpleNamespace(get_settings=lambda: dict(etat["settings"])),
            # Chaine vide : `start_quarantine_ttl_cron` saute alors
            # `register_runs_root`, dont l'etat est un global de module.
            _get_state_dir=lambda: "",
        )
        run.api = api
        return api

    def _jouer_deux_cycles(self, api, *, ttl_boot: int) -> None:
        thread = start_quarantine_ttl_cron(api, ttl_days=ttl_boot, initial_delay_s=0.0, interval_s=_INTERVALLE_TEST_S)
        self.assertIsNotNone(thread, "le cron doit demarrer pour un TTL de boot > 0")
        try:
            thread.join(timeout=30.0)
            self.assertFalse(
                thread.is_alive(),
                "le worker ne s'est pas arrete : la doublure n'a pas ete appelee deux fois",
            )
        finally:
            # Un thread daemon survivrait au test et degraderait la suite.
            stop = getattr(api, "_quarantine_ttl_stop", None)
            if isinstance(stop, threading.Event):
                stop.set()


class LeCycleRelitLeReglageTests(_BaseCycle):
    """Le cœur : ce que la batterie existante ne pouvait pas voir."""

    def test_un_zero_saisi_APRES_le_boot_desactive_des_le_cycle_suivant(self) -> None:
        """LE test. Sans le correctif : `[(30, False), (30, False)]`."""
        appels: list = []
        etat = {"settings": {"quarantaine_ttl_days": 30}}
        api = self._api(appels, etat)
        # L'utilisateur ouvre Parametres et saisit 0 pendant que le cron dort.
        api.run.au_premier_appel = lambda: etat.update(settings={"quarantaine_ttl_days": 0})

        self._jouer_deux_cycles(api, ttl_boot=30)

        self.assertEqual([(30, False), (0, False)], appels)

    def test_un_ttl_ALLONGE_apres_le_boot_est_pris_en_compte(self) -> None:
        """L'autre direction : le defaut ne portait pas que sur la desactivation.

        Sans ce cas, un correctif qui ne traiterait que le zero satisferait le
        test precedent en laissant le defaut entier.
        """
        appels: list = []
        etat = {"settings": {"quarantaine_ttl_days": 30}}
        api = self._api(appels, etat)
        api.run.au_premier_appel = lambda: etat.update(settings={"quarantaine_ttl_days": 365})

        self._jouer_deux_cycles(api, ttl_boot=30)

        self.assertEqual([(30, False), (365, False)], appels)

    def test_un_reglage_inchange_ne_change_rien(self) -> None:
        """CONTRE-EPREUVE : le cas nominal est stable.

        Sans elle, « le cron relit » serait satisfait par un cron qui rendrait
        n'importe quoi.
        """
        appels: list = []
        etat = {"settings": {"quarantaine_ttl_days": 45}}

        self._jouer_deux_cycles(self._api(appels, etat), ttl_boot=45)

        self.assertEqual([(45, False), (45, False)], appels)

    def test_la_suppression_reste_EXPLICITE_apres_relecture(self) -> None:
        """`dry_run=False` est l'autre moitie de l'invariant du cron.

        Le defaut de la facade est `dry_run=True` (un POST au corps vide ne doit
        rien supprimer). Le cron est le seul appelant dont le travail EST de
        supprimer : relire le TTL ne doit pas le rendre inoffensif.
        """
        appels: list = []
        etat = {"settings": {"quarantaine_ttl_days": 30}}

        self._jouer_deux_cycles(self._api(appels, etat), ttl_boot=30)

        self.assertTrue(appels, "aucun cycle joue")
        for _ttl, dry_run in appels:
            self.assertFalse(dry_run, "le cron doit demander la suppression explicitement")


class LeRepliProtegeLExistantTests(_BaseCycle):
    """Un `api` sans facade `settings` se comporte exactement comme avant.

    C'est ce qui garantit que le correctif n'ETEINT rien : les doublures des
    batteries existantes (`test_quarantaine_ttl_v77`, `test_purge_dry_run_par_
    defaut`) sont des `SimpleNamespace(run=...)`, sans `.settings`.
    """

    def test_sans_facade_settings_le_ttl_du_boot_est_conserve(self) -> None:
        appels: list = []
        run = _RunQuiEnregistre(appels)
        api = SimpleNamespace(run=run, _get_state_dir=lambda: "")
        run.api = api

        self._jouer_deux_cycles(api, ttl_boot=15)

        self.assertEqual([(15, False), (15, False)], appels)


class TtlDuCycleTests(unittest.TestCase):
    """Les cas limites de la lecture elle-meme.

    Meme semantique qu'`app.reglage_entier` : seul le zero EXPLICITE est
    preserve ; absent, vide et illisible retombent sur le defaut du boot.
    """

    @staticmethod
    def _api(valeur, *, present: bool = True):
        payload = {"quarantaine_ttl_days": valeur} if present else {}
        return SimpleNamespace(settings=SimpleNamespace(get_settings=lambda: payload))

    def test_zero_explicite_est_preserve(self) -> None:
        self.assertEqual(0, _ttl_du_cycle(self._api(0), 30))

    def test_valeur_normale_est_lue(self) -> None:
        self.assertEqual(45, _ttl_du_cycle(self._api(45), 30))
        self.assertEqual(45, _ttl_du_cycle(self._api("45"), 30))

    def test_absent_retombe_sur_le_defaut_du_boot(self) -> None:
        self.assertEqual(30, _ttl_du_cycle(self._api(None, present=False), 30))
        self.assertEqual(30, _ttl_du_cycle(self._api(None), 30))

    def test_vide_retombe_sur_le_defaut_du_boot(self) -> None:
        self.assertEqual(30, _ttl_du_cycle(self._api("   "), 30))

    def test_valeur_illisible_ne_vaut_JAMAIS_zero(self) -> None:
        """Une valeur corrompue ne doit pas DESACTIVER une purge active.

        Meme arbitrage que `test_valeur_illisible_retombe_sur_le_defaut` dans
        `test_zero_desactive_les_crons.py` : l'erreur va vers « on garde le
        comportement que l'utilisateur a choisi », jamais vers un silence.
        """
        for pourri in ("abc", [], {}, object()):
            with self.subTest(valeur=pourri):
                self.assertEqual(30, _ttl_du_cycle(self._api(pourri), 30))

    def test_une_facade_qui_leve_retombe_sur_le_defaut(self) -> None:
        """Le cron ne doit pas mourir : sa mort = quarantaine non bornee."""

        def _boom():
            raise RuntimeError("settings indisponibles")

        api = SimpleNamespace(settings=SimpleNamespace(get_settings=_boom))
        self.assertEqual(30, _ttl_du_cycle(api, 30))

    def test_un_retour_non_dict_retombe_sur_le_defaut(self) -> None:
        api = SimpleNamespace(settings=SimpleNamespace(get_settings=lambda: ["pas", "un", "dict"]))
        self.assertEqual(30, _ttl_du_cycle(api, 30))


if __name__ == "__main__":
    unittest.main()
