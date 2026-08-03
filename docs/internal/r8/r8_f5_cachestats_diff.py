"""R8 F5 — DIFFERENTIEL R8-060 : round-trip du snapshot de stats de scan (cache incrémental).

Vecteur : stats_snapshot_for_cache OMETTAIT 6 compteurs (tv_episodes_seen,
root_level_films_seen, films_rejected_ext/size/name, folders_rejected_scandir_error)
-> sur cache HIT incrémental, la contribution des dossiers cachés était PERDUE
(Diagnostic scan sous-compte + warning « films à la racine » supprimé à tort).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f5_cachestats_diff.py
"""

from __future__ import annotations

import json

from cinesort.app.plan_support_core import (
    stats_apply_cached_delta,
    stats_delta_for_cache,
    stats_snapshot_for_cache,
)
from cinesort.domain.core import Stats

OMITTED = [
    "tv_episodes_seen",
    "root_level_films_seen",
    "films_rejected_ext",
    "films_rejected_size",
    "films_rejected_name",
    "folders_rejected_scandir_error",
]


def _avant_snapshot(stats):
    """Réplique de l'ancien snapshot (sans les 6 champs omis)."""
    snap = stats_snapshot_for_cache(stats)
    for k in OMITTED:
        snap.pop(k, None)
    return snap


def run():
    results = {}
    # Stats des dossiers "cachés" à reporter au round-trip.
    cached = Stats()
    cached.tv_episodes_seen = 5
    cached.root_level_films_seen = 3
    cached.films_rejected_ext = 2
    cached.films_rejected_size = 1
    cached.films_rejected_name = 4
    cached.folders_rejected_scandir_error = 7
    cached.folders_scanned = 10  # champ déjà présent (témoin)

    def _round_trip(snapshot_fn):
        snap = snapshot_fn(cached)
        delta = stats_delta_for_cache({}, snap)  # delta vs before vide = valeurs cachées
        fresh = Stats()
        stats_apply_cached_delta(fresh, delta)
        return fresh

    avant = _round_trip(_avant_snapshot)
    apres = _round_trip(stats_snapshot_for_cache)

    print("=== R8-060 : round-trip snapshot -> delta -> apply ===")
    print(f"{'champ':32} {'caché':>6} {'AVANT':>6} {'APRÈS':>6}")
    avant_lost = []
    apres_kept = True
    for k in OMITTED:
        cv = getattr(cached, k)
        av = getattr(avant, k)
        ap = getattr(apres, k)
        if av != cv:
            avant_lost.append(k)
        if ap != cv:
            apres_kept = False
        print(f"{k:32} {cv:>6} {av:>6} {ap:>6}")
    # Témoin : folders_scanned (déjà présent) préservé dans les deux.
    print(
        f"{'folders_scanned (témoin)':32} {cached.folders_scanned:>6} {avant.folders_scanned:>6} {apres.folders_scanned:>6}"
    )

    results["R8060_avant_loses_fields"] = len(avant_lost) == len(OMITTED)  # tous perdus AVANT
    results["R8060_apres_preserves_all"] = apres_kept
    print(f"\n  AVANT : {len(avant_lost)}/{len(OMITTED)} compteurs PERDUS au round-trip")
    print(f"  APRÈS : tous préservés = {apres_kept}")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (round-trip sans perte)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
