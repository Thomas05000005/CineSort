"""R8 F4 — DIFFERENTIEL R8-038 : normalisation du bitrate audio (bps -> kbps).

Vecteur : _normalize_audio_bitrate_kbps divisait /1000 SEULEMENT si > 10000.
Le bitrate stocké est TOUJOURS en bps (probe normalise tout via to_optional_bitrate).
Un flux ~8 kbps (8000 bps, mono dégradé) restait à 8000 -> lu comme 8000 kbps ->
per_channel=8000 -> bonus +4 « débit élevé » AU LIEU du malus -3 (inversion de signe).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_bitrate_diff.py [ffprobe] [a8k.m4a]
"""
from __future__ import annotations
import json
import subprocess
import sys

from cinesort.domain.quality_score import _normalize_audio_bitrate_kbps


def _avant(raw):
    """Réplique de l'ancienne logique (seuil > 10000)."""
    n = float(raw)
    if n <= 0:
        return None
    if n > 10000.0:
        return int(round(n / 1000.0))
    return int(round(n))


def _per_channel_score(kbps, channels):
    if not kbps or channels <= 0:
        return 0, "n/a"
    pc = float(kbps) / float(max(1, channels))
    if pc >= 650:
        return +4, "Debit audio eleve (bonus)"
    if pc >= 320:
        return +2, "Debit audio correct (bonus)"
    if pc < 120:
        return -3, "Debit audio faible (malus)"
    return 0, "neutre"


def run(ffprobe=None, real_file=None):
    results = {}
    # Cas du registre : flux mono ~8 kbps stocké en bps (8000), 1 canal.
    raw_bps = 8000
    av = _avant(raw_bps)
    ap = _normalize_audio_bitrate_kbps(raw_bps)
    av_score, av_lbl = _per_channel_score(av, 1)
    ap_score, ap_lbl = _per_channel_score(ap, 1)
    results["R8038_value_corrected"] = (av == 8000 and ap == 8)
    results["R8038_score_inversion_fixed"] = (av_score == 4 and ap_score == -3)
    print("=== R8-038 : flux mono 8000 bps (= 8 kbps dégradé) ===")
    print(f"  _normalize_audio_bitrate_kbps(8000) : AVANT={av} (lu 8000 kbps)  APRÈS={ap} (8 kbps)")
    print(f"  per_channel score (1 canal)         : AVANT={av_score:+d} '{av_lbl}'  APRÈS={ap_score:+d} '{ap_lbl}'")
    print(f"  -> inversion de signe corrigée : +4 (bonus fabriqué) -> -3 (malus réel)")

    # Cohérence sur un débit élevé légitime (8 Mbps lossless en bps) : inchangé.
    hi = 8_000_000
    print("\n=== cohérence : 8 Mbps lossless (8000000 bps) ===")
    print(f"  AVANT={_avant(hi)} kbps  APRÈS={_normalize_audio_bitrate_kbps(hi)} kbps (les deux = 8000, inchangé)")
    results["R8038_high_unchanged"] = (_avant(hi) == _normalize_audio_bitrate_kbps(hi) == 8000)

    # Valeur RÉELLE ffprobe (PLAN A) si fournie.
    if ffprobe and real_file:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate", "-of", "default=noprint_wrappers=1:nokey=1", real_file],
            capture_output=True, text=True,
        )
        raw = out.stdout.strip()
        print(f"\n=== valeur RÉELLE ffprobe ({real_file}) ===")
        print(f"  bit_rate brut = {raw} bps  -> _normalize = {_normalize_audio_bitrate_kbps(raw)} kbps")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (bps->kbps inconditionnel, inversion réparée, débits élevés inchangés)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    run(a[0] if len(a) > 0 else None, a[1] if len(a) > 1 else None)
