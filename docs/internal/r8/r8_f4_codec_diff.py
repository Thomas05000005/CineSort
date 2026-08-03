"""R8 F4 — DIFFERENTIEL R8-039 : sélection de la meilleure piste audio (codec-aware).

Vecteur : _best_audio_track triait par (channels, bitrate) — CODEC-AVEUGLE. Sur un
film lossless + piste lossy compatible (mêmes canaux, bitrate lossy supérieur), il
choisissait la LOSSY -> étiquette codec fausse. Divergeait de
duplicate_compare._best_audio (codec_rank d'abord) : 113 films (h6_best_audio_divergence).

Fixture RÉELLE (PLAN A) : FLAC 6ch (lossless, rank 3, bitrate VBR N/A) + EAC3 6ch @640k
(lossy, rank 2, bitrate élevé). AVANT -> eac3 (faux) ; APRÈS -> flac (correct).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_codec_diff.py [ffprobe] [file.mkv]
"""

from __future__ import annotations

import json
import subprocess
import sys

from cinesort.domain.duplicate_compare import _best_audio as _dup_best_audio
from cinesort.domain.quality_score import _best_audio_track, _to_int


def _avant_best(tracks):
    """Réplique de l'ancien tri CODEC-AVEUGLE (channels, bitrate)."""
    if not tracks:
        return {}
    return max(tracks, key=lambda t: (_to_int(t.get("channels"), 0), _to_int(t.get("bitrate"), 0)))


def _probe_tracks(ffprobe, path):
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_name,channels,bit_rate",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
    )
    streams = json.loads(out.stdout).get("streams", [])
    tracks = []
    for s in streams:
        br = s.get("bit_rate")
        tracks.append(
            {
                "codec": s.get("codec_name"),
                "channels": s.get("channels"),
                "bitrate": int(br) if (br and str(br).isdigit()) else None,
            }
        )
    return tracks


def run(ffprobe=None, path=None):
    if ffprobe and path:
        tracks = _probe_tracks(ffprobe, path)
        src = f"RÉEL ({path})"
    else:
        # Fallback synthétique (TrueHD lossless vs EAC3 lossy, mêmes canaux).
        tracks = [
            {"codec": "truehd", "channels": 8, "bitrate": None},
            {"codec": "eac3", "channels": 8, "bitrate": 1024000},
        ]
        src = "synthétique (truehd vs eac3)"

    av = _avant_best(tracks)
    ap = _best_audio_track(tracks)
    dup = _dup_best_audio({"audio_tracks": tracks})

    av_codec = (av or {}).get("codec")
    ap_codec = (ap or {}).get("codec")
    dup_codec = (dup or {}).get("codec")

    print(f"=== R8-039 — pistes {src} ===")
    for t in tracks:
        print(f"  codec={t['codec']:6} channels={t['channels']} bitrate={t['bitrate']}")
    print(f"  AVANT (channels,bitrate)        -> {av_codec}")
    print(f"  APRÈS (codec_rank,channels,br)  -> {ap_codec}")
    print(f"  duplicate_compare._best_audio   -> {dup_codec}")

    # Le lossless attendu = la piste de plus haut rang codec.
    from cinesort.domain.codec_ranks import AUDIO_CODEC_RANK

    expected = max(tracks, key=lambda t: AUDIO_CODEC_RANK.get(str(t.get("codec") or "").lower(), 0)).get("codec")

    results = {
        "R8039_avant_picks_lossy": av_codec != expected,  # AVANT se trompe
        "R8039_apres_picks_lossless": ap_codec == expected,  # APRÈS correct
        "R8039_agrees_with_dup": ap_codec == dup_codec,  # plus de divergence
    }
    print(f"  attendu (plus haut rang) = {expected}")
    allok = all(results.values())
    print(
        f"\nVERDICT : {'CORRIGE (APRÈS = lossless = duplicate_compare ; AVANT prenait la lossy)' if allok else 'INCOMPLET'}"
    )
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    run(a[0] if len(a) > 0 else None, a[1] if len(a) > 1 else None)
