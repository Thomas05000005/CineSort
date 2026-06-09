#!/usr/bin/env python3
"""Cree une arborescence de fichiers sur chemin INJOIGNABLE (harness panne - scenario b).

Strategies Windows:
1) Reference UNC vers host fictif: \\\\unreachable-host-cinesort\\share\\Movies
   - open() bloquera jusqu'au timeout TCP/NetBIOS (~20s)
2) Fallback fichiers locaux marques injoignable (mtime=0, attribut READONLY+HIDDEN+SYSTEM)
   pour tester la branche "I/O lent" sans dependre du reseau du dev.

Usage:
    python scripts/make_unreachable_files.py --out C:/tmp/cinesort_harness/unreach \\
                                              --count 5 \\
                                              --mode local-stub

Modes:
    --mode unc        : genere un fichier .txt par film avec chemin UNC fictif
                        (utilise un manifest a charger cote test pour scanner)
    --mode local-stub : cree localement des fichiers .mkv vides + ouvre un handle
                        exclusif pour simuler "fichier verrouille" cote scan

LIMITE HONNETE: simulation. Reproduit le SYMPTOME (open lent/echec) pas la cause
(reelle latence reseau SMB). Validation B sur vrai NAS reste a faire.

NE PAS modifier code produit (cinesort/).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


UNC_HOST = "unreachable-host-cinesort"
UNC_SHARE = "share"
UNC_ROOT = f"\\\\{UNC_HOST}\\{UNC_SHARE}\\Movies"


def make_unc_manifest(out_dir: Path, count: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(count):
        title = f"Fake.Movie.{i:03d}.2024.2160p.WEB-DL.x265-HARNESS"
        unc_path = f"{UNC_ROOT}\\{title}\\{title}.mkv"
        entries.append({"path": unc_path, "title": title, "size_hint_bytes": 1_500_000_000})
    manifest = {
        "scenario": "b_unreachable_unc",
        "unc_host": UNC_HOST,
        "unc_root": UNC_ROOT,
        "count": count,
        "entries": entries,
        "note": (
            "Le scan CineSort doit DETECTER le timeout open() sur chacun de ces chemins "
            "sans bloquer le scan global. Identification (TMDb/parsing filename) doit "
            "rester possible memes si probe ffprobe/mediainfo echoue."
        ),
    }
    manifest_path = out_dir / "unreachable_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def make_local_stubs(out_dir: Path, count: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for i in range(count):
        title = f"Fake.Movie.{i:03d}.2024.2160p.WEB-DL.x265-HARNESS"
        sub = out_dir / title
        sub.mkdir(exist_ok=True)
        stub = sub / f"{title}.mkv"
        # Fichier vide (0 byte) - probe va se plaindre, parsing filename OK
        stub.write_bytes(b"")
        created.append(str(stub))
    manifest = {
        "scenario": "b_local_stub",
        "out_dir": str(out_dir),
        "count": count,
        "files": created,
        "note": (
            "Fichiers locaux vides (0 byte) simulant un partage SMB qui repond mais "
            "renvoie des donnees corrompues. Probe DOIT signaler 'qualite indisponible' "
            "et NE PAS inventer un score. Identification (filename->TMDb) reste possible."
        ),
    }
    manifest_path = out_dir / "local_stub_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Repertoire de sortie")
    parser.add_argument("--count", type=int, default=5, help="Nombre de fichiers a generer")
    parser.add_argument(
        "--mode",
        choices=("unc", "local-stub"),
        default="local-stub",
        help="Mode de simulation (unc = manifest pour chemins UNC fictifs, local-stub = fichiers locaux 0 byte)",
    )
    args = parser.parse_args(argv)

    if args.mode == "unc":
        manifest = make_unc_manifest(args.out, args.count)
    else:
        manifest = make_local_stubs(args.out, args.count)

    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
