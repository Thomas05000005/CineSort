"""Garde de non-retour : aucun harnais ne passe le jeton par la QUERY.

Le 2026-08-31, #1207 a deplace le jeton de boot de la query vers le FRAGMENT, et
`web/dashboard/app.js` a cesse de lire la query DU TOUT — c'est meme grave par
`test_boot_natif_jeton.py::test_le_jeton_de_la_QUERY_n_est_PLUS_lu`.

DEUX harnais Playwright n'ont pas suivi et ont continue d'appeler
`page.goto(f"{DASHBOARD_URL}?ntoken={token}&native=1")` : `test_axe_dashboard.py`
(audit a11y WCAG) et `tests/visual/test_responsive_viewports.py` (captures +
detection de debordement). Ils fournissaient donc un jeton par un canal mort.

RIEN NE L'A SIGNALE, et c'est le point de ce garde. `requireAuth()` rend `true`
en loopback (`_isNativeMode` : hostname 127.0.0.1), donc les vues se rendaient
quand meme — mais sans Bearer, donc peuplees d'erreurs 401. Les deux harnais
sont par ailleurs `skipUnless(CINESORT_API_TOKEN)`, donc SKIPPES en CI : leur
rupture ne pouvait etre vue que par un humain qui lit un rapport faux.

CE QUE CE GARDE VERIFIE, et pourquoi a l'AST. Il inspecte les ARGUMENTS des
appels `.goto(...)`, pas les lignes. Un garde ligne-par-ligne mordrait les
docstrings qui DECRIVENT le defaut — dont celles des deux correctifs ci-dessus,
et celle-ci. Le depot a deja paye cette lecon en #1207 : « un garde qui mord la
documentation de son propre correctif finit desactive ».

Il ne dit RIEN du canal a employer : il interdit seulement le canal mort. La
forme vivante est `sessionStorage` via `add_init_script`, cf.
`tests/e2e_dashboard/conftest.py`.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_RACINE_TESTS = Path(__file__).resolve().parent

# `?ntoken=` / `&ntoken=` : le jeton en QUERY STRING. La forme `#ntoken=`
# (fragment) est celle qu'`app.py` emet et reste legitime.
_MARQUEURS_DE_QUERY = ("?ntoken=", "&ntoken=")


def _appels_goto(arbre: ast.AST, source: str) -> list[tuple[int, str]]:
    """Yield (ligne, source de l'argument) pour chaque appel `X.goto(...)`."""
    trouves: list[tuple[int, str]] = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = noeud.func
        if not isinstance(cible, ast.Attribute) or cible.attr != "goto":
            continue
        for argument in list(noeud.args) + [kw.value for kw in noeud.keywords]:
            segment = ast.get_source_segment(source, argument)
            if segment is not None:
                trouves.append((noeud.lineno, segment))
    return trouves


def _fichiers_de_test() -> list[Path]:
    return sorted(p for p in _RACINE_TESTS.rglob("*.py") if p.name != Path(__file__).name)


class LeJetonNeRepartJamaisEnQueryTests(unittest.TestCase):
    def test_aucun_goto_de_harnais_ne_porte_le_jeton_en_query(self) -> None:
        coupables: list[str] = []
        for chemin in _fichiers_de_test():
            try:
                source = chemin.read_text(encoding="utf-8")
                arbre = ast.parse(source)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for ligne, segment in _appels_goto(arbre, source):
                if any(marqueur in segment for marqueur in _MARQUEURS_DE_QUERY):
                    rel = chemin.relative_to(_RACINE_TESTS.parent).as_posix()
                    coupables.append(f"{rel}:{ligne} -> {segment}")

        self.assertEqual(
            coupables,
            [],
            "Un harnais passe le jeton en QUERY STRING a `page.goto`. `app.js` ne lit "
            "plus la query depuis #1207 (2026-08-31) : le jeton n'arrive pas, les vues "
            "se rendent quand meme (requireAuth() est vrai en loopback) mais sans "
            "Bearer, et le rapport produit est FAUX sans que rien ne le signale. "
            "Poser le jeton en sessionStorage via `add_init_script` — cf. "
            "tests/e2e_dashboard/conftest.py :\n  " + "\n  ".join(coupables),
        )

    def test_le_garde_VOIT_bien_les_appels_goto(self) -> None:
        """Contre-epreuve : un garde qui n'inspecte rien rend zero coupable.

        Sans elle, une regression d'`_appels_goto` (mauvais nom d'attribut,
        `get_source_segment` qui rend None sur un arbre sans positions) rendrait
        le test ci-dessus vert pour la pire des raisons.
        """
        vus = 0
        for chemin in _fichiers_de_test():
            try:
                source = chemin.read_text(encoding="utf-8")
                arbre = ast.parse(source)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            vus += len(_appels_goto(arbre, source))
        self.assertGreater(vus, 0, "Le garde n'a inspecte AUCUN appel `.goto(...)` : il ne prouve rien.")

    def test_le_garde_ATTRAPE_la_forme_fautive(self) -> None:
        """Contre-epreuve : la forme d'avant #1207 doit bien etre detectee."""
        source = 'page.goto(f"{DASHBOARD_URL}?ntoken={self.token}&native=1")\n'
        segments = [seg for _ligne, seg in _appels_goto(ast.parse(source), source)]
        self.assertTrue(
            any(any(m in seg for m in _MARQUEURS_DE_QUERY) for seg in segments),
            f"La forme fautive historique n'est plus reconnue : {segments}",
        )

    def test_le_garde_LAISSE_passer_le_fragment(self) -> None:
        """Le fragment est le canal VIVANT : il ne doit pas etre accuse."""
        source = 'page.goto(f"{DASHBOARD_URL}?native=1#ntoken={token}")\n'
        segments = [seg for _ligne, seg in _appels_goto(ast.parse(source), source)]
        self.assertTrue(segments, "L'appel n'a meme pas ete vu.")
        self.assertFalse(
            any(any(m in seg for m in _MARQUEURS_DE_QUERY) for seg in segments),
            f"Le fragment est accuse a tort : {segments}",
        )


if __name__ == "__main__":
    unittest.main()
