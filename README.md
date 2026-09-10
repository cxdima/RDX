# RDX Studio

A local, editable music-production workspace with an offline AI co-producer. This is a working first development build, not a finished autonomous producer or a replacement for Ableton.

## Open RDX

Double-click **RDX.command**. It starts the local service and opens the studio. An existing matching instance is reused; an occupied port is never taken over. Keep its terminal window open during the session.

The initial preview was started at http://127.0.0.1:8765. The launcher prints the actual address if it uses another port.

The initial dependencies and model are installed on this Mac. Normal inference, playback, recording analysis, editing, and export run locally. Nothing in the app sends recordings or conversation to an online inference service. Software/model installation requires downloads; recording requires the browser's microphone permission.

## Implemented

- Composition and variation across drums, bass, chords, lead and pad; editable MIDI notes and timing.
- Section arrangement, duplication, resizing and removal; track duplication, naming and protection.
- Synth presets, filter, envelope, EQ, drive, delay, reverb, basic automation and mixing.
- Playback, section looping, actual output meters and basic master compression/limiting.
- Audio recording/import, local monophonic humming transcription and rhythm-onset transcription.
- AI edit proposals, original/alternative auditioning, explicit keep/discard, feedback and undo/redo.
- SQLite persistence, project archive round trips, MIDI export and stereo WAV rendering.
- A packaged Max for Live bridge targeting Live 12.2: append rendered audio stems and separate muted, editable MIDI source tracks.

Audio stems contain the track's processing and automation. They are not native synth/effect racks, and the separate MIDI source tracks need an instrument before they can replace the rendered audio. Existing Live tracks are not deleted or overwritten. A nonempty Set must match RDX's tempo; transfers are appended after existing Arrangement clips.

## Model

The local base is `mlx-community/Qwen3-4B-Instruct-2507-4bit`, pinned to revision `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b`. An actual MLX LoRA adapter was trained on this M2 Pro: 120 steps, rank 8, four layers, batch size 1, 4.242 GB reported peak training memory, 476 seconds.

The synthetic dataset has 1,104 training, 138 validation and 138 test examples. The run used 120 batches, not a complete pass through all training examples. Request templates are shared across dataset splits; these are schema/instruction examples, not expert musical-quality labels. Evaluation project IDs vary between runs, so the small benchmark can be prompt-sensitive.

On the separate 12-request authored benchmark, the activated adapter passed **9/12**, versus **4/12** for the base. Known failures include a tempo action, missing drum targets and a section-copy instruction. This small benchmark does not establish broad generalization, musical taste or audio understanding. The model proposes edits; it does not directly control Live, execute code or hear the mix. Every accepted change still goes through validation and revision checks.

Logs, settings, weights and complete evaluation outputs are in `data/training/` and `data/models/rdx-v1/`. Feedback is stored locally with accepted/rejected labels. It does not automatically retrain the model.

## Verification And Limits

The desktop/mobile browser workflow passed playback, moving audio meters, editing, undo, synth selection, automation, WAV/MIDI downloads and canvas-content checks. Generated WAV audio was measured as non-silent and without clipped samples. Backend tests cover validation, protected edits, history, transcription, archive import/export, proposals and bridge authentication.

The Max device was built and opened through Live, but **a real Live API handshake and transfer have not been confirmed**. Treat that integration as experimental. No existing song was transferred or overwritten during verification. The session's final restrictions prevented further local-network/GPU checks and a refresh of the earlier preview server. The launcher starts the latest backend on a free port.

Other current limits: 4/4 meter; up to 24 tracks, 16 sections and 256 bars; one clip per track/section; humming/rhythm analysis limited to 30 seconds; audio imports/recordings limited to five minutes. No spoken-instruction transcription, arbitrary plugin hosting, polyphonic audio-to-MIDI, native Ableton automation writing, bidirectional Set synchronization or perceptual mastering judgment yet. WAV rendering is in-memory and large arrangements need more memory. The app has no mandatory cloud service or telemetry.

## Developer Operations

These commands are for maintenance by the coding assistant, not prerequisites for the user's musical feedback:

```sh
npm run build
npm start
npm test
npm run test:browser
.venv/bin/python scripts/build_bridge.py
.venv/bin/python scripts/build_training_data.py
.venv/bin/python -m rdx.training
.venv/bin/python -m rdx.evaluate
.venv/bin/python -m rdx.evaluate --adapter
.venv/bin/python -m rdx.promote
```

Python 3.12, Apple silicon, Node 24 and ffmpeg are the tested environment. `requirements-macos.lock` is an installed-package snapshot for this machine, not a cross-platform resolver lock. `RDX_DATA_DIR` isolates runtime projects/recordings for tests. Model weights remain in the main project's `data/models`. `RDX_PORT` chooses the first port to try. Do not run training and inference together on this 16 GB machine. The default trainer refuses to overwrite an activated adapter; the assistant must configure a new version for subsequent training.

See [RDX_PLAN.md](RDX_PLAN.md) for architecture and continuation work, and [RDX_HANDOFF.md](RDX_HANDOFF.md) for the user's direction. Generated models, audio, test artifacts and local databases are intentionally excluded from Git.
