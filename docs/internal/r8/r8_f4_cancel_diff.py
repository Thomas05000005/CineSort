"""R8 F4 — DIFFERENTIEL R8-037 : annulation perceptuelle inerte (events disjoints).

Vecteur : request_cancel pose `rt.cancel_event` (event PAR-RUN) ; mais le batch
perceptuel post-scan lisait `api._perceptual_cancel_event` (via _resolve_cancel_event)
JAMAIS assigné -> toujours None -> checks d'annulation inertes -> request_cancel
n'arrêtait pas l'analyse perceptuelle.

Fix : JobRunner.get_cancel_event(run_id) expose rt.cancel_event ; le job_fn
(run_flow_support) câble `api._perceptual_cancel_event = runner.get_cancel_event(run_id)`
AVANT le batch -> les deux events sont le MÊME.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f4_cancel_diff.py
"""
from __future__ import annotations
import json
import threading
import types

from cinesort.app.job_runner import JobRunner
from cinesort.ui.api.perceptual_support import _resolve_cancel_event


def run():
    results = {}
    runner = JobRunner(store=None)  # store inutilisé par get_cancel_event
    run_id = "run-test-1"
    ev = threading.Event()
    # Simule un run actif (request_cancel poserait ev = rt.cancel_event).
    runner._runs[run_id] = types.SimpleNamespace(cancel_event=ev)

    # L'accesseur expose bien l'event du run.
    got = runner.get_cancel_event(run_id)
    results["R8037_accessor_returns_event"] = got is ev
    results["R8037_accessor_unknown_none"] = runner.get_cancel_event("nope") is None

    # ===== AVANT (api sans _perceptual_cancel_event) =====
    api_avant = types.SimpleNamespace()
    ev.set()  # request_cancel a posé le flag du run
    avant = _resolve_cancel_event(api_avant)
    avant_inert = avant is None  # cancel non vu par le batch
    results["R8037_avant_inert"] = avant_inert

    # ===== APRÈS (job_fn câble l'event du run sur l'api) =====
    ev2 = threading.Event()
    runner._runs[run_id] = types.SimpleNamespace(cancel_event=ev2)
    api_apres = types.SimpleNamespace()
    api_apres._perceptual_cancel_event = runner.get_cancel_event(run_id)  # le câblage R8-037
    resolved_before = _resolve_cancel_event(api_apres)
    not_set_yet = resolved_before is not None and not resolved_before.is_set()
    ev2.set()  # request_cancel pose rt.cancel_event -> MÊME objet
    resolved_after = _resolve_cancel_event(api_apres)
    apres_sees_cancel = resolved_after is not None and resolved_after.is_set()
    results["R8037_apres_resolves_event"] = not_set_yet
    results["R8037_apres_cancel_propagates"] = apres_sees_cancel

    print("=== R8-037 — câblage cancel_event run <-> batch perceptuel ===")
    print(f"  get_cancel_event(run) is rt.cancel_event : {got is ev}")
    print(f"  AVANT : _resolve_cancel_event(api) = {avant}  (None -> annulation INERTE)")
    print(f"  APRÈS : event résolu avant set = {resolved_before is not None} (set={resolved_before.is_set() if resolved_before else None})")
    print(f"  APRÈS : après request_cancel (ev.set) -> _resolve.is_set() = {apres_sees_cancel}  (annulation VUE)")

    allok = all(results.values())
    print(f"\nVERDICT : {'CORRIGE (event du run câblé sur api -> annulation propagée au batch)' if allok else 'INCOMPLET'}")
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
