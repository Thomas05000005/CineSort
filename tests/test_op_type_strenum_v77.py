"""Tests pour OpType StrEnum (VO-D-1).

Verifie :
1. OpType.RENAME / MOVE / NOOP valeurs canoniques UPPERCASE.
2. StrEnum implique str equality : OpType.RENAME == "RENAME".
3. OpType.from_str() supporte la normalisation (case-insensitive, strip).
4. OpType.from_str() leve ValueError sur valeur invalide.
5. BACKWARD COMPAT : OP_TYPE_RENAME / OP_TYPE_MOVE / OP_TYPE_NOOP alias.
6. BACKWARD COMPAT : RenameProposal accepte OpType ET str pour op_type.
7. __all__ exporte OpType.
"""

from __future__ import annotations

import unittest

from cinesort.domain import probe_models
from cinesort.domain.probe_models import (
    OP_TYPE_MOVE,
    OP_TYPE_NOOP,
    OP_TYPE_RENAME,
    OP_TYPE_VALUES,
    OpType,
    RenameProposal,
)


class OpTypeStrEnumValuesTests(unittest.TestCase):
    """Verifie les valeurs canoniques de l'enum OpType."""

    def test_rename_value(self) -> None:
        self.assertEqual(OpType.RENAME.value, "RENAME")

    def test_move_value(self) -> None:
        self.assertEqual(OpType.MOVE.value, "MOVE")

    def test_noop_value(self) -> None:
        self.assertEqual(OpType.NOOP.value, "NOOP")

    def test_all_three_members(self) -> None:
        members = {m.value for m in OpType}
        self.assertEqual(members, {"RENAME", "MOVE", "NOOP"})


class OpTypeStrEnumIsStrTests(unittest.TestCase):
    """StrEnum garantit l'equality et l'heritage str (backward compat ABSOLUE)."""

    def test_op_type_is_str_instance(self) -> None:
        self.assertIsInstance(OpType.RENAME, str)
        self.assertIsInstance(OpType.MOVE, str)
        self.assertIsInstance(OpType.NOOP, str)

    def test_op_type_equals_str_literal(self) -> None:
        # StrEnum equality avec litterals str
        self.assertEqual(OpType.RENAME, "RENAME")
        self.assertEqual(OpType.MOVE, "MOVE")
        self.assertEqual(OpType.NOOP, "NOOP")

    def test_str_literal_equals_op_type(self) -> None:
        # Equality symetrique
        self.assertEqual("RENAME", OpType.RENAME)
        self.assertEqual("MOVE", OpType.MOVE)
        self.assertEqual("NOOP", OpType.NOOP)

    def test_op_type_in_str_collection(self) -> None:
        # Un set de str contient OpType.RENAME via hash compatible str
        valid = {"RENAME", "MOVE", "NOOP"}
        self.assertIn(OpType.RENAME, valid)
        self.assertIn(OpType.MOVE, valid)
        self.assertIn(OpType.NOOP, valid)

    def test_op_type_in_frozenset_values(self) -> None:
        # OP_TYPE_VALUES contient les str canoniques, OpType.* doit y matcher
        self.assertIn(OpType.RENAME, OP_TYPE_VALUES)
        self.assertIn(OpType.MOVE, OP_TYPE_VALUES)
        self.assertIn(OpType.NOOP, OP_TYPE_VALUES)


class OpTypeFromStrTests(unittest.TestCase):
    """OpType.from_str : conversion tolerante depuis string."""

    def test_from_str_uppercase_canonical(self) -> None:
        self.assertEqual(OpType.from_str("RENAME"), OpType.RENAME)
        self.assertEqual(OpType.from_str("MOVE"), OpType.MOVE)
        self.assertEqual(OpType.from_str("NOOP"), OpType.NOOP)

    def test_from_str_lowercase_legacy(self) -> None:
        # Supporte les anciennes valeurs lowercase (legacy migration)
        self.assertEqual(OpType.from_str("rename"), OpType.RENAME)
        self.assertEqual(OpType.from_str("move"), OpType.MOVE)
        self.assertEqual(OpType.from_str("noop"), OpType.NOOP)

    def test_from_str_mixed_case(self) -> None:
        self.assertEqual(OpType.from_str("Rename"), OpType.RENAME)
        self.assertEqual(OpType.from_str("MoVe"), OpType.MOVE)

    def test_from_str_with_whitespace(self) -> None:
        self.assertEqual(OpType.from_str("  RENAME  "), OpType.RENAME)
        self.assertEqual(OpType.from_str("\tmove\n"), OpType.MOVE)

    def test_from_str_invalid_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            OpType.from_str("INVALID")
        msg = str(ctx.exception)
        self.assertIn("Unknown OpType", msg)
        self.assertIn("'INVALID'", msg)
        # Message mentionne les valeurs attendues
        self.assertIn("RENAME", msg)
        self.assertIn("MOVE", msg)
        self.assertIn("NOOP", msg)

    def test_from_str_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            OpType.from_str("")

    def test_from_str_returns_canonical_op_type(self) -> None:
        # Le retour est bien un OpType, pas un str
        result = OpType.from_str("rename")
        self.assertIsInstance(result, OpType)
        self.assertIs(result, OpType.RENAME)


class BackwardCompatAliasesTests(unittest.TestCase):
    """Les constantes OP_TYPE_* legacy DOIVENT continuer de fonctionner."""

    def test_op_type_rename_alias_equals_enum_value(self) -> None:
        self.assertEqual(OP_TYPE_RENAME, OpType.RENAME.value)
        self.assertEqual(OP_TYPE_RENAME, "RENAME")

    def test_op_type_move_alias_equals_enum_value(self) -> None:
        self.assertEqual(OP_TYPE_MOVE, OpType.MOVE.value)
        self.assertEqual(OP_TYPE_MOVE, "MOVE")

    def test_op_type_noop_alias_equals_enum_value(self) -> None:
        self.assertEqual(OP_TYPE_NOOP, OpType.NOOP.value)
        self.assertEqual(OP_TYPE_NOOP, "NOOP")

    def test_op_type_alias_is_plain_str(self) -> None:
        # Les alias restent des str pures (pas des OpType) pour 100% compat
        self.assertIsInstance(OP_TYPE_RENAME, str)
        self.assertIsInstance(OP_TYPE_MOVE, str)
        self.assertIsInstance(OP_TYPE_NOOP, str)

    def test_op_type_values_frozenset_intact(self) -> None:
        self.assertEqual(
            OP_TYPE_VALUES,
            frozenset({"RENAME", "MOVE", "NOOP"}),
        )


class RenameProposalAcceptsOpTypeTests(unittest.TestCase):
    """RenameProposal doit accepter str OU OpType pour op_type (backward compat)."""

    def test_with_str_literal_legacy(self) -> None:
        # Ancien code passant une str litterale : doit toujours marcher
        rp = RenameProposal(
            src_path="/src/a.mkv",
            target_path="/dst/a.mkv",
            op_type="RENAME",
        )
        self.assertEqual(rp.op_type, "RENAME")
        self.assertEqual(rp.op_type, OpType.RENAME)

    def test_with_op_type_constant_legacy(self) -> None:
        # Ancien code passant OP_TYPE_RENAME : doit toujours marcher
        rp = RenameProposal(
            src_path="/src/a.mkv",
            target_path="/dst/a.mkv",
            op_type=OP_TYPE_MOVE,
        )
        self.assertEqual(rp.op_type, "MOVE")

    def test_with_op_type_enum_member(self) -> None:
        # Nouveau code passant OpType.RENAME : marche grace a StrEnum
        rp = RenameProposal(
            src_path="/src/a.mkv",
            target_path="/dst/a.mkv",
            op_type=OpType.NOOP,
        )
        self.assertEqual(rp.op_type, "NOOP")
        self.assertEqual(rp.op_type, OpType.NOOP)


class OpTypeExportedInAllTests(unittest.TestCase):
    """__all__ doit exposer OpType en plus des alias existants."""

    def test_op_type_in_all(self) -> None:
        self.assertIn("OpType", probe_models.__all__)

    def test_backward_compat_aliases_still_in_all(self) -> None:
        self.assertIn("OP_TYPE_RENAME", probe_models.__all__)
        self.assertIn("OP_TYPE_MOVE", probe_models.__all__)
        self.assertIn("OP_TYPE_NOOP", probe_models.__all__)
        self.assertIn("OP_TYPE_VALUES", probe_models.__all__)


if __name__ == "__main__":
    unittest.main()
