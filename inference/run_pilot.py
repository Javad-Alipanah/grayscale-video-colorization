"""Isolated CMNET2 pilot runner: one uninterrupted shot per invocation.

Produces a lossless RGB prediction for a later, independently verified source-Y merge.
Uses the official model API with bounded shot-local reference and working memory.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from config import WORKSPACE, REPO, FFMPEG, FFPROBE, PROJECT
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(PROJECT / 'hf-cache'))
os.environ["HF_HUB_OFFLINE"] = "1"
# PyTorch 2.11 uses weights_only=True by default for the main CMNET2 checkpoint.
# The official ResNet dependencies use an older tar serialization that requires
# model_zoo's explicit weights_only=False. Verify the canonical hashes below.
sys.path.insert(0, str(REPO))

import cv2
import numpy as np
from PIL import Image
import torch
from colormnet.colormnet_render import ColorMNetRender


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--refs", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--start-frame", type=int, default=0)
    p.add_argument("--frames", type=int, default=0)
    p.add_argument("--max-side", type=int, default=512)
    p.add_argument("--top-k", type=int, default=30)
    p.add_argument("--proximity-bias", action="store_true")
    p.add_argument("--disable-autotune", action="store_true")
    args = p.parse_args()
    started = time.perf_counter()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    refs = sorted((int(re.search(r"(\d+)$", f.stem).group(1)), f)
                  for f in args.refs.glob("*.png"))
    if not refs:
        raise RuntimeError("No numbered PNG references provided")
    probe = json.loads(subprocess.check_output([
        str(FFPROBE), "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-of", "json", str(args.input)]))["streams"][0]
    width, height = probe["width"], probe["height"]
    rate = probe["r_frame_rate"]
    cap = cv2.VideoCapture(str(args.input))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    frames = args.frames or total_frames - args.start_frame
    if args.start_frame < 0 or frames < 1 or args.start_frame + frames > total_frames:
        raise ValueError("Requested frame range is outside input")
    for idx, path in refs:
        if not 0 <= idx < frames:
            raise ValueError(f"Reference {path.name} must use shot-local zero-based frame index")
    scale = min(1, args.max_side / max(width, height)) if args.max_side > 0 else 1
    proc_w = int(round(width * scale / 2)) * 2
    proc_h = int(round(height * scale / 2)) * 2
    torch.hub.set_dir(str(REPO / "models"))
    torch.set_grad_enabled(False)
    torch.backends.cudnn.benchmark = True
    torch.cuda.reset_peak_memory_stats()
    legacy_hashes = {
        "resnet18-5c106cde.pth": "5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8",
        "resnet50-19c8e357.pth": "19c8e3572231adff6824a2da93fd67b5986919a2e65f8b6007eab4edee220097",
    }
    for filename, expected in legacy_hashes.items():
        if sha(REPO / "models/checkpoints" / filename) != expected:
            raise RuntimeError(f"Official legacy ResNet hash mismatch: {filename}")
    print(json.dumps({"stage": "initialize", "frames": frames, "processing_size": [proc_w, proc_h],
                      "refs": [i for i, f in refs]}, ensure_ascii=True), flush=True)
    colorizer = ColorMNetRender(vid_length=frames, encode_mode=1, max_memory_frames=frames,
        reset_on_ref_update=False, top_k=args.top_k, mem_every=5, project_dir=str(REPO),
        backbone="dinov3", enable_proximity_bias=args.proximity_bias)
    if args.disable_autotune:
        torch.backends.cudnn.benchmark = False
    checkpoint_keys = colorizer.model_weights
    unmatched_keys = []
    shape_mismatches = []
    own_state = colorizer.network.state_dict()
    for key, tensor in own_state.items():
        alternate = key.replace("backbone.layer.", "backbone.model.layer.")
        source = checkpoint_keys.get(key, checkpoint_keys.get(alternate))
        if source is None:
            unmatched_keys.append(key)
        elif tuple(source.shape) != tuple(tensor.shape):
            shape_mismatches.append(key)
    important_missing = [key for key in unmatched_keys if not key.endswith("num_batches_tracked")]
    if important_missing or shape_mismatches:
        raise RuntimeError(f"Incomplete trained checkpoint coverage: {important_missing}, {shape_mismatches}")
    weight_coverage = {"state_entries": len(own_state), "unmatched_keys": unmatched_keys,
                       "shape_mismatches": shape_mismatches, "all_trained_parameters_matched": True}
    references = []
    for idx, path in refs:
        ref = Image.open(path).convert("RGB").resize((proc_w, proc_h), Image.Resampling.LANCZOS)
        colorizer.preload_reference(ref, frame_idx=idx)
        references.append((idx, ref))
    torch.cuda.synchronize()
    init_seconds = time.perf_counter() - started
    output = args.output_dir / "prediction_rgb_ffv1.mkv"
    decoder_log = open(args.output_dir / "decode.log", "w")
    encoder_log = open(args.output_dir / "encode.log", "w")
    decoder = subprocess.Popen([str(FFMPEG), "-v", "error", "-i", str(args.input),
        "-an", "-vf", f"trim=start_frame={args.start_frame}:end_frame={args.start_frame+frames},setpts=PTS-STARTPTS",
        "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        stdout=subprocess.PIPE, stderr=decoder_log)
    encoder = subprocess.Popen([str(FFMPEG), "-v", "error", "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}", "-framerate", rate, "-i", "pipe:0", "-an",
        "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0", str(output)],
        stdin=subprocess.PIPE, stderr=encoder_log)
    inference_seconds = 0.0
    min_free = torch.cuda.mem_get_info()[0]
    render_start = time.perf_counter()
    timings = []
    try:
        for i in range(frames):
            raw = decoder.stdout.read(width * height * 3)
            if len(raw) != width * height * 3:
                raise RuntimeError(f"Short decode at frame {i}")
            original = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
            proc = Image.fromarray(original).resize((proc_w, proc_h), Image.Resampling.LANCZOS)
            colorizer.set_ref_frame(references[0][1] if i == 0 else None)
            t0 = time.perf_counter()
            colored = colorizer.colorize_frame(ti=i, frame_i=proc, lab_mode="gpu")
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - t0
            timings.append(elapsed)
            inference_seconds += elapsed
            colored_full = colored.resize((width, height), Image.Resampling.LANCZOS)
            encoder.stdin.write(np.asarray(colored_full, dtype=np.uint8).tobytes())
            if i in (0, 1, 5, 12, frames - 1) or i % 48 == 0:
                colored_full.save(args.output_dir / f"preview_{i:06d}.png")
            free, total = torch.cuda.mem_get_info()
            min_free = min(min_free, free)
            if i % 24 == 0 or i == frames - 1:
                print(json.dumps({"stage": "render", "done": i + 1, "total": frames,
                    "elapsed_s": round(time.perf_counter() - render_start, 2),
                    "gpu_allocated_mib": round(torch.cuda.memory_allocated() / 1024**2),
                    "gpu_free_mib": round(free / 1024**2)}), flush=True)
    finally:
        encoder.stdin.close()
        decoder.stdout.close()
        encoder.wait()
        decoder.wait()
        encoder_log.close()
        decoder_log.close()
    if encoder.returncode or decoder.returncode:
        raise RuntimeError(f"FFmpeg failure encode={encoder.returncode} decode={decoder.returncode}")
    render_seconds = time.perf_counter() - render_start
    metrics = {
        "input": str(args.input.resolve()), "input_start_frame": args.start_frame,
        "frames": frames, "rate": rate, "source_size": [width, height], "processing_size": [proc_w, proc_h],
        "output": str(output.resolve()), "output_kind": "lossless RGB chroma prediction; source Y not merged here",
        "model": "CMNET2 DINOv3 p374099", "repo_commit": subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip(),
        "weight_key_coverage": weight_coverage,
        "settings": {"top_k": args.top_k, "mem_every": 5, "max_memory_frames": frames,
                     "references_preloaded": len(refs), "proximity_bias": args.proximity_bias,
                     "precision": "float32, official default", "separate_process_per_shot": True,
                     "cudnn_benchmark": not args.disable_autotune},
        "references": [{"frame": i, "path": str(f.resolve()), "sha256": sha(f)} for i, f in refs],
        "gpu": torch.cuda.get_device_name(), "compute_capability": list(torch.cuda.get_device_capability()),
        "torch_cuda": torch.version.cuda,
        "versions": {name: importlib.metadata.version(name) for name in ["torch", "torchvision", "transformers", "numpy", "opencv-python", "scikit-image"]},
        "initialization_seconds": init_seconds, "render_seconds": render_seconds,
        "inference_seconds": inference_seconds, "inference_fps": frames / inference_seconds,
        "render_fps": frames / render_seconds,
        "peak_torch_allocated_mib": torch.cuda.max_memory_allocated() / 1024**2,
        "peak_torch_reserved_mib": torch.cuda.max_memory_reserved() / 1024**2,
        "minimum_system_free_mib_during_inference": min_free / 1024**2,
        "per_frame_inference_seconds": timings,
        "output_sha256": sha(output),
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({"stage": "complete", "render_fps": metrics["render_fps"],
        "peak_torch_allocated_mib": metrics["peak_torch_allocated_mib"], "output": str(output)}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
