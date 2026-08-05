"""GATE #637 — `folder_signature` ne fait plus 3 `stat()` par video, mais 1.

Chaine d'appels avant correctif, pour CHAQUE fichier video d'un dossier :
  1. `entry.stat(follow_symlinks=False)` dans `folder_signature` — deja fait,
     et gratuit sous Windows (metadonnees ramenees par le listing `os.scandir`) ;
  2. `path.stat()` en tete de `resolve_incremental_quick_hash` ;
  3. `path.stat()` a nouveau dans `quick_hash_cache_key(path)`.

2 et 3 sont des SYSCALLS `os.stat` reels : sur SMB/NAS chacun est un aller-retour
reseau, et ils tombent AVANT le hit de cache, donc le cache ne les evite pas.

Grandeur mesuree : le nombre d'appels a `os.stat` (deterministe), pas des
millisecondes. `entry.stat` etant une methode C de `os.DirEntry`, elle n'entre
pas dans ce compte — c'est voulu : le compte isole exactement les syscalls
redondants. Mesure sur DEUX tailles, donc la loi d'echelle est constatee, pas
extrapolee :

    videos | hash deja en cache : avant -> apres | hash a calculer : avant -> apres
    -------+-------------------------------------+---------------------------------
         3 |                    6 -> 0           |               9 -> 3
        12 |                   24 -> 0           |              36 -> 12

Sur le scenario "hash a calculer", aucun test double n'intervient : le `1` qui
reste par video est le `stat()` que `sha1_quick` fait lui-meme pour decider de
sa strategie de lecture.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional, Tuple

from cinesort.app.apply_core import quick_hash_cache_key, sha1_quick
from cinesort.app.plan_support_core import folder_signature, resolve_incremental_quick_hash


class _CachedScanIndex:
    """Index de scan qui repond TOUJOURS depuis son cache.

    Il ne fabrique pas le verdict du test : les deux `stat()` traques tombaient,
    dans l'ancien code, AVANT toute consultation de cet index (c'est le coeur du
    finding #637). Mesure de controle : avec l'ancien code et ce meme double,
    le compte valait 2 x nb_videos, pas 0.
    """

    def __init__(self, digest: str) -> None:
        self.digest = digest
        self.upserts = 0

    def get_incremental_file_hash(self, *, path: str, size: int, mtime_ns: int) -> str:
        return self.digest

    def upsert_incremental_file_hash(self, **kwargs: Any) -> None:
        self.upserts += 1


class _RowCacheScanIndex(_CachedScanIndex):
    """Ajoute au double precedent les deux methodes du cache de lignes v2."""

    def __init__(self, digest: str) -> None:
        super().__init__(digest)
        self.stored = 0

    def get_incremental_row_cache(self, **kwargs: Any) -> None:
        return None

    def upsert_incremental_row_cache(self, **kwargs: Any) -> None:
        self.stored += 1


@contextlib.contextmanager
def _count_os_stat() -> Iterator[List[int]]:
    """Compte les appels a `os.stat` (que `Path.stat()` resout a l'execution)."""
    counter = [0]
    real_stat = os.stat

    def counting(*args: Any, **kwargs: Any) -> Any:
        counter[0] += 1
        return real_stat(*args, **kwargs)

    os.stat = counting  # type: ignore[assignment]
    try:
        yield counter
    finally:
        os.stat = real_stat  # type: ignore[assignment]


class FolderSignatureStatBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_p637_"))
        self.cfg = SimpleNamespace(video_exts={".mkv"})

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_folder(self, name: str, videos: int) -> Tuple[Path, List[Path]]:
        folder = self._tmp / name
        folder.mkdir(parents=True)
        paths: List[Path] = []
        for i in range(videos):
            video = folder / f"film_{i}.mkv"
            video.write_bytes(b"v" * (256 + i))
            paths.append(video)
        # Un fichier non-video : il ne doit declencher aucun quick-hash.
        (folder / "movie.nfo").write_bytes(b"<nfo/>")
        return folder, paths

    def _stats_for(self, videos: int, *, scan_index: Optional[Any]) -> int:
        folder, _paths = self._make_folder(f"n{videos}_{'idx' if scan_index else 'raw'}", videos)
        run_hash_cache: Dict[Tuple[str, int, int], str] = {}
        with _count_os_stat() as counter:
            folder_signature(self.cfg, folder, scan_index=scan_index, run_hash_cache=run_hash_cache)
        return counter[0]

    def test_aucun_stat_redondant_quand_le_hash_est_deja_connu(self) -> None:
        measured = {n: self._stats_for(n, scan_index=_CachedScanIndex("cafe" * 10)) for n in (3, 12)}
        self.assertEqual(measured[3], 0, "3 videos ne doivent declencher aucun os.stat redondant")
        self.assertEqual(measured[12], 0, "12 videos non plus — le cout ne doit pas croitre")

    def test_un_seul_stat_par_video_quand_le_hash_doit_etre_calcule(self) -> None:
        measured = {n: self._stats_for(n, scan_index=None) for n in (3, 12)}
        # Le stat restant est celui de `sha1_quick` lui-meme (1 par video).
        self.assertEqual(measured[3], 3)
        self.assertEqual(measured[12], 12)
        self.assertEqual(measured[12], 4 * measured[3], "la loi d'echelle doit rester lineaire a 1 stat/video")


class ResolveIncrementalQuickHashStatBudgetTests(unittest.TestCase):
    """Le helper lui-meme ne doit plus stater deux fois quand il stat.

    `folder_signature` n'est pas son seul appelant : `plan_support_replan`
    l'invoque au lookup ET a l'ecriture du cache de lignes, une fois par video de
    scan. Sans ce test, la deduplication interne (`path.stat()` puis
    `quick_hash_cache_key(path)` qui restatait) resterait non couverte — le
    budget mesure sur `folder_signature` ne l'exerce plus, puisqu'il transmet
    desormais son propre stat.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_p637r_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _videos(self, count: int) -> List[Path]:
        paths = []
        for i in range(count):
            video = self._tmp / f"solo_{count}_{i}.mkv"
            video.write_bytes(b"r" * (128 + i))
            paths.append(video)
        return paths

    def _stats_for(self, count: int, *, scan_index: Optional[Any]) -> int:
        videos = self._videos(count)
        run_hash_cache: Dict[Tuple[str, int, int], str] = {}
        with _count_os_stat() as counter:
            for video in videos:
                resolve_incremental_quick_hash(video, scan_index=scan_index, run_hash_cache=run_hash_cache)
        return counter[0]

    def test_un_stat_par_fichier_quand_le_hash_est_deja_connu(self) -> None:
        measured = {n: self._stats_for(n, scan_index=_CachedScanIndex("beef" * 10)) for n in (2, 8)}
        self.assertEqual(measured[2], 2, "1 stat par fichier, pas 2")
        self.assertEqual(measured[8], 8)

    def test_deux_stats_par_fichier_quand_le_hash_doit_etre_calcule(self) -> None:
        measured = {n: self._stats_for(n, scan_index=None) for n in (2, 8)}
        # 1 stat pour la clef de cache + 1 stat interne a `sha1_quick`.
        self.assertEqual(measured[2], 4)
        self.assertEqual(measured[8], 16)


class RowCacheStatBudgetTests(unittest.TestCase):
    """Les deux sites du cache de lignes v2 transmettent aussi leur `stat()`.

    `_try_lookup_row_cache` et `_store_row_cache` sont appeles UNE FOIS PAR VIDEO
    a chaque scan, et faisaient chacun `video.stat()` juste avant d'appeler
    `resolve_incremental_quick_hash`, qui restatait le meme fichier. Ici le
    `stat()` de l'appelant suit les liens, exactement comme celui du helper : il
    est donc transmissible sans condition (contrairement au lstat de `scandir`).
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_p637rc_"))
        self.folder = self._tmp / "Film (2000)"
        self.folder.mkdir(parents=True)
        self.video = self.folder / "film.mkv"
        self.video.write_bytes(b"c" * 512)
        self.cfg = SimpleNamespace(
            root=str(self._tmp),
            video_exts={".mkv"},
            side_exts=set(),
            generic_side_files=set(),
        )
        self.index = _RowCacheScanIndex("cafe" * 10)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_lookup_ne_stat_plus_le_fichier_deux_fois(self) -> None:
        from cinesort.app.plan_support_replan import _try_lookup_row_cache

        with _count_os_stat() as counter:
            _try_lookup_row_cache(
                self.cfg,
                self.folder,
                self.video,
                kind="single",
                cfg_sig="sig",
                scan_index=self.index,
                run_hash_cache={},
                row_cache_stats={},
            )
        # 1 stat de la video (celui de l'appelant) + 1 pour la resolution du NFO.
        self.assertEqual(counter[0], 2)

    def test_store_ne_stat_plus_le_fichier_deux_fois(self) -> None:
        from cinesort.app.plan_support_replan import _store_row_cache
        from cinesort.domain.core import PlanRow

        row = PlanRow(
            row_id="S|1",
            kind="single",
            folder=str(self.folder),
            video=self.video.name,
            proposed_title="Film",
            proposed_year=2000,
            proposed_source="name",
            confidence=50,
            confidence_label="low",
            candidates=[],
        )
        with _count_os_stat() as counter:
            _store_row_cache(
                self.cfg,
                self.folder,
                self.video,
                None,
                row,
                kind="single",
                cfg_sig="sig",
                run_id="run1",
                scan_index=self.index,
                run_hash_cache={},
            )
        self.assertEqual(counter[0], 1, "seul le stat de l'appelant doit subsister")
        self.assertEqual(self.index.stored, 1, "la ligne doit bien avoir ete persistee")


class FolderSignatureCacheKeyEquivalenceTests(unittest.TestCase):
    """Le `stat` reutilise doit produire EXACTEMENT la meme clef qu'un `stat` frais.

    Sans ce verrou, l'economie de syscalls pourrait scinder le cache de quick-hash
    en deux jeux de clefs et faire rehacher tous les fichiers a chaque scan — une
    "optimisation" qui coute plus qu'elle ne rapporte, en restant verte.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_p637k_"))
        self.cfg = SimpleNamespace(video_exts={".mkv"})

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_clef_et_valeur_identiques_au_calcul_direct(self) -> None:
        folder = self._tmp / "lib"
        folder.mkdir(parents=True)
        videos = []
        for i in range(3):
            video = folder / f"film_{i}.mkv"
            video.write_bytes(b"z" * (512 + i))
            videos.append(video)

        run_hash_cache: Dict[Tuple[str, int, int], str] = {}
        folder_signature(self.cfg, folder, scan_index=None, run_hash_cache=run_hash_cache)

        expected = {}
        for video in videos:
            key = quick_hash_cache_key(video)
            self.assertIsNotNone(key)
            expected[key] = sha1_quick(video)
        self.assertEqual(run_hash_cache, expected)

    def test_lien_symbolique_indexe_sur_le_stat_de_la_cible(self) -> None:
        """Un lien symbolique doit rester indexe sur size/mtime de sa CIBLE.

        `entry.stat(follow_symlinks=False)` est un LSTAT : il decrit le LIEN
        (taille 0 sous Windows), alors que le quick-hash lit la cible. Reutiliser
        ce lstat figerait le hash de la cible sur les metadonnees du lien : une
        cible modifiee ne serait plus jamais rehachee.
        """
        target_dir = self._tmp / "targets"
        target_dir.mkdir(parents=True)
        target = target_dir / "reel.mkv"
        target.write_bytes(b"t" * 4096)

        folder = self._tmp / "lib_link"
        folder.mkdir(parents=True)
        link = folder / "film.mkv"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - depend du poste
            raise unittest.SkipTest(f"creation de lien symbolique impossible ici: {exc}") from exc

        lstat = os.lstat(link)
        stat_target = os.stat(link)
        if (lstat.st_size, lstat.st_mtime_ns) == (stat_target.st_size, stat_target.st_mtime_ns):
            raise unittest.SkipTest("lstat et stat identiques sur ce systeme de fichiers : garde non observable")

        run_hash_cache: Dict[Tuple[str, int, int], str] = {}
        folder_signature(self.cfg, folder, scan_index=None, run_hash_cache=run_hash_cache)

        expected_key = quick_hash_cache_key(link)
        self.assertEqual(list(run_hash_cache.keys()), [expected_key])
        self.assertEqual(run_hash_cache[expected_key], sha1_quick(link))


if __name__ == "__main__":
    unittest.main()
