# Consuming from webmedia (sketch)

Wire this up after a Release is published with Range + CORS confirmed.

## Env

| Var | Meaning |
| --- | ------- |
| `TESTVIDEO_BASE` | e.g. `https://github.com/<org>/testvideo/releases/download/v0.1.0` |
| `TESTVIDEO_MANIFEST` | optional path/URL to `manifest.json` |

## Expand fps × variants

```python
def expand(manifest: dict) -> list[dict]:
    clips = []
    w = manifest["resolution"]["width"]
    h = manifest["resolution"]["height"]
    for fps in manifest["fps"]:
        for var in manifest["variants"]:
            prefix = "hevc" if var["codec"] == "hvc1" else "avc"
            vid = var["id"]
            if var["codec"] == "hvc1" and vid.startswith("hevc_"):
                vid = vid[len("hevc_") :]
            cid = f"{prefix}_1080p_{fps['id']}_{vid}"
            clips.append({
                "id": cid,
                "asset": f"{cid}.mp4",
                "fps": fps,
                "variant": var,
                "width": w,
                "height": h,
            })
    return clips


def fixture_url(clip: dict, base: str) -> str:
    return f"{base.rstrip('/')}/{clip['asset']}"
```

## Sync expectations

- Soft tick / flash @ `t = 0, 0.5, 1.0, …`
- Loud tick / wash @ `t = 0, 2, 4, …`
- Burn-in `frame=` is **presentation** index
- Burn-in `t=` is media PTS (hms)
