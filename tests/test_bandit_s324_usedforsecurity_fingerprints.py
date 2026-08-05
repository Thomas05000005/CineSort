"""bandit S324/B324 — les empreintes SHA-1 de `cinesort/app/` doivent porter
`usedforsecurity=False`.

Les 5 appels concernes (`sha1_quick`, `cfg_signature_for_incremental`,
`_nfo_signature`, `folder_signature` x2) sont des empreintes de CONTENU pour le
cache / le dedup incremental, jamais des hachages de securite. Sans le kwarg :

- bandit les remonte (B324) dans l'onglet Security a chaque scan ;
- ils LEVENT une exception sur un interpreteur dont OpenSSL est en mode FIPS
  (SHA-1 y est interdit pour un usage « securite »).

Ce module verrouille les deux moitiés de l'affirmation :

1. `Sha1FipsModeTests` : on simule le mode FIPS (un `hashlib.sha1` qui refuse
   tout appel non annote) et on exerce les 5 sites REELLEMENT. C'est la preuve
   comportementale — retirer le kwarg fait tomber ces tests.
2. `Sha1AnnotationSourceTests` : garde statique (AST) sur le nombre et
   l'emplacement des sites, pour qu'un nouvel appel nu ne se glisse pas.
3. `Sha1DigestUnchangedTests` : NON-REGRESSION — `usedforsecurity=False` ne
   change pas le digest. Ces assertions restent VERTES avec ou sans le kwarg,
   elles prouvent que le correctif est purement additif.

Le kwarg `usedforsecurity` existe sur tous les constructeurs `hashlib` depuis
Python 3.9 (verifie a l'execution en 3.12 et 3.13) : aucun risque de
compatibilite sur les runtimes cibles.
"""

from __future__ import annotations

import ast
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Set, Tuple
from unittest import mock

import cinesort.app.plan_support_core as plan_support_core
import cinesort.domain.core as core
from cinesort.app.apply_core import sha1_quick
from cinesort.app.plan_support_core import (
    _nfo_signature,
    cfg_signature_for_incremental,
    folder_signature,
)

_REAL_SHA1 = hashlib.sha1

# Constructeurs `hashlib` que bandit remonte en B324 (hachages « faibles »).
_WEAK_CONSTRUCTORS = frozenset({"sha1", "sha", "md5", "md4", "new"})

# Les 5 sites du correctif : fichier -> {fonction englobante: nombre d'appels}.
_EXPECTED_ANNOTATED: Dict[str, Dict[str, int]] = {
    "cinesort/app/apply_core.py": {"sha1_quick": 1},
    "cinesort/app/plan_support_core.py": {
        "cfg_signature_for_incremental": 1,
        "_nfo_signature": 1,
        # 2 -> 1 le 2026-08-05 (#696) : la branche `except OSError` ne hache
        # PLUS. Elle rendait `sha1(b"")`, exactement la signature d'un dossier
        # VIDE — un dossier peuple momentanement illisible heritait donc de
        # cette signature et pouvait etre servi depuis le cache incremental,
        # faisant DISPARAITRE ses films du plan sans aucun log. Le sentinel est
        # devenu None : pas de hachage, donc plus de site a annoter ici.
        "folder_signature": 1,
    },
}

# Exception ASSUMEE et hors perimetre de ce correctif :
# `_tmdb_api_key_fingerprint` hache une cle API TMDb pour ne PAS la stocker en
# clair dans la signature de cache. C'est le seul site dont l'usage a une
# dimension securite reelle (non-reversibilite d'un secret) : y coller
# `usedforsecurity=False` serait une etiquette mensongere. Arbitrage a trancher
# separement (migration vers sha256 plutot qu'annotation).
# Assertion en SOUS-ENSEMBLE : annoter/corriger ce site plus tard ne cassera pas
# ce test, mais tout NOUVEL appel nu le fera tomber.
_TOLERATED_BARE = frozenset({"_tmdb_api_key_fingerprint"})


def _fips_sha1(*args: object, **kwargs: object):
    """`hashlib.sha1` d'un interpreteur en mode FIPS : refuse l'usage securite.

    Reproduit le comportement d'OpenSSL en mode FIPS, ou seul un appel
    explicitement marque `usedforsecurity=False` est autorise.
    """
    if kwargs.get("usedforsecurity", True) is not False:
        raise ValueError("[FIPS] SHA-1 interdit sans usedforsecurity=False")
    return _REAL_SHA1(*args)  # type: ignore[arg-type]


def _is_weak_hashlib_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "hashlib"
        and node.func.attr in _WEAK_CONSTRUCTORS
    )


def _is_annotated(node: ast.Call) -> bool:
    return any(
        kw.arg == "usedforsecurity" and isinstance(kw.value, ast.Constant) and kw.value.value is False
        for kw in node.keywords
    )


def _weak_hash_sites(path: Path) -> List[Tuple[str, bool]]:
    """Retourne [(fonction englobante, annote?)] pour chaque appel faible."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner: Dict[ast.Call, Tuple[int, str]] = {}
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if not _is_weak_hashlib_call(node):
                continue
            assert isinstance(node, ast.Call)
            previous = owner.get(node)
            # Fonction imbriquee la plus PROCHE = celle qui commence le plus tard.
            if previous is None or func.lineno > previous[0]:
                owner[node] = (func.lineno, func.name)
    return [(name, _is_annotated(call)) for call, (_lineno, name) in owner.items()]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class Sha1FipsModeTests(unittest.TestCase):
    """Preuve COMPORTEMENTALE : les 5 sites survivent a un SHA-1 FIPS."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_s324_fips_")
        self.tmp = Path(self._tmp)
        self.root = self.tmp / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        # `_nfo_signature` memoise (path, size, mtime_ns) -> sig : sans purge, un
        # hit de cache ferait passer le test SANS jamais appeler hashlib.
        plan_support_core._NFO_SIG_CACHE.clear()

    def tearDown(self) -> None:
        plan_support_core._NFO_SIG_CACHE.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> "core.Config":
        return core.Config(root=self.root).normalized()

    def test_sha1_quick_survit_au_mode_fips(self) -> None:
        target = self.tmp / "film.mkv"
        target.write_bytes(b"x" * 4096)
        with mock.patch.object(hashlib, "sha1", _fips_sha1):
            digest = sha1_quick(target)
        self.assertEqual(digest, _REAL_SHA1(b"x" * 4096).hexdigest())

    def test_cfg_signature_survit_au_mode_fips(self) -> None:
        cfg = self._cfg()
        with mock.patch.object(hashlib, "sha1", _fips_sha1):
            # tmdb_api_key=None : `_tmdb_api_key_fingerprint` sort avant de
            # hacher, on n'exerce que le site du correctif.
            signature = cfg_signature_for_incremental(cfg, tmdb_api_key=None)
        self.assertEqual(len(signature), 40)

    def test_nfo_signature_survit_au_mode_fips(self) -> None:
        nfo = self.tmp / "movie.nfo"
        nfo.write_bytes(b"<movie><title>Heat</title></movie>")
        with mock.patch.object(hashlib, "sha1", _fips_sha1):
            signature = _nfo_signature(nfo)
        self.assertEqual(signature, _REAL_SHA1(nfo.read_bytes()).hexdigest())

    def test_folder_signature_survit_au_mode_fips(self) -> None:
        folder = self.tmp / "Heat (1995)"
        folder.mkdir(parents=True, exist_ok=True)
        # Fichier NON video : pas de quick-hash, on isole le sha1 final.
        (folder / "notes.txt").write_text("bonjour", encoding="utf-8")
        cfg = self._cfg()
        with mock.patch.object(hashlib, "sha1", _fips_sha1):
            signature = folder_signature(cfg, folder, scan_index=None)
        self.assertEqual(len(signature), 40)

    def test_folder_signature_fallback_scandir_ne_hache_plus_du_tout(self) -> None:
        """La branche `except OSError` ne hache plus : FIPS-safe par construction (#696).

        Elle rendait `sha1(b"")` — le 5e site annote. Ce n'etait pas seulement
        un site de hachage de trop, c'etait un BUG : cette valeur est aussi la
        signature d'un dossier VIDE, donc « inaccessible » et « vide » etaient
        indiscernables. Le sentinel est desormais None.

        On garde le mode FIPS actif dans ce test : il prouve que le chemin
        d'erreur n'appelle plus sha1 DU TOUT, pas seulement qu'il l'appelle
        correctement.
        """
        missing = self.tmp / "dossier_inexistant"
        cfg = self._cfg()
        with mock.patch.object(hashlib, "sha1", _fips_sha1):
            signature = folder_signature(cfg, missing, scan_index=None)
        self.assertIsNone(signature)


class Sha1AnnotationSourceTests(unittest.TestCase):
    """Garde STATIQUE : nombre et emplacement des sites annotes."""

    def test_les_cinq_sites_attendus_sont_annotes(self) -> None:
        for relative, expected in _EXPECTED_ANNOTATED.items():
            with self.subTest(fichier=relative):
                sites = _weak_hash_sites(_repo_root() / relative)
                annotated: Dict[str, int] = {}
                for name, is_annotated in sites:
                    if is_annotated:
                        annotated[name] = annotated.get(name, 0) + 1
                self.assertEqual(annotated, expected)

    def test_aucun_appel_nu_hors_exception_assumee(self) -> None:
        bare: Set[str] = set()
        for relative in _EXPECTED_ANNOTATED:
            for name, is_annotated in _weak_hash_sites(_repo_root() / relative):
                if not is_annotated:
                    bare.add(name)
        self.assertTrue(
            bare <= _TOLERATED_BARE,
            f"appel hashlib faible sans usedforsecurity=False : {sorted(bare - _TOLERATED_BARE)}",
        )

    def test_total_annote_vaut_quatre(self) -> None:
        """Etait CINQ jusqu'au 2026-08-05 : #696 a supprime un site, pas une annotation.

        La garde n'est pas affaiblie — elle compte toujours EXACTEMENT les
        appels de hachage faible, et un nouveau site non annote la fait rougir.
        Seule la valeur attendue suit la realite du code.
        """
        total = sum(sum(counts.values()) for counts in _EXPECTED_ANNOTATED.values())
        self.assertEqual(total, 4)
        measured = sum(
            1
            for relative in _EXPECTED_ANNOTATED
            for _name, is_annotated in _weak_hash_sites(_repo_root() / relative)
            if is_annotated
        )
        self.assertEqual(measured, 4)


class Sha1DigestUnchangedTests(unittest.TestCase):
    """NON-REGRESSION : le kwarg ne change AUCUN digest.

    Ces assertions sont vertes avec ET sans `usedforsecurity=False` : elles
    prouvent que le correctif est purement additif (aucun cache invalide, aucun
    dedup casse).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_s324_digest_")
        self.tmp = Path(self._tmp)
        self.root = self.tmp / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        plan_support_core._NFO_SIG_CACHE.clear()

    def tearDown(self) -> None:
        plan_support_core._NFO_SIG_CACHE.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_kwarg_ne_change_pas_le_digest_sha1(self) -> None:
        for payload in (b"", b"abc", b"x" * 4096):
            with self.subTest(taille=len(payload)):
                self.assertEqual(
                    hashlib.sha1(payload, usedforsecurity=False).hexdigest(),
                    hashlib.sha1(payload).hexdigest(),  # noqa: S324
                )

    def test_sha1_quick_reste_le_sha1_du_contenu(self) -> None:
        target = self.tmp / "film.mkv"
        target.write_bytes(b"contenu de reference")
        self.assertEqual(sha1_quick(target), _REAL_SHA1(b"contenu de reference").hexdigest())

    def test_nfo_signature_reste_le_sha1_du_fichier(self) -> None:
        nfo = self.tmp / "movie.nfo"
        nfo.write_bytes(b"<movie/>")
        self.assertEqual(_nfo_signature(nfo), _REAL_SHA1(b"<movie/>").hexdigest())

    def test_folder_signature_fallback_ne_vaut_PLUS_le_sha1_vide(self) -> None:
        """Ce test VERROUILLAIT le defaut #696 : il exigeait la collision.

        Il affirmait que le repli d'erreur DOIT valoir `sha1(b"")` — soit
        exactement la signature d'un dossier vide. Tant qu'il tenait, corriger
        la confusion faisait rougir la CI.

        Un dossier vide garde sa signature ; un dossier inaccessible n'en a
        aucune. C'est la distinction que ce test protege desormais.
        """
        cfg = core.Config(root=self.root).normalized()
        vide = self.tmp / "vraiment_vide"
        vide.mkdir()

        self.assertEqual(folder_signature(cfg, vide, scan_index=None), _REAL_SHA1(b"").hexdigest())
        self.assertIsNone(folder_signature(cfg, self.tmp / "absent", scan_index=None))


if __name__ == "__main__":
    unittest.main()
