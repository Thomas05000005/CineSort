"""R8 F5 — DIFFERENTIEL R8-057 (DUP-DECISION) + R8-059 (DUP1 codec/résolution/audio).

R8-057 : check_duplicates ne relisait jamais la décision -> badge « Décidé » disparaît
au refresh (decidedCount=0). Fix : _annotate_groups_with_decisions joint la décision
persistée (winner_decided/winner_side).
R8-059 : _quality_info_for_row ne renvoyait que {score,tier} ; doublons.js lit
qualityA.codec/.resolution/.audio_codec -> lignes jamais affichées. Fix : enrichi depuis le probe.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f5_doublons_diff.py
"""

from __future__ import annotations

import json
import types

from cinesort.ui.api.run_flow_support import _annotate_groups_with_decisions, _quality_info_for_row


def run():
    results = {}

    # ===== R8-057 : annotation des décisions =====
    decisions = [{"group_key": "k1", "winner_row_id": "r1", "loser_row_ids": ["r2"]}]
    store = types.SimpleNamespace(apply=types.SimpleNamespace(list_duplicate_decisions=lambda run_id: decisions))
    data = {
        "groups": [
            {"group_key": "k1", "rows": [{"row_id": "r1"}, {"row_id": "r2"}]},
            {"group_key": "k2", "rows": [{"row_id": "r3"}, {"row_id": "r4"}]},  # pas de décision
        ]
    }
    # AVANT : aucune annotation (le helper n'existait pas) -> winner_decided absent.
    avant_decided = "winner_decided" in data["groups"][0]
    _annotate_groups_with_decisions(data, "run1", store)
    g0, g1 = data["groups"]
    results["R8057_decided_annotated"] = (not avant_decided) and g0.get("winner_decided") is True
    results["R8057_winner_side_a"] = g0.get("winner_side") == "a"
    results["R8057_undecided_untouched"] = "winner_decided" not in g1
    print("=== R8-057 (DUP-DECISION) ===")
    print(f"  AVANT groupe décidé : winner_decided absent = {not avant_decided}")
    print(
        f"  APRÈS groupe k1 : winner_decided={g0.get('winner_decided')} winner_side={g0.get('winner_side')} winner_row_id={g0.get('winner_row_id')}"
    )
    print(f"  groupe k2 (sans décision) : winner_decided absent = {'winner_decided' not in g1}")

    # ===== R8-059 : codec/résolution/audio depuis le probe =====
    probe = {
        "video": {"codec": "hevc", "width": 1920, "height": 1080},
        "audio_tracks": [{"codec": "eac3", "channels": 6}],
    }
    avant = _quality_info_for_row(None, "run1", {"row_id": ""}, None)  # AVANT (probe=None)
    apres = _quality_info_for_row(None, "run1", {"row_id": ""}, probe)  # APRÈS (probe)
    results["R8059_avant_no_codec"] = "codec" not in avant
    results["R8059_apres_codec_res_audio"] = (
        apres.get("codec") == "hevc" and apres.get("resolution") == "1920x1080" and apres.get("audio_codec") == "eac3"
    )
    print("\n=== R8-059 (codec/résolution/audio) ===")
    print(f"  AVANT (sans probe) : {avant}  (pas de codec/résolution/audio)")
    print(f"  APRÈS (avec probe) : {apres}")

    allok = all(results.values())
    print(
        f"\nVERDICT : {'CORRIGE (décision visible au refresh + codec/résolution/audio affichés)' if allok else 'INCOMPLET'}"
    )
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
