# RDX

All project instructions live in one place so Claude Code and Codex behave
identically. Read it here:

@AGENTS.md

## Claude Code specifics

- Two stale dev servers may be listening from earlier sessions. Check
  `lsof -nP -iTCP:8765-8770 -sTCP:LISTEN` before assuming a port is free;
  `npm start` picks the next free port on its own.
- `npm start` reuses a running instance only when its build hash matches the
  current `rdx/*.py`. A mismatched server is stale — restart rather than test
  against it.
- Model inference takes 3–8s per request on this machine. Give MLX calls a
  generous timeout; do not treat 30s as a hang.
