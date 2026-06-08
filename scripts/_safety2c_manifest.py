"""Manifeste FS test_library/ pour non-regression iter3 etape 2c."""
import hashlib
import json
import os
import sys


def build(root: str) -> dict:
    manifest = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        for f in filenames:
            p = os.path.join(dirpath, f).replace("\\", "/")
            try:
                st = os.stat(p)
                with open(p, "rb") as fh:
                    h = hashlib.sha1(fh.read()).hexdigest()
                manifest[p] = {"size": st.st_size, "sha1": h, "mtime": int(st.st_mtime)}
            except Exception as e:
                manifest[p] = {"error": str(e)}
    return manifest


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    root = sys.argv[2] if len(sys.argv) > 2 else "test_library"
    m = build(root)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, sort_keys=True)
    sha = hashlib.sha1(json.dumps(m, sort_keys=True).encode()).hexdigest()
    print(f"files={len(m)} sha1={sha}")
