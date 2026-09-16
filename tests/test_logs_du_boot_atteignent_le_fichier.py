"""Ce que le boot CONFIGURE pour les logs doit atteindre le FICHIER de log.

Deux defauts de la meme forme, mesures le 2026-09-16 : une valeur de logging
est posee au boot **avant** que sa cible existe ou que sa vraie valeur soit
connue, et plus personne ne la reprend ensuite.

1. **Le niveau choisi par l'utilisateur n'atteignait pas le fichier.**
   Les deux chemins de boot d'`app.py` font, dans cet ordre :

       boot_level = resolve_log_level(None)         # settings.json PAS lu
       install_rotating_log(..., level=boot_level)  # handler.setLevel(INFO)
       ...
       effective_level = resolve_log_level(settings.get("log_level"))
       logging.getLogger().setLevel(effective_level)    # le ROOT seul bouge

   Un handler filtre pour son propre compte (`record.levelno >= handler.level`),
   donc le fichier restait a INFO pendant que le root passait a DEBUG. Le
   bundle est construit SANS console : `cinesort.log` est le seul canal, et
   c'est celui que la visionneuse de Diagnostics lit
   (`runtime_support._logs_dir`). Choisir « DEBUG » dans Parametres > Logs ne
   produisait donc AUCUNE ligne de plus, nulle part — pas meme apres
   redemarrage.

2. **L'anti-spam d'exceptions repetees (Vague H) n'etait attache a aucun
   handler.** `install_repeated_exception_dedup` court-circuitait sur son
   drapeau, et `main_api` l'appelait AVANT `basicConfig` et
   `install_rotating_log` : le filtre n'atteignait que le root LOGGER, ou il ne
   voit rien — un filtre de logger ne s'applique PAS aux records propages
   depuis un logger enfant. Comme aucun module de `cinesort/` ne logge
   directement sur le root (mesure du 2026-09-16 : 0 occurrence de
   `logging.exception(...)` hors `logger = getLogger(__name__)`), il ne pouvait
   filtrer aucun record. Le mode BUREAU, lui — celui de l'EXE distribue — ne
   l'appelait pas du tout, alors que la docstring de la fonction prescrit
   « app.py:main / app.py:main_api ».

   Le depot connaissait deja ce mecanisme : `install_global_scrubber` a perdu
   son court-circuit le 2026-06-10 pour cette raison exacte, et
   `attach_filter_to_handler` existe pour la meme raison. Deux des trois
   filtres du fichier de log etaient couverts ; le troisieme manquait.

Les classes de comportement ci-dessous eprouvent le MECANISME ; la derniere
eprouve les SITES D'APPEL, parce qu'un correctif pose d'un seul cote est le
defaut n°2 lui-meme.
"""

from __future__ import annotations

import ast
import contextlib
import logging
import logging.handlers
import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.infra import log_context as _log_context
from cinesort.infra.log_context import (
    RepeatedExceptionDedupFilter,
    install_repeated_exception_dedup,
)
from cinesort.infra.log_scrubber import (
    install_rotating_log,
    reset_for_tests,
    set_rotating_log_level,
)

_RACINE = Path(__file__).resolve().parents[1]

#: Les DEUX chemins de demarrage. `main_api` sert `--api` (sans interface) ;
#: `main` est celui du bundle distribue. Ce sont les noms que
#: `test_zero_desactive_les_crons.py` utilise deja pour le meme controle.
_CHEMINS_DE_BOOT = ("main_api", "main")

#: Ce que CHAQUE chemin de boot doit appeler pour que la configuration de
#: logging atteigne le fichier.
_APPELS_REQUIS = ("install_rotating_log", "install_repeated_exception_dedup", "set_rotating_log_level")


class _BaseLogTests(unittest.TestCase):
    """Isolation : handlers ajoutes retires, niveau du root restaure."""

    def setUp(self) -> None:
        reset_for_tests()
        _log_context.reset_for_tests()
        self._tmp = tempfile.mkdtemp(prefix="cinesort_logboot_")
        self.log_dir = Path(self._tmp) / "logs"
        self._root = logging.getLogger()
        self._handlers_initiaux = list(self._root.handlers)
        self._niveau_initial = self._root.level
        self._filtres_initiaux = list(self._root.filters)

    def tearDown(self) -> None:
        for h in list(self._root.handlers):
            if h not in self._handlers_initiaux:
                self._root.removeHandler(h)
                with contextlib.suppress(Exception):
                    h.close()
        for f in list(self._root.filters):
            if f not in self._filtres_initiaux:
                self._root.removeFilter(f)
        # `install_repeated_exception_dedup` attache aussi son filtre aux
        # handlers PREEXISTANTS du root (ceux du runner). Sans ce retrait, il
        # survivrait au test et rate-limiterait les exceptions de ses voisins —
        # exactement le genre de fuite inter-tests que ce depot a deja paye.
        for h in self._handlers_initiaux:
            for f in list(h.filters):
                if isinstance(f, RepeatedExceptionDedupFilter):
                    h.removeFilter(f)
        self._root.setLevel(self._niveau_initial)
        shutil.rmtree(self._tmp, ignore_errors=True)
        reset_for_tests()
        _log_context.reset_for_tests()

    def _handler_du_fichier(self, chemin: Path) -> logging.Handler:
        """Le handler pose par CE test, repere par son fichier.

        Pas `handlers[0]` : la suite complete peut laisser un handler residuel
        d'un test precedent (piege deja documente dans `test_log_scrubber.py`).
        """
        cible = str(chemin).lower()
        notres = [
            h
            for h in self._root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
            and getattr(h, "baseFilename", "").lower() == cible
        ]
        self.assertEqual(len(notres), 1, f"handler introuvable parmi {self._root.handlers}")
        return notres[0]

    def _contenu(self, chemin: Path) -> str:
        for h in self._root.handlers:
            with contextlib.suppress(Exception):
                h.flush()
        return chemin.read_text(encoding="utf-8", errors="replace")


class LeNiveauDuFichierSuitLeReglageTests(_BaseLogTests):
    """Defaut n°1 — le handler de fichier garde le niveau du boot."""

    def test_le_handler_filtre_pour_son_propre_compte(self) -> None:
        """CARACTERISATION du mecanisme : vrai avant comme apres le correctif.

        Il ne prouve pas le correctif, il prouve pourquoi il est necessaire —
        remonter le ROOT ne suffit pas, le handler a son propre seuil. Sans ce
        constat, « il suffit de changer le niveau du logger » reste plausible.
        """
        chemin = install_rotating_log(self.log_dir, level=logging.INFO)
        self.assertIsNotNone(chemin)
        self._root.setLevel(logging.DEBUG)  # exactement ce que fait app.py

        logging.getLogger("cinesort.test.boot").debug("sentinelle-rejetee-par-le-handler")

        self.assertNotIn("sentinelle-rejetee-par-le-handler", self._contenu(chemin))
        self.assertEqual(logging.INFO, self._handler_du_fichier(chemin).level)

    def test_le_reglage_atteint_le_fichier_apres_set_rotating_log_level(self) -> None:
        """Le correctif : la sequence REELLE du boot, dans son ordre."""
        chemin = install_rotating_log(self.log_dir, level=logging.INFO)
        self.assertIsNotNone(chemin)
        self._root.setLevel(logging.DEBUG)

        self.assertTrue(set_rotating_log_level(logging.DEBUG))
        logging.getLogger("cinesort.test.boot").debug("sentinelle-arrivee-au-fichier")

        self.assertIn("sentinelle-arrivee-au-fichier", self._contenu(chemin))

    def test_un_niveau_plus_haut_est_honore_lui_aussi(self) -> None:
        """CONTRE-EPREUVE : la fonction ne fait pas qu'« ouvrir en grand ».

        Un correctif qui mettrait le handler a NOTSET passerait le test
        precedent et casserait celui-ci : l'utilisateur qui choisit ERROR ne
        doit plus voir ses WARNING dans le fichier.
        """
        chemin = install_rotating_log(self.log_dir, level=logging.INFO)
        self.assertIsNotNone(chemin)
        self._root.setLevel(logging.DEBUG)

        set_rotating_log_level(logging.ERROR)
        journal = logging.getLogger("cinesort.test.boot")
        journal.warning("sentinelle-sous-le-seuil")
        journal.error("sentinelle-au-dessus-du-seuil")

        contenu = self._contenu(chemin)
        self.assertNotIn("sentinelle-sous-le-seuil", contenu)
        self.assertIn("sentinelle-au-dessus-du-seuil", contenu)

    def test_sans_handler_installe_la_fonction_le_dit_au_lieu_de_lever(self) -> None:
        """Mode test, echec d'install disque : l'appelant n'a rien a gerer."""
        self.assertFalse(set_rotating_log_level(logging.DEBUG))


class LAntiSpamAtteintLesHandlersTests(_BaseLogTests):
    """Defaut n°2 — le filtre Vague H n'etait attache a aucun handler."""

    def test_un_handler_cree_APRES_le_premier_appel_recoit_le_filtre(self) -> None:
        """LE test qui separe : c'est la SEQUENCE du boot qui etait fautive.

        Avant le correctif, le second appel court-circuitait sur
        `_DEDUP_INSTALLED` et le handler ne recevait jamais le filtre.
        """
        install_repeated_exception_dedup(max_per_minute=5)  # aucun handler encore

        chemin = install_rotating_log(self.log_dir, level=logging.INFO)
        self.assertIsNotNone(chemin)
        handler = self._handler_du_fichier(chemin)
        self.assertFalse(
            any(isinstance(f, RepeatedExceptionDedupFilter) for f in handler.filters),
            "pre-condition : le handler vient d'etre cree, il ne peut pas deja porter le filtre",
        )

        install_repeated_exception_dedup(max_per_minute=5)  # re-synchronisation

        self.assertTrue(
            any(isinstance(f, RepeatedExceptionDedupFilter) for f in handler.filters),
            "le filtre anti-spam n'atteint pas le fichier de log : une exception en boucle "
            "y ecrit sans limite et fait tourner la rotation, qui efface les logs utiles.",
        )

    def test_le_filtre_n_est_pas_duplique_sur_le_root(self) -> None:
        """CONTRE-EPREUVE : retirer le court-circuit ne doit pas empiler.

        L'idempotence reelle tient aux `if not any(...)`, pas au drapeau — c'est
        ce que `test_vague_h_logging.py` eprouve deja sur le root logger ; ici
        on l'exige aussi apres l'ajout d'un handler entre deux appels.
        """
        avant = sum(isinstance(f, RepeatedExceptionDedupFilter) for f in self._root.filters)
        install_repeated_exception_dedup(max_per_minute=5)
        install_rotating_log(self.log_dir, level=logging.INFO)
        install_repeated_exception_dedup(max_per_minute=5)
        install_repeated_exception_dedup(max_per_minute=5)

        apres = sum(isinstance(f, RepeatedExceptionDedupFilter) for f in self._root.filters)
        self.assertEqual(1, apres - avant)

    def test_un_filtre_de_logger_seul_ne_voit_pas_les_records_propages(self) -> None:
        """CARACTERISATION : pourquoi le root logger ne suffisait pas.

        C'est la propriete que le depot a deja payee pour le scrubber (AUDIT
        2026-06-10) et qui justifie `attach_filter_to_handler`. Sans elle,
        « le filtre est sur le root, donc il filtre » reste plausible.
        """
        vus: list[str] = []

        class _Mouchard(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
                vus.append(record.getMessage())
                return True

        mouchard = _Mouchard()
        self._root.addFilter(mouchard)
        self._root.setLevel(logging.DEBUG)
        try:
            logging.getLogger("cinesort.test.enfant").warning("record-propage")
        finally:
            self._root.removeFilter(mouchard)

        self.assertEqual([], vus, "un filtre de LOGGER ne voit pas les records propages d'un enfant")


class LesDeuxCheminsDeBootConfigurentLeFichierTests(unittest.TestCase):
    """Les SITES D'APPEL — statique, parce que le defaut vit dans `app.py`.

    Instrumenter le boot demanderait de demarrer l'application entiere (serveur
    REST, crons, effets sur la bibliotheque REELLE). Le cliquet est donc pose a
    l'AST, comme `test_zero_desactive_les_crons.py` pour les crons destructifs.
    """

    @staticmethod
    def _appels_par_fonction() -> dict[str, dict[str, int]]:
        """{fonction: {nom_appele: premiere ligne}}, fonction la plus INTERNE.

        L'attribution a la plus interne compte : `main` contient `_startup` et
        `_on_main_loaded`, qu'un simple `ast.walk` confondrait avec elle.
        """
        arbre = ast.parse((_RACINE / "app.py").read_text(encoding="utf-8", errors="replace"))
        porteur: dict[int, str] = {}
        for fonction in ast.walk(arbre):
            if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for noeud in ast.walk(fonction):
                if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name):
                    # `ast.walk` va du plus externe au plus imbrique : la
                    # derniere fonction vue pour ce noeud est la plus interne.
                    porteur[id(noeud)] = fonction.name

        resultat: dict[str, dict[str, int]] = {}
        for fonction in ast.walk(arbre):
            if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for noeud in ast.walk(fonction):
                if (
                    isinstance(noeud, ast.Call)
                    and isinstance(noeud.func, ast.Name)
                    and porteur.get(id(noeud)) == fonction.name
                ):
                    vus = resultat.setdefault(fonction.name, {})
                    vus.setdefault(noeud.func.id, noeud.lineno)
        return resultat

    def test_chaque_chemin_de_boot_appelle_les_trois(self) -> None:
        appels = self._appels_par_fonction()
        for chemin in _CHEMINS_DE_BOOT:
            for requis in _APPELS_REQUIS:
                with self.subTest(chemin=chemin, appel=requis):
                    self.assertIn(
                        requis,
                        appels.get(chemin, {}),
                        f"`{requis}` manque dans `{chemin}`. Un correctif pose d'un seul cote "
                        "laisse l'autre chemin de boot sans sa garantie — c'est exactement le "
                        "defaut que ce fichier documente (le mode bureau n'avait pas l'anti-spam).",
                    )

    def test_l_anti_spam_est_pose_APRES_les_handlers(self) -> None:
        """Le compte ne dit pas QUAND. Pose avant, le filtre ne couvre rien.

        C'etait l'etat de `main_api` : l'appel existait, 15 lignes trop tot.
        Un cliquet qui se contente de sa PRESENCE aurait ete vert tout du long.
        """
        appels = self._appels_par_fonction()
        for chemin in _CHEMINS_DE_BOOT:
            with self.subTest(chemin=chemin):
                vus = appels.get(chemin, {})
                self.assertIn("install_rotating_log", vus)
                self.assertIn("install_repeated_exception_dedup", vus)
                self.assertLess(
                    vus["install_rotating_log"],
                    vus["install_repeated_exception_dedup"],
                    f"dans `{chemin}`, l'anti-spam est installe AVANT le handler de fichier : "
                    "il ne sera attache qu'au root logger, ou il ne voit aucun record propage.",
                )


if __name__ == "__main__":
    unittest.main()
