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

BACKWARD COMPAT : si pydantic est absent (ex : venv minimal pre-V2.1), on
sort un avertissement et un schema vide plutot que de crasher.
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


def build_schema() -> Dict[str, Any]:
    """Compile le JSON Schema unifie pour les endpoints REELS du run_facade."""
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
        sys.stderr.write(
            f"[generate_api_schema] pydantic ou schemas indisponibles : {exc}\n"
            "Installer via 'pip install pydantic>=2.13' (ou 'pip install -r requirements.txt').\n"
        )
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "CineSort API Schemas (unavailable — pydantic missing)",
            "endpoints": {},
            "reports": {},
        }

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
        "version": "v1.5.2-beta",
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

    schema = build_schema()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(schema, indent=args.indent, ensure_ascii=False, sort_keys=False),
        encoding="utf-8",
    )
    print(f"[generate_api_schema] OK -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
