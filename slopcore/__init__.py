"""Slopcore — the verified music-video pipeline, as Hermes tools.

The fleet's production law, encoded as gates instead of advice:

- A performance insert is fed the isolated VOCAL STEM, never the full mix.
- Envelope correlation is rhythm, not lip-sync: it is a lag record, never
  articulation proof. A batch ships only behind a hero insert a human
  watched full-screen and passed (the Director's Law).
- The finished film must land on the exact frame grid, and its audio must
  BE the master (waveform correlation), laid at the exact seconds the
  generator was fed.

`slopcore_verify` is the first tool: pure gates + measurements over a
build folder. It runs anywhere ffmpeg/ffprobe exist.
"""

from __future__ import annotations

import json
import math
import subprocess
from array import array
from pathlib import Path
from typing import Any, Optional

CORR_MIN = 0.98          # final audio vs master, waveform Pearson at lag 0
LAG_TOLERANCE_FRAMES = 1  # an adopted insert's lag record must be 0 ± 1


# ---------------------------------------------------------------- gates

def gate_takes(takes: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Fidelity gates over the take ledger. Returns (failures, warnings)."""
    failures: list[str] = []
    warnings: list[str] = []
    adopted = [t for t in takes if t.get("adopted")]
    inserts = [t for t in adopted if t.get("role") == "insert"]
    for take in inserts:
        tid = take.get("id", "?")
        if take.get("feed") == "full_mix":
            failures.append(
                f"{tid}: fed the FULL MIX — inserts are fed the vocal stem, never the mix")
        if take.get("feed") not in ("vocal_stem", "full_mix"):
            failures.append(f"{tid}: feed not declared (must be vocal_stem)")
        lag = take.get("lag_frames")
        if lag is None:
            failures.append(f"{tid}: no lag record — every take carries its own")
        elif abs(int(lag)) > LAG_TOLERANCE_FRAMES:
            failures.append(f"{tid}: lag {lag} frames exceeds ±{LAG_TOLERANCE_FRAMES}")
        if take.get("sync_evidence") == "envelope":
            warnings.append(
                f"{tid}: sync evidence is envelope-only (rhythm, not articulation)")
    if inserts and not any(t.get("hero") and t.get("hero_eye_pass") for t in inserts):
        failures.append(
            "no hero insert passed a human full-screen eye — the batch is locked "
            "(Director's Law: envelope numbers never unlock a batch)")
    return failures, warnings


# ---------------------------------------------------------- measurements

def _ffprobe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_entries",
         "stream=codec_type,nb_read_frames,r_frame_rate",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def _decode_mono(path: Path, rate: int = 8000) -> array:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate),
         "-f", "f32le", "-"],
        capture_output=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed on {path}")
    samples = array("f")
    samples.frombytes(out.stdout)
    return samples


def _pearson(a: array, b: array) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    ma = math.fsum(a[:n]) / n
    mb = math.fsum(b[:n]) / n
    num = math.fsum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(math.fsum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(math.fsum((b[i] - mb) ** 2 for i in range(n)))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def verify_build(build_dir: str, final: Optional[str] = None,
                 master: Optional[str] = None, fps: int = 24) -> dict[str, Any]:
    root = Path(build_dir)
    failures: list[str] = []
    warnings: list[str] = []
    measurements: dict[str, Any] = {}

    ledger_path = root / "takes.json"
    if not ledger_path.exists():
        return {"verdict": "fail", "failures": [f"no take ledger at {ledger_path}"],
                "warnings": [], "measurements": {}}
    takes = json.loads(ledger_path.read_text(encoding="utf-8"))
    f, w = gate_takes(takes)
    failures += f
    warnings += w

    final_path = Path(final) if final else None
    if final_path is None:
        for cand in ("final.mp4", "final.mkv", "final.mov"):
            if (root / cand).exists():
                final_path = root / cand
                break
    if final_path is None or not final_path.exists():
        failures.append("final film not found in the build folder")
    else:
        probe = _ffprobe(final_path)
        vstream = next(s for s in probe["streams"] if s["codec_type"] == "video")
        frames = int(vstream.get("nb_read_frames") or 0)
        duration = float(probe["format"]["duration"])
        measurements["final_frames"] = frames
        measurements["final_duration_s"] = round(duration, 3)
        expected = round(duration * fps)
        if abs(frames - expected) > 1:
            failures.append(
                f"frame grid: final has {frames} frames but {duration:.2f}s at "
                f"{fps}fps expects {expected} — off-grid assembly")
        manifest_path = root / "manifest.json"
        if manifest_path.exists():
            segments = json.loads(manifest_path.read_text(encoding="utf-8"))
            total = sum(int(s.get("frames", 0)) for s in segments)
            measurements["manifest_frames"] = total
            if total != frames:
                failures.append(
                    f"manifest sums to {total} frames, final has {frames} — "
                    "the assembly drifted from its own manifest")

    master_path = Path(master) if master else None
    if master_path is not None and final_path is not None and final_path.exists():
        if not master_path.exists():
            failures.append(f"master audio not found: {master_path}")
        else:
            mdur = float(_ffprobe(master_path)["format"]["duration"])
            measurements["master_duration_s"] = round(mdur, 3)
            fdur = measurements.get("final_duration_s", 0.0)
            if abs(fdur - mdur) > (1.0 / fps):
                failures.append(
                    f"duration mismatch: final {fdur:.2f}s vs master {mdur:.2f}s "
                    "— the film must be exactly the master long")
            corr = _pearson(_decode_mono(final_path), _decode_mono(master_path))
            measurements["audio_correlation"] = round(corr, 4)
            if corr < CORR_MIN:
                failures.append(
                    f"audio correlation {corr:.4f} < {CORR_MIN} — the final's "
                    "audio is not the master, sample for sample")

    return {"verdict": "fail" if failures else "pass",
            "failures": failures, "warnings": warnings,
            "measurements": measurements}


# ------------------------------------------------------------- wordmap

def _rms_envelope(samples: array, rate: int, hop_s: float = 0.01,
                  win_s: float = 0.025) -> list[float]:
    hop = max(1, int(rate * hop_s))
    win = max(1, int(rate * win_s))
    env: list[float] = []
    for start in range(0, max(1, len(samples) - win), hop):
        seg = samples[start:start + win]
        env.append(math.sqrt(math.fsum(x * x for x in seg) / len(seg)))
    return env


def detect_onsets(samples: array, rate: int) -> tuple[list[float], float]:
    """Energy-flux onset picking. Returns (onset seconds, peak RMS)."""
    env = _rms_envelope(samples, rate)
    if not env:
        return [], 0.0
    peak = max(env)
    flux = [0.0] + [max(0.0, env[i] - env[i - 1]) for i in range(1, len(env))]
    ordered = sorted(flux)
    median = ordered[len(ordered) // 2]
    threshold = max(median * 4.0, peak * 0.04, 1e-5)
    onsets: list[float] = []
    min_gap_frames = 12  # 120 ms
    last = -min_gap_frames
    for i, value in enumerate(flux):
        if value >= threshold and i - last >= min_gap_frames:
            if i + 1 < len(flux) and flux[i + 1] > value:
                continue  # let the local peak win
            onsets.append(i * 0.01)
            last = i
    return onsets, peak


def _tokens(text: str) -> list[str]:
    out = []
    for raw in text.replace("—", " ").replace("-", " ").split():
        word = "".join(c for c in raw.lower() if c.isalnum() or c == "'")
        if word:
            out.append(word)
    return out


def build_wordmap(stem_path: str, lyrics: str,
                  transcript: Optional[str] = None) -> dict[str, Any]:
    """Align lyric words to measured onsets in the vocal stem.

    The gate this encodes: a wordmap is only worth anything if it is
    checked against the stem's MEASURED onsets — never against where the
    words were supposed to be. Silence where words are claimed, or a
    transcript that does not contain the words, fails the build.
    """
    failures: list[str] = []
    warnings: list[str] = []
    samples = _decode_mono(Path(stem_path), rate=16000)
    onsets, peak = detect_onsets(samples, 16000)
    words = _tokens(lyrics)
    if peak < 1e-4:
        failures.append("the stem is silent — no vocal to align words to")
    entries: list[dict[str, Any]] = []
    cursor = 0
    last_t = 0.0
    for word in words:
        hit: Optional[float] = None
        while cursor < len(onsets):
            t = onsets[cursor]
            cursor += 1
            if t >= last_t - 0.05:
                hit = t
                break
        if hit is None:
            entries.append({"word": word, "t": None, "source": "unmatched"})
        else:
            entries.append({"word": word, "t": round(hit, 3), "source": "onset"})
            last_t = hit
    matched = sum(1 for e in entries if e["source"] == "onset")
    coverage = matched / len(words) if words else 0.0
    prev: Optional[float] = None
    for e in entries:  # fill unmatched with monotone estimates, flagged
        if e["t"] is None:
            e["t"] = round((prev or 0.0) + 0.3, 3)
            e["source"] = "estimated"
        prev = e["t"]
    if words and coverage < 0.5:
        failures.append(
            f"onset coverage {coverage:.0%} — fewer than half the lyric words "
            "land on a measured onset; the wordmap does not describe this stem")
    elif coverage < 0.85:
        warnings.append(
            f"onset coverage {coverage:.0%}; unmatched words carry estimated times")
    agreement: Optional[float] = None
    if transcript is not None:
        heard = _tokens(transcript)
        same = sum(1 for a, b in zip(words, heard) if a == b)
        agreement = same / max(1, min(len(words), len(heard)))
        if agreement < 0.6:
            failures.append(
                f"transcript agreement {agreement:.0%} — the stem does not "
                "sing these words (content proof failed)")
    return {
        "verdict": "fail" if failures else "pass",
        "failures": failures, "warnings": warnings,
        "words": len(words), "onsets": len(onsets),
        "coverage": round(coverage, 3),
        "transcript_agreement": None if agreement is None else round(agreement, 3),
        "wordmap": entries,
    }

# --------------------------------------------------------------- intake

import hashlib  # noqa: E402  (intake section)

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTS = {".md", ".txt", ".json"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def intake_bundle(build_dir: str, sources: list[str]) -> dict[str, Any]:
    """Open a build folder from a multi-source bundle (the source board).

    Song-first law, encoded: a bundle with no audio source cannot open a
    build. Every source is fingerprinted (SHA-256) so later stages can
    prove they worked on the material that was actually handed in.
    """
    failures: list[str] = []
    root = Path(build_dir)
    root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    kinds: dict[str, str] = {".wav": "audio", ".mp3": "audio", ".flac": "audio",
                             ".m4a": "audio", ".ogg": "audio",
                             ".png": "image", ".jpg": "image", ".jpeg": "image",
                             ".webp": "image", ".md": "text", ".txt": "text",
                             ".json": "text"}
    for raw in sources:
        p = Path(raw)
        if not p.exists():
            failures.append(f"source not found: {raw}")
            continue
        kind = kinds.get(p.suffix.lower(), "file")
        entry: dict[str, Any] = {
            "path": str(p), "kind": kind, "bytes": p.stat().st_size,
            "sha256": _sha256(p),
        }
        if kind == "audio":
            try:
                entry["duration_s"] = round(
                    float(_ffprobe(p)["format"]["duration"]), 3)
            except Exception as exc:
                failures.append(f"audio source unreadable: {raw} ({exc})")
        entries.append(entry)
    if not any(e["kind"] == "audio" for e in entries):
        failures.append(
            "no audio source in the bundle — song first: a build opens from "
            "a finished song, everything else is built around it")
    manifest = {"version": 1, "sources": entries}
    (root / "intake.json").write_text(json.dumps(manifest, indent=2),
                                      encoding="utf-8")
    return {"verdict": "fail" if failures else "pass", "failures": failures,
            "build_dir": str(root), "sources": len(entries),
            "kinds": sorted({e["kind"] for e in entries})}


# ----------------------------------------------------------------- stem

STEM_API_DEFAULT = "https://aichord-aichordfinder-api.hf.space/separate"
STEM_ORIGIN = "https://aichordfinder.com"


def _find_vocal_payload(node: Any, depth: int = 0) -> Optional[str]:
    """Locate the vocals stem (base64 audio) in a separation response."""
    if depth > 4:
        return None
    if isinstance(node, dict):
        for key, value in node.items():
            if "vocal" in str(key).lower() and isinstance(value, str) \
                    and len(value) > 1000:
                return value
        for value in node.values():
            found = _find_vocal_payload(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_vocal_payload(value, depth + 1)
            if found:
                return found
    return None


def separate_stem(audio_path: str, out_dir: str,
                  api_url: str = STEM_API_DEFAULT,
                  timeout: int = 900) -> dict[str, Any]:
    """Isolate the vocal stem via a hosted Demucs separator (fleet-proven
    route: the aichord FastAPI Space runs htdemucs on its own CPU — no
    local model downloads, $0). The returned stem is content-checked:
    a silent 'vocal' stem is a failure, never a deliverable (the Pika
    audio-stems lesson: sung vocals came back as silence there)."""
    import base64
    import urllib.request
    import uuid

    src = Path(audio_path)
    if not src.exists():
        return {"verdict": "fail", "failures": [f"audio not found: {audio_path}"]}
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{src.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + src.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        api_url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Origin": STEM_ORIGIN})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"verdict": "fail",
                "failures": [f"separator request failed: {exc}"]}
    encoded = _find_vocal_payload(payload)
    if not encoded:
        return {"verdict": "fail",
                "failures": ["separator response held no vocals stem "
                             f"(keys: {list(payload)[:8] if isinstance(payload, dict) else type(payload).__name__})"]}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mp3_path = out / "vocal-stem.mp3"
    wav_path = out / "vocal-stem.wav"
    mp3_path.write_bytes(base64.b64decode(encoded))
    conv = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp3_path),
         "-ac", "1", "-ar", "44100", str(wav_path)],
        capture_output=True, text=True, timeout=300)
    if conv.returncode != 0:
        return {"verdict": "fail",
                "failures": [f"stem decode failed: {conv.stderr.strip()[:200]}"]}
    samples = _decode_mono(wav_path, rate=16000)
    _, peak = detect_onsets(samples, 16000)
    if peak < 1e-3:
        return {"verdict": "fail",
                "failures": ["the returned vocal stem is silent — a sung "
                             "vocal classified away is a failed separation, "
                             "not a stem"]}
    return {"verdict": "pass", "failures": [],
            "vocal_stem": str(wav_path), "peak_rms": round(peak, 4),
            "note": "content-check the stem (transcription / wordmap onset "
                    "gate) before any performance stage consumes it"}


# --------------------------------------------------------------- insert

REF2VA_RATE_PER_S = 0.03  # Pika H3 Flex reference-to-video, 480p (fleet receipts)
PIKA_HOST = "https://api.dev.pika.art"


def _env_of(path: Path, rate: int = 16000) -> list[float]:
    return _rms_envelope(_decode_mono(path, rate=rate), rate)


def measure_alignment(reference: str, clip: str) -> dict[str, Any]:
    """Envelope cross-correlation of a generated clip against its reference.

    Returns the offset where the clip's audio best matches the reference
    and the correlation there. This is a LAG record — rhythm alignment,
    never articulation proof (that is the human eye's job, per the gates
    in verify)."""
    ref = _env_of(Path(reference))
    got = _env_of(Path(clip))
    if not ref or not got:
        return {"offset_s": None, "corr": 0.0}
    if len(got) >= len(ref):
        got = got[:len(ref)]  # clip vs its own slice: compare the overlap
    best_off, best_val = 0, -1.0
    mg = math.fsum(got) / len(got)
    dg = math.sqrt(math.fsum((x - mg) ** 2 for x in got)) or 1.0
    for off in range(0, len(ref) - len(got) + 1):
        seg = ref[off:off + len(got)]
        ms = math.fsum(seg) / len(seg)
        num = math.fsum((seg[i] - ms) * (got[i] - mg) for i in range(len(got)))
        ds = math.sqrt(math.fsum((x - ms) ** 2 for x in seg)) or 1.0
        val = num / (ds * dg)
        if val > best_val:
            best_val, best_off = val, off
    return {"offset_s": round(best_off * 0.01, 3), "corr": round(best_val, 4)}


def _pika_call(method: str, path: str, key: str,
               payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    import urllib.request
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        PIKA_HOST + path, data=data, method=method,
        headers={"X-API-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fire_insert(build_dir: str, stem_slice: str, audio_url: str,
                image_urls: list[str], prompt: str, seconds: int = 5,
                expected_start_s: float = 0.0, ceiling_usd: Optional[float] = None,
                take_id: str = "insert-1", fps: int = 24) -> dict[str, Any]:
    """Fire ONE performance insert: a character reference + the vocal-stem
    slice into Pika H3 Flex reference-to-video.

    The paid stage, gated like the fleet gates it: a declared key, a
    priced estimate, and a caller-set ceiling are all required before a
    cent moves. The returned take is measured for lag and written into
    the build's takes.json as an UNADOPTED take — adoption is a human
    eye's decision, never this tool's."""
    import os
    import time
    import urllib.request

    estimate = round(seconds * REF2VA_RATE_PER_S, 4)
    key = os.environ.get("PIKA_API_KEY", "")
    if not key:
        return {"verdict": "fail", "estimate_usd": estimate,
                "failures": ["PIKA_API_KEY is not set — declare it through "
                             "Hermes (env / auth) before the paid stage"]}
    if ceiling_usd is None:
        return {"verdict": "fail", "estimate_usd": estimate,
                "failures": [f"no spend ceiling given — this fire costs about "
                             f"${estimate:.2f}; pass ceiling_usd to approve it"]}
    if estimate > ceiling_usd:
        return {"verdict": "fail", "estimate_usd": estimate,
                "failures": [f"estimate ${estimate:.2f} exceeds the ceiling "
                             f"${ceiling_usd:.2f} — refused before firing"]}
    if not Path(stem_slice).exists():
        return {"verdict": "fail", "estimate_usd": estimate,
                "failures": [f"stem slice not found: {stem_slice}"]}

    refs = [{"type": "image", "url": u} for u in image_urls]
    refs.append({"type": "audio", "url": audio_url})
    body = _pika_call("POST", "/v1/media/pika/pika-h3-flex/reference-to-video",
                      key, {"prompt": prompt, "references": refs,
                            "duration": seconds, "resolution": "480p"})
    job_id = str(body.get("request_id") or body.get("id") or "")
    if not job_id:
        return {"verdict": "fail", "estimate_usd": estimate,
                "failures": [f"submit returned no job id: {str(body)[:200]}"]}
    status = ""
    for _ in range(60):
        time.sleep(10)
        job = _pika_call("GET", f"/v1/media/jobs/{job_id}", key)
        status = str(job.get("status") or job.get("state") or "")
        if status.lower() in ("completed", "complete", "succeeded", "success"):
            break
        if status.lower() in ("failed", "error", "cancelled"):
            return {"verdict": "fail", "estimate_usd": estimate,
                    "failures": [f"generation job {job_id} ended: {status}"]}
    else:
        return {"verdict": "fail", "estimate_usd": estimate,
                "failures": [f"generation job {job_id} did not finish in time"]}
    content = _pika_call("GET", f"/v1/media/jobs/{job_id}/content", key)
    url = content.get("url") or content.get("download_url") or ""
    root = Path(build_dir)
    root.mkdir(parents=True, exist_ok=True)
    clip_path = root / f"{take_id}.mp4"
    if url:
        raw = b""
        for _attempt in range(3):  # chunked, LENGTH-CHECKED, retried: a bare
            try:                   # read() died mid-stream on a real CDN
                req = urllib.request.Request(str(url))  # download, and a
                with urllib.request.urlopen(req, timeout=300) as resp:
                    expected = int(resp.headers.get("Content-Length") or 0)
                    chunks = []
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        chunks.append(chunk)
                candidate = b"".join(chunks)
                if expected and len(candidate) != expected:
                    raise OSError(f"short download: {len(candidate)} of "
                                  f"{expected} bytes")
                raw = candidate
                break
            except Exception:
                raw = b""
                time.sleep(5)
        if raw:
            clip_path.write_bytes(raw)
    alignment = measure_alignment(stem_slice, str(clip_path)) \
        if clip_path.exists() else {"offset_s": None, "corr": 0.0}
    lag_frames = None
    if alignment["offset_s"] is not None:
        lag_frames = int(round((alignment["offset_s"] - expected_start_s) * fps))
    ledger_path = root / "takes.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) \
        if ledger_path.exists() else []
    ledger.append({
        "id": take_id, "role": "insert", "adopted": False,
        "feed": "vocal_stem", "job": job_id, "lag_frames": lag_frames,
        "sync_evidence": "envelope", "corr": alignment["corr"],
        "hero": False, "hero_eye_pass": False,
        "note": "awaiting the human full-screen eye; unadopted until passed",
    })
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    return {"verdict": "pass", "estimate_usd": estimate, "job": job_id,
            "clip": str(clip_path), "lag_frames": lag_frames,
            "corr": alignment["corr"],
            "note": "take recorded UNADOPTED — slopcore_verify keeps the "
                    "batch locked until a hero passes the human eye"}

# ---------------------------------------------------------------- tools

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "build_dir": {"type": "string",
                      "description": "Build folder holding takes.json, manifest.json and the final film"},
        "final": {"type": "string", "description": "Final film path (default: build_dir/final.mp4)"},
        "master": {"type": "string", "description": "Master audio path to correlate the final against"},
        "fps": {"type": "integer", "description": "Timeline frame rate (default 24)"},
    },
    "required": ["build_dir"],
}


def _tool_verify(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        result = verify_build(
            str(args["build_dir"]),
            final=args.get("final"), master=args.get("master"),
            fps=int(args.get("fps", 24)))
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"verdict": "fail",
                           "failures": [f"slopcore_verify error: {exc}"],
                           "warnings": [], "measurements": {}})


WORDMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "stem_path": {"type": "string",
                      "description": "Isolated vocal stem (WAV/MP3) to measure onsets from"},
        "lyrics": {"type": "string", "description": "The lyric text the stem sings"},
        "transcript": {"type": "string",
                       "description": "Optional transcription of the stem; when given, the stem must actually contain the lyric words"},
        "out_path": {"type": "string",
                     "description": "Where to write the wordmap JSON (default: wordmap.json beside the stem)"},
    },
    "required": ["stem_path", "lyrics"],
}


def _tool_wordmap(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        result = build_wordmap(str(args["stem_path"]), str(args["lyrics"]),
                               transcript=args.get("transcript"))
        out = Path(args.get("out_path")
                   or (Path(str(args["stem_path"])).parent / "wordmap.json"))
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        summary = {k: v for k, v in result.items() if k != "wordmap"}
        summary["out_path"] = str(out)
        return json.dumps(summary)
    except Exception as exc:
        return json.dumps({"verdict": "fail",
                           "failures": [f"slopcore_wordmap error: {exc}"]})


INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "build_dir": {"type": "string",
                      "description": "Build folder to open (intake.json is written here)"},
        "sources": {"type": "array", "items": {"type": "string"},
                    "description": "Source files: the song, lyrics, character sheets, notes"},
    },
    "required": ["build_dir", "sources"],
}


def _tool_intake(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        return json.dumps(intake_bundle(str(args["build_dir"]),
                                        list(args["sources"])))
    except Exception as exc:
        return json.dumps({"verdict": "fail",
                           "failures": [f"slopcore_intake error: {exc}"]})


STEM_SCHEMA = {
    "type": "object",
    "properties": {
        "audio_path": {"type": "string", "description": "The finished song (MP3/WAV)"},
        "out_dir": {"type": "string",
                    "description": "Folder for vocal-stem.wav / vocal-stem.mp3"},
        "api_url": {"type": "string",
                    "description": "Hosted separator endpoint (default: the fleet-proven aichord Demucs Space)"},
    },
    "required": ["audio_path", "out_dir"],
}


def _tool_stem(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        return json.dumps(separate_stem(
            str(args["audio_path"]), str(args["out_dir"]),
            api_url=str(args.get("api_url") or STEM_API_DEFAULT)))
    except Exception as exc:
        return json.dumps({"verdict": "fail",
                           "failures": [f"slopcore_stem error: {exc}"]})


INSERT_SCHEMA = {
    "type": "object",
    "properties": {
        "build_dir": {"type": "string", "description": "Build folder (takes.json ledger lives here)"},
        "stem_slice": {"type": "string",
                       "description": "Local vocal-stem slice the insert must sync to (exact seconds)"},
        "audio_url": {"type": "string",
                      "description": "Hosted URL of that same stem slice, fed to the generator"},
        "image_urls": {"type": "array", "items": {"type": "string"},
                       "description": "Hosted character-sheet / wardrobe reference images"},
        "prompt": {"type": "string", "description": "Shot prompt for the insert"},
        "seconds": {"type": "integer", "description": "Clip length (default 5)"},
        "expected_start_s": {"type": "number",
                             "description": "Where the slice starts in the stem (for the lag record)"},
        "ceiling_usd": {"type": "number",
                        "description": "REQUIRED spend ceiling; the fire is refused above it"},
        "take_id": {"type": "string", "description": "Ledger id for the new take"},
    },
    "required": ["build_dir", "stem_slice", "audio_url", "image_urls", "prompt"],
}


def _tool_insert(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        return json.dumps(fire_insert(
            str(args["build_dir"]), str(args["stem_slice"]),
            str(args["audio_url"]), list(args["image_urls"]),
            str(args["prompt"]), seconds=int(args.get("seconds", 5)),
            expected_start_s=float(args.get("expected_start_s", 0.0)),
            ceiling_usd=args.get("ceiling_usd"),
            take_id=str(args.get("take_id", "insert-1"))))
    except Exception as exc:
        return json.dumps({"verdict": "fail",
                           "failures": [f"slopcore_insert error: {exc}"]})


def register(ctx: Any) -> None:
    """Called by the plugin discovery system."""
    ctx.register_tool(
        name="slopcore_insert", toolset="slopcore", schema=INSERT_SCHEMA,
        handler=_tool_insert, emoji="🎤", requires_env=["PIKA_API_KEY"],
        description=("Fire ONE stem-fed performance insert (Pika H3 Flex "
                     "reference-to-video). Spend-gated: no key or no ceiling, "
                     "no fire. The take is lag-measured and recorded "
                     "UNADOPTED — only a human eye adopts."),
    )
    ctx.register_tool(
        name="slopcore_stem", toolset="slopcore", schema=STEM_SCHEMA,
        handler=_tool_stem, emoji="🎙️", requires_env=[],
        description=("Isolate the vocal stem from a finished song via a hosted "
                     "Demucs separator (no local model downloads). The result "
                     "is peak-checked: a silent stem fails, never ships."),
    )
    ctx.register_tool(
        name="slopcore_intake", toolset="slopcore", schema=INTAKE_SCHEMA,
        handler=_tool_intake, emoji="🧺",
        description=("Open a build from a multi-source bundle: fingerprints "
                     "every source (SHA-256), probes audio durations, writes "
                     "intake.json. Fails without an audio source — song first."),
    )
    ctx.register_tool(
        name="slopcore_verify", toolset="slopcore", schema=VERIFY_SCHEMA,
        handler=_tool_verify, emoji="🎬",
        description=("Verify a finished slopcore build: fidelity gates over the "
                     "take ledger (stem-fed inserts, per-take lag records, a "
                     "human-passed hero) plus measured frame grid and master "
                     "audio correlation. Fails closed."),
    )
    ctx.register_tool(
        name="slopcore_wordmap", toolset="slopcore", schema=WORDMAP_SCHEMA,
        handler=_tool_wordmap, emoji="🗺️",
        description=("Build a wordmap from a vocal stem: lyric words aligned to "
                     "MEASURED onsets in the stem, gate-checked for coverage, "
                     "with an optional transcript content proof. Unmatched "
                     "words are flagged as estimates, never silently placed."),
    )
