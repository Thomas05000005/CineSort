#!/usr/bin/env python3
"""Genere des fichiers MKV 4K H265 SYNTHETIQUES (harness panne - scenario d).

Utilise ffmpeg pour produire un .mkv court (1-2s) mais avec attributs 3840x2160
hevc + audio multi-canaux, header gros. Probe est lent mais ABOUTIT - sert a
tester un timeout adaptatif vs timeout brut.

Usage:
    python scripts/make_synthetic_4k.py --out C:/tmp/cinesort_harness/big4k \\
                                        --count 3 \\
                                        --duration 2

Pre-requis: ffmpeg dans PATH (verifie au demarrage).

Fallback si ffmpeg absent: genere un manifest JSON listant les fichiers a creer
manuellement (pas d'invention de binaire MKV factice cote Python).

LIMITE HONNETE: simulation. Le vrai cas SMB lent + gros header H265 peut avoir
d'autres pathologies (block size, kerberos...) non couvertes ici.

NE PAS modifier code produit (cinesort/).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _check_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _build_ffmpeg_cmd(ffmpeg: str, out_path: Path, duration: int) -> list[str]:
    # Synthese video 4K HEVC + audio 5.1 AAC, header gros mais fichier court
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c=darkblue:s=3840x2160:d={duration}:r=24",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=5.1:sample_rate=48000:d={duration}",
        "-c:v", "libx265",
        "-preset", "ultrafast",
        "-x265-params", "log-level=error",
        "-c:a", "aac",
        "-b:a", "640k",
        "-t", str(duration),
        str(out_path),
    ]


def make_clips(out_dir: Path, count: int, duration: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _check_ffmpeg()

    if not ffmpeg:
        manifest = {
            "scenario": "d_synthetic_4k_h265",
            "status": "ffmpeg_missing",
            "out_dir": str(out_dir),
            "count": count,
            "duration_s": duration,
            "note": (
                "ffmpeg introuvable dans PATH. Manifest seul, fichiers non crees. "
                "Installer ffmpeg puis relancer."
            ),
            "files": [],
        }
        manifest_path = out_dir / "synthetic_4k_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    created: list[dict] = []
    for i in range(count):
        title = f"Synthetic.4K.Movie.{i:03d}.2024.2160p.UHD.BluRay.x265.DTS-HD.MA.5.1-HARNESS"
        sub = out_dir / title
        sub.mkdir(exist_ok=True)
        clip = sub / f"{title}.mkv"
        cmd = _build_ffmpeg_cmd(ffmpeg, clip, duration)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ok = proc.returncode == 0 and clip.exists()
            created.append({
                "path": str(clip),
                "ok": ok,
                "size_bytes": clip.stat().st_size if clip.exists() else 0,
                "stderr_tail": (proc.stderr or "")[-400:],
            })
        except subprocess.TimeoutExpired:
            created.append({"path": str(clip), "ok": False, "error": "timeout_120s"})
        except OSError as exc:
            created.append({"path": str(clip), "ok": False, "error": str(exc)})

    manifest = {
        "scenario": "d_synthetic_4k_h265",
        "status": "generated",
        "ffmpeg": ffmpeg,
        "out_dir": str(out_dir),
        "count": count,
        "duration_s": duration,
        "files": created,
        "note": (
            "Clips 4K HEVC 5.1 reels (courts mais avec header gros). Probe ffprobe "
            "lent (>1s/fichier sur SMB lent) mais ABOUTIT. Tester timeout adaptatif "
            "vs brut: brut(10s) coupe a tort, adaptatif (size-aware) aboutit."
        ),
    }
    manifest_path = out_dir / "synthetic_4k_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Repertoire de sortie")
    parser.add_argument("--count", type=int, default=3, help="Nombre de clips a generer")
    parser.add_argument("--duration", type=int, default=2, help="Duree en secondes par clip")
    args = parser.parse_args(argv)

    manifest = make_clips(args.out, args.count, args.duration)
    print(json.dumps(manifest, indent=2))
    return 0 if manifest.get("status") != "ffmpeg_missing" else 2


if __name__ == "__main__":
    sys.exit(main())
