"""Gardes sur `scripts/i18n_full_sync.py` — un muteur du depot sans filet.

Le script mute des fichiers SUIVIS puis s'interrompt en cours de route. Sequence
d'origine : `FR_PATH.write_text` et `EN_PATH.write_text` reecrivent les deux
locales, `patch_login_js()` reecrit `login.js`, puis `patch_plex_js()` fait
`path.read_text()` sur `web/dashboard/views/plex.js` — **qui n'existe pas**
(mesure 2026-08-31 : le dossier des vues ne contient ni `plex.js` ni
`radarr.js`). `FileNotFoundError` remonte. Trois fichiers du depot ont deja
change, le test de parite annonce a l'etape 4 n'est jamais ecrit, et rien ne
revient en arriere : ni `--dry-run`, ni sauvegarde, ni transaction.

La commande documentee en tete du script (`python scripts/i18n_full_sync.py`)
plante donc TOUJOURS, apres avoir modifie le depot.

Ce que les tests exigent :

1. **Une cible manquante se voit AVANT toute ecriture.** Le script doit refuser
   de commencer et laisser le depot BIT POUR BIT identique.
2. **`--dry-run` existe** et n'ecrit rien.
3. **Un echec en cours d'application defait ce qui a deja ete ecrit** — une
   ecriture partielle est le pire des trois etats possibles.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "i18n_full_sync.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_i18n_full_sync_ut", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNC = _load_script()

_LOGIN_JS = 'import { navigateTo } from "../core/router.js";\nexport function x() { return "Connexion refusee."; }\n'


class _FauxDepot:
    """Un depot minimal : deux locales, le dossier des vues, le dossier tests."""

    def __init__(self, avec_plex_et_radarr: bool) -> None:
        self.root = Path(tempfile.mkdtemp())
        (self.root / "locales").mkdir()
        (self.root / "tests").mkdir()
        views = self.root / "web" / "dashboard" / "views"
        views.mkdir(parents=True)
        self.en = self.root / "locales" / "en.json"
        self.fr = self.root / "locales" / "fr.json"
        # EN porte une cle que FR n'a pas : le script a donc du travail a faire.
        self.en.write_text(json.dumps({"common": {"all": "All", "apply": "Apply"}}, indent=2) + "\n", encoding="utf-8")
        self.fr.write_text(json.dumps({"common": {"all": "Tout"}}, indent=2) + "\n", encoding="utf-8")
        (views / "login.js").write_text(_LOGIN_JS, encoding="utf-8")
        if avec_plex_et_radarr:
            for nom in ("plex.js", "radarr.js"):
                (views / nom).write_text("// vue\n", encoding="utf-8")
        self.views = views

    def empreinte(self) -> dict[str, bytes]:
        """Contenu BINAIRE de chaque fichier suivi — la seule preuve honnete."""
        return {
            str(p.relative_to(self.root).as_posix()): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def patch(self):
        return mock.patch.multiple(
            SYNC,
            ROOT=self.root,
            EN_PATH=self.en,
            FR_PATH=self.fr,
            VIEWS_DIR=self.views,
            TESTS_DIR=self.root / "tests",
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class CibleManquanteTests(unittest.TestCase):
    """Une vue absente doit etre vue AVANT la premiere ecriture."""

    def setUp(self) -> None:
        self.depot = _FauxDepot(avec_plex_et_radarr=False)
        self.addCleanup(self.depot.cleanup)

    def test_le_depot_est_intact_quand_une_vue_cible_manque(self) -> None:
        avant = self.depot.empreinte()
        with self.depot.patch():
            try:
                code = SYNC.main([])
            except FileNotFoundError as exc:
                self.fail(
                    "Le script s'interrompt en cours de route sur une cible absente "
                    f"({exc}) : les ecritures deja faites restent en place."
                )
        self.assertNotEqual(code, 0, "Une cible manquante doit produire un code de sortie non nul.")
        self.assertEqual(
            self.depot.empreinte(),
            avant,
            "Le depot a ete modifie alors que le script ne pouvait pas aller au bout : "
            "les locales et login.js sont reecrits AVANT que l'absence de plex.js "
            "ne soit decouverte.",
        )

    def test_le_rapport_nomme_les_cibles_absentes(self) -> None:
        with self.depot.patch(), mock.patch("builtins.print") as faux_print:
            SYNC.main([])
        sortie = " ".join(str(appel.args[0]) for appel in faux_print.call_args_list if appel.args)
        for attendu in ("plex.js", "radarr.js"):
            self.assertIn(attendu, sortie, f"Le rapport ne nomme pas la cible absente {attendu}.")


class DryRunTests(unittest.TestCase):
    """`--dry-run` doit exister et ne rien ecrire."""

    def setUp(self) -> None:
        self.depot = _FauxDepot(avec_plex_et_radarr=True)
        self.addCleanup(self.depot.cleanup)

    def test_dry_run_n_ecrit_rien(self) -> None:
        avant = self.depot.empreinte()
        with self.depot.patch():
            code = SYNC.main(["--dry-run"])
        self.assertEqual(code, 0, "Un dry-run sur un depot complet doit reussir.")
        self.assertEqual(
            self.depot.empreinte(),
            avant,
            "--dry-run a modifie le depot.",
        )

    def test_sans_dry_run_le_depot_complet_est_bien_mute(self) -> None:
        """Contre-test : le script doit continuer a faire son travail."""
        avant = self.depot.empreinte()
        with self.depot.patch():
            code = SYNC.main([])
        self.assertEqual(code, 0)
        apres = self.depot.empreinte()
        self.assertNotEqual(apres, avant, "Le script n'a plus aucun effet.")
        self.assertIn("tests/test_phase6_i18n_parity.py", apres, "Le test de parite n'a pas ete cree.")
        fr = json.loads(self.depot.fr.read_text(encoding="utf-8"))
        self.assertEqual(fr["common"]["apply"], "Appliquer", "La cle FR manquante n'a pas ete ajoutee.")


class TransactionTests(unittest.TestCase):
    """Un echec pendant l'application doit defaire les ecritures deja passees."""

    def setUp(self) -> None:
        self.depot = _FauxDepot(avec_plex_et_radarr=True)
        self.addCleanup(self.depot.cleanup)

    def test_un_echec_a_mi_parcours_restaure_tout(self) -> None:
        avant = self.depot.empreinte()
        vraie_ecriture = SYNC._ecrire_fichier
        appels = {"n": 0}

        def echoue_au_troisieme(path: Path, texte: str) -> None:
            appels["n"] += 1
            if appels["n"] == 3:
                raise OSError("disque plein (simule)")
            vraie_ecriture(path, texte)

        with self.depot.patch(), mock.patch.object(SYNC, "_ecrire_fichier", echoue_au_troisieme):
            code = SYNC.main([])
        self.assertNotEqual(code, 0, "Un echec d'ecriture doit produire un code non nul.")
        self.assertEqual(
            self.depot.empreinte(),
            avant,
            "Une ecriture a echoue a mi-parcours et les precedentes sont restees : "
            "le depot est dans un etat mixte, ni avant ni apres.",
        )


if __name__ == "__main__":
    unittest.main()
