"""R8 F4 — INSTRUMENTATION PERCEPTUELLE RÉELLE (PLAN A, vrai ffmpeg 8.1.1).

Appelle le VRAI pipeline (analyze_loudnorm, analyze_astats, run_filter_graph) sur des
fixtures vidéo RÉELLES — JAMAIS le mock. Démontre R8-034/035/036 :
  AVANT : loudnorm=None (R8-034), crest/dynrange=None (R8-035), block_mean=blur_mean=0
          -> _score_blockiness(0)=95, _score_blur(0)=95 (mesure du VIDE, fabriqué).
  APRÈS : valeurs RÉELLES, non nulles, DISCRIMINANTES (clean != dégradé) et MONOTONES.

Relations métamorphiques (pas d'oracle absolu) :
  (i) invariance  : même fichier ré-encodé identique -> mesures ~stables.
  (ii) monotonie  : fichier dégradé -> block/blur plus élevés.
  (iii) discrimination : deux fichiers distincts -> mesures distinctes.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_perceptual_instr.py <ffmpeg> <fix1.mp4> <fix2.mp4> ...
"""
from __future__ import annotations
import json
import shutil
import sys

from cinesort.domain.perceptual.audio_perceptual import analyze_loudnorm, analyze_astats
from cinesort.domain.perceptual import video_analysis as VA


def analyze_one(ffmpeg: str, media: str, duration_s: float = 4.0):
    loud = analyze_loudnorm(ffmpeg, media, 0)
    astats = analyze_astats(ffmpeg, media, 0)
    frames = VA.run_filter_graph(ffmpeg, media, duration_s, sample_count=40)

    # Agréger comme le fait le pipeline réel.
    vp = VA.VideoPerceptual()
    VA._aggregate_filter_metrics(vp, frames)
    s_block = VA._score_blockiness(vp.blockiness_mean)
    s_blur = VA._score_blur(vp.blur_mean)
    return {
        "frames_parsed": len(frames),
        "loudnorm_il": (loud or {}).get("integrated_loudness"),
        "loudnorm_lra": (loud or {}).get("loudness_range"),
        "crest_factor": (astats or {}).get("crest_factor"),
        "dynamic_range": (astats or {}).get("dynamic_range"),
        "blockiness_mean": round(vp.blockiness_mean, 4),
        "blur_mean": round(vp.blur_mean, 4),
        "score_blockiness": s_block,
        "score_blur": s_blur,
    }


def run(ffmpeg, fixtures):
    if not ffmpeg or ffmpeg == "auto":
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    print(f"ffmpeg = {ffmpeg}\n")
    results = {}
    for fx in fixtures:
        name = fx.replace("\\", "/").rsplit("/", 1)[-1]
        r = analyze_one(ffmpeg, fx)
        results[name] = r
        print(f"=== {name} ===")
        print(f"  frames_parsés       : {r['frames_parsed']}  (AVANT=0 -> mesure du vide)")
        print(f"  loudnorm IL / LRA   : {r['loudnorm_il']} / {r['loudnorm_lra']}  (R8-034 ; AVANT=None)")
        print(f"  crest / dynrange    : {r['crest_factor']} / {r['dynamic_range']}  (R8-035 ; AVANT=None)")
        print(f"  block_mean / score  : {r['blockiness_mean']} -> {r['score_blockiness']}  (R8-036 ; AVANT 0->95)")
        print(f"  blur_mean  / score  : {r['blur_mean']} -> {r['score_blur']}  (R8-036 ; AVANT 0->95)")
        print()
    print("RESUME:", json.dumps(results, ensure_ascii=False))
    return results


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print("usage: <ffmpeg|auto> <fix1> [fix2 ...]")
        sys.exit(2)
    run(args[0], args[1:])
