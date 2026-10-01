# Consuming Release assets

Point a player or test harness at a published GitHub Release. Prefer **HTTP Range** (`206` + `Content-Range`). If the host lacks CORS (GitHub Releases do), fetch via a same-origin proxy or download locally.

## Env (suggested)

| Var | Meaning |
| --- | ------- |
| `TESTVIDEO_BASE` | e.g. `https://github.com/alexantoshuk/testvideo/releases/download/v0.3.0` |
| `TESTVIDEO_MANIFEST` | optional path/URL to `manifest.json` |

Clip URL: `{TESTVIDEO_BASE}/{asset}` — usually `{clipId}.mp4`, PCM QT plates use `.mov` (see expand).

## Expand fps × variants

```python
def expand(manifest: dict) -> list[dict]:
    clips = []
    w = manifest["resolution"]["width"]
    h = manifest["resolution"]["height"]
    fps_by_id = {f["id"]: f for f in manifest["fps"]}
    for var in manifest["variants"]:
        fps_ids = var.get("fpsIds")
        fps_list = (
            [fps_by_id[i] for i in fps_ids]
            if fps_ids is not None
            else list(manifest["fps"])
        )
        for fps in fps_list:
            prefix = "hevc" if var["codec"] == "hvc1" else "avc"
            vid = var["id"]
            if var["codec"] == "hvc1" and vid.startswith("hevc_"):
                vid = vid[len("hevc_") :]
            cid = f"{prefix}_1080p_{fps['id']}_{vid}"
            ext = "mov" if var["container"] == "mov" else "mp4"
            clips.append({
                "id": cid,
                "asset": f"{cid}.{ext}",
                "fps": fps,
                "variant": var,
                "width": w,
                "height": h,
            })
    return clips


def fixture_url(clip: dict, base: str) -> str:
    return f"{base.rstrip('/')}/{clip['asset']}"
```

## Useful stems (v0.3.0)

Not every consumer needs the full matrix. Common picks:

| Role | Asset stem |
| ---- | ---------- |
| short-GOP / baseline | `avc_1080p_25_gop12_bf0` |
| B-frames | `avc_1080p_25_gop12_bf2` |
| long-GOP + B-frames / Play lag | `avc_1080p_25_gop33_bf2` |
| long-GOP / scrub | `avc_1080p_25_gop48_bf0` |
| high-fps | `avc_1080p_60_gop12_bf0` |
| variable keys (scenecut) | `avc_1080p_25_scenecut_bf0` |
| fMP4 progressive | `avc_1080p_25_fmp4_gop12_bf0` |
| HEVC | `hevc_1080p_25_gop12_bf0` |
| QT MOV + PCM s24 (demux stress) | `avc_1080p_25_mov_pcm24_gop12_bf0` (`.mov`) |

Full list: `python scripts/generate.py --list` or `manifest.json`.

## Sync expectations

- Soft tick / flash @ `t = 0, 0.5, 1.0, …`
- Loud tick / wash @ `t = 0, 2, 4, …`
- Burn-in `frame=` is **presentation** index
- Burn-in `t=` is media PTS (hms)
