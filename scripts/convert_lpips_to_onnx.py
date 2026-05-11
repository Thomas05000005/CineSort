"""Script one-shot : export du modele LPIPS AlexNet au format ONNX.

Ce script est execute manuellement une fois par le developpeur avant le
build, pour generer `assets/models/lpips_alexnet.onnx` qui sera inclus dans
le bundle PyInstaller. Il n'est PAS appele au runtime.

Prerequis (installation temporaire dans un venv dedie) :
    pip install torch lpips onnx

Usage :
    python scripts/convert_lpips_to_onnx.py

Sortie : assets/models/lpips_alexnet.onnx (~55 MB)
"""

from __future__ import annotations

import sys
from pathlib import Path


OUTPUT_PATH = Path("assets/models/lpips_alexnet.onnx")
INPUT_SIZE = 256
OPSET_VERSION = 17


def _build_wrapper(lpips_model, torch):
    """nn.Module wrapper : signature fixe (img_a, img_b) -> distance scalaire."""

    class LpipsWrapper(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, img_a, img_b):
            return self.m.forward(img_a, img_b, normalize=False)

    return LpipsWrapper(lpips_model)


def main() -> int:
    try:
        import torch
        import lpips
    except ImportError as exc:
        print(f"[ERREUR] Dependance manquante : {exc}", file=sys.stderr)
        print("Installer avec : pip install torch lpips onnx", file=sys.stderr)
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Chargement LPIPS AlexNet...")
    model = lpips.LPIPS(net="alex", verbose=False)
    model.eval()

    dummy_a = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE, dtype=torch.float32)
    dummy_b = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE, dtype=torch.float32)

    wrapper = _build_wrapper(model, torch)
    wrapper.eval()

    # Sanity check : appel direct avant export
    with torch.no_grad():
        sanity = wrapper(dummy_a, dummy_b)
        print(f"Sanity forward OK : shape={tuple(sanity.shape)}")

    print(f"Export ONNX vers {OUTPUT_PATH}...")
    # Note : `dynamo=False` -> mode tracing legacy, plus robuste pour embarquer
    # tous les poids dans le .onnx (evite le bug weight-sharing du mode dynamo).
    torch.onnx.export(
        wrapper,
        (dummy_a, dummy_b),
        str(OUTPUT_PATH),
        input_names=["img_a", "img_b"],
        output_names=["distance"],
        dynamic_axes=None,
        opset_version=OPSET_VERSION,
        do_constant_folding=True,
        dynamo=False,
    )

    # Consolider en un seul fichier .onnx (inclut tous les poids inline).
    # Par defaut torch 2.x externalise les poids dans un fichier .data separe.
    try:
        import onnx

        model_proto = onnx.load(str(OUTPUT_PATH), load_external_data=True)
        for tensor in model_proto.graph.initializer:
            if tensor.data_location == onnx.TensorProto.EXTERNAL:
                tensor.data_location = onnx.TensorProto.DEFAULT
                tensor.ClearField("external_data")
        onnx.save_model(
            model_proto,
            str(OUTPUT_PATH),
            save_as_external_data=False,
        )
        external_data_file = OUTPUT_PATH.with_suffix(".onnx.data")
        if external_data_file.exists():
            external_data_file.unlink()
        print("Poids consolides dans le fichier .onnx (self-contained).")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Consolidation external data : {exc}", file=sys.stderr)

    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(f"OK : {OUTPUT_PATH} ({size_mb:.1f} MB)")

    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(str(OUTPUT_PATH), providers=["CPUExecutionProvider"])
        test_a = dummy_a.numpy()
        test_b = dummy_b.numpy()
        result = sess.run(None, {"img_a": test_a, "img_b": test_b})
        arr = result[0]
        dist = float(arr.reshape(-1)[0])
        print(f"Validation inference : distance = {dist:.4f}")
    except ImportError:
        print("onnxruntime non installe -> validation ignoree")
    except Exception as exc:
        print(f"[WARN] Validation inference echouee : {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
