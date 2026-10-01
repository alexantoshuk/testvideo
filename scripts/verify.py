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


def asset_name(cid: str, container: str) -> str:
    ext = "mov" if container == "mov" else "mp4"
    return f"{cid}.{ext}"


def expand_clip_ids(data: dict) -> list[tuple[str, str, dict]]:
    """Return (clip_id, asset, variant) from compact manifest (honors fpsIds)."""
    fps_by_id = {f["id"]: f for f in data["fps"]}
    out: list[tuple[str, str, dict]] = []
    for var in data["variants"]:
        fps_ids = var.get("fpsIds")
        fps_list = (
            [fps_by_id[i] for i in fps_ids]
            if fps_ids is not None
            else list(data["fps"])
        )
        for fps in fps_list:
            prefix = "hevc" if var["codec"] == "hvc1" else "avc"
            vid = var["id"]
            if var["codec"] == "hvc1" and vid.startswith("hevc_"):
                vid = vid[len("hevc_") :]
            cid = f"{prefix}_1080p_{fps['id']}_{vid}"
            out.append((cid, asset_name(cid, var["container"]), var))
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


def probe_audio(path: Path) -> tuple[str, int] | None:
    """Return (codec_name, channels) for first audio stream, or None."""
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,channels",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
        errors="replace",
    ).strip()
    if not out:
        return None
    # codec_name,channels  e.g. aac,1  or  pcm_s24le,2
    parts = out.split(",")
    if len(parts) < 2:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return parts[0], 0


def main() -> None:
    need("ffprobe")
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = float(data.get("template", {}).get("durationSec", 60))
    missing: list[str] = []
    failed: list[str] = []

    clips = expand_clip_ids(data)
    print(f"expect {len(clips)} clips (after fpsIds filters)")

    for cid, asset, var in clips:
        path = CLIPS_DIR / asset
        if not path.is_file():
            missing.append(cid)
            continue
        try:
            dur = probe_duration(path)
            audio = probe_audio(path)
            if audio is None:
                failed.append(f"{cid}: no audio stream")
                continue
            codec_name, channels = audio
            want_audio = var.get("audio", "aac")
            want_ch = int(var.get("audioChannels", 1))
            if codec_name != want_audio:
                failed.append(
                    f"{cid}: audio codec {codec_name!r} (expected {want_audio})"
                )
                continue
            if want_ch and channels and channels != want_ch:
                failed.append(
                    f"{cid}: channels {channels} (expected {want_ch})"
                )
                continue
            if abs(dur - expected) > 1.0:
                failed.append(f"{cid}: duration {dur:.2f}s (expected ~{expected})")
                continue
            print(
                f"ok {cid}  duration={dur:.2f}s  audio={codec_name}/{channels}ch"
            )
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
