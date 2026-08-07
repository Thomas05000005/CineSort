"""Un POST au corps VIDE ne doit pas effacer la bibliotheque de l'utilisateur.

La regle n3 du depot — « confirmation avec la liste des elements, la
consequence, et 3 s au-dela de 50 » — est appliquee par `dangerConfirmModal`,
DANS LE FRONTEND UNIQUEMENT. Or toute methode de facade est atteignable en
`POST /api/<facade>/<methode>` : un appel REST direct ne traverse aucune modale.

CE QUI A ETE MESURE AVANT DE CODER (issue #997). Sur les 12 methodes
destructives sans garde-fou, **6 seulement agissent sur un corps vide** ; les
6 autres exigent un identifiant (`run_id`, `playlist_id`, `film_id`...) et
echouent donc deja sans effet. Leur imposer une ceremonie ne protegerait de
rien. Le perimetre reel est donc :

    settings.reset_database        AGIT sur corps vide   IRREVERSIBLE
    settings.reset_settings        AGIT sur corps vide   IRREVERSIBLE
    quality.reset_quality_profile  AGIT sur corps vide   recuperable
    runtime.clear_notifications    AGIT sur corps vide   cache
    runtime.purge_probe_cache      AGIT sur corps vide   cache
    runtime.reset_incremental_cache AGIT sur corps vide  cache

Les trois premieres basculent a `dry_run=True` par defaut. Les trois caches
sont laisses tels quels : les purger ne perd aucune donnee de l'utilisateur,
et une confirmation y userait le reflexe de confirmation exactement la ou il
ne doit pas s'user.

CE QUE CE CORRECTIF NE FAIT PAS : rendre la reinitialisation impossible. Le
bouton « Zone de danger » des parametres fonctionne exactement comme avant — il
dit maintenant `dry_run: false`, ce qu'il faisait implicitement.
"""

from __future__ import annotations

import inspect
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.ui.api import quality_profile_support, reset_support
from cinesort.ui.api.facades.quality_facade import QualityFacade
from cinesort.ui.api.facades.settings_facade import SettingsFacade


class LesDefautsDeFacadePREVISUALISENTTests(unittest.TestCase):
    """Le defaut de signature est la premiere ligne de defense : c'est lui qui
    decide de ce que fait un POST au corps vide."""

    def test_reset_database_previsualise_par_defaut(self) -> None:
        defaut = inspect.signature(SettingsFacade.reset_database).parameters["dry_run"].default

        self.assertIs(defaut, True, "un POST au corps vide EFFACE toute la bibliotheque")

    def test_reset_settings_previsualise_par_defaut(self) -> None:
        defaut = inspect.signature(SettingsFacade.reset_settings).parameters["dry_run"].default

        self.assertIs(defaut, True, "un POST au corps vide reinitialise TOUS les reglages")

    def test_reset_quality_profile_previsualise_par_defaut(self) -> None:
        defaut = inspect.signature(QualityFacade.reset_quality_profile).parameters["dry_run"].default

        self.assertIs(defaut, True, "un POST au corps vide ecrase le profil de scoring")


class LaFacadeTRANSMETLeChoixTests(unittest.TestCase):
    """La chaine complete doit porter le choix, pas seulement le defaut.

    CE BLOC EXISTE PARCE QUE LA MUTATION DU SITE D'APPEL A REVELE UN TROU. Les
    tests qui n'eprouvent que `reset_support` restent TOUS VERTS si la facade
    cesse de transmettre `dry_run` — le support retombe alors sur son propre
    defaut (`True`), et l'utilisateur qui demande une suppression REELLE obtient
    un apercu. Echec silencieux : `ok=True`, et rien n'est efface.

    C'est la regle « muter le SITE D'APPEL separement » : un test qui eprouve la
    fonction laisse survivre la mutation qui retire son appel.
    """

    def _facade_settings(self, recu: list) -> SettingsFacade:
        api = SimpleNamespace(
            _reset_database_impl=lambda **kw: recu.append(("db", kw)) or {"ok": True},
            _reset_settings_impl=lambda scope, **kw: recu.append(("settings", scope, kw)) or {"ok": True},
        )
        return SettingsFacade(api)

    def test_reset_database_transmet_dry_run_FALSE(self) -> None:
        recu: list = []

        self._facade_settings(recu).reset_database(dry_run=False)

        self.assertEqual(recu, [("db", {"dry_run": False})], "la facade a perdu le choix en route")

    def test_reset_database_transmet_aussi_le_defaut(self) -> None:
        recu: list = []

        self._facade_settings(recu).reset_database()

        self.assertEqual(recu, [("db", {"dry_run": True})])

    def test_reset_settings_transmet_dry_run_ET_le_scope(self) -> None:
        recu: list = []

        self._facade_settings(recu).reset_settings("apparence", dry_run=False)

        self.assertEqual(recu, [("settings", "apparence", {"dry_run": False})])

    def test_reset_quality_profile_transmet_dry_run_FALSE(self) -> None:
        recu: list = []
        api = SimpleNamespace(_reset_quality_profile_impl=lambda **kw: recu.append(kw) or {"ok": True})

        QualityFacade(api).reset_quality_profile(dry_run=False)

        self.assertEqual(recu, [{"dry_run": False}], "la facade qualite a perdu le choix en route")


class LApercuNeTOUCHERienSurDisqueTests(unittest.TestCase):
    """La preuve qui compte : on regarde le DISQUE, pas la valeur de retour.

    Une implementation qui rendrait `dry_run: True` tout en supprimant quand
    meme passerait un test qui n'assert que sur le payload.
    """

    def setUp(self) -> None:
        # Le chemin de la base vient de `db_path_for_state_dir`, PAS d'une
        # convention devinee : une version anterieure de `_resolve_db_path`
        # cherchait `state_dir/cinesort.db` alors que la vraie base est
        # `state_dir/db/cinesort.sqlite` — `exists()` etait donc toujours False
        # et le wipe promis par l'UI ne se produisait JAMAIS, sans erreur
        # visible. Coder le chemin en dur ici rejouerait exactement ce piege.
        from cinesort.infra.db import db_path_for_state_dir

        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_reset_dry_"))
        self.db = Path(db_path_for_state_dir(self._tmp))
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.db.write_bytes(b"SQLite format 3\x00" + b"x" * 500)
        self.api = SimpleNamespace(_get_state_dir=lambda: str(self._tmp))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_l_apercu_laisse_la_base_INTACTE(self) -> None:
        """Le coeur du correctif."""
        taille_avant = self.db.stat().st_size

        res = reset_support.reset_database(self.api)

        self.assertTrue(res.get("ok"))
        self.assertIs(res.get("dry_run"), True)
        self.assertTrue(self.db.is_file(), "la base a ete SUPPRIMEE par un apercu")
        self.assertEqual(self.db.stat().st_size, taille_avant)

    def test_l_apercu_annonce_la_taille_reelle(self) -> None:
        """Un apercu qui ne dit rien de ce qu'il detruirait ne sert a rien."""
        res = reset_support.reset_database(self.api)

        self.assertEqual(res.get("db_size_bytes"), self.db.stat().st_size)
        self.assertIn("db", str(res.get("backup_dir", "")))

    def test_l_apercu_n_ecrit_AUCUN_fichier(self) -> None:
        """Contre-epreuve : creer le dossier de sauvegarde serait deja une
        ecriture. Un apercu ne touche pas le disque."""
        avant = sorted(p.relative_to(self._tmp).as_posix() for p in self._tmp.rglob("*"))

        reset_support.reset_database(self.api)

        apres = sorted(p.relative_to(self._tmp).as_posix() for p in self._tmp.rglob("*"))
        self.assertEqual(apres, avant, "l'apercu a modifie l'arborescence sur disque")

    def test_dry_run_FALSE_supprime_toujours(self) -> None:
        """Contre-epreuve indispensable : basculer le defaut ne doit pas rendre
        la reinitialisation inoperante — sinon le correctif casse la fonction
        qu'il protege."""
        res = reset_support.reset_database(self.api, dry_run=False)

        self.assertTrue(res.get("ok"), f"la suppression reelle a echoue : {res}")
        self.assertIs(res.get("dry_run"), False)
        self.assertFalse(self.db.is_file(), "la base n'a PAS ete supprimee")
        self.assertTrue(Path(res["backup_path"]).is_file(), "aucune sauvegarde ecrite")


class LApercuDesReglagesNeSAUVEGARDEPasTests(unittest.TestCase):
    def _api(self, sauvegardes: list) -> SimpleNamespace:
        return SimpleNamespace(
            settings=SimpleNamespace(
                get_settings=lambda: {"root": "D:/Films", "locale": "fr"},
                save_settings=lambda payload: sauvegardes.append(payload),
            ),
        )

    def test_l_apercu_n_appelle_PAS_save_settings(self) -> None:
        sauvegardes: list = []

        res = reset_support.reset_settings(self._api(sauvegardes))

        self.assertTrue(res.get("ok"))
        self.assertIs(res.get("dry_run"), True)
        self.assertEqual(sauvegardes, [], "les reglages ont ete ECRASES par un apercu")

    def test_l_apercu_annonce_les_cles_qui_SERAIENT_remises_a_zero(self) -> None:
        res = reset_support.reset_settings(self._api([]))

        self.assertTrue(res.get("reset_keys"), "l'apercu ne dit pas ce qu'il remettrait a zero")

    def test_dry_run_FALSE_sauvegarde_toujours(self) -> None:
        sauvegardes: list = []

        res = reset_support.reset_settings(self._api(sauvegardes), dry_run=False)

        self.assertTrue(res.get("ok"), f"echec : {res}")
        self.assertIs(res.get("dry_run"), False)
        self.assertEqual(len(sauvegardes), 1, "la reinitialisation reelle n'a rien ecrit")

    def test_un_scope_INVALIDE_est_refuse_AVANT_meme_l_apercu(self) -> None:
        """La validation ne doit pas etre court-circuitee par le mode apercu."""
        res = reset_support.reset_settings(self._api([]), scope="n-existe-pas")

        self.assertFalse(res.get("ok", True))


class LApercuDuProfilQualiteNEcritPasTests(unittest.TestCase):
    def test_l_apercu_n_appelle_PAS_la_sauvegarde(self) -> None:
        ecrits: list = []
        api = SimpleNamespace(_save_active_quality_profile=lambda p: ecrits.append(p) or {})

        res = quality_profile_support.reset_quality_profile(api)

        self.assertTrue(res.get("ok"))
        self.assertIs(res.get("dry_run"), True)
        self.assertEqual(ecrits, [], "le profil a ete ECRASE par un apercu")
        self.assertTrue(res.get("profile"), "l'apercu ne montre pas le profil qu'il appliquerait")

    def test_dry_run_FALSE_ecrit_toujours(self) -> None:
        ecrits: list = []
        api = SimpleNamespace(_save_active_quality_profile=lambda p: (ecrits.append(p), {})[1])

        res = quality_profile_support.reset_quality_profile(api, dry_run=False)

        self.assertTrue(res.get("ok"), f"echec : {res}")
        self.assertEqual(len(ecrits), 1, "la reinitialisation reelle n'a rien ecrit")


if __name__ == "__main__":
    unittest.main()
