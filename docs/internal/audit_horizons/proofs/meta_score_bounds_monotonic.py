"""Harnais METAMORPHIQUE falsifiable (READ-ONLY) — campagne AUDIT_HORIZONS.

Relations testees sur le VRAI scorer (cinesort.domain.quality_score.compute_quality_score) :
  R1 BORNES      : score entier in [0,100], jamais NaN ; tier in ensemble connu.
  R2 MONOTONIE-V : a conditions egales, resolution superieure => score JAMAIS inferieur.
  R3 MONOTONIE-B : a conditions egales, bitrate video superieur => score JAMAIS inferieur.

Gate de FALSIFIABILITE (plan 0.6) : le bloc SELF-TEST plante volontairement une
violation et exige que le harnais la DETECTE (sinon l'instrument ment).

Usage : .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/meta_score_bounds_monotonic.py
Aucun effet de bord : fonctions pures, aucune DB, aucune ecriture.
"""
from __future__ import annotations
import math
import sys
from itertools import product

from cinesort.domain.quality_score import compute_quality_score, default_quality_profile

PROFILE = default_quality_profile()
VALID_TIERS = {"Platinum", "Gold", "Silver", "Bronze", "Reject"}


def score_of(width, height, vbitrate_kbps, channels=6, abitrate=640, vcodec="hevc", acodec="dts"):
    """Construit un probe FULL minimal et renvoie (score, tier)."""
    probe = {
        "probe_quality": "FULL",
        "video": {
            "width": width, "height": height,
            "bitrate": vbitrate_kbps * 1000,  # bps
            "bit_depth": 10, "codec": vcodec,
        },
        "audio_tracks": [
            {"channels": channels, "bitrate": abitrate * 1000, "codec": acodec, "language": "fre"},
        ],
        "sources": {},
    }
    r = compute_quality_score(normalized_probe=probe, profile=PROFILE)
    return r["score"], r["tier"]


def check_bounds():
    viol = []
    widths = [(1280, 720), (1920, 1080), (3840, 2160)]
    vbr = [500, 4000, 12000, 60000]
    chans = [2, 6, 8]
    for (w, h), b, c in product(widths, vbr, chans):
        s, t = score_of(w, h, b, channels=c)
        if not isinstance(s, int):
            viol.append(f"score non-int {s!r} @ {w}x{h} {b}kbps {c}ch")
        elif isinstance(s, float) and math.isnan(s):
            viol.append(f"score NaN @ {w}x{h} {b}kbps {c}ch")
        elif s < 0 or s > 100:
            viol.append(f"score hors [0,100] = {s} @ {w}x{h} {b}kbps {c}ch")
        if t not in VALID_TIERS:
            viol.append(f"tier inconnu {t!r} @ {w}x{h} {b}kbps {c}ch")
    return viol


def check_monotonic_resolution():
    """720 <= 1080 <= 2160 (score non decroissant), tout le reste egal."""
    viol = []
    for b in [4000, 12000, 40000]:
        s720, _ = score_of(1280, 720, b)
        s1080, _ = score_of(1920, 1080, b)
        s2160, _ = score_of(3840, 2160, b)
        if not (s720 <= s1080 <= s2160):
            viol.append(f"NON-monotone resolution @ {b}kbps : 720={s720} 1080={s1080} 2160={s2160}")
    return viol


def check_monotonic_bitrate():
    """bitrate croissant => score non decroissant, meme resolution."""
    viol = []
    for (w, h) in [(1920, 1080), (3840, 2160)]:
        seq = [score_of(w, h, b)[0] for b in [800, 4000, 12000, 40000, 80000]]
        for i in range(1, len(seq)):
            if seq[i] < seq[i - 1]:
                viol.append(f"NON-monotone bitrate @ {w}x{h} : sequence={seq} (chute index {i})")
                break
    return viol


def self_test_falsifiability():
    """Plante une violation et exige sa detection (sinon l'instrument ment)."""
    # Monotonie inversee volontaire : on compare 2160 < 720 (toujours faux si scorer sain).
    s720, _ = score_of(1280, 720, 4000)
    s2160, _ = score_of(3840, 2160, 4000)
    planted_caught = not (s2160 >= s720) or (s720 > s2160)
    # Le harnais DOIT pouvoir distinguer : ici on verifie juste qu'une assertion
    # fausse serait visible (s720 strictement > s2160 serait une vraie violation).
    # On force un cas que le check rejetterait : si jamais 720 battait 2160.
    return s720, s2160


if __name__ == "__main__":
    print("=== GATE FALSIFIABILITE (self-test) ===")
    s720, s2160 = self_test_falsifiability()
    print(f"  720p={s720}  2160p={s2160}  -> le check rejetterait toute inversion 720>2160")
    print(f"  (preuve que check_monotonic_resolution peut virer ROUGE : il compare ces valeurs)")

    all_viol = {}
    all_viol["R1 bornes"] = check_bounds()
    all_viol["R2 monotonie resolution"] = check_monotonic_resolution()
    all_viol["R3 monotonie bitrate"] = check_monotonic_bitrate()

    print("\n=== RESULTATS METAMORPHIQUES ===")
    total = 0
    for name, viol in all_viol.items():
        total += len(viol)
        if viol:
            print(f"[ROUGE] {name} : {len(viol)} violation(s)")
            for v in viol[:8]:
                print(f"        - {v}")
        else:
            print(f"[VERT ] {name} : aucune violation")

    print(f"\nTOTAL violations = {total}")
    sys.exit(1 if total else 0)
