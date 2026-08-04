"""R8 F4 (filet) — DIFFERENTIELS des résidus survivants : R8-097 / R8-098 / R8-099.

- R8-097 : search_tv() cachait une réponse VIDE (jumeau exact de R8-041, jamais
  appliqué au TV) -> série figée « non identifiée » 7j. Fix : `if cache_items:`.
- R8-098 : clipping non mesuré (total_segments=0, verdict 'unknown') -> s_clip=90
  fabriqué (classe R8-034/035). Fix : gate `total_segments > 0`.
- R8-099 : _bitrate_label : seuil bps/kbps (classe R8-038) -> division /1000 inconditionnelle.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_filet_residuals_diff.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cinesort.domain.duplicate_compare import _bitrate_label
from cinesort.domain.perceptual.audio_perceptual import _compute_audio_score
from cinesort.infra.tmdb_client import TmdbClient


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def run():
    results = {}

    # ===== R8-097 : search_tv ne cache pas une réponse vide =====
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        calls = {"n": 0}
        show = {"id": 1399, "name": "Game of Thrones", "first_air_date": "2011-04-17"}

        def fake_http(url, *, params=None):
            calls["n"] += 1
            return _FakeResp({"results": []}) if calls["n"] == 1 else _FakeResp({"results": [show]})

        c = TmdbClient(api_key="fake", cache_path=tmp / "cache.json", timeout_s=5.0)
        c._http_get = fake_http  # type: ignore[assignment]
        key = "tv_search:game of thrones||fr-FR"
        c.search_tv("Game of Thrones")
        cached_after_empty = c._cache_get(key)
        r2 = c.search_tv("Game of Thrones")
        results["R8097_empty_not_cached"] = cached_after_empty is None
        results["R8097_refetch_recovers"] = len(r2) == 1 and r2[0].id == 1399
        print("=== R8-097 (search_tv, jumeau R8-041) ===")
        print(
            f"  cache après vide = {cached_after_empty} (None attendu) ; re-fetch = {len(r2)} résultat(s) id={r2[0].id if r2 else None}"
        )

    # ===== R8-098 : clipping non mesuré -> pas de s_clip=90 fabriqué =====
    clip_unmeasured = {"total_segments": 0, "clipping_segments": 0, "clipping_pct": 0.0, "verdict": "unknown"}
    clip_measured = {"total_segments": 100, "clipping_segments": 0, "clipping_pct": 0.0, "verdict": "clean"}
    score_unmeasured = _compute_audio_score(None, None, clip_unmeasured)
    score_measured = _compute_audio_score(None, None, clip_measured)
    # AVANT : les deux donnaient le MÊME score (s_clip=90 fabriqué pour l'unmeasured).
    # APRÈS : unmeasured -> s_clip=80 (neutre) < measured -> s_clip=90 -> score plus bas.
    results["R8098_unmeasured_lower_than_measured"] = score_unmeasured < score_measured
    print("\n=== R8-098 (clipping mesure du vide) ===")
    print(f"  clip non mesuré (total_segments=0) -> score audio {score_unmeasured}")
    print(f"  clip mesuré sans clipping          -> score audio {score_measured}")
    print(f"  -> non-mesuré n'est plus aussi flatteur que mesuré-parfait : {score_unmeasured < score_measured}")

    # ===== R8-099 : _bitrate_label divise bps inconditionnellement =====
    def _avant_label(br):
        kbps = br // 1000 if br > 10000 else br
        return f"{kbps // 1000} Mbps" if kbps >= 1000 else f"{kbps} kbps"

    av = _avant_label(8000)
    ap = _bitrate_label(8000)
    # AVANT traite 8000 comme 8000 kbps -> « 8 Mbps » (1000x faux) ; APRÈS « 8 kbps ».
    results["R8099_bps_divided"] = av == "8 Mbps" and ap == "8 kbps"
    # Cohérence débit élevé : 25 Mbps (25000000 bps) inchangé.
    results["R8099_high_unchanged"] = _avant_label(25_000_000) == _bitrate_label(25_000_000) == "25 Mbps"
    print("\n=== R8-099 (_bitrate_label bps/kbps) ===")
    print(f"  8000 bps : AVANT '{av}'  APRÈS '{ap}' ; 25 Mbps inchangé '{_bitrate_label(25_000_000)}'")

    allok = all(results.values())
    print(
        f"\nVERDICT : {'CORRIGE (3 résidus filet : cache TV, clipping vide, bitrate label)' if allok else 'INCOMPLET'}"
    )
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
