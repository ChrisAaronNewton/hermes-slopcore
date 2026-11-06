# Slopcore — the verified music-video pipeline, as Hermes tools

A song and a character sheet go in. A *verified* slopcore music video comes
out. The pipeline's production law is encoded as gates that fail closed,
not as advice a model can forget:

- **Song first.** A build cannot open without an audio source.
- **The vocal stem is the performance feed.** Inserts are generated from
  the isolated vocal stem, never the full mix.
- **A wordmap is measured, not assumed.** Lyric words are aligned to
  onsets measured in the stem and gate-checked; an optional transcript
  must actually contain the words.
- **Envelope correlation is a lag record, not lip-sync.** It proves the
  mouth moves *with* the track. Articulation is a human judgment.
- **The Director's Law.** A batch ships only behind one hero insert a
  human watched full-screen and passed. New takes are recorded
  *unadopted*; only the human eye adopts.
- **The film must prove itself.** Exact frame count, manifest sums, and
  waveform correlation against the master, or it does not ship.

## Tools

| Tool | What it does |
|---|---|
| `slopcore_intake` | Opens a build folder from a multi-source bundle: SHA-256 fingerprints every source, probes audio durations, writes `intake.json`. Fails without a song. |
| `slopcore_stem` | Isolates the vocal stem via a hosted Demucs separator (no local model downloads). A silent returned stem fails, never ships. |
| `slopcore_wordmap` | Aligns lyric words to measured onsets in the stem; coverage gate + optional transcript content proof; unmatched words are flagged estimates. |
| `slopcore_insert` | Fires ONE stem-fed performance insert (Pika H3 Flex reference-to-video). Spend-gated: no `PIKA_API_KEY` or no caller ceiling, no fire. Measures the take's lag and records it unadopted. |
| `slopcore_verify` | The final gate: take-ledger fidelity rules (full-mix feeds fail, missing lag records fail, no human-passed hero = batch locked) plus measured frame grid, manifest sum, and master audio correlation. |

## Requirements

- `ffmpeg` / `ffprobe` on PATH (measurements and audio decoding).
- `slopcore_stem` uses a hosted separator over HTTPS (default: the
  aichord Demucs Space, $0). `slopcore_insert` is the only paid stage and
  the only other network caller; it needs `PIKA_API_KEY` (declared via
  Hermes' env/auth routes — the plugin never stores it) and an explicit
  per-call spend ceiling from the caller.
- Everything else is local files and the Python standard library.

## Proof

The gates were developed against a real shipped film (STRIP-MINE,
198.79 s). On its artifacts, `slopcore_verify` passes the film
(4,771 frames exact, manifest sum 4,771, audio correlation 0.9992
measured by the tool itself, five stem-fed inserts at lag 0), and
`slopcore_insert`'s lag measurement reproduces the build log's hero
record (envelope corr 0.7515 measured vs 0.754 logged).
21 tests cover the gates, the onset alignment, the request shapes, and
these real-artifact integrations.
