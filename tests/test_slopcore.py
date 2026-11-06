"""Gate + measurement tests for the Slopcore plugin's verify tool.

Pure stdlib plugin: these run in any Python with pytest. The integration
test exercises the REAL STRIP-MINE artifacts (shipped film, master WAV,
assembly manifest, and a take ledger transcribed from BUILD-LOG.md) and is
skipped when those files are absent.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slopcore import gate_takes, register, verify_build  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "stripmine_takes.json"
STRIP_MINE = Path("~/workspace/strip-mine").expanduser()
FINAL = Path("~/workspace/your_files/strip-mine/strip-mine-v1-2026-11-05.mp4").expanduser()
MASTER = STRIP_MINE / "capture" / "strip-mine-master.wav"


def take(**kw):
    base = {"id": "t", "role": "insert", "adopted": True,
            "feed": "vocal_stem", "lag_frames": 0, "sync_evidence": "envelope"}
    base.update(kw)
    return base


def test_clean_batch_passes_with_hero():
    takes = [take(id="hero", hero=True, hero_eye_pass=True), take(id="i2")]
    failures, warnings = gate_takes(takes)
    assert failures == []
    assert any("envelope-only" in w for w in warnings)  # surfaced, not hidden


def test_full_mix_feed_fails():
    failures, _ = gate_takes([take(hero=True, hero_eye_pass=True, feed="full_mix")])
    assert any("FULL MIX" in f for f in failures)


def test_missing_lag_record_fails():
    failures, _ = gate_takes([take(hero=True, hero_eye_pass=True, lag_frames=None)])
    assert any("no lag record" in f for f in failures)


def test_lag_beyond_a_frame_fails():
    failures, _ = gate_takes([take(hero=True, hero_eye_pass=True, lag_frames=4)])
    assert any("lag 4 frames" in f for f in failures)


def test_batch_without_passed_hero_is_locked():
    failures, _ = gate_takes([take(id="hero", hero=True, hero_eye_pass=False),
                              take(id="i2")])
    assert any("Director's Law" in f for f in failures)


def test_rejected_takes_do_not_fail_the_build():
    takes = [take(id="hero", hero=True, hero_eye_pass=True),
             take(id="bad", adopted=False, feed="full_mix", lag_frames=None)]
    failures, _ = gate_takes(takes)
    assert failures == []


def test_register_registers_verify_tool():
    class FakeCtx:
        def __init__(self):
            self.tools = []

        def register_tool(self, **kw):
            self.tools.append(kw)

    ctx = FakeCtx()
    register(ctx)
    assert [t["name"] for t in ctx.tools] == [
        "slopcore_insert", "slopcore_stem", "slopcore_intake",
        "slopcore_verify", "slopcore_wordmap"]
    assert all(t["toolset"] == "slopcore" for t in ctx.tools)


def test_measure_alignment_finds_the_offset(tmp_path: Path):
    import subprocess as sp
    from slopcore import measure_alignment
    ref = tmp_path / "ref.wav"
    _burst_wav(ref, bursts=((1.0, 1.4), (3.0, 3.9), (5.5, 5.9)), seconds=8.0)
    clip = tmp_path / "clip.wav"
    sp.run(["ffmpeg", "-y", "-v", "error", "-ss", "3.0", "-t", "2.0",
            "-i", str(ref), str(clip)], check=True)
    result = measure_alignment(str(ref), str(clip))
    assert result["offset_s"] is not None and abs(result["offset_s"] - 3.0) <= 0.06
    assert result["corr"] >= 0.9


def test_insert_refuses_without_key_or_ceiling(tmp_path: Path, monkeypatch):
    from slopcore import fire_insert
    stem = tmp_path / "slice.wav"
    _burst_wav(stem, seconds=2.0)
    monkeypatch.delenv("PIKA_API_KEY", raising=False)
    r = fire_insert(str(tmp_path), str(stem), "https://x/a.mp3",
                    ["https://x/face.png"], "sing", ceiling_usd=1.0)
    assert r["verdict"] == "fail" and "PIKA_API_KEY" in r["failures"][0]
    monkeypatch.setenv("PIKA_API_KEY", "test-key")
    r = fire_insert(str(tmp_path), str(stem), "https://x/a.mp3",
                    ["https://x/face.png"], "sing")
    assert r["verdict"] == "fail" and "ceiling" in r["failures"][0]
    r = fire_insert(str(tmp_path), str(stem), "https://x/a.mp3",
                    ["https://x/face.png"], "sing", ceiling_usd=0.05)
    assert r["verdict"] == "fail" and "exceeds" in r["failures"][0]


def test_insert_submit_shape_and_ledger(tmp_path: Path, monkeypatch):
    import slopcore
    stem = tmp_path / "slice.wav"
    _burst_wav(stem, seconds=2.0)
    monkeypatch.setenv("PIKA_API_KEY", "test-key")
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def fake_call(method, path, key, payload=None):
        calls.append((method, path, payload))
        if method == "POST":
            return {"request_id": "job123"}
        if path.endswith("/content"):
            return {}
        return {"status": "completed"}

    monkeypatch.setattr(slopcore, "_pika_call", fake_call)
    r = slopcore.fire_insert(str(tmp_path), str(stem), "https://x/a.mp3",
                             ["https://x/face.png"], "sing the line",
                             ceiling_usd=1.0, take_id="insert-9")
    assert r["verdict"] == "pass", r
    post = next(c for c in calls if c[0] == "POST")
    assert post[1] == "/v1/media/pika/pika-h3-flex/reference-to-video"
    assert post[2]["references"][-1] == {"type": "audio", "url": "https://x/a.mp3"}
    assert post[2]["duration"] == 5
    ledger = json.loads((tmp_path / "takes.json").read_text())
    assert ledger[0]["id"] == "insert-9" and ledger[0]["adopted"] is False
    assert ledger[0]["feed"] == "vocal_stem"


@pytest.mark.skipif(not (STRIP_MINE / "build" / "insert-1.mp4").exists(),
                    reason="STRIP-MINE hero insert not present")
def test_measure_alignment_on_real_hero_insert():
    from slopcore import measure_alignment
    # The hero take against the exact stem slice it was fed: the fleet's
    # build log records envelope corr 0.754 at lag 0 for this pair.
    result = measure_alignment(str(STRIP_MINE / "build" / "stem-slices" / "stem-1.wav"),
                               str(STRIP_MINE / "build" / "insert-1.mp4"))
    assert result["offset_s"] is not None and result["offset_s"] <= 0.05, result
    assert result["corr"] >= 0.7, result


def test_find_vocal_payload_shapes():
    from slopcore import _find_vocal_payload
    blob = "A" * 5000
    assert _find_vocal_payload({"vocals": blob}) == blob
    assert _find_vocal_payload({"stems": {"bass": "B" * 5000,
                                          "vocals": blob}}) == blob
    assert _find_vocal_payload({"result": [{"name": "x"}, {"vocals": blob}]}) == blob
    assert _find_vocal_payload({"drums": blob}) is None
    assert _find_vocal_payload({"vocals": "too-short"}) is None


def test_stem_missing_audio_fails(tmp_path: Path):
    from slopcore import separate_stem
    result = separate_stem(str(tmp_path / "nope.mp3"), str(tmp_path / "out"))
    assert result["verdict"] == "fail"


def test_intake_opens_build_with_song(tmp_path: Path):
    from slopcore import intake_bundle
    song = tmp_path / "song.wav"
    _burst_wav(song, seconds=2.0)
    sheet = tmp_path / "sheet.md"
    sheet.write_text("# character sheet", encoding="utf-8")
    result = intake_bundle(str(tmp_path / "build"), [str(song), str(sheet)])
    assert result["verdict"] == "pass", result["failures"]
    manifest = json.loads((tmp_path / "build" / "intake.json").read_text())
    assert [s["kind"] for s in manifest["sources"]] == ["audio", "text"]
    assert manifest["sources"][0]["duration_s"] == 2.0
    assert len(manifest["sources"][0]["sha256"]) == 64


def test_intake_without_song_fails(tmp_path: Path):
    from slopcore import intake_bundle
    sheet = tmp_path / "sheet.md"
    sheet.write_text("# notes only", encoding="utf-8")
    result = intake_bundle(str(tmp_path / "build"), [str(sheet)])
    assert result["verdict"] == "fail"
    assert any("song first" in f for f in result["failures"])


def test_intake_missing_source_fails_loudly(tmp_path: Path):
    from slopcore import intake_bundle
    result = intake_bundle(str(tmp_path / "build"), [str(tmp_path / "nope.wav")])
    assert result["verdict"] == "fail"
    assert any("not found" in f for f in result["failures"])


def _burst_wav(path: Path, bursts=((1.0, 1.4), (2.2, 2.6), (3.6, 4.0)),
               seconds: float = 5.0, rate: int = 16000) -> None:
    import math as _math
    import wave
    frames = bytearray()
    for i in range(int(seconds * rate)):
        t = i / rate
        v = 0.5 * _math.sin(2 * _math.pi * 440 * t) if any(a <= t < b for a, b in bursts) else 0.0
        frames += int(v * 32767).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def test_wordmap_aligns_words_to_measured_onsets(tmp_path: Path):
    from slopcore import build_wordmap
    stem = tmp_path / "stem.wav"
    _burst_wav(stem)
    result = build_wordmap(str(stem), "alpha bravo charlie")
    assert result["verdict"] == "pass", result["failures"]
    times = [e["t"] for e in result["wordmap"]]
    for got, want in zip(times, (1.0, 2.2, 3.6)):
        assert abs(got - want) <= 0.25, times


def test_wordmap_silent_stem_fails(tmp_path: Path):
    from slopcore import build_wordmap
    stem = tmp_path / "stem.wav"
    _burst_wav(stem, bursts=())
    result = build_wordmap(str(stem), "alpha bravo")
    assert result["verdict"] == "fail"
    assert any("silent" in f for f in result["failures"])


def test_wordmap_transcript_mismatch_fails(tmp_path: Path):
    from slopcore import build_wordmap
    stem = tmp_path / "stem.wav"
    _burst_wav(stem)
    result = build_wordmap(str(stem), "alpha bravo charlie",
                           transcript="completely different words here")
    assert result["verdict"] == "fail"
    assert any("content proof" in f for f in result["failures"])


@pytest.mark.skipif(not (STRIP_MINE / "stems" / "vocal-stem-full.wav").exists(),
                    reason="STRIP-MINE vocal stem not present")
def test_wordmap_stripmine_hook_lands_in_first_seconds():
    from slopcore import build_wordmap
    result = build_wordmap(
        str(STRIP_MINE / "stems" / "vocal-stem-full.wav"),
        "they're not training — they're strip-mining it!")
    times = [e["t"] for e in result["wordmap"]]
    assert times == sorted(times)  # monotone placement
    assert times[0] is not None and times[0] <= 6.5  # the hook opens the song


@pytest.mark.skipif(not (FINAL.exists() and MASTER.exists()
                         and (STRIP_MINE / "build" / "manifest.json").exists()),
                    reason="STRIP-MINE artifacts not present")
def test_stripmine_shipped_film_verifies(tmp_path: Path):
    shutil.copy(FIXTURE, tmp_path / "takes.json")
    shutil.copy(STRIP_MINE / "build" / "manifest.json", tmp_path / "manifest.json")
    result = verify_build(str(tmp_path), final=str(FINAL), master=str(MASTER))
    assert result["measurements"]["final_frames"] == 4771
    assert result["measurements"]["audio_correlation"] >= 0.98
    assert result["verdict"] == "pass", json.dumps(result, indent=2)
