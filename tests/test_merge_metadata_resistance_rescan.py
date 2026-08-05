"""Vague P / VP-C : merge_metadata resiste a un refresh OMDb/TMDb.

AC-2 : un champ verrouille resiste a `_rescan_single_row_full_pipeline`
complet (en pratique : la barriere `merge_metadata` consulte les locks
et ne touche pas aux champs verrouilles).

On teste la barriere pure (sans IO), puis l'integration logique en
mockant les sources OMDb/TMDb pour valider que les champs verrouilles
ne sont pas modifies.
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from cinesort.app.merge_metadata import merge_metadata


class MergeMetadataBarrierTests(unittest.TestCase):
    """Barriere `merge_metadata` : tests purs sans IO."""

    def test_locked_field_never_overwritten_in_replace_mode(self):
        """Mode "Tout reconstruire" : champ verrouille = intact."""
        source = {"title": "Le Matrix (TMDb refresh)", "year": 2000, "overview": "OOPS"}
        target = {"title": "The Matrix", "year": 1999, "overview": "original"}
        locked = ["title", "overview"]

        result = merge_metadata(source, target, locked_fields=locked, replace_data=True)

        self.assertEqual(result["title"], "The Matrix", "title verrouille doit etre intact")
        self.assertEqual(result["overview"], "original", "overview verrouille doit etre intact")
        self.assertEqual(result["year"], 2000, "year non-verrouille doit etre ecrase")

    def test_locked_field_never_overwritten_in_fill_mode(self):
        """Mode "Completer les manques" : meme regle."""
        source = {"title": "Whatever", "rating": 8.7}
        target = {"title": "The Matrix", "year": 1999, "rating": None}
        locked = ["title"]

        result = merge_metadata(source, target, locked_fields=locked, replace_data=False)

        self.assertEqual(result["title"], "The Matrix")
        # rating etait None (vide), pas verrouille -> remplit
        self.assertEqual(result["rating"], 8.7)
        # year etait pre-existant, pas verrouille -> garde
        self.assertEqual(result["year"], 1999)

    def test_unlocked_fields_replaced_in_replace_mode(self):
        source = {"a": 1, "b": 2, "c": 3}
        target = {"a": 10, "b": 20, "c": 30}
        result = merge_metadata(source, target, locked_fields=[], replace_data=True)
        self.assertEqual(result, {"a": 1, "b": 2, "c": 3})

    def test_fill_mode_keeps_non_empty_target(self):
        """Mode "completer" : ne touche pas un champ deja rempli."""
        source = {"title": "BAD", "overview": "BAD"}
        target = {"title": "GOOD", "overview": "GOOD"}
        result = merge_metadata(source, target, locked_fields=[], replace_data=False)
        self.assertEqual(result["title"], "GOOD")
        self.assertEqual(result["overview"], "GOOD")

    def test_fill_mode_remplit_les_vrais_vides(self):
        """Contrat #638 : "vide" == None, chaine blanche, collection vide."""
        source = {"a": 1, "b": "src", "c": ["x"], "d": 2}
        target = {"a": None, "b": "   ", "c": [], "d": 2}
        result = merge_metadata(source, target, locked_fields=[], replace_data=False)
        self.assertEqual(result["a"], 1, "None doit etre rempli")
        self.assertEqual(result["b"], "src", "chaine blanche doit etre remplie")
        self.assertEqual(result["c"], ["x"], "collection vide doit etre remplie")
        self.assertEqual(result["d"], 2, "valeur presente : intacte")

    def test_case_insensitive_locked_fields(self):
        """Jellyfin-style : noms de champ insensibles a la casse."""
        source = {"Title": "BAD"}
        target = {"Title": "GOOD"}
        result = merge_metadata(source, target, locked_fields=["title"], replace_data=True)
        self.assertEqual(result["Title"], "GOOD", "Case-insensitive lock matching")

    def test_does_not_mutate_inputs(self):
        source = {"a": 1}
        target = {"a": 2}
        _ = merge_metadata(source, target, locked_fields=["a"], replace_data=True)
        self.assertEqual(source, {"a": 1})
        self.assertEqual(target, {"a": 2})

    def test_empty_source_returns_copy_of_target(self):
        target = {"x": 42}
        result = merge_metadata({}, target, locked_fields=[], replace_data=True)
        self.assertEqual(result, target)
        self.assertIsNot(result, target, "Doit retourner copie, pas reference")

    def test_none_locked_fields_safe(self):
        result = merge_metadata({"a": 1}, {"a": 2}, locked_fields=None, replace_data=True)
        self.assertEqual(result, {"a": 1})

    def test_simulated_omdb_refresh_respects_locks(self):
        """Scenario reel : refresh OMDb tente d'ecraser title verrouille."""
        # Etat actuel (target = ce qu'il y a dans plan.jsonl)
        target = {
            "row_id": "row-1",
            "tmdb_id": 603,
            "proposed_title": "Matrix, The (FR)",  # verrouille (user edit)
            "proposed_year": 1999,
            "overview": "Un hacker decouvre la realite simulee.",
        }
        # Source = ce que retourne OMDb refresh
        omdb_refresh = {
            "proposed_title": "The Matrix",  # OMDb dit "The Matrix"
            "proposed_year": 1999,
            "overview": "A computer hacker learns from mysterious rebels...",  # anglais
            "imdb_id": "tt0133093",  # nouveau champ pas verrouille
        }
        # User a verrouille proposed_title + overview (preferences linguistiques)
        result = merge_metadata(
            source=omdb_refresh,
            target=target,
            locked_fields=["proposed_title", "overview"],
            replace_data=True,
        )

        self.assertEqual(result["proposed_title"], "Matrix, The (FR)", "user lock preserve")
        self.assertEqual(result["overview"], "Un hacker decouvre la realite simulee.", "lock preserve")
        self.assertEqual(result["imdb_id"], "tt0133093", "Nouveau champ ajoute")
        # row_id du target preserve
        self.assertEqual(result["row_id"], "row-1")

    def test_simulated_tmdb_rescan_respects_year_lock(self):
        """Scenario : rescan TMDb tente de changer year (mauvais re-match)."""
        target = {
            "row_id": "abc",
            "tmdb_id": 100,
            "proposed_title": "Mon Film",
            "proposed_year": 2010,  # verrouille
        }
        tmdb_refresh = {
            "tmdb_id": 200,  # autre tmdb_id (false match)
            "proposed_title": "Other Film",
            "proposed_year": 2015,
        }
        result = merge_metadata(
            source=tmdb_refresh,
            target=target,
            locked_fields=["proposed_year", "tmdb_id"],
            replace_data=True,
        )
        self.assertEqual(result["proposed_year"], 2010)
        self.assertEqual(result["tmdb_id"], 100)
        # title non-verrouille : ecrase
        self.assertEqual(result["proposed_title"], "Other Film")


class MergeMetadataEdgeCasesTests(unittest.TestCase):
    def test_non_string_field_in_source_skipped(self):
        # Les keys non-str doivent etre ignorees (defense)
        source = {123: "skip", "title": "OK"}
        target = {"title": "old"}
        result = merge_metadata(source, target, locked_fields=[], replace_data=True)
        self.assertEqual(result["title"], "OK")
        self.assertNotIn(123, result)

    def test_locked_fields_with_whitespace_and_case(self):
        source = {"title": "BAD"}
        target = {"title": "GOOD"}
        result = merge_metadata(source, target, locked_fields=["  Title  "], replace_data=True)
        self.assertEqual(result["title"], "GOOD")


class MergeMetadataZeroNestPasVideTests(unittest.TestCase):
    """#638 : en mode "completer les manques", `0` / `0.0` / `False` sont PRESENTS.

    L'ancien `_is_empty` retournait True pour tout `int`/`float` valant 0. Comme
    `bool` est une sous-classe de `int` et que `False == 0`, un flag
    explicitement desactive tombait dans le meme piege. Une source externe
    (OMDb/TMDb/probe) ecrasait donc des valeurs legitimes dans le mode dont la
    docstring promet qu'il « ne remplace que les champs vides/None ».
    """

    def test_zero_entier_nest_pas_ecrase(self):
        result = merge_metadata({"episode_count": 12}, {"episode_count": 0}, replace_data=False)
        self.assertEqual(result["episode_count"], 0, "un compteur a 0 est une valeur, pas une absence")

    def test_zero_flottant_nest_pas_ecrase(self):
        result = merge_metadata({"community_rating": 7.4}, {"community_rating": 0.0}, replace_data=False)
        self.assertEqual(result["community_rating"], 0.0, "une note nulle est une valeur mesuree")

    def test_false_nest_pas_ecrase(self):
        """`isinstance(False, int)` vaut True en Python : le sous-cas le plus vicieux."""
        result = merge_metadata({"has_subtitles": True}, {"has_subtitles": False}, replace_data=False)
        self.assertIs(result["has_subtitles"], False, "un flag desactive est un choix, pas un manque")

    def test_le_mode_tout_reconstruire_ecrase_toujours_le_zero(self):
        """Anti-correctif-nuisible : `replace_data=True` n'est PAS concerne par #638."""
        result = merge_metadata({"community_rating": 7.4}, {"community_rating": 0.0}, replace_data=True)
        self.assertEqual(result["community_rating"], 7.4)


if __name__ == "__main__":
    unittest.main()
