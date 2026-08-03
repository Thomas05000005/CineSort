"""R8 F4 — DIFFERENTIEL R8-041 : une réponse TMDb vide n'empoisonne plus le cache.

Vecteur : search_movie cachait `[]` (200 + results=[]) ; `_cache_get` fait
`if cached is not None` (vrai pour []) -> servait [] pendant 7 jours -> film figé
« non identifié » à travers les re-scans après UN hoquet TMDb, même quand TMDb
répond ensuite. Fix : ne pas cacher une liste vide -> re-fetch au prochain appel.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_tmdb_cache_diff.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cinesort.infra.tmdb_client import TmdbClient


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _mk_client(tmp):
    return TmdbClient(api_key="fake-key", cache_path=tmp / "tmdb_cache.json", timeout_s=5.0)


def run():
    results = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # Stub HTTP contrôlable : 1er appel -> 200 vide, 2e appel -> 200 avec résultat.
        calls = {"n": 0}
        movie = {"id": 27205, "title": "Inception", "release_date": "2010-07-16", "poster_path": "/x.jpg"}

        def fake_http_get(url, *, params=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResp({"results": []})  # hoquet TMDb : 200 mais vide
            return _FakeResp({"results": [movie]})  # TMDb répond ensuite

        # ===== APRÈS (code corrigé) =====
        c = _mk_client(tmp)
        c._http_get = fake_http_get  # type: ignore[assignment]
        key = "search|fr-FR|inception|2010"

        r1 = c.search_movie("Inception", 2010)  # 1er : vide
        cached_after_empty = c._cache_get(key)
        r2 = c.search_movie("Inception", 2010)  # 2e : doit RE-FETCH

        apres_empty_not_cached = cached_after_empty is None
        apres_refetch_ok = len(r2) == 1 and r2[0].id == 27205
        apres_http_calls = calls["n"]
        results["R8041_empty_not_cached"] = apres_empty_not_cached
        results["R8041_refetch_recovers"] = apres_refetch_ok

        print("=== APRÈS (R8-041 corrigé) ===")
        print(f"  1er search (TMDb 200 vide)        : {len(r1)} résultats")
        print(f"  cache après vide                  : {cached_after_empty}  (attendu None -> non empoisonné)")
        print(
            f"  2e search (TMDb répond)           : {len(r2)} résultats, id={r2[0].id if r2 else None}  (RE-FETCH ok)"
        )
        print(
            f"  appels HTTP totaux                : {apres_http_calls}  (2 = re-fetch, pas servi depuis le cache vide)"
        )

        # ===== AVANT (réplique du bug : cacher la liste vide) =====
        c2 = _mk_client(tmp)
        c2._cache_set(key, [])  # AVANT : la réponse vide était cachée
        avant_served = c2._cache_get(key)  # `cached is not None` vrai pour []
        avant_poisons = avant_served == []  # servi [] -> film figé non identifié
        results["R8041_avant_poisons"] = avant_poisons
        print("\n=== AVANT (réplique : _cache_set(key, [])) ===")
        print(f"  cache après vide                  : {avant_served!r}  (servi [] -> EMPOISONNÉ 7 jours)")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (vide non caché, re-fetch récupère ; AVANT empoisonnait)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
