"""Harnais METAMORPHIQUE round-trip SETTINGS (READ-ONLY corpus reel, ecriture
sur state_dir JETABLE uniquement) — campagne AUDIT_HORIZONS.

Relation : pour toute cle NON-secrete d'un payload settings valide,
  GET(save(payload_mute))[k] == payload_mute[k]   (a normalisation pres).
Toute cle perdue / silencieusement reecrite = candidat perte-de-config.

Gate FALSIFIABILITE : on plante une cle bidon ('__canary__') ET on verifie
qu'une vraie divergence serait visible (le diff compare valeur a valeur).

Aucun effet de bord sur la vraie biblio : tempfile.mkdtemp() exclusif.
Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/meta_settings_roundtrip.py
"""
from __future__ import annotations
import tempfile
from pathlib import Path

from cinesort.ui.api.settings_support import get_settings_payload, save_settings_payload

D = dict(
    default_root="C:/Films",
    default_collection_folder_name="_Collection",
    default_empty_folders_folder_name="_Vide",
    default_residual_cleanup_folder_name="_Dossier Nettoyage",
    default_probe_backend="auto",
    debug_enabled=False,
)
SECRET_HINTS = ("token", "api_key", "apikey", "password", "secret", "bearer")


def is_secretish(key, val):
    k = key.lower()
    if any(h in k for h in SECRET_HINTS):
        return True
    if isinstance(val, str) and set(val) == {"*"} and val:
        return True
    return False


def mutate(payload):
    """Change deterministiquement les scalaires non-secrets, profondeur 1+2."""
    changed = {}

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                p = f"{path}.{k}" if path else k
                if isinstance(v, (dict, list)):
                    walk(v, p)
                elif is_secretish(k, v):
                    continue
                elif isinstance(v, bool):
                    obj[k] = not v
                    changed[p] = obj[k]
                elif isinstance(v, int):
                    obj[k] = v + 1 if v < 9000 else v  # eviter franchir seuils absurdes
                    changed[p] = obj[k]
                elif isinstance(v, str) and v and "path" not in k.lower() and "root" not in k.lower() and "dir" not in k.lower():
                    # eviter de muter les chemins (normalises) -> faux positifs
                    if v in ("default", "plex", "jellyfin", "quality", "custom"):
                        obj[k] = "custom" if v != "custom" else "plex"
                    elif len(v) <= 4 and not v.isalpha():
                        obj[k] = v + "_x"
                    changed[p] = obj[k]

    walk(payload, "")
    return changed


def get_at(payload, dotted):
    cur = payload
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ("__ABSENT__",)
    return cur


def main():
    tmp = Path(tempfile.mkdtemp(prefix="cs_settings_rt_"))
    print(f"state_dir jetable: {tmp}")

    base = get_settings_payload(state_dir=tmp, default_state_dir_example=str(tmp), **D)
    changed = mutate(base)
    print(f"cles mutees (non-secretes): {len(changed)}")

    # plante une canary pour prouver la falsifiabilite
    base["__canary_roundtrip__"] = "CANARY-12345"

    save_settings_payload(
        base, current_state_dir=tmp,
        default_collection_folder_name=D["default_collection_folder_name"],
        default_empty_folders_folder_name=D["default_empty_folders_folder_name"],
        default_residual_cleanup_folder_name=D["default_residual_cleanup_folder_name"],
        default_root=D["default_root"], default_probe_backend=D["default_probe_backend"],
        debug_enabled=D["debug_enabled"],
    )
    after = get_settings_payload(state_dir=tmp, default_state_dir_example=str(tmp), **D)

    lost = []
    for dotted, want in changed.items():
        got = get_at(after, dotted)
        if got != want:
            lost.append((dotted, want, got))

    print(f"\n=== DIVERGENCES round-trip ({len(lost)}/{len(changed)}) ===")
    for dotted, want, got in lost[:40]:
        print(f"  [DIFF] {dotted}: ecrit={want!r}  relu={got!r}")
    if len(lost) > 40:
        print(f"  ... (+{len(lost)-40} autres)")

    canary = get_at(after, "__canary_roundtrip__")
    print(f"\n[falsifiabilite] canary relu = {canary!r} (si conserve => harnais voit bien les valeurs)")
    print("\nNOTE: une divergence peut etre une NORMALISATION legitime (chemin, "
          "alias, clamp) — a juger une par une, PAS un bug automatique.")


if __name__ == "__main__":
    main()
