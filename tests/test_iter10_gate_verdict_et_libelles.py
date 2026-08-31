"""Gardes sur `scripts/_iter10_gate_lisibilite.py` — le GATE de lisibilite.

Deux defauts, la meme famille que le reste du lot.

**Le code de sortie ne dependait d'AUCUN des quatre verdicts.** `out["ok"]`
etait pose a `True` inconditionnellement a la fin du bloc `try`, juste apres les
mesures, et la sortie valait `0 if out.get("ok") else 1`. `mojibake_OK`,
`contraste_4_themes_OK`, `tier_colors_intactes` et `unmount_no_poll_OK` etaient
calcules, ecrits dans le JSON, imprimes sur stderr — et ignores. Un gate qui
rend 0 quoi qu'il mesure ne garde rien : il ne pouvait echouer que si Playwright
levait, c'est-a-dire quand la mesure n'avait PAS eu lieu.

**Les cinq libelles d'etapes etaient encodes trois fois dans `scripts/`** :
`EXPECTED_LABELS["step1".."step5"]` (jamais relu — encodage MORT), la liste
litterale de la boucle de verification, et la liste de
`_iter10_gate_lisibilite_v2.py`. Trois exemplaires d'une meme verite : renommer
une etape dans l'application en laisse deux qui mentent, et le premier ne fait
meme pas echouer le gate puisque personne ne le lit.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
GATE_PATH = SCRIPTS_DIR / "_iter10_gate_lisibilite.py"
GATE_V2_PATH = SCRIPTS_DIR / "_iter10_gate_lisibilite_v2.py"


def _load_gate():
    """Importe le gate. Il doit etre importable sans rien ecrire sur disque."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("_iter10_gate_lisibilite_ut", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _load_gate()

#: Les quatre verdicts que le gate calcule et affiche.
VERDICTS = ("mojibake_OK", "contraste_4_themes_OK", "tier_colors_intactes", "unmount_no_poll_OK")


def _mesure_complete(**surcharges) -> dict:
    """Un `out` de gate dont la mesure a abouti, tous verdicts verts par defaut."""
    base = {"measured": True}
    base.update(dict.fromkeys(VERDICTS, True))
    base.update(surcharges)
    return base


class CodeDeSortieDuGateTests(unittest.TestCase):
    """Le verdict global doit dependre des quatre verdicts mesures."""

    def test_tous_verts_vaut_succes(self) -> None:
        self.assertTrue(GATE.gate_ok(_mesure_complete()))

    def test_chaque_verdict_rouge_fait_echouer_le_gate(self) -> None:
        for verdict in VERDICTS:
            with self.subTest(verdict=verdict):
                self.assertFalse(
                    GATE.gate_ok(_mesure_complete(**{verdict: False})),
                    f"Le gate reste vert alors que {verdict} est rouge : son code de "
                    f"sortie ne depend pas de ce qu'il mesure.",
                )

    def test_les_quatre_verdicts_rouges_font_echouer_le_gate(self) -> None:
        rouge = _mesure_complete(**dict.fromkeys(VERDICTS, False))
        self.assertFalse(
            GATE.gate_ok(rouge),
            "Les QUATRE verdicts sont rouges et le gate rend quand meme un succes.",
        )

    def test_un_verdict_non_calcule_ne_vaut_pas_un_succes(self) -> None:
        partiel = _mesure_complete()
        del partiel["contraste_4_themes_OK"]
        self.assertFalse(
            GATE.gate_ok(partiel),
            "Un verdict absent du rapport est traite comme un succes : une mesure "
            "qui n'a pas eu lieu ne peut pas etre verte.",
        )

    def test_une_mesure_interrompue_ne_vaut_pas_un_succes(self) -> None:
        interrompu = _mesure_complete(measured=False)
        self.assertFalse(GATE.gate_ok(interrompu), "Une mesure interrompue rend un succes.")


class ImportSansEffetDeBordTests(unittest.TestCase):
    """Importer un outil de mesure ne doit rien ecrire sur disque."""

    def test_le_module_ne_cree_pas_son_dossier_de_capture_a_l_import(self) -> None:
        source = GATE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(GATE_PATH))
        appels_toplevel = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "mkdir"
        ]
        self.assertEqual(
            appels_toplevel,
            [],
            "Le module cree un repertoire au moment de l'import : il n'est pas mesurable sans effet de bord.",
        )


class LibellesDEtapesUniqueSourceTests(unittest.TestCase):
    """Les cinq libelles d'etapes ne doivent etre ecrits qu'une seule fois."""

    #: Deux libelles suffisent a reconnaitre la sequence des etapes.
    _MARQUEURS = ("Analyse", "Application")

    @staticmethod
    def _sequences_litterales(path: Path) -> list[list[str]]:
        """Toute liste/tuple litteral de >= 5 chaines contenant les marqueurs."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trouvees: list[list[str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            valeurs = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
            if len(valeurs) >= 5 and all(m in valeurs for m in LibellesDEtapesUniqueSourceTests._MARQUEURS):
                trouvees.append(valeurs)
        return trouvees

    def test_une_seule_definition_litterale_dans_scripts(self) -> None:
        par_fichier = {
            p.name: self._sequences_litterales(p)
            for p in sorted(SCRIPTS_DIR.glob("*.py"))
            if self._sequences_litterales(p)
        }
        total = sum(len(v) for v in par_fichier.values())
        self.assertEqual(
            total,
            1,
            "Les libelles d'etapes sont encodes plusieurs fois dans scripts/ : "
            f"{par_fichier}. Renommer une etape en laisserait qui mentent.",
        )

    def test_expected_labels_derive_de_la_source_unique(self) -> None:
        """EXPECTED_LABELS['stepN'] ne doit pas etre un second encodage mort."""
        for i, libelle in enumerate(GATE.STEP_LABELS, 1):
            with self.subTest(step=i):
                self.assertEqual(
                    GATE.EXPECTED_LABELS[f"step{i}"],
                    libelle,
                    "EXPECTED_LABELS porte des libelles d'etapes qui divergent de "
                    "la liste effectivement verifiee par le gate.",
                )

    def test_la_v2_consomme_la_meme_source(self) -> None:
        source_v2 = GATE_V2_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "STEP_LABELS",
            source_v2,
            "La v2 reencode les libelles au lieu de lire la source unique du gate.",
        )


class VerdictMojibakeTests(unittest.TestCase):
    """Le verdict mojibake ne doit tolerer AUCUN libelle reellement casse.

    `checks["bullets_u2022"]` porte `"ok": True` EN DUR — c'est un controle
    informatif (les champs masques ne sont pas forcement montes). Le verdict
    appliquait par-dessus une tolerance d'un echec, commentee « tolerance 1
    (bullets) ». Mais le controle bullets etant deja toujours vert, cette
    tolerance ne le couvrait pas : elle etait disponible pour un VRAI libelle.
    Un `Bibliothèque` rendu en mojibake passait donc le gate.
    """

    @staticmethod
    def _checks(nb_reels: int, nb_casses: int) -> dict:
        checks = {f"label{i}": {"ok": i >= nb_casses} for i in range(nb_reels)}
        # Le controle informatif, vert par construction.
        checks["bullets_u2022"] = {"ok": True, "note": "informatif"}
        return checks

    def test_tous_les_libelles_corrects_passent(self) -> None:
        self.assertTrue(GATE.verdict_mojibake(self._checks(11, 0))["mojibake_OK"])

    def test_un_seul_libelle_casse_fait_echouer(self) -> None:
        self.assertFalse(
            GATE.verdict_mojibake(self._checks(11, 1))["mojibake_OK"],
            "Un libelle reellement mojibake passe le verdict : la tolerance dite "
            "« pour bullets » est consommee par un vrai controle, puisque bullets "
            "est vert en dur.",
        )

    def test_le_controle_informatif_ne_compte_pas_dans_le_total(self) -> None:
        resultat = GATE.verdict_mojibake(self._checks(11, 0))
        self.assertEqual(
            resultat["labels_total"],
            11,
            "Le controle informatif `bullets_u2022` est compte dans le total du "
            "verdict alors qu'il ne peut rendre que vert.",
        )


class VerificationDesEtapesTests(unittest.TestCase):
    """Le controle des libelles doit etre positionnel et exact.

    L'ancien `any(expected in s for s in steps)` acceptait n'importe quel noeud
    CONTENANT le libelle : les cas ci-dessous le satisfaisaient tous.
    """

    def test_les_libelles_exacts_dans_l_ordre_passent(self) -> None:
        checks = GATE.verifier_etapes(list(GATE.STEP_LABELS))
        self.assertTrue(all(c["ok"] for c in checks.values()))

    def test_un_conteneur_portant_les_cinq_textes_ne_valide_rien(self) -> None:
        # Sous l'ancien `any(expected in s ...)` ce cas rendait 5/5 verts
        # (mesure comparative du 2026-08-31) ; il en rend desormais 0/5.
        blob = [" ".join(GATE.STEP_LABELS)]
        checks = GATE.verifier_etapes(blob)
        self.assertEqual(
            [c["ok"] for c in checks.values()],
            [False] * 5,
            "Un seul noeud portant les cinq libelles validait les cinq etapes : "
            "le controle repondait a la presence du texte, pas au rendu de chaque "
            "etape.",
        )

    def test_un_libelle_suffixe_est_refuse(self) -> None:
        pollue = list(GATE.STEP_LABELS)
        pollue[0] = "Analyse (2/5)"
        checks = GATE.verifier_etapes(pollue)
        self.assertFalse(checks["step1"]["ok"], "Un libelle suffixe passe l'exact-match annonce.")

    def test_un_ordre_permute_est_refuse(self) -> None:
        permute = list(GATE.STEP_LABELS)
        permute[1], permute[2] = permute[2], permute[1]
        checks = GATE.verifier_etapes(permute)
        self.assertFalse(checks["step2"]["ok"], "Un ordre permute passe le controle.")

    def test_une_collecte_vide_ne_valide_aucune_etape(self) -> None:
        checks = GATE.verifier_etapes([])
        self.assertEqual([c["ok"] for c in checks.values()], [False] * 5)


class SelecteurDuGateTests(unittest.TestCase):
    """Le gate doit chercher les libelles LA OU la vue les pose.

    La vue Traitement rend chaque libelle dans
    `<span class="traitement-step-label">` (`web/dashboard/views/traitement.js`).
    Le gate v1 les cherchait avec `[data-step] .step-label, .step-card
    .step-label, .step-label, [data-step] span` : **aucun** de ces quatre
    selecteurs n'existe dans l'arbre front (l'attribut reel est
    `data-traitement-step`, la classe reelle `traitement-step-label` — un
    selecteur de classe ne matche pas un prefixe). `steps` etait donc VIDE et
    les cinq controles d'etape echouaient tous, sans consequence puisque le
    code de sortie ne les regardait pas.
    """

    VUE = REPO_ROOT / "web" / "dashboard" / "views" / "traitement.js"

    @staticmethod
    def _classes_et_attributs(selecteur: str) -> list[str]:
        """Les jetons `.classe` / `[attribut]` d'un selecteur composite."""
        jetons: list[str] = []
        for partie in selecteur.split(","):
            jetons += re.findall(r"\.([A-Za-z0-9_-]+)|\[([A-Za-z0-9_-]+)", partie)
        return [classe or attribut for classe, attribut in jetons]

    def test_chaque_jeton_du_selecteur_existe_dans_la_vue(self) -> None:
        source = self.VUE.read_text(encoding="utf-8")
        jetons = self._classes_et_attributs(GATE.STEP_LABEL_SELECTOR)
        self.assertTrue(jetons, "Selecteur d'etapes vide.")
        absents = [j for j in jetons if not re.search(rf'["\s]{re.escape(j)}["\s=]', source)]
        self.assertEqual(
            absents,
            [],
            f"Le gate cherche les libelles d'etapes avec des jetons qui n'existent "
            f"nulle part dans {self.VUE.name} : {absents}. Il ne collecte donc rien "
            f"et ne mesure rien.",
        )

    def test_les_libelles_du_gate_sont_ceux_de_la_vue(self) -> None:
        """Quatrieme encodage : la vue de PRODUCTION porte la verite."""
        source = self.VUE.read_text(encoding="utf-8")
        bloc = re.search(r"const STEPS = \[(.*?)\];", source, re.DOTALL)
        self.assertIsNotNone(bloc, "Bloc `const STEPS` introuvable dans la vue Traitement.")
        labels = tuple(re.findall(r'label:\s*"([^"]+)"', bloc.group(1)))
        self.assertEqual(
            labels,
            tuple(GATE.STEP_LABELS),
            "Les libelles attendus par le gate ont derive de ceux que la vue rend "
            "reellement : le gate mesurerait un mojibake qui n'existe pas, ou "
            "laisserait passer un renommage.",
        )


if __name__ == "__main__":
    unittest.main()
