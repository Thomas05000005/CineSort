"""R8 F3 (filet) — DIFFERENTIEL R8-093 : 2e chemin d'exec binaire (tools_manager).

Survivant du filet F3 (exec-0, 3/3) : `detect_probe_tools` -> `_build_tool_status`
-> `_probe_version_line([tool_path, '-version'])` executait le `ffprobe_path` /
`mediainfo_path` explicite des settings SANS `_binary_name_allowed`. R8-032 n'avait
durci que tooling._resolve_tool_path ; tools_manager._candidate_paths_for_tool
ajoutait ('explicit', path) sans garde. Atteignable via les endpoints REST
get_probe_tools_status / recheck_probe_tools (check_versions=True).

Double diff : (1) malware.exe configure -> AVANT candidat d'exec, APRES filtre ;
(2) ffprobe.exe legitime -> reste candidat.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f3_tools_manager_exec_diff.py
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from cinesort.infra.probe.tools_manager import _candidate_paths_for_tool


def _avant_candidates(explicit_path: str):
    """AVANT : explicit ajoute INCONDITIONNELLEMENT (sans whitelist)."""
    cands = []
    if explicit_path:
        cands.append(("explicit", explicit_path))
    return cands


def run():
    results = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        malware = tmp / "malware.exe"
        malware.write_bytes(b"MZ")
        legit = tmp / "ffprobe.exe"
        legit.write_bytes(b"MZ")
        no_which = lambda _exe: None  # pas de PATH fallback (isole le candidat explicit)

        # (1) ATTAQUE : ffprobe_path = malware.exe
        avant = _avant_candidates(str(malware))
        apres = _candidate_paths_for_tool(
            tool_name="ffprobe", explicit_path=str(malware), state_dir=tmp,
            which_fn=no_which, scan_winget_packages=False,
        )
        avant_has_malware = any(p == str(malware) for _s, p in avant)
        apres_has_malware = any(p == str(malware) for _s, p in apres)
        results["R8093_attaque_malware_non_candidat"] = avant_has_malware and not apres_has_malware
        print("=== (1) ATTAQUE : ffprobe_path=malware.exe ===")
        print(f"  AVANT candidats : {avant}  (malware present = {avant_has_malware})")
        print(f"  APRES candidats : {apres}  (malware present = {apres_has_malware} -> filtre = {not apres_has_malware})")

        # (2) LEGITIME : ffprobe_path = vrai ffprobe.exe
        apres_legit = _candidate_paths_for_tool(
            tool_name="ffprobe", explicit_path=str(legit), state_dir=tmp,
            which_fn=no_which, scan_winget_packages=False,
        )
        legit_kept = any(p == str(legit) and s == "explicit" for s, p in apres_legit)
        results["R8093_legitime_ffprobe_conserve"] = legit_kept
        print("\n=== (2) LEGITIME : ffprobe_path=ffprobe.exe ===")
        print(f"  APRES candidats : {apres_legit}  (explicit conserve = {legit_kept})")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (2e chemin exec whiteliste, legitime intact)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
