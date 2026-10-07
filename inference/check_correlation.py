import json
from pathlib import Path
import os
import torch
from spatial_correlation_sampler import SpatialCorrelationSampler

torch.manual_seed(42)
records = []
for patch, dilation in [(3, 1), (5, 2), (15, 1)]:
    a = torch.randn(2, 7, 8, 9)
    b = torch.randn_like(a)
    expected = torch.zeros(2, patch, patch, 8, 9)
    for py in range(patch):
        for px in range(patch):
            for y in range(8):
                for x in range(9):
                    yy = y + (py - patch // 2) * dilation
                    xx = x + (px - patch // 2) * dilation
                    if 0 <= yy < 8 and 0 <= xx < 9:
                        expected[:, py, px, y, x] = (a[:, :, y, x] * b[:, :, yy, xx]).sum(dim=1)
    op = SpatialCorrelationSampler(patch_size=patch, dilation_patch=dilation)
    for device in (["cpu", "cuda"] if torch.cuda.is_available() and os.environ.get("COLOR_CHECK_CUDA")=="1" else ["cpu"]):
        actual = op(a.to(device), b.to(device)).cpu()
        max_error = float((actual - expected).abs().max())
        assert torch.allclose(actual, expected, atol=2e-6, rtol=2e-6)
        records.append({"patch_size": patch, "dilation_patch": dilation, "device": device,
                        "max_absolute_error": max_error, "passed": True})
result = {"operation": "channel dot-product local correlation", "reference": "explicit spatial-offset loops",
          "torch": torch.__version__, "cuda": torch.version.cuda, "checks": records}
output = Path(os.environ.get("COLOR_PROJECT", str(Path(__file__).resolve().parents[1] / "work/projects/default"))) / "correlation_verification.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, indent=2))
print(json.dumps(result))
