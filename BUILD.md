# Slopcore workflow plugin — build plan (Hermes hackathon entry #2)

Brief: ~/workspace/hermes-hackathon/SLOPCORE-SECOND-ENTRY-BRIEF.md (design,
risks, demo). Chris enters this one himself too (decided 2026-11-06), in his
own repo, same as Commonplace. Sequencing gate from the brief is satisfied:
Commonplace's repo is live and verified (2026-11-06), so this build starts
Fri Nov 6 instead of the weekend.

## Tools (register ONLY what runs end-to-end in a fresh home)

1. `slopcore_verify` — pure local, build FIRST (provable today):
   frame-count check, audio correlation vs master, per-take lag records;
   FAILS a build fed the full mix or resting on envelope-only sync evidence
   (the 2026-11-02 Friction Skimmer gates, as code). Proof target: the real
   STRIP-MINE receipts (198.79s · 4,771 frames · corr 0.9985 · 5 inserts lag 0).
2. `slopcore_wordmap` — pure local: alignment of lyric lines to a vocal
   stem's measured onsets; gate-checks word timings against onsets
   (STRIP-MINE standard: 363/363 words within ±0.20s).
3. `slopcore_intake` — assemble a multi-source bundle (character sheets,
   prompt, song file/link) into a build folder with a manifest.
4. `slopcore_stem` — hosted Demucs route (aichord FastAPI, proven $0 on
   STRIP-MINE) + whisper content proof of the returned vocal stem.
5. `slopcore_insert` — ONE hero insert via Pika Ref2VA fed the vocal-stem
   slice; returns the take + its lag record. Batch generation stays locked
   until a hero passes (Director's Law, encoded). Pika key via Hermes'
   credential routes only; spend goes through the pre-fire gate.

## Manifest / registration reference

Mirror a bundled media plugin from the v0.23.0 checkout
(~/workspace/hermes-hackathon/v023/hermes-agent-0.23.0/plugins/video_gen/)
for plugin.yaml shape and register(ctx) tool registration — do not invent
manifest fields. v0.23.0 affordances to use where real: plugin OAuth for
the Pika key (token attached only to declared hosts) and paid-tool cost
declaration for `slopcore_insert` (per-call price + per-chat limit).

## Validation bar (same as Commonplace)

- `hermes plugins validate` + Plugin Doctor green on the v0.23.0 checkout
  in a virgin HERMES_HOME.
- Tests green via scripts/run_tests.sh; every tool exercised against real
  fleet artifacts (STRIP-MINE build folder) before it is registered.
- Disclosures in the README: network calls (Pika, hosted Demucs), third
  parties, credential route, per-call costs. Declared capabilities must
  match what actually runs — anything not proven by Mon Nov 10 does not
  ship in the entry.

## Demo (Mon Nov 10)

Opens on STRIP-MINE's first 6 seconds (the film itself, already made);
then the five stages + their receipts on screen. No new film build.
Post copy + catalog YAML + Typeform notes join the submission pack.
