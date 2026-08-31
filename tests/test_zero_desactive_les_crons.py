"""« 0 = desactive » doit ATTEINDRE les crons destructifs, pas seulement exister.

Le defaut n'etait pas dans la garde : elle est correcte, et elle est deja
eprouvee (`test_quarantaine_ttl_v77.py` appelle
`start_quarantine_ttl_cron(api, ttl_days=0)` et verifie qu'il rend `None`).
Ce test-la etait VERT pendant tout le defaut, parce qu'il passe le zero
LUI-MEME. Personne n'eprouvait que le zero PARVIENT jusqu'a la garde.

Le seul chemin qui relie le reglage a la garde, `app.py`, valait :

    int(settings.get("quarantaine_ttl_days") or _Q_DEFAULT_TTL)

et `0 or 30` vaut `30`. La garde etait donc CORRECTE et INATTEIGNABLE.

Cinq endroits promettaient pourtant le contraire :

  1. l'ecran Parametres, a l'utilisateur : `min: 0`, hint « 0 = désactivé »
     (`web/dashboard/views/parametres.js`) ;
  2. le commentaire du meme ecran : « `quarantaine_ttl_days = 0` desactive le cron » ;
  3. le validateur backend : borne `[0, 3650]`, commentaire « 0 = OFF »
     (`settings_support._save_section_advanced`) — il PERSISTE donc un entier 0 ;
  4. les deux demarreurs : `if days <= 0: return None` ;
  5. les commentaires d'`app.py`, une ligne au-dessus du `or` qui l'annulait.

Consequence : l'utilisateur qui saisissait 0 pour ne JAMAIS purger sa
quarantaine voyait `_review/` (conflits, doublons, leftovers, lignes non
approuvees — des fichiers video) purge a 30 jours.

Ce fichier eprouve donc le SITE D'APPEL, pas la decision.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]

# Reglages dont le ZERO est une valeur signifiante (« ne le fais jamais »),
# et non un synonyme d'« absent ». Les lire avec `or` les detruit.
_ZERO_SIGNIFIANT = ("history_retention_days", "quarantaine_ttl_days")

#: Les DEUX chemins de demarrage qui arment un cron destructif : `--api`
#: (`main_api`) et le mode bureau (`_startup`, imbriquee dans `main`).
_CHEMINS_DE_BOOT = ("main_api", "_startup")


class ReglageEntierTests(unittest.TestCase):
    """La decision : distinguer ABSENT de ZERO."""

    @property
    def app_module(self):
        """Import DIFFERE, a dessein.

        `import app` tire `cinesort.ui.api`, donc `numpy`. En tete de fichier,
        une dependance manquante mettrait `LeZeroATTEINTLeCronTests` — qui est
        purement statique — en ERROR at setup, c'est-a-dire INVISIBLE dans un
        grep `FAILED` (piege documente dans `/CLAUDE.md`). Le cliquet doit
        pouvoir rougir meme quand l'application ne s'importe pas.
        """
        import app

        return app

    def test_zero_explicite_est_conserve(self) -> None:
        for cle in _ZERO_SIGNIFIANT:
            with self.subTest(cle=cle):
                self.assertEqual(0, self.app_module.reglage_entier({cle: 0}, cle, 30))

    def test_absent_ou_vide_retombe_sur_le_defaut(self) -> None:
        self.assertEqual(30, self.app_module.reglage_entier({}, "quarantaine_ttl_days", 30))
        self.assertEqual(30, self.app_module.reglage_entier({"quarantaine_ttl_days": None}, "quarantaine_ttl_days", 30))
        self.assertEqual(30, self.app_module.reglage_entier({"quarantaine_ttl_days": "  "}, "quarantaine_ttl_days", 30))

    def test_valeur_illisible_retombe_sur_le_defaut(self) -> None:
        """Une valeur corrompue ne doit pas faire tomber le boot, ni valoir 0 —
        ce qui DESACTIVERAIT une purge que l'utilisateur n'a pas desactivee."""
        for pourri in ("abc", [], {}, object()):
            with self.subTest(valeur=pourri):
                self.assertEqual(
                    30, self.app_module.reglage_entier({"quarantaine_ttl_days": pourri}, "quarantaine_ttl_days", 30)
                )

    def test_une_valeur_normale_passe_inchangee(self) -> None:
        """CONTRE-EPREUVE : le cas nominal ne bouge pas."""
        self.assertEqual(45, self.app_module.reglage_entier({"quarantaine_ttl_days": 45}, "quarantaine_ttl_days", 30))
        self.assertEqual(
            7, self.app_module.reglage_entier({"history_retention_days": "7"}, "history_retention_days", 90)
        )


class LeZeroATTEINTLeCronTests(unittest.TestCase):
    """Le SITE D'APPEL — ce que la batterie existante ne pouvait pas voir.

    Statique a dessein : le defaut vit dans `app.py`, dont le boot ne
    s'instrumente pas sans demarrer l'application entiere (serveur REST, crons,
    et — pour le cron de purge TTL — un effet sur la bibliotheque REELLE).
    """

    def _appels_fautifs(self) -> list[str]:
        """Tout `... .get("<cle a zero signifiant>") or <defaut>` dans app.py."""
        source = (_RACINE / "app.py").read_text(encoding="utf-8", errors="replace")
        arbre = ast.parse(source)
        fautifs: list[str] = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.BoolOp) or not isinstance(noeud.op, ast.Or):
                continue
            gauche = noeud.values[0]
            if not (isinstance(gauche, ast.Call) and isinstance(gauche.func, ast.Attribute)):
                continue
            if gauche.func.attr != "get" or not gauche.args:
                continue
            cle = gauche.args[0]
            if isinstance(cle, ast.Constant) and cle.value in _ZERO_SIGNIFIANT:
                fautifs.append(f"app.py:{noeud.lineno} -> {cle.value}")
        return fautifs

    def test_aucun_reglage_a_zero_signifiant_n_est_lu_avec_or(self) -> None:
        fautifs = self._appels_fautifs()
        self.assertEqual(
            [],
            fautifs,
            "`x.get(cle) or defaut` AVALE le zero : la garde `<= 0` du cron devient "
            "inatteignable et la purge tourne alors que l'utilisateur l'a desactivee. "
            f"Utiliser `reglage_entier(settings, cle, defaut)`. Sites : {fautifs}",
        )

    def test_les_quatre_sites_passent_par_le_lecteur_honnete(self) -> None:
        """Contre-epreuve du test precedent : il rougit si le motif revient,
        celui-ci rougit si les appels DISPARAISSENT (renommage, suppression) —
        sans quoi « 0 site fautif » serait satisfait par un fichier vide."""
        source = (_RACINE / "app.py").read_text(encoding="utf-8", errors="replace")
        arbre = ast.parse(source)
        vus = [
            noeud.args[1].value
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Name)
            and noeud.func.id == "reglage_entier"
            and len(noeud.args) >= 2
            and isinstance(noeud.args[1], ast.Constant)
        ]
        for cle in _ZERO_SIGNIFIANT:
            with self.subTest(cle=cle):
                self.assertEqual(
                    2,
                    vus.count(cle),
                    f"{cle} doit etre lu par `reglage_entier` sur les DEUX chemins de boot "
                    f"(mode --api et mode desktop) ; trouve {vus.count(cle)}",
                )

    def test_les_deux_chemins_de_boot_lisent_CHACUN_le_reglage(self) -> None:
        """Le compte ne dit pas OU. Signale par une revue automatique.

        Le test ci-dessus exige DEUX appels par cle. Deux appels tous deux
        places dans `main_api` le satisferaient, et le mode bureau perdrait
        sa garde sans que rien ne rougisse. Un compte est un PROXY de la
        propriete visee ; ici la propriete est l APPARTENANCE.

        Chaque appel est attribue a sa fonction englobante la plus INTERNE :
        `_startup` est imbriquee dans `main`, donc un simple `ast.walk` la
        compte deux fois et ferait croire a trois chemins la ou il y en a
        deux.
        """
        source = (_RACINE / "app.py").read_text(encoding="utf-8", errors="replace")
        arbre = ast.parse(source)
        porteur: dict[int, str] = {}
        for fonction in ast.walk(arbre):
            if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for noeud in ast.walk(fonction):
                if (
                    isinstance(noeud, ast.Call)
                    and isinstance(noeud.func, ast.Name)
                    and noeud.func.id == "reglage_entier"
                    and len(noeud.args) >= 2
                    and isinstance(noeud.args[1], ast.Constant)
                ):
                    # La derniere fonction vue est la plus interne : `ast.walk`
                    # parcourt du plus externe au plus imbrique.
                    porteur[id(noeud)] = fonction.name

        par_fonction: dict[str, set] = {}
        for fonction in ast.walk(arbre):
            if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for noeud in ast.walk(fonction):
                if porteur.get(id(noeud)) == fonction.name:
                    par_fonction.setdefault(fonction.name, set()).add(noeud.args[1].value)

        for cle in _ZERO_SIGNIFIANT:
            for chemin in _CHEMINS_DE_BOOT:
                with self.subTest(cle=cle, chemin=chemin):
                    self.assertIn(
                        cle,
                        par_fonction.get(chemin, set()),
                        f"{cle} n est pas lu par `reglage_entier` dans {chemin}. "
                        "Le cron destructif de ce chemin de boot n a donc plus sa garde, "
                        "meme si le COMPTE global reste a 2.",
                    )


if __name__ == "__main__":
    unittest.main()
