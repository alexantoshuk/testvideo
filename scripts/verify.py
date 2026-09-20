#!/usr/bin/env python3
"""Verify clips/ against expanded manifest (fps × variants). Stdlib only."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIPS_DIR = ROOT / "clips"
MANIFEST_PATH = ROOT / "manifest.json"


def need(tool: str) -> None:
    if not shutil.which(tool):
        sys.exit(f"error: '{tool}' not found on PATH")


def expand_clip_ids(data: dict) -> list[tuple[str, str]]:
    """Return (clip_id, asset) pairs from compact manifest."""
    out: list[tuple[str, str]] = []
    for fps in data["fps"]:
        for var in data["variants"]:
            prefix = "hevc" if var["codec"] == "hvc1" else "avc"
            vid = var["id"]
            if var["codec"] == "hvc1" and vid.startswith("hevc_"):
                vid = vid[len("hevc_") :]
            cid = f"{prefix}_1080p_{fps['id']}_{vid}"
            out.append((cid, f"{cid}.mp4"))
    return out


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        text=True,
        errors="replace",
    ).strip()
    return float(out)


def probe_has_audio(path: Path) -> bool:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
        errors="replace",
    ).strip()
    return bool(out)


def main() -> None:
    need("ffprobe")
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = float(data.get("template", {}).get("durationSec", 60))
    missing: list[str] = []
    failed: list[str] = []

    clips = expand_clip_ids(data)
    print(f"expect {len(clips)} clips "
          f"({len(data['fps'])} fps x {len(data['variants'])} variants)")

    for cid, asset in clips:
        path = CLIPS_DIR / asset
        if not path.is_file():
            missing.append(cid)
            continue
        try:
            dur = probe_duration(path)
            if not probe_has_audio(path):
                failed.append(f"{cid}: no audio stream")
                continue
            if abs(dur - expected) > 1.0:
                failed.append(f"{cid}: duration {dur:.2f}s (expected ~{expected})")
                continue
            print(f"ok {cid}  duration={dur:.2f}s")
        except (subprocess.CalledProcessError, ValueError) as e:
            failed.append(f"{cid}: {e}")

    if missing:
        print("missing:", ", ".join(missing), file=sys.stderr)
    if failed:
        print("failed:", file=sys.stderr)
        for line in failed:
            print(" ", line, file=sys.stderr)
    if missing or failed:
        sys.exit(1)
    print("verify ok")


if __name__ == "__main__":
    main()
