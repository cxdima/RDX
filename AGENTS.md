# RDX — agent guide

Shared instructions for any coding agent working in this repo (Claude Code reads
this via the `CLAUDE.md` symlink; Codex reads it directly).

## What RDX is

A local, offline AI co-producer for music. The user directs music through
conversation, humming and rhythmic demonstration; RDX turns that into an
editable arrangement they can audition immediately and export to Ableton.

The user has strong musical instincts but is not an Ableton engineer. They
describe **feelings and directions** ("this needs more tension", "warm it up",
"a flanger so it gives goosebumps"). RDX's job is to translate that into
musically-correct, inspectable edits — never to guess and hope.

Full scope is the whole production process: composition, sound design,
arrangement, mixing, revision. Do not silently narrow it to one trick.

## Architecture

| Layer | Responsibility | Files |
| --- | --- | --- |
| Studio UI | Arrangement, piano roll, mixer, sound controls, chat, comparison | `src/App.tsx`, `src/PianoRoll.tsx`, `src/studio.css` |
| Audio engine | Tone.js synths, drums, effects, automation, playback, WAV render | `src/audio.ts` |
| Musical state | Typed projects, tracks, sections, clips, notes, sound, automation | `rdx/domain.py` |
| Edit execution | Validated atomic edits, musical generators, protection | `rdx/engine.py` |
| HTTP service | Proposals, assets, import/export, bridge auth | `rdx/server.py` |
| Persistence | SQLite projects, snapshots, revisions, feedback, chat | `rdx/store.py` |
| Language model | Persistent MLX subprocess: local base + trained LoRA adapter | `rdx/model.py`, `rdx/model_worker.py` |
| Audio analysis | ffmpeg decode, librosa pitch/onset, MIDI import/export | `rdx/audio.py` |
| Live bridge | Node for Max transport + Live API device (**experimental**) | `bridge/`, `scripts/build_bridge.py` |
| Training | Dataset build, LoRA job, evaluation, activation | `scripts/build_training_data.py`, `rdx/training.py`, `rdx/evaluate.py`, `rdx/promote.py` |

## Commands

Always run from the repo root. Always use `.venv/bin/python`, never bare `python`.

```sh
npm start                                   # launch backend + open studio
npm run build                               # tsc -b && vite build
npm run check                               # tsc --noEmit
npm test                                    # pytest
npm run test:browser                        # playwright
npm run format                              # prettier

.venv/bin/python scripts/build_training_data.py
.venv/bin/python -m rdx.training            # LoRA train
.venv/bin/python -m rdx.evaluate            # base benchmark
.venv/bin/python -m rdx.evaluate --adapter  # adapter benchmark
.venv/bin/python -m rdx.promote             # activate adapter (gated on benchmark)
.venv/bin/python scripts/build_bridge.py    # rebuild the Max device
```

`RDX_DATA_DIR` isolates runtime data — always set it when testing so you never
touch the user's real projects. `RDX_PORT` picks the first port to try.

## Hard rules

1. **This is a 16 GB M2 Pro. Never run training and inference at the same time.**
2. **Never overwrite the active adapter.** `data/models/rdx-v1/approved.json`
   guards it, and `rdx/training.py` refuses to run while it exists. Configure a
   new adapter version instead of deleting the guard.
3. **Model output is data, never code.** It is parsed as JSON, validated against
   `Action`, and executed by the engine. Never `eval`, shell out, or let it
   choose a file path.
4. **Never claim the Ableton bridge is verified.** A real Live API handshake and
   transfer has not been confirmed. It stays labelled experimental until someone
   watches it work in Live.
5. **Never commit `data/` or `artifacts/`** — model weights, recordings and
   databases stay local.
6. **No cloud inference, no telemetry.** Everything the user says, hums or
   records stays on this machine. Adding a network call to an inference service
   breaks the core promise of the product.
7. **Do not fake a capability.** If RDX cannot do what was asked, it must say so
   and offer the nearest real thing. An edit that looks plausible but does
   something else is the worst possible outcome — worse than refusing.

## The edit engine contract

`apply_actions(original, actions) -> Project` is the only path that changes
music. It must remain:

- **Pure.** Deep-copies its input; the original is never mutated, even on error.
- **Atomic.** Either every action applies or the whole plan raises `EditError`.
  Partial mutation of saved state is a bug.
- **Total.** The result always goes through `Project.model_validate` before
  return, so an invalid arrangement can never be persisted.
- **Protective.** Tracks locked *at entry* stay untouched. A plan cannot unlock
  a track and then edit it in the same call.

Every user-visible error message must be plain language a musician understands.
Raw pydantic validation strings leaking to the UI is a bug.

## The proposal flow

Chat never edits directly. `POST /chat` returns `{plan, preview}` computed
against a copy; the project only changes when the user accepts via
`POST /proposals/{id}`. Feedback is recorded with an accepted/rejected label and
**rejected plans are never reused as positive training examples.**

## Conventions

- Python: 3.12, `from __future__ import annotations`, pydantic v2 models with
  `extra="forbid"`. Validate at the boundary; trust nothing from the model.
- TypeScript: strict, React 19 function components, no `any`.
- Prefer many small focused files. 200–400 lines typical, 800 max.
- Immutability: build new objects rather than mutating shared ones.
- Names say what something *is*, in musician's language where user-facing.

## Testing

- `tests/` covers engine validation, protection, history, transcription, archive
  round trips, proposals and bridge auth.
- `tests/browser/` is Playwright against the real built app.
- New musical capability needs an engine test proving the *musical* result, not
  just that the call returned. A drum pattern test should assert the notes land
  where a producer expects them.

## Honesty rules for docs

`README.md`, `RDX_PLAN.md` and `RDX_HANDOFF.md` deliberately separate what is
**implemented and verified** from what is **proposed**. Preserve that. Do not
upgrade "built" to "working" without evidence, and record known failures rather
than quietly dropping them.
