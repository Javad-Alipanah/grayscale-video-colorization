"""Portable paths. Code and per-project mutable state have separate roots."""
import os
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
REPOSITORY = CODE_DIR.parent
WORKSPACE = Path(os.environ.get('COLOR_WORKSPACE', REPOSITORY)).expanduser().resolve()
PROJECT = Path(os.environ.get('COLOR_PROJECT', WORKSPACE / 'work/projects/default')).expanduser().resolve()
PYTHON = Path(os.environ.get('COLOR_PYTHON', sys.executable)).expanduser()
REPO = Path(os.environ.get('COLOR_CMNET2', REPOSITORY / 'external/cmnet2')).expanduser().resolve()
RUNNER = REPOSITORY / 'inference/run_pilot.py'
FFMPEG = os.environ.get('COLOR_FFMPEG', 'ffmpeg')
FFPROBE = os.environ.get('COLOR_FFPROBE', 'ffprobe')
GPU_LOCK = WORKSPACE / 'work/gpu_queue.lock'
