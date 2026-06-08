"""Telecharge le runtime WebView2 Fixed Version pour bundling avec CineSort.

V3.1 SCAFFOLDING — Script execute MANUELLEMENT par les mainteneurs avant une
release qui doit embarquer WebView2 (pas integre dans build_windows.bat /
build CI). Permet d'embarquer une version connue/figee du runtime WebView2
plutot que de dependre de l'Evergreen runtime installe sur la machine
utilisateur (qui peut etre absent / corrompu / decale).

Reference Microsoft :
    https://developer.microsoft.com/en-us/microsoft-edge/webview2/

Usage typique :
    .venv313\\Scripts\\python.exe scripts\\download_webview2_fixed.py

Sortie : `webview2_fixed/` a la racine du depot, contenant le bundle
fixed-version (extrait du .cab Microsoft). Le repertoire est volontairement
GIT-IGNORE — chaque mainteneur le regenere localement avant une release
bundle si necessaire. Le contenu est embarque dans le .exe via
`CineSort.spec` (datas=..., conditionnel sur env `CINESORT_BUNDLE_WEBVIEW2=1`).

Notes :
- Pas execute par le build auto / CI / build_windows.bat (cf cahier des
  charges V3.1 : "PAS DE DL maintenant").
- Le script verifie la presence des fichiers attendus apres extraction
  (msedgewebview2.exe / EBWebView/...). Si le hash ou la structure changent
  cote Microsoft, mettre a jour les constantes ci-dessous.
- L'URL officielle Microsoft requiert une acceptation manuelle des EULA :
  on conserve donc ici uniquement la page de download. Le script affiche
  les instructions et NE telecharge PAS automatiquement par defaut sauf si
  une URL directe est fournie via `--url` (cas mainteneur ayant deja
  recupere le lien direct CDN).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

# Page officielle Microsoft d'ou recuperer le lien direct "Fixed Version".
# Le lien CDN direct change a chaque release Edge -> on ne hardcode PAS ici.
WEBVIEW2_LANDING_URL = (
    "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
)

# Repertoire cible (a la racine du depot CineSort). Ignore par git.
DEFAULT_TARGET_DIR = "webview2_fixed"

# Fichiers attendus apres extraction (sanity-check post-DL).
EXPECTED_FILES = (
    "msedgewebview2.exe",
    "EBWebView/x64/msedge.dll",
)


def _print_instructions(target_dir: Path) -> None:
    """Affiche les instructions pour telecharger manuellement le bundle."""
    print("=" * 72)
    print("CineSort V3.1 — Bundle WebView2 Fixed Version (scaffolding)")
    print("=" * 72)
    print()
    print("Le script V3.1 est en mode SCAFFOLDING : aucun telechargement")
    print("automatique pour l'instant (cf cahier des charges).")
    print()
    print("Pour preparer un bundle manuellement :")
    print()
    print(f"  1. Ouvrir : {WEBVIEW2_LANDING_URL}")
    print("  2. Section 'Fixed Version' -> selectionner architecture x64")
    print("  3. Accepter EULA, telecharger le .cab")
    print(f"  4. Extraire le contenu dans : {target_dir}")
    print("     (utiliser `expand <fichier>.cab -F:* webview2_fixed`)")
    print()
    print("Verifier ensuite la presence des fichiers cles :")
    for rel in EXPECTED_FILES:
        print(f"     - {target_dir / rel}")
    print()
    print("Une fois pret, builder avec :")
    print("     set CINESORT_BUNDLE_WEBVIEW2=1")
    print("     build_windows.bat")
    print()
    print("=" * 72)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_direct(url: str, dest: Path) -> Path:
    """Telecharge un .cab/.zip a une URL directe (mainteneur a deja l'URL).

    Pas appele par defaut : reserve aux cas ou le mainteneur a recupere
    une URL CDN directe via la page Microsoft.
    """
    print(f"[DL] Telechargement {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "CineSort/V3.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    print(f"[DL] OK ({dest.stat().st_size / 1_000_000:.1f} MB)")
    print(f"[DL] SHA-256: {_sha256(dest)}")
    return dest


def _validate_target(target_dir: Path) -> bool:
    """Verifie que le bundle telecharge est complet."""
    missing: list[str] = []
    for rel in EXPECTED_FILES:
        if not (target_dir / rel).is_file():
            missing.append(rel)
    if missing:
        print("[CHECK] Bundle incomplet, fichiers manquants :", file=sys.stderr)
        for rel in missing:
            print(f"   - {target_dir / rel}", file=sys.stderr)
        return False
    print("[CHECK] Bundle WebView2 Fixed valide :")
    for rel in EXPECTED_FILES:
        p = target_dir / rel
        print(f"   - {p} ({p.stat().st_size / 1_000_000:.1f} MB)")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scaffolding pour bundler WebView2 Fixed Version dans CineSort. "
            "Par defaut : affiche les instructions de telechargement manuel. "
            "Avec --url : telecharge directement (mainteneur uniquement)."
        )
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET_DIR,
        help=f"Repertoire cible (defaut: {DEFAULT_TARGET_DIR})",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="URL CDN directe du .cab Fixed Version (optionnel, mainteneur).",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verifie uniquement la presence des fichiers attendus.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    target_dir = (repo_root / args.target).resolve()

    if args.check_only:
        ok = _validate_target(target_dir)
        return 0 if ok else 1

    if args.url:
        archive = target_dir.with_suffix(".cab")
        try:
            _download_direct(args.url, archive)
        except Exception as exc:  # noqa: BLE001 — entry-point script
            print(f"[ERR] Telechargement echoue : {exc}", file=sys.stderr)
            return 2
        print(
            "[DL] Archive recue. Extraire manuellement via "
            f"`expand {archive} -F:* {target_dir}` puis relancer "
            "`--check-only` pour valider."
        )
        return 0

    _print_instructions(target_dir)
    if target_dir.is_dir():
        print()
        print(f"[INFO] Repertoire {target_dir} deja present, validation :")
        ok = _validate_target(target_dir)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
