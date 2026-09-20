#!/usr/bin/env python3
"""Generate A/V sync plates for the testvideo matrix.

Requires: Python 3.10+, ffmpeg, ffprobe on PATH.
Stdlib only (no pip deps).

Each clip is ~60s with:
  - burned-in timecode / frame / fps / encode metadata
  - soft tick every 0.5s, loud tick every 2.0s (WAV, exact phase)
  - visual flash on each tick (brighter on loud)
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLIPS_DIR = ROOT / "clips"
MANIFEST_PATH = ROOT / "manifest.json"

SAMPLE_RATE = 48_000
DURATION_SEC = 60.0
WIDTH = 1920
HEIGHT = 1080
SOFT_TICK_PERIOD = 0.5
LOUD_TICK_PERIOD = 2.0
SOFT_TICK_MS = 18
LOUD_TICK_MS = 35
SOFT_HZ = 1000.0
LOUD_HZ = 1500.0
SOFT_AMP = 0.22
LOUD_AMP = 0.85

# Flash windows (seconds) — must match tick phases.
SOFT_FLASH = 0.04
LOUD_FLASH = 0.07


@dataclass(frozen=True)
class FpsRate:
    """One frame-rate to generate for every variant."""

    id: str  # stable token in clip ids / filenames
    rate: str  # ffmpeg -r / lavfi rate (e.g. "24", "30000/1001")
    label: str  # burn-in label


@dataclass(frozen=True)
class Variant:
    """Encode knobs shared across FPS rates (no fps here)."""

    id: str
    gop: int | None
    b_frames: int
    key_mode: str  # "fixed" | "scenecut"
    codec: str  # "avc1" | "hvc1"
    container: str  # "mp4" | "fmp4"
    purpose: list[str]
    notes: str = ""


@dataclass(frozen=True)
class EncodeSpec:
    """Fully resolved clip (variant × fps) ready to encode."""

    id: str
    asset: str
    width: int
    height: int
    fps: str
    fps_label: str
    gop: int | None
    b_frames: int
    key_mode: str
    codec: str
    container: str
    purpose: list[str]
    notes: str = ""


# Frame rates — every variant is generated at each of these.
FPS_RATES: list[FpsRate] = [
    FpsRate("24", "24", "24"),
    FpsRate("60", "60", "60"),
    FpsRate("2997", "30000/1001", "29.97"),
]

# Encode variants (GOP / B-frames / keys / container / codec) — FPS-agnostic.
VARIANTS: list[Variant] = [
    Variant(
        "gop12_bf0",
        12,
        0,
        "fixed",
        "avc1",
        "mp4",
        ["smoke", "av-sync", "seek"],
    ),
    Variant(
        "gop12_bf2",
        12,
        2,
        "fixed",
        "avc1",
        "mp4",
        ["b-frames", "av-sync", "scrub"],
    ),
    Variant(
        "gop48_bf0",
        48,
        0,
        "fixed",
        "avc1",
        "mp4",
        ["long-gop", "av-sync", "scrub-settle"],
    ),
    Variant(
        "scenecut_bf0",
        None,
        0,
        "scenecut",
        "avc1",
        "mp4",
        ["variable-keys", "av-sync"],
        "Background hue shifts every 2s to encourage scenecuts.",
    ),
    Variant(
        "fmp4_gop12_bf0",
        12,
        0,
        "fixed",
        "avc1",
        "fmp4",
        ["fmp4", "progressive-open", "av-sync"],
    ),
    Variant(
        "hevc_gop12_bf0",
        12,
        0,
        "fixed",
        "hvc1",
        "mp4",
        ["hevc-key-verify", "av-sync"],
        "Skipped if libx265 is unavailable.",
    ),
]


def codec_prefix(codec: str) -> str:
    return "hevc" if codec == "hvc1" else "avc"


def expand_matrix() -> list[EncodeSpec]:
    """Cartesian product: each variant × each FPS → FullHD plate."""
    out: list[EncodeSpec] = []
    for fps in FPS_RATES:
        for var in VARIANTS:
            prefix = codec_prefix(var.codec)
            # Variant ids may start with hevc_ / fmp4_; strip codec echo from filename.
            vid = var.id
            if var.codec == "hvc1" and vid.startswith("hevc_"):
                vid = vid[len("hevc_") :]
            cid = f"{prefix}_1080p_{fps.id}_{vid}"
            out.append(
                EncodeSpec(
                    id=cid,
                    asset=f"{cid}.mp4",
                    width=WIDTH,
                    height=HEIGHT,
                    fps=fps.rate,
                    fps_label=fps.label,
                    gop=var.gop,
                    b_frames=var.b_frames,
                    key_mode=var.key_mode,
                    codec=var.codec,
                    container=var.container,
                    purpose=list(var.purpose),
                    notes=var.notes,
                )
            )
    return out


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        sys.exit(f"error: '{tool}' not found on PATH")
    return path


def find_font() -> str | None:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\consola.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/SFNSMono.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def write_tick_wav(path: Path, duration: float = DURATION_SEC) -> None:
    """Soft click @ 0.5s, loud click @ 2.0s (phase-aligned from t=0)."""
    n = int(duration * SAMPLE_RATE)
    buf = bytearray(n * 2)  # mono s16le

    def paint(t0: float, length_ms: float, hz: float, amp: float) -> None:
        length = int(SAMPLE_RATE * length_ms / 1000.0)
        start = int(t0 * SAMPLE_RATE)
        for i in range(length):
            idx = start + i
            if idx >= n:
                break
            # Hann envelope avoids clicks/pops at edges.
            env = 0.5 - 0.5 * math.cos(2 * math.pi * i / max(length - 1, 1))
            sample = amp * env * math.sin(2 * math.pi * hz * (i / SAMPLE_RATE))
            val = max(-32767, min(32767, int(sample * 32767)))
            struct.pack_into("<h", buf, idx * 2, val)

    steps = int(round(duration / SOFT_TICK_PERIOD))
    loud_every = int(round(LOUD_TICK_PERIOD / SOFT_TICK_PERIOD))
    for i in range(steps):
        t = i * SOFT_TICK_PERIOD
        if i % loud_every == 0:
            paint(t, LOUD_TICK_MS, LOUD_HZ, LOUD_AMP)
        else:
            paint(t, SOFT_TICK_MS, SOFT_HZ, SOFT_AMP)

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(buf))


def has_encoder(name: str) -> bool:
    out = subprocess.check_output(
        ["ffmpeg", "-hide_banner", "-encoders"],
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    return name in out


def build_vf_script(spec: EncodeSpec, meta_name: str) -> str:
    """Return -vf graph. Paths are basenames; ffmpeg cwd = work dir."""
    w, h = spec.width, spec.height
    soft = (
        f"drawbox=x=0:y=0:w={w}:h=12:color=white@0.55:t=fill:"
        f"enable='lt(mod(t\\,{SOFT_TICK_PERIOD})\\,{SOFT_FLASH})'"
    )
    loud = (
        f"drawbox=x=0:y=0:w={w}:h={h}:color=white@0.22:t=fill:"
        f"enable='lt(mod(t\\,{LOUD_TICK_PERIOD})\\,{LOUD_FLASH})'"
    )
    pulse = (
        f"drawbox=x={w - 80}:y={h - 80}:w=64:h=64:color=yellow@0.9:t=fill:"
        f"enable='lt(mod(t\\,{SOFT_TICK_PERIOD})\\,{SOFT_FLASH})'"
    )
    # Relative font + meta sidecars avoid Windows drive-letter escaping hell.
    fo = "fontfile=burnin.ttf:"
    line1 = (
        f"drawtext={fo}fontsize=36:fontcolor=white:box=1:boxcolor=black@0.65:"
        f"x=24:y=28:"
        f"text='t\\=%{{pts\\:hms}}  frame\\=%{{eif\\:n\\:d}}  fps\\={spec.fps_label}'"
    )
    line2 = (
        f"drawtext={fo}fontsize=22:fontcolor=white:box=1:boxcolor=black@0.65:"
        f"x=24:y=78:textfile={meta_name}:reload=0"
    )
    line3 = (
        f"drawtext={fo}fontsize=20:fontcolor=yellow:box=1:boxcolor=black@0.65:"
        f"x=24:y=120:"
        f"text='ticks  soft {SOFT_TICK_PERIOD}s / loud {LOUD_TICK_PERIOD}s'"
    )
    if spec.key_mode == "scenecut":
        head = "hue=h='360*floor(t/2)/30':s=1"
        return ",".join([head, soft, loud, pulse, line1, line2, line3])
    return ",".join([soft, loud, pulse, line1, line2, line3])


def lavfi_src(spec: EncodeSpec, duration: float) -> str:
    w, h = spec.width, spec.height
    if spec.key_mode == "scenecut":
        return f"color=c=0x1a1a2e:s={w}x{h}:d={duration}:r={spec.fps}"
    return f"testsrc2=size={w}x{h}:rate={spec.fps}:duration={duration}"


def encode(
    spec: EncodeSpec,
    wav: Path,
    font: str | None,
    out: Path,
    duration: float,
    work: Path,
) -> None:
    if spec.codec == "hvc1" and not has_encoder("libx265"):
        print(f"skip {spec.id} (libx265 not found)", file=sys.stderr)
        return
    if not font:
        print(f"skip {spec.id} (no TTF for burn-in)", file=sys.stderr)
        return

    gop_label = "scenecut" if spec.gop is None else str(spec.gop)
    meta = (
        f"{spec.id}  |  {spec.codec}  {spec.width}x{spec.height}  "
        f"{spec.fps_label}fps  gop={gop_label}  bf={spec.b_frames}  "
        f"keys={spec.key_mode}  {spec.container}"
    )
    meta_name = f"{spec.id}_meta.txt"
    (work / meta_name).write_text(meta + "\n", encoding="utf-8")
    font_dst = work / "burnin.ttf"
    if not font_dst.is_file():
        shutil.copy2(font, font_dst)
    vf_file = work / f"{spec.id}_vf.txt"
    vf_file.write_text(build_vf_script(spec, meta_name), encoding="utf-8")

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stats",
        "-f",
        "lavfi",
        "-i",
        lavfi_src(spec, duration),
        "-i",
        str(wav.resolve()),
        "-filter_script:v",
        vf_file.name,
        "-shortest",
        "-c:a",
        "aac",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-b:a",
        "128k",
    ]

    if spec.codec == "avc1":
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
        if spec.key_mode == "fixed":
            assert spec.gop is not None
            cmd += [
                "-g",
                str(spec.gop),
                "-keyint_min",
                str(spec.gop),
                "-sc_threshold",
                "0",
                "-bf",
                str(spec.b_frames),
            ]
        else:
            cmd += ["-g", "250", "-keyint_min", "24", "-sc_threshold", "40", "-bf", "0"]
    elif spec.codec == "hvc1":
        assert spec.gop is not None
        cmd += [
            "-c:v",
            "libx265",
            "-pix_fmt",
            "yuv420p",
            "-tag:v",
            "hvc1",
            "-x265-params",
            f"keyint={spec.gop}:min-keyint={spec.gop}:scenecut=0:bframes={spec.b_frames}",
        ]
    else:
        raise ValueError(spec.codec)

    if spec.container == "fmp4":
        cmd += ["-movflags", "frag_keyframe+empty_moov+default_base_moof"]
    else:
        cmd += ["-movflags", "+faststart"]

    cmd.append(str(out.resolve()))
    print(f"encode {spec.id} -> {out.name}")
    subprocess.run(cmd, check=True, cwd=str(work))


def write_manifest(path: Path, duration: float) -> None:
    """Compact manifest: fps × variants (no exploded clip list)."""
    doc: dict[str, Any] = {
        "name": "testvideo",
        "version": "0.1.0",
        "description": (
            "Synthetic A/V sync plates: burn-in timecode/frame/meta, "
            "soft ticks @0.5s and loud @2s with matching flashes. "
            "Expand fps[] × variants[] → clip id "
            "`{avc|hevc}_1080p_{fpsId}_{variantId}`."
        ),
        "baseUrlHint": "https://github.com/alexantoshuk/testvideo/releases/download/v0.1.0",
        "resolution": {"width": WIDTH, "height": HEIGHT},
        "template": {
            "durationSec": duration,
            "softTickSec": SOFT_TICK_PERIOD,
            "loudTickSec": LOUD_TICK_PERIOD,
            "audio": {
                "codec": "aac",
                "channels": 1,
                "sampleRate": SAMPLE_RATE,
                "pattern": {
                    "softTickSec": SOFT_TICK_PERIOD,
                    "loudTickSec": LOUD_TICK_PERIOD,
                    "alignedAt": 0.0,
                },
            },
            "burnIn": [
                "timecode (pts hms)",
                "presentation frame index",
                "fps label",
                "encode metadata",
                "tick flash (soft bar + loud wash + corner pulse)",
            ],
        },
        "fps": [
            {"id": f.id, "rate": f.rate, "label": f.label} for f in FPS_RATES
        ],
        "variants": [
            {
                "id": v.id,
                "codec": v.codec,
                "container": v.container,
                "gop": v.gop,
                "bFrames": v.b_frames,
                "keyMode": v.key_mode,
                "purpose": v.purpose,
                "notes": v.notes or None,
            }
            for v in VARIANTS
        ],
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    n = len(FPS_RATES) * len(VARIANTS)
    print(f"wrote {path}  ({len(FPS_RATES)} fps x {len(VARIANTS)} variants = {n} clips)")


def select_specs(only: list[str]) -> list[EncodeSpec]:
    """Filter expanded matrix by full clip id, variant id, or fps id."""
    matrix = expand_matrix()
    if not only:
        return matrix
    fps_ids = {f.id for f in FPS_RATES}
    var_ids = {v.id for v in VARIANTS}
    selected: list[EncodeSpec] = []
    seen: set[str] = set()
    for token in only:
        matched = False
        for spec in matrix:
            parts = spec.id.split("_")
            # avc_1080p_{fps}_{variant…} — fps token is parts[2]
            if token in fps_ids:
                hit = len(parts) >= 4 and parts[2] == token
            elif token in var_ids:
                if token.startswith("hevc_"):
                    vid = token[len("hevc_") :]
                    hit = spec.id.startswith("hevc_") and spec.id.endswith(f"_{vid}")
                else:
                    hit = (not spec.id.startswith("hevc_")) and spec.id.endswith(
                        f"_{token}"
                    )
            else:
                hit = spec.id == token
            if hit and spec.id not in seen:
                selected.append(spec)
                seen.add(spec.id)
                matched = True
        if not matched:
            sys.exit(
                f"unknown --only {token!r} "
                f"(use clip id, fps id {sorted(fps_ids)}, "
                f"or variant id {sorted(var_ids)})"
            )
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Clip id, fps id (24/60/2997), or variant id (repeatable).",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Rewrite manifest.json; do not encode.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DURATION_SEC,
        help=f"Plate length in seconds (default {DURATION_SEC}).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print expanded clip ids and exit.",
    )
    args = parser.parse_args()
    duration = float(args.duration)

    if args.list:
        for spec in expand_matrix():
            print(spec.id)
        return

    need("ffmpeg")
    need("ffprobe")
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    write_manifest(MANIFEST_PATH, duration)
    if args.manifest_only:
        return

    font = find_font()
    if font:
        print(f"font: {font}")
    else:
        print(
            "warning: no TTF found; drawtext may fail — install a system font",
            file=sys.stderr,
        )

    selected = select_specs(args.only)
    print(f"encoding {len(selected)} clip(s)")

    with tempfile.TemporaryDirectory(prefix="testvideo-") as tmp:
        work = Path(tmp)
        wav = work / "ticks.wav"
        write_tick_wav(wav, duration)
        for spec in selected:
            encode(spec, wav, font, CLIPS_DIR / spec.asset, duration, work)

    print("done.")


if __name__ == "__main__":
    main()
