"""PREUVE F-H6-01 (rejouable) : divergence _best_audio quality vs compare -> audio sous-score.
Lancer : .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/h6_best_audio_divergence.py
Inclut le GATE de falsifiabilite (plant connu -> doit detecter) + le run sur corpus reel (copie RO)."""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.getcwd())
from cinesort.domain.duplicate_compare import _audio_codec_rank_value, _best_audio
from cinesort.domain.quality_score import _best_audio_track


def codec_rank(t):
    return _audio_codec_rank_value(t) or 0


def diverge(tracks):
    q = _best_audio_track(tracks)
    d = _best_audio({"audio_tracks": tracks})
    if not q or not d:
        return None
    rq, rd = codec_rank(q), codec_rank(d)
    return (
        {
            "q_codec": str(q.get("codec")),
            "q_ch": q.get("channels"),
            "q_rank": rq,
            "d_codec": str(d.get("codec")),
            "d_ch": d.get("channels"),
            "d_rank": rd,
        }
        if rq < rd
        else None
    )


# GATE 0.6
assert diverge(
    [{"codec": "truehd", "channels": 6, "bitrate": 600000}, {"codec": "aac", "channels": 8, "bitrate": 128000}]
)
assert diverge([{"codec": "truehd", "channels": 8, "bitrate": 600000}]) is None
print("GATE falsifiabilite OK")
# Derive de l'environnement : le chemin absolu d'origine portait un nom
# d'utilisateur REEL dans un depot PUBLIC, et ne valait que sur une machine.
db = str(Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "CineSort" / "db" / "cinesort.sqlite")
tmp = os.path.join(tempfile.gettempdir(), "cinesort_corpus_ro.sqlite")
shutil.copy2(db, tmp)
c = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
divs = []
multi = 0
for path, nj in c.execute("SELECT path,normalized_json FROM probe_cache WHERE normalized_json IS NOT NULL"):
    try:
        tracks = json.loads(nj).get("audio_tracks") or []
    except Exception:
        continue
    if len(tracks) >= 2:
        multi += 1
    h = diverge(tracks)
    if h:
        divs.append((os.path.basename(path), h))
c.close()
print(f"multi-pistes={multi} divergences={len(divs)}")
