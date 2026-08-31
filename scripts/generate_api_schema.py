"""V2.1 — Genere `docs/api/schema.json` a partir des schemas Pydantic.

Usage :
    python scripts/generate_api_schema.py
    python scripts/generate_api_schema.py --out docs/api/schema.json --indent 2

Endpoints couverts (memoire utilisateur : "endpoints REELS run_facade.py:
start_plan / check_duplicates / apply complet — NE PAS inventer noms") :
    - start_plan       : StartPlanRequest / StartPlanResponse
    - check_duplicates : CheckDuplicatesRequest / CheckDuplicatesResponse
    - apply            : ApplyRequest / ApplyResponse
    - reports          : PerceptualReport | QualityReport (discriminated)

Si pydantic est absent (ex : venv minimal pre-V2.1), le script ECHOUE : message
sur stderr, code retour 1, et `--out` reste INTACT.

Audit 2026-08-31, constat #40 (MAJEUR) : la branche `except ImportError`
retournait un schema vide (`"endpoints": {}, "reports": {}`) que `main()`
ecrivait quand meme, avant d'annoncer `[generate_api_schema] OK -> ...` et de
rendre 0. MESURE dans `.venv`, qui n'a pas pydantic : rc=0, 167 octets ecrits,
message « OK » — la ou `docs/api/schema.json` en fait 20 915. Un lancement dans
le mauvais venv effacait donc le schema reel sans le moindre signal d'echec.

Constat #37 (MINEUR) : la version etait recopiee ici en dur, troisieme copie a
cote de `VERSION` et `pyproject.toml` (eux verrouilles l'un a l'autre par
`tests/test_pyproject_pep621_v77.py`). Elle est desormais LUE dans `VERSION`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

# Racine projet : <repo>/scripts/generate_api_schema.py -> <repo>/
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "api" / "schema.json"

# Permet `python scripts/generate_api_schema.py` depuis la racine sans
# devoir exporter PYTHONPATH manuellement (CI / dev local).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SchemaUnavailableError(RuntimeError):
    """pydantic (ou les schemas) manquent : impossible de construire le schema.

    Levee plutot que de rendre un document vide : un appelant qui ne teste que
    la valeur de retour ecrirait ce vide par-dessus le schema reel (constat #40).
    """


def _schema_version() -> str:
    """Version applicative, LUE dans le fichier `VERSION` (source unique).

    `VERSION` est deja la reference de `pyproject.toml:version`, verrouillee par
    `tests/test_pyproject_pep621_v77.py`. La recopier ici en faisait une
    troisieme copie que rien ne gardait (constat #37).
    """
    return "v" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def build_schema() -> Dict[str, Any]:
    """Compile le JSON Schema unifie pour les endpoints REELS du run_facade.

    Leve `SchemaUnavailableError` si pydantic ou les schemas sont absents.
    """
    try:
        from pydantic import TypeAdapter  # type: ignore  # noqa: F401 - sonde de disponibilite de pydantic

        from cinesort.domain.report_types import REPORT_ADAPTER  # noqa: F401
        from cinesort.ui.api.schemas import (
            ApplyRequest,
            ApplyResponse,
            CheckDuplicatesRequest,
            CheckDuplicatesResponse,
            StartPlanRequest,
            StartPlanResponse,
        )
    except ImportError as exc:
        raise SchemaUnavailableError(
            f"pydantic ou schemas indisponibles : {exc}. "
            "Installer via 'pip install pydantic>=2.13' (ou 'pip install -r requirements.txt')."
        ) from exc

    endpoints = {
        "start_plan": {
            "request": StartPlanRequest.model_json_schema(),
            "response": StartPlanResponse.model_json_schema(),
        },
        "check_duplicates": {
            "request": CheckDuplicatesRequest.model_json_schema(),
            "response": CheckDuplicatesResponse.model_json_schema(),
        },
        "apply": {
            "request": ApplyRequest.model_json_schema(),
            "response": ApplyResponse.model_json_schema(),
        },
    }

    # Reports polymorphique (PerceptualReport | QualityReport) via le
    # TypeAdapter singleton de domain.report_types.
    reports_schema = REPORT_ADAPTER.json_schema()

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CineSort API Schemas (V2.1)",
        "version": _schema_version(),
        "endpoints": endpoints,
        "reports": reports_schema,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genere docs/api/schema.json (V2.1).")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Chemin de sortie (defaut : {DEFAULT_OUT}).",
    )
    parser.add_argument("--indent", type=int, default=2, help="Indentation JSON (defaut 2).")
    args = parser.parse_args(argv)

    try:
        schema = build_schema()
    except SchemaUnavailableError as exc:
        # Aucun `mkdir`, aucune ecriture : `--out` doit rester tel quel. Ecrire
        # un schema vide ici effacait le schema reel en annoncant « OK ».
        sys.stderr.write(f"[generate_api_schema] ECHEC : {exc}\n")
        sys.stderr.write(f"[generate_api_schema] {args.out} est laisse INCHANGE.\n")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(schema, indent=args.indent, ensure_ascii=False, sort_keys=False),
        encoding="utf-8",
    )
    print(f"[generate_api_schema] OK -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
