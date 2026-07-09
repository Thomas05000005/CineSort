# -*- coding: utf-8 -*-
"""LOTD-ITERVIDEOS-KWARG — fallback iter_videos de resolve_media_path_for_row.

Garde unitaire du fix run_read_support.py : le fallback appelait
`core.iter_videos(cfg, folder)` sans le kwarg keyword-only OBLIGATOIRE
`min_video_bytes` (signature domain/scan_helpers.py) -> TypeError des que la
resolution directe echouait (fichier supprime/renomme apres le plan, row sans
nom video), y compris pendant l'auto-scoring d'un run nominal. Le TypeError
fuyait ensuite dans le message de get_quality_report au lieu d'une degradation
propre "media introuvable".

Verifie ici, directement sur resolve_media_path_for_row :
  1. le fallback fonctionne (plus de TypeError) et retourne la video du dossier ;
  2. le seuil vient bien de cfg.min_video_bytes (fichier trop petit -> None) ;
  3. cfg.min_video_bytes=None -> retombe sur core.MIN_VIDEO_BYTES (lu a l'appel,
     comme le patch runtime de test_reset) ;
  4. cfg.min_video_bytes invalide (non numerique) -> degrade en None, pas de
     ValueError/TypeError qui fuit.

Chaine e2e correspondante : tests/test_lotd_chain_rest.py::test_06 (xfail
nominative qui redevient PASS avec ce fix).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cinesort.domain.core as core
from cinesort.ui.api.run_read_support import resolve_media_path_for_row

_ENV_OFF = lambda _name: False  # noqa: E731 - stub minimal, pas de debug log


def _cfg(root: Path, **overrides):
    params = {"root": root, "video_exts": {".mkv"}}
    params.update(overrides)
    return core.Config(**params)


def _row(folder: Path, video: str) -> SimpleNamespace:
    return SimpleNamespace(folder=str(folder), video=video)


def _make_folder_with_video(tmp_path: Path, size: int = 64) -> Path:
    folder = tmp_path / "Film (2020)"
    folder.mkdir()
    (folder / "present.mkv").write_bytes(b"x" * size)
    return folder


def test_fallback_passes_min_video_bytes_kwarg(tmp_path):
    """Resolution directe en echec (video supprimee) -> fallback iter_videos OK."""
    folder = _make_folder_with_video(tmp_path)
    cfg = _cfg(tmp_path, min_video_bytes=1)
    row = _row(folder, "disparu.mkv")  # fichier renomme/supprime apres le plan

    result = resolve_media_path_for_row(
        SimpleNamespace(), cfg, row, env_truthy_fn=_ENV_OFF
    )

    assert result == folder / "present.mkv"


def test_fallback_threshold_comes_from_cfg(tmp_path):
    """Fichier sous cfg.min_video_bytes -> filtre -> None (media introuvable)."""
    folder = _make_folder_with_video(tmp_path, size=10)
    cfg = _cfg(tmp_path, min_video_bytes=1024)
    row = _row(folder, "disparu.mkv")

    result = resolve_media_path_for_row(
        SimpleNamespace(), cfg, row, env_truthy_fn=_ENV_OFF
    )

    assert result is None


def test_fallback_defaults_to_core_min_video_bytes(tmp_path, monkeypatch):
    """cfg.min_video_bytes=None -> core.MIN_VIDEO_BYTES lu au moment de l'appel
    (test_reset le patche en E2E, cf cinesort_api.py)."""
    folder = _make_folder_with_video(tmp_path, size=64)
    cfg = _cfg(tmp_path, min_video_bytes=None)
    row = _row(folder, "disparu.mkv")

    monkeypatch.setattr(core, "MIN_VIDEO_BYTES", 1)
    assert resolve_media_path_for_row(
        SimpleNamespace(), cfg, row, env_truthy_fn=_ENV_OFF
    ) == folder / "present.mkv"

    monkeypatch.setattr(core, "MIN_VIDEO_BYTES", 1024)
    assert (
        resolve_media_path_for_row(SimpleNamespace(), cfg, row, env_truthy_fn=_ENV_OFF)
        is None
    )


def test_fallback_invalid_min_video_bytes_degrades_to_none(tmp_path):
    """cfg.min_video_bytes non numerique : degradation propre en None, aucune
    exception ne fuit vers le boundary (except elargi a TypeError/ValueError)."""
    folder = _make_folder_with_video(tmp_path)
    cfg = _cfg(tmp_path, min_video_bytes="pas-un-nombre")
    row = _row(folder, "disparu.mkv")

    result = resolve_media_path_for_row(
        SimpleNamespace(), cfg, row, env_truthy_fn=_ENV_OFF
    )

    assert result is None
