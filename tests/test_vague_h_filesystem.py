"""Tests Vague H filesystem (v1.5.3) - edge cases critiques systeme de fichiers.

Fix audit 2026-05-25 (v1.5.3) Vague H : 4 fixes filesystem.

Couvre :

1. ``apply_core.py`` : ``PermissionError`` lors d'un apply produit un message
   clair (nom du film + cause probable VLC/lecteur video) et alimente
   ``ApplyResult.error_messages`` pour remontee UI.

2. ``sqlite_store._check_integrity`` : ``PRAGMA wal_checkpoint(RESTART)`` est
   execute AVANT ``PRAGMA integrity_check`` pour flush le WAL et obtenir un
   check fiable (sans pages WAL non-mergees pouvant masquer une corruption).

3. ``app.main`` : ``InstanceLock.acquire()`` est appele AVANT la creation de
   ``CineSortApi`` (qui declenche ``SQLiteStore.initialize``). Garantit
   l'anti-corruption multi-instance.

4. ``apply_core.sha1_quick`` : timeout configurable (``max_seconds`` kwarg,
   defaut 30s) sur les lectures pour eviter les blocages indefinis sur SMB
   lent / NAS deconnecte ; retourne "" sur OSError/TimeoutError au lieu de
   propager. ``files_identical_quick`` traite "" comme "non identique" pour
   eviter une fusion incorrecte de deux fichiers illisibles.
"""

from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# FIX 1 - PermissionError -> message clair + error_messages
# ---------------------------------------------------------------------------


def _handler_exception_names(handler: ast.ExceptHandler) -> list[str]:
    """Noms d'exceptions attrapes par un `except`, tuple ou non (`[]` si nu)."""
    if handler.type is None:
        return []
    if isinstance(handler.type, ast.Tuple):
        return [ast.unparse(elt) for elt in handler.type.elts]
    return [ast.unparse(handler.type)]


class TestApplyPermissionErrorMessage(unittest.TestCase):
    """Vague H fix 1 : PermissionError lors d'un apply produit un message
    contextualise (nom du film + cause VLC) et alimente error_messages.
    """

    def test_apply_result_has_error_messages_field(self) -> None:
        """ApplyResult expose un champ ``error_messages`` (list) pour remontee UI."""
        from cinesort.domain.core import ApplyResult

        res = ApplyResult()
        self.assertTrue(hasattr(res, "error_messages"))
        self.assertEqual(res.error_messages, [])
        # Ecriture OK (mutable, pas un default partage entre instances).
        res.error_messages.append("test")
        res2 = ApplyResult()
        self.assertEqual(res2.error_messages, [])

    def test_apply_core_catches_permission_error_separately(self) -> None:
        """Le bloc try/except dans apply_rows catch PermissionError AVANT le catch
        generique OSError, et le handler PermissionError construit un message clair.
        """
        apply_core_path = Path(__file__).resolve().parent.parent / "cinesort" / "app" / "apply_core.py"
        source = apply_core_path.read_text(encoding="utf-8")

        # Le marqueur du fix Vague H doit etre present.
        self.assertIn("Vague H : message clair Windows file lock", source)

        # Le handler doit construire un message contenant "FICHIER VERROUILLE"
        # et "VLC".
        self.assertIn("FICHIER VERROUILLE", source)
        self.assertIn("VLC", source)

        # res.error_messages.append doit etre appele dans le handler.
        self.assertIn("res.error_messages.append", source)

        # Le handler `PermissionError` doit precede le fourre-tout `OSError`,
        # sinon il est MORT : `PermissionError` herite d'`OSError`, donc un
        # `except OSError` place avant l'attrape en premier et le message clair
        # ci-dessus n'est jamais construit.
        #
        # Verifie par AST, et handler par handler DANS LE MEME `try`. La version
        # d'origine comparait deux `source.find(...)` sur le fichier ENTIER : elle
        # aurait ete verte avec les deux handlers dans des `try` differents (donc
        # sans rien prouver), et elle tombait des que le texte exact du tuple
        # changeait (c'est arrive avec le nettoyage #585, qui n'a pourtant touche
        # ni l'ordre ni l'ensemble reellement attrape).
        checked = 0
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Try):
                continue
            caught = [_handler_exception_names(h) for h in node.handlers]
            perm = [i for i, names in enumerate(caught) if "PermissionError" in names]
            oserr = [i for i, names in enumerate(caught) if "OSError" in names]
            if not (perm and oserr):
                continue
            checked += 1
            self.assertLess(
                min(perm),
                min(oserr),
                msg=(
                    f"apply_core.py, try ligne {node.lineno} : le handler `OSError` precede "
                    "`PermissionError`, qui devient donc du code mort (PermissionError herite "
                    "d'OSError)."
                ),
            )
        # Anti-test-vacant : sans cette borne, supprimer les deux handlers rendrait
        # la boucle vide et le test vert.
        self.assertGreaterEqual(
            checked,
            5,
            msg=f"seulement {checked} try associent PermissionError et OSError dans apply_core.py (5 attendus)",
        )

    def test_apply_handler_simulated_permission_error_appends_message(self) -> None:
        """Simule directement la logique du handler : un PermissionError sur un
        folder donne doit produire un message contenant le nom du folder.
        """
        from cinesort.domain.core import ApplyResult

        res = ApplyResult()
        folder = Path("X:/Movies/My Locked Movie (2024)")

        # Reproduit la logique du handler (copie litterale du bloc Vague H).
        err_msg = (
            f"FICHIER VERROUILLE : '{folder.name}' est ouvert dans un autre logiciel "
            f"(VLC ? lecteur video ? indexeur Windows ?). Ferme-le et relance l'apply "
            f"pour ce film."
        )
        res.errors += 1
        res.error_messages.append(err_msg)

        self.assertEqual(res.errors, 1)
        self.assertEqual(len(res.error_messages), 1)
        self.assertIn("My Locked Movie (2024)", res.error_messages[0])
        self.assertIn("VLC", res.error_messages[0])


# ---------------------------------------------------------------------------
# FIX 2 - wal_checkpoint avant integrity_check
# ---------------------------------------------------------------------------


class TestWalCheckpointBeforeIntegrity(unittest.TestCase):
    """Vague H fix 2 : PRAGMA wal_checkpoint(RESTART) execute AVANT PRAGMA
    integrity_check pour garantir un check fiable (pas de pages WAL stale).
    """

    def test_check_integrity_runs_wal_checkpoint_first(self) -> None:
        """Mock la connexion et verifie l'ordre des PRAGMA executes."""
        from cinesort.infra.db import sqlite_store

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            # Cree un fichier vide pour que .is_file() retourne True.
            db_path.write_bytes(b"\x00")

            executed: list[str] = []

            class _FakeConn:
                def execute(self, sql: str) -> "_FakeCursor":
                    executed.append(sql)
                    return _FakeCursor(sql)

                def close(self) -> None:
                    pass

            class _FakeCursor:
                def __init__(self, sql: str) -> None:
                    self._sql = sql

                def fetchone(self) -> tuple:
                    if "integrity_check" in self._sql:
                        return ("ok",)
                    return (0,)

            store = sqlite_store.SQLiteStore.__new__(sqlite_store.SQLiteStore)
            store.db_path = db_path
            store._connect = lambda: _FakeConn()  # type: ignore[method-assign]

            status = store._check_integrity()

            self.assertEqual(status, "ok")
            # Le checkpoint doit etre execute, et AVANT integrity_check.
            self.assertEqual(len(executed), 2, f"Attendu 2 PRAGMA, recu {executed}")
            self.assertIn("wal_checkpoint", executed[0])
            self.assertIn("integrity_check", executed[1])
            self.assertLess(
                executed.index(next(s for s in executed if "wal_checkpoint" in s)),
                executed.index(next(s for s in executed if "integrity_check" in s)),
            )

    def test_check_integrity_tolerates_wal_checkpoint_failure(self) -> None:
        """Si le wal_checkpoint leve OperationalError (DB read-only, lock concurrent),
        on continue tout de meme avec integrity_check (best-effort)."""
        from cinesort.infra.db import sqlite_store

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            db_path.write_bytes(b"\x00")

            executed: list[str] = []

            class _FakeConn:
                def execute(self, sql: str):
                    executed.append(sql)
                    if "wal_checkpoint" in sql:
                        raise sqlite3.OperationalError("database is locked")
                    return _FakeCursor()

                def close(self) -> None:
                    pass

            class _FakeCursor:
                def fetchone(self) -> tuple:
                    return ("ok",)

            store = sqlite_store.SQLiteStore.__new__(sqlite_store.SQLiteStore)
            store.db_path = db_path
            store._connect = lambda: _FakeConn()  # type: ignore[method-assign]

            status = store._check_integrity()

            # Status doit etre "ok" : on a continue malgre l'echec du checkpoint.
            self.assertEqual(status, "ok")
            # Les deux PRAGMA ont ete tentes.
            self.assertEqual(len(executed), 2)
            self.assertIn("wal_checkpoint", executed[0])
            self.assertIn("integrity_check", executed[1])


# ---------------------------------------------------------------------------
# FIX 3 - InstanceLock appele AVANT SQLite init
# ---------------------------------------------------------------------------


class TestInstanceLockCalledFirst(unittest.TestCase):
    """Vague H fix 3 : InstanceLock.acquire() doit etre invoque AVANT
    CineSortApi() (qui declenche SQLiteStore.initialize). Analyse statique
    de app.py pour confirmer l'ordre.
    """

    def test_instance_lock_acquire_before_cinesortapi_construction(self) -> None:
        """Dans la fonction ``main()`` de app.py, le premier appel a
        ``instance_lock.acquire()`` doit apparaitre AVANT le premier appel a
        ``CineSortApi()`` dans le flux non-API.
        """
        app_path = Path(__file__).resolve().parent.parent / "app.py"
        source = app_path.read_text(encoding="utf-8")

        tree = ast.parse(source)
        main_fn = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                main_fn = node
                break
        self.assertIsNotNone(main_fn, "Fonction main() introuvable dans app.py")

        # On parcourt le corps de main() en cherchant l'apparition (par lineno)
        # du premier appel instance_lock.acquire() et de la premiere instanciation
        # CineSortApi().
        acquire_line: int | None = None
        cinesortapi_line: int | None = None

        for node in ast.walk(main_fn):  # type: ignore[arg-type]
            if isinstance(node, ast.Call):
                # instance_lock.acquire()
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "acquire":
                    val = func.value
                    if isinstance(val, ast.Name) and val.id == "instance_lock":
                        if acquire_line is None or node.lineno < acquire_line:
                            acquire_line = node.lineno
                # CineSortApi()
                if isinstance(func, ast.Name) and func.id == "CineSortApi":
                    if cinesortapi_line is None or node.lineno < cinesortapi_line:
                        cinesortapi_line = node.lineno

        self.assertIsNotNone(acquire_line, "instance_lock.acquire() introuvable")
        self.assertIsNotNone(cinesortapi_line, "CineSortApi() introuvable dans main()")
        self.assertLess(
            acquire_line,  # type: ignore[arg-type]
            cinesortapi_line,  # type: ignore[arg-type]
            f"InstanceLock.acquire() (L{acquire_line}) doit etre AVANT "
            f"CineSortApi() (L{cinesortapi_line}) pour eviter la corruption DB",
        )

    def test_vague_h_marker_present_in_app_main(self) -> None:
        """Le commentaire d'audit Vague H confirmant l'ordre doit etre present."""
        app_path = Path(__file__).resolve().parent.parent / "app.py"
        source = app_path.read_text(encoding="utf-8")
        self.assertIn(
            "Vague H : InstanceLock confirme avant",
            source,
            "Marqueur d'audit Vague H absent — l'ordre n'est plus garanti par le code",
        )


# ---------------------------------------------------------------------------
# FIX 4 - sha1_quick timeout + comportement OSError
# ---------------------------------------------------------------------------


class TestSha1QuickTimeout(unittest.TestCase):
    """Vague H fix 4 : sha1_quick accepte un kwarg max_seconds et retourne ""
    sur OSError/TimeoutError au lieu de propager. files_identical_quick traite
    "" comme "non identique" pour eviter une fusion fausse.
    """

    def test_signature_accepts_max_seconds_kwarg(self) -> None:
        """sha1_quick(path) reste valide, et sha1_quick(path, max_seconds=...) aussi."""
        import inspect

        from cinesort.app.apply_core import sha1_quick

        sig = inspect.signature(sha1_quick)
        self.assertIn("max_seconds", sig.parameters)
        param = sig.parameters["max_seconds"]
        # kwarg-only avec un defaut.
        self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(param.default, 30.0)

    def test_returns_empty_string_on_oserror(self) -> None:
        """Si path.stat() leve OSError (NAS deconnecte), retourne "" et logue."""
        from cinesort.app.apply_core import sha1_quick

        fake_path = MagicMock(spec=Path)
        fake_path.stat.side_effect = OSError("NAS unreachable")

        result = sha1_quick(fake_path)
        self.assertEqual(result, "")

    def test_returns_empty_string_on_timeout(self) -> None:
        """Si la lecture depasse max_seconds, on retourne "" (pas de TimeoutError
        propage). On simule en passant max_seconds=0 (immediatement expire)."""
        from cinesort.app.apply_core import sha1_quick

        # Cree un vrai petit fichier (< 16 MB -> branche "small file").
        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "tiny.bin"
            test_file.write_bytes(b"x" * 1024)

            # max_seconds=0 declenche le timeout des la premiere iteration de la
            # boucle de lecture.
            result = sha1_quick(test_file, max_seconds=0.0)
            self.assertEqual(result, "")

    def test_le_budget_EXACTEMENT_epuise_declenche_le_timeout(self) -> None:
        """Le test ci-dessus depend de l'HORLOGE REELLE ; celui-ci non.

        La garde s'ecrivait `time.monotonic() - start > max_seconds`. Une
        inegalite STRICTE rend le declenchement dependant de la GRANULARITE de
        l'horloge : sous Windows `time.monotonic()` a une resolution de
        15,625 ms, et deux lectures consecutives y rendent la MEME valeur dans
        100 % des cas (mesure : 200 000 tirages). `ecoule` vaut alors exactement
        `0.0`, et `0.0 > 0.0` est faux — le budget est epuise et la boucle lit
        quand meme.

        Mesure du defaut : `test_returns_empty_string_on_timeout` echouait
        19 fois sur 20 en local, et passait en CI. Un test qui depend du tick
        d'une horloge ne dit pas si le code est juste, il dit sur quelle machine
        il tourne.

        Ici l'horloge est FIGEE : le temps ne s'ecoule pas du tout, donc
        `ecoule == 0.0` a coup sur, et le seul comportement conforme est de
        traiter un budget de 0 comme epuise."""
        from cinesort.app import apply_core

        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "tiny.bin"
            test_file.write_bytes(b"x" * 1024)

            with patch.object(apply_core.time, "monotonic", return_value=1234.5):
                resultat = apply_core.sha1_quick(test_file, max_seconds=0.0)

        self.assertEqual(
            resultat,
            "",
            "budget de 0 s : le temps imparti est ecoule des le depart, "
            "l'egalite doit compter",
        )

    def test_un_budget_NON_nul_laisse_le_hash_se_calculer(self) -> None:
        """Contre-epreuve, sans laquelle « timeout toujours vrai » passerait le
        test precedent. L'horloge est figee ici aussi : `ecoule` vaut 0, donc un
        budget de 30 s n'est PAS epuise et le hash doit sortir."""
        from cinesort.app import apply_core

        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "tiny.bin"
            test_file.write_bytes(b"x" * 1024)

            with patch.object(apply_core.time, "monotonic", return_value=1234.5):
                resultat = apply_core.sha1_quick(test_file, max_seconds=30.0)

        self.assertEqual(len(resultat), 40, "un sha1 hexadecimal fait 40 caracteres")

    def test_normal_case_still_works(self) -> None:
        """Le cas nominal (fichier petit, lecture rapide) reste fonctionnel et
        renvoie un SHA-1 hexadecimal de 40 caracteres."""
        from cinesort.app.apply_core import sha1_quick

        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "tiny.bin"
            test_file.write_bytes(b"hello world")

            result = sha1_quick(test_file)
            self.assertEqual(len(result), 40)
            self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_files_identical_quick_treats_empty_hash_as_not_identical(self) -> None:
        """Si sha1_quick retourne "" pour l'un des deux fichiers, on doit
        renvoyer False (sinon "" == "" -> True declencherait une fusion fausse).
        """
        from cinesort.app import apply_core
        from cinesort.app.apply_core import files_identical_quick

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.bin"
            dst = Path(tmp) / "dst.bin"
            data = b"abc" * 100
            src.write_bytes(data)
            dst.write_bytes(data)

            # Sanity : sans patch, identiques -> True.
            self.assertTrue(files_identical_quick(src, dst))

            # Avec sha1_quick stubbe pour renvoyer "" sur src : False attendu.
            original = apply_core.sha1_quick

            def _stub_empty_src(path: Path, *, max_seconds: float = 30.0) -> str:
                if path == src:
                    return ""
                return original(path, max_seconds=max_seconds)

            with patch.object(apply_core, "sha1_quick", side_effect=_stub_empty_src):
                self.assertFalse(
                    files_identical_quick(src, dst),
                    "files_identical_quick devrait renvoyer False quand un hash est vide",
                )


if __name__ == "__main__":
    unittest.main()
