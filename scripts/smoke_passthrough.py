"""Replay the portable CPU chain using generated synthetic media only.

Run with COLOR_FFMPEG/COLOR_FFPROBE configured, or FFmpeg on PATH.
The explicit fixture review below approves synthetic test output only.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
out = Path(tempfile.mkdtemp(prefix="color-passthrough-smoke-"))
source, project = out / "source.mp4", out / "project"
env = dict(os.environ)
ffmpeg = env.get("COLOR_FFMPEG", "ffmpeg")
ffprobe = env.get("COLOR_FFPROBE", "ffprobe")
subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
    "testsrc2=size=64x48:rate=24:duration=1", "-f", "lavfi", "-i",
    "sine=frequency=300:sample_rate=48000:duration=1", "-vf", "format=gray,format=yuv420p",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_range", "tv",
    "-colorspace", "smpte170m", "-color_trc", "smpte170m", "-color_primaries",
    "smpte170m", "-c:a", "aac", str(source)], check=True)
census = out / "shots.json"
census.write_text(json.dumps(dict(status="reviewed", reviewed_by="synthetic-integration-fixture",
    reviewed_at="2026-10-07", shots=[dict(id="a", start_frame=0, end_frame=12, mode="passthrough"),
    dict(id="b", start_frame=12, end_frame=24, mode="passthrough")])), encoding="utf-8")

def cli(*args):
    try:
        subprocess.run([sys.executable, str(repo / "pipeline.py"), *map(str, args),
            "--project", str(project)], env=env, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", file=sys.stderr)
        print(error.stderr or "", file=sys.stderr)
        raise

cli("init", "--source", source, "--shots", census)
cli("next")
cli("status")
cli("render", "--batch", "batch_001")
cli("deliver", "--batch", "batch_001")
state = json.loads((project / "pipeline.json").read_text())
review = out / "synthetic-review.json"
review.write_text(json.dumps(dict(status="accepted", reviewed_by="synthetic-integration-fixture",
    reviewed_at="2026-10-07", notes="Synthetic CPU integration only; not lecture or visual approval",
    master_sha256=state["batches"][0]["master_sha256"])), encoding="utf-8")
cli("review", "--batch", "batch_001", "--review-file", review)
cli("assemble")
state = json.loads((project / "pipeline.json").read_text())
assert state["full_artifact"]["automatically_accepted"] is False
subprocess.run([sys.executable, str(repo / "scripts/verify_preservation.py"), "--source", str(source),
    "--master", state["full_artifact"]["master"], "--ffmpeg", ffmpeg, "--ffprobe", ffprobe,
    "--pts-tolerance-ms", "1", "--report", str(out / "preservation.json")],
    env=env, check=True, capture_output=True, text=True)
print(json.dumps(dict(synthetic_only=True, project=str(project),
    full_artifact_status=state["full_artifact"]["status"], preservation_receipt=str(out / "preservation.json"))))
