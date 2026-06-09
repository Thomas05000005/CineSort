"""GATE ITER7 — Template custom AVEC SEPARATEUR EMBEDDED hardcode.

Sujet (mission iter7 risque regression templates custom) :

> "Tester template custom existant qui embed un separateur dans le format
>  (ex `{title}_{year}`). Si separator change la sortie DE CE TEMPLATE custom
>  = FORK SEMANTIQUE STOP. Si template custom reste avec son separateur
>  embedded = bon."

Strategie : pour chaque template custom avec un caractere separateur litteral
(`_`, `.`, `-`) entre les variables, on verifie qu'aucune valeur de
`cfg.separator` ne modifie la sortie de `format_movie_folder`.

Pourquoi c'est important : MEMOIRE inviolable
"FORK SEMANTIQUE CUSTOM TEMPLATE = STOP REMONTER si separator/lowercase modifie
 sortie template custom existant".

Le fix ITER7 etape 3 est opt-in via la variable `{sep}` : seuls les templates
qui referencent `{sep}` explicitement reagissent au selecteur UI. Les templates
existants qui embarquent leur propre separateur litteral DOIVENT rester
strictement invariants — c'est la garantie qui evite de casser les
installations utilisateurs.

Pattern reference : test_separator_iter7.py + test_lowercase_extensions_iter7_custom_template.py.
"""

from __future__ import annotations

import unittest

from cinesort.domain.naming import build_naming_context, format_movie_folder


class CustomTemplateEmbeddedSeparatorForkGuardTests(unittest.TestCase):
    """ITER7 GATE : template custom avec separateur embedded reste invariant."""

    _SEPARATOR_VALUES = ("_", " ", ".", "-")

    def _ctx_for(self, sep_value: str):
        """Contexte naming minimal avec cfg.separator donne."""
        return build_naming_context(title="Inception", year=2010, separator=sep_value)

    def test_custom_template_underscore_embedded_invariant(self) -> None:
        """Template `{title}_{year}` reste `Inception_2010` quelque soit cfg.separator."""
        tpl = "{title}_{year}"
        outputs = {
            sep: format_movie_folder(tpl, self._ctx_for(sep))
            for sep in self._SEPARATOR_VALUES
        }
        expected = "Inception_2010"
        for sep, out in outputs.items():
            self.assertEqual(
                out,
                expected,
                f"FORK SEMANTIQUE CUSTOM TEMPLATE detecte : template '{tpl}' "
                f"avec separator={sep!r} a produit {out!r} au lieu de {expected!r}. "
                f"MEMOIRE 'STOP REMONTER si separator modifie sortie template custom' violee.",
            )

    def test_custom_template_dot_embedded_invariant(self) -> None:
        """Template `{title}.{year}` reste `Inception.2010` quelque soit cfg.separator."""
        tpl = "{title}.{year}"
        outputs = {
            sep: format_movie_folder(tpl, self._ctx_for(sep))
            for sep in self._SEPARATOR_VALUES
        }
        expected = "Inception.2010"
        for sep, out in outputs.items():
            self.assertEqual(
                out,
                expected,
                f"FORK SEMANTIQUE CUSTOM TEMPLATE detecte : template '{tpl}' "
                f"avec separator={sep!r} a produit {out!r} au lieu de {expected!r}.",
            )

    def test_custom_template_dash_embedded_invariant(self) -> None:
        """Template `{title}-{year}` reste `Inception-2010` quelque soit cfg.separator.

        Note : `_CLEANUP_PATTERNS` a une regle `\\s*-\\s*$` qui strip un tiret en
        fin. Ici le tiret est ENTRE les variables (pas en fin), donc preserve.
        """
        tpl = "{title}-{year}"
        outputs = {
            sep: format_movie_folder(tpl, self._ctx_for(sep))
            for sep in self._SEPARATOR_VALUES
        }
        expected = "Inception-2010"
        for sep, out in outputs.items():
            self.assertEqual(
                out,
                expected,
                f"FORK SEMANTIQUE CUSTOM TEMPLATE detecte : template '{tpl}' "
                f"avec separator={sep!r} a produit {out!r} au lieu de {expected!r}.",
            )

    def test_custom_template_multi_separator_invariant(self) -> None:
        """Template avec separateurs litteraux multiples preserve l'integralite.

        Exemple : `{title}.{year}.{tmdb_id}` doit rester `Inception.2010.27205`
        quel que soit `cfg.separator`. Seuls les points hardcodes sont les
        separateurs, ils ne doivent jamais etre transformes.
        """
        tpl = "{title}.{year}.{tmdb_id}"
        for sep_value in self._SEPARATOR_VALUES:
            ctx = build_naming_context(
                title="Inception",
                year=2010,
                tmdb_id=27205,
                separator=sep_value,
            )
            out = format_movie_folder(tpl, ctx)
            self.assertEqual(
                out,
                "Inception.2010.27205",
                f"FORK SEMANTIQUE detecte : template '{tpl}' avec "
                f"separator={sep_value!r} a produit {out!r}.",
            )

    def test_default_template_also_invariant_control(self) -> None:
        """Controle non-regression : preset default reste invariant.

        C'est la meme garantie deja couverte par test_separator_iter7.py
        (test_preset_default_invariance_under_vs_space) mais en unitaire
        rapide pour panneau de bord.
        """
        tpl = "{title} ({year})"
        outputs = {
            sep: format_movie_folder(tpl, self._ctx_for(sep))
            for sep in self._SEPARATOR_VALUES
        }
        expected = "Inception (2010)"
        for sep, out in outputs.items():
            self.assertEqual(
                out,
                expected,
                f"REGRESSION preset default : separator={sep!r} -> {out!r}",
            )

    def test_optin_template_with_sep_does_react(self) -> None:
        """Differentiel OPT-IN : seuls les templates referencant `{sep}` reagissent.

        Garantit que le mecanisme opt-in n'est pas casse (fail-safe : si ce test
        FAIL alors plus rien ne reagit au selecteur, le fix etape 3 est mort).
        """
        tpl = "{title}{sep}{year}"
        outputs = {
            sep: format_movie_folder(tpl, self._ctx_for(sep))
            for sep in self._SEPARATOR_VALUES
        }
        self.assertEqual(outputs["_"], "Inception_2010")
        self.assertEqual(outputs["."], "Inception.2010")
        self.assertEqual(outputs["-"], "Inception-2010")
        self.assertEqual(outputs[" "], "Inception 2010")
        # Les 4 sorties doivent etre DIFFERENTES entre elles (le selecteur a un effet).
        self.assertEqual(
            len(set(outputs.values())),
            4,
            "REGRESSION MECANISME OPT-IN : les 4 valeurs de cfg.separator devraient "
            f"produire 4 sorties distinctes via {{sep}}. Vu : {outputs}.",
        )


if __name__ == "__main__":
    unittest.main()
