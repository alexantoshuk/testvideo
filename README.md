# testvideo

Public, versioned **A/V sync plates** for [webmedia](https://github.com/) (and similar players).

Agents: see **[`AGENTS.md`](./AGENTS.md)** first.

Each clip is ~**60 seconds**, **Full HD**, always with **audio**, burned-in **timecode / frame / fps / encode meta**, and a metronome:

| Tick | Interval | Visual |
| ---- | -------- | ------ |
| Soft | every **0.5 s** | top bar + yellow corner pulse |
| Loud | every **2.0 s** | full-frame wash (plus soft cues) |

## Manifest shape

Compact — **not** one row per clip:

- `fps[]` — rates to generate (`24`, `60`, `2997` = 29.97)
- `variants[]` — GOP / B-frames / keyMode / codec / container
- `resolution` — currently always 1920×1080

Expand: every variant × every fps →

```text
{avc|hevc}_1080p_{fpsId}_{variantId}.mp4
```

Example: `avc_1080p_60_gop12_bf2.mp4`

## Why Python

`scripts/*.py` are **stdlib-only** (3.10+). Same commands on Windows / macOS / Linux.
External tools: **ffmpeg** + **ffprobe** on `PATH`.

## Quick start

```bash
python scripts/generate.py --list              # print all clip ids
python scripts/generate.py --manifest-only
python scripts/generate.py --only 60           # all variants @ 60fps
python scripts/generate.py --only gop12_bf2    # that variant @ every fps
python scripts/generate.py --only avc_1080p_24_gop12_bf0
python scripts/generate.py --duration 15
python scripts/verify.py
```

## Hosting (hard)

1. **HTTP Range** → `206` + `Content-Range`
2. **CORS** for the demo origin (e.g. `http://127.0.0.1:3000`)

See `CONSUMING.md`.

## License

**CC0-1.0** — synthetic lavfi + generated PCM only.
