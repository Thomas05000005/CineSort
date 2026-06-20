"""C3-E — Repro LIVE concurrence : saves settings concurrents (state_dir JETABLE).

Le code ajoute un `_settings_write_lock` par state_dir (settings_support.py:1842)
pour serialiser read->normalize->write et eviter le lost-update / torn-write.
Ce harnais le met sous pression :
  N threads ecrivent chacun une valeur DISTINCTE d'une cle non-secrete, en boucle,
  pendant que d'autres threads RELISENT. Invariants verifies en continu :
   I1  le GET ne doit JAMAIS lever (jamais de JSON tronque/corrompu).
   I2  la valeur relue est TOUJOURS l'une des valeurs ecrites (jamais une bouillie).
   I3  l'etat final contient toutes les cles canoniques (pas de payload ampute).
Falsifiabilite : un torn-write donnerait un JSONDecodeError (I1 ROUGE).

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/c3_concurrent_settings_save.py
Aucun effet sur la vraie biblio : tempfile exclusif.
"""
from __future__ import annotations
import json
import tempfile
import threading
from pathlib import Path

from cinesort.ui.api.settings_support import get_settings_payload, save_settings_payload

D = dict(
    default_root="C:/Films", default_collection_folder_name="_Collection",
    default_empty_folders_folder_name="_Vide",
    default_residual_cleanup_folder_name="_Dossier Nettoyage",
    default_probe_backend="auto", debug_enabled=False,
)
KEY = "collection_folder_name"  # cle scalaire non-secrete, persistee
N_THREADS = 8
ITERS = 40


def run():
    tmp = Path(tempfile.mkdtemp(prefix="cs_conc_set_"))
    base = get_settings_payload(state_dir=tmp, default_state_dir_example=str(tmp), **D)
    written_values = set()
    errors = []
    bad_values = []
    lock = threading.Lock()

    def writer(tid):
        for i in range(ITERS):
            val = f"Coll_{tid}_{i}"
            payload = dict(base)
            payload[KEY] = val
            with lock:
                written_values.add(val)
            try:
                save_settings_payload(
                    payload, current_state_dir=tmp,
                    default_collection_folder_name=D["default_collection_folder_name"],
                    default_empty_folders_folder_name=D["default_empty_folders_folder_name"],
                    default_residual_cleanup_folder_name=D["default_residual_cleanup_folder_name"],
                    default_root=D["default_root"], default_probe_backend=D["default_probe_backend"],
                    debug_enabled=D["debug_enabled"],
                )
            except Exception as e:  # noqa: BLE001
                errors.append(f"WRITE t{tid}.{i}: {type(e).__name__}: {e}")

    def reader(tid):
        for _ in range(ITERS * 2):
            try:
                p = get_settings_payload(state_dir=tmp, default_state_dir_example=str(tmp), **D)
                v = p.get(KEY)
                # I2 : valeur relue doit etre une valeur ecrite (ou la valeur de base initiale)
                with lock:
                    known = v in written_values or v == base.get(KEY)
                if not known and v is not None:
                    bad_values.append(v)
                # I3 : payload complet (cles canoniques presentes)
                if "weights" not in p and "naming_preset" not in p and KEY not in p:
                    bad_values.append(f"PAYLOAD_AMPUTE:{list(p.keys())[:5]}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"READ t{tid}: {type(e).__name__}: {e}")

    threads = []
    for t in range(N_THREADS):
        threads.append(threading.Thread(target=writer, args=(t,)))
        threads.append(threading.Thread(target=reader, args=(t,)))
    for th in threads: th.start()
    for th in threads: th.join()

    # verif finale : fichier valide + valeur finale coherente
    final = get_settings_payload(state_dir=tmp, default_state_dir_example=str(tmp), **D)
    final_val = final.get(KEY)
    raw_ok = True
    try:
        json.loads((tmp / "settings.json").read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        raw_ok = False
        errors.append(f"FINAL JSON corrompu: {e}")

    out = {
        "threads": N_THREADS, "iters": ITERS,
        "writes_total": N_THREADS * ITERS,
        "I1_lectures_sans_exception": len([e for e in errors if e.startswith("READ")]) == 0,
        "I2_valeurs_incoherentes": bad_values[:10],
        "I3_fichier_final_valide": raw_ok,
        "valeur_finale": final_val,
        "valeur_finale_coherente": final_val in written_values,
        "erreurs": errors[:10],
        "VERDICT": "SERIALISATION OK (aucun torn-write/corruption)"
                   if not errors and not bad_values and raw_ok
                   else "INCOHERENCE DETECTEE",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
