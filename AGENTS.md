# AGENTS.md — testvideo

Portable notes for any editor/agent.

## Start of session

1. Read **`README.md`** (matrix + generate commands).
2. Skim **`CONSUMING.md`** if wiring URLs into a player/tests.
3. Source of truth for the matrix: `FPS_RATES` + `VARIANTS` in `scripts/generate.py` (also written to `manifest.json`).

## Generate

Needs **Python 3.10+**, **ffmpeg**, **ffprobe** on `PATH`. No pip deps.

```bash
python scripts/generate.py --list
python scripts/generate.py --manifest-only
python scripts/generate.py                  # all fps × variants (~60s FullHD)
python scripts/generate.py --only 60
python scripts/generate.py --only gop12_bf2
python scripts/generate.py --duration 15    # short smoke plates
python scripts/verify.py
```

Outputs → `clips/` (gitignored). Ship via GitHub Releases; keep Range + CORS.

## Do not

- Commit multi‑MB MP4s to git by default.
- Add third-party copyrighted movies.
- Invent a parallel manifest format — expand `fps[]` × `variants[]` as in README.
