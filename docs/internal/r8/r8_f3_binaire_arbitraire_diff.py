"""R8 F3 — DOUBLE DIFFERENTIEL binaire arbitraire (R8-032 ffprobe exec + R8-033 ffmpeg sibling).

Vecteur : un attaquant qui ecrit settings.json place `ffprobe_path` sur un binaire
arbitraire (calc.exe / malware.exe) ; le flux perceptuel l'executait en argv[0]
SANS la garde `_binary_name_allowed` (asymetrie save/exec). De plus
`resolve_ffmpeg_path` executait le `ffmpeg.exe` VOISIN d'un chemin arbitraire.

Double diff exige :
  (1) ATTAQUE : binaire non-whiteliste configure -> AVANT execute, APRES refuse.
  (2) LEGITIME : ffprobe.exe (auto-install / config manuelle) -> marche toujours.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f3_binaire_arbitraire_diff.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cinesort.domain.perceptual.ffmpeg_runner import resolve_ffmpeg_path
from cinesort.infra.probe.tooling import safe_tool_path


def _avant_raw(ffprobe_setting: str) -> str:
    """Comportement AVANT (perceptual_support) : valeur brute, aucune garde."""
    return str(ffprobe_setting or "") or "ffprobe"


def _avant_sibling(ffprobe_path: str) -> str:
    """Comportement AVANT (resolve_ffmpeg_path) : sibling sans controle du nom."""
    if not ffprobe_path:
        return "ffmpeg"
    parent = Path(ffprobe_path).parent
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = parent / name
        if candidate.is_file():
            return str(candidate)
    return "ffmpeg"


def run():
    results = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # Fixtures : un binaire ARBITRAIRE + son ffmpeg voisin, et un ffprobe LEGITIME.
        evil = tmp / "evil"
        evil.mkdir()
        malware = evil / "malware.exe"
        malware.write_bytes(b"MZ")  # faux exe
        evil_ffmpeg = evil / "ffmpeg.exe"
        evil_ffmpeg.write_bytes(b"MZ")  # ffmpeg voisin malveillant

        legit = tmp / "tools"
        legit.mkdir()
        legit_ffprobe = legit / "ffprobe.exe"
        legit_ffprobe.write_bytes(b"MZ")
        legit_ffmpeg = legit / "ffmpeg.exe"
        legit_ffmpeg.write_bytes(b"MZ")

        # ---- (1) ATTAQUE R8-032 : ffprobe_path = malware.exe ----
        avant_032 = _avant_raw(str(malware))
        apres_032 = safe_tool_path(str(malware), "ffprobe")
        # AVANT renvoie le malware (execute) ; APRES ne le renvoie JAMAIS.
        atk_032_avant_exec = avant_032 == str(malware)
        atk_032_apres_refuse = apres_032 != str(malware)
        results["R8032_attaque_malware_refusee"] = atk_032_avant_exec and atk_032_apres_refuse
        print("=== (1) R8-032 ATTAQUE : ffprobe_path=malware.exe ===")
        print(f"  AVANT renvoie pour exec : {avant_032!r}  (== malware -> execute = {atk_032_avant_exec})")
        print(f"  APRES (safe_tool_path)  : {apres_032!r}  (!= malware -> refuse = {atk_032_apres_refuse})")

        # ---- (2) LEGITIME R8-032 : ffprobe_path = vrai ffprobe.exe ----
        apres_032_legit = safe_tool_path(str(legit_ffprobe), "ffprobe")
        leg_032 = apres_032_legit == str(legit_ffprobe)
        results["R8032_legitime_preserve"] = leg_032
        print("\n=== (2) R8-032 LEGITIME : ffprobe_path=tools/ffprobe.exe ===")
        print(f"  APRES (safe_tool_path) : {apres_032_legit!r}  (== legit -> preserve = {leg_032})")

        # ---- (1) ATTAQUE R8-033 : sibling ffmpeg d'un chemin arbitraire ----
        avant_033 = _avant_sibling(str(malware))
        apres_033 = resolve_ffmpeg_path(str(malware))
        atk_033_avant = avant_033 == str(evil_ffmpeg)  # AVANT derive le ffmpeg voisin malveillant
        atk_033_apres = apres_033 != str(evil_ffmpeg)  # APRES ne le derive PLUS
        results["R8033_attaque_sibling_refuse"] = atk_033_avant and atk_033_apres
        print("\n=== (1) R8-033 ATTAQUE : sibling ffmpeg de evil/malware.exe ===")
        print(f"  AVANT derive : {avant_033!r}  (== evil/ffmpeg.exe -> execute = {atk_033_avant})")
        print(f"  APRES        : {apres_033!r}  (!= evil/ffmpeg.exe -> refuse = {atk_033_apres})")

        # ---- (2) LEGITIME R8-033 : sibling d'un vrai ffprobe.exe ----
        apres_033_legit = resolve_ffmpeg_path(str(legit_ffprobe))
        leg_033 = apres_033_legit == str(legit_ffmpeg)
        results["R8033_legitime_preserve"] = leg_033
        print("\n=== (2) R8-033 LEGITIME : sibling de tools/ffprobe.exe ===")
        print(f"  APRES : {apres_033_legit!r}  (== tools/ffmpeg.exe -> preserve = {leg_033})")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (attaque fermee + legitime intact, R8-032 & R8-033)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
