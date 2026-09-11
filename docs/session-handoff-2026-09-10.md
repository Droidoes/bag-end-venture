# Session handoff — 2026-09-10 (Roth, COS)

**Session:** `session-65f91fa9…` ("Agent Team on 3081", workspace `bag-end-venture`)
**Ends with:** a WSL restart (`wsl --shutdown`) — no dsh process survives it.
**Figures scrubbed** per house rule; method-level state only.

## What this session did

1. **Root-caused the Agent Team panel error** (first screenshot): the panel resolves
   its session through the "live agent" lookup and *resumes* it when no live agent
   exists; session `74ccbbbb` ("COS - dsv4-pro") is owned by the other `dsh web`
   instance on **:3080**, and both servers share `~/.dsh/sessions`, so the resume hit
   the single-writer lease (`SessionAlreadyOwnedError` → `gateway/internal`).
   Reproduced against the live :3081 API with the token recovered from the boot log;
   the control case (a session :3081 owns) returns `members:[lead]`, no error.
   **Operating rule:** use the Agent Team panel only from a session the server
   you are on actually owns; never keep one session open on both :3080 and :3081.
2. **Pilot (Agent Team mechanics):** two teammates (`parser`, `verifier`), a shared
   task board with a `blocked_by` gate, and a wake-on-dependency. Verifier found a
   material defect in the parser's artifact: `cmd_query` opens `books.db` read-write
   with no `mode=ro` and no `commit()`, so DDL persists (`DROP TABLE` destroys data)
   while DML rolls back on `close()`. Confirmed independently by the COS.
3. **Task #3 executed to a proposal** — 11 unresolved allow-list entries:
   8 tabs pre-fetched through the native-read path, 3 independent flash legs,
   convergence graded, every load-bearing item spot-verified at source.
   **Nothing applied** — allow-list and curation are untouched, pending Joe's rulings.

## Open at handoff

- **Task #3 — 7 rulings requested** (`private/layouts/task3-proposal-2026-09-10.md`).
  Load-bearing: CSV `header_row` is inert (loader CSV path uses `csv_skip`); 6 of 11
  headers are two-tier; `VCA_PLAN`'s rows duplicate `Row Data`; `Row Data`'s recorded
  `header_row: 5` is stale (physical label row is 1).
- **Harness finding (dsh 0.1.5-rc.1):** workflow children cannot use tools — a
  tool-using child returns `null` while tool-free children on the same route pass
  (controlled probe). Both fan-out templates are annotated; the working fan-out path
  is Team teammates (`spawn_teammate`).
- **Protocol gap:** no cross-family leg was achievable (workflow children can't use
  tools; teammates expose no provider/model override). Task #3 legs were all
  `deepseek-flash` *instances* + COS source verification — instance independence only.
- Uncommitted in the working tree: `docs/TASKS.md`, `tools/workflows/survey_fanout.workflow.js`,
  new `tools/workflows/header_proposal.workflow.js`, `private/layouts/task3-proposal-2026-09-10.md`.

## Restart after the WSL shutdown

The trial profile and its packages live on disk (`~/.dsh/profiles/teamlab/`) and are
unaffected by a reboot; only running processes die.

```bash
# daily driver (as before)
dsh web --no-open
# Agent Teams trial profile — the working form (NOT `dsh web --profile teamlab`)
dsh --profile teamlab --port 3081 --no-open
```

- Each boot prints a fresh tokenized URL (`dsh web: http://127.0.0.1:3081/?token=…`);
  the old token dies with the process.
- Liveness check: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3081/`
  → `401` means up and requiring the token.
- Boot the trial from a **plain terminal**, not as a background job inside a dsh
  session: a session-hosted server dies with its session.
- Pre-teamlab config restore path (if the trial is retired):
  `~/.dsh/backups/pre-teamlab-<timestamp>/restore.sh`.

## What survives / what dies

| Survives (disk) | Dies (process) |
|---|---|
| This session's transcript + task board (`~/.dsh/sessions/…`) | the running :3080 and :3081 servers |
| The `teamlab` profile and its packages | live teammates/agents (all idle at handoff) |
| The Task #3 proposal, leg reports, ledger edits | the :3081 URL token |
| The pre-teamlab backup + restore script | the write leases (released by the kernel on process death) |

The session is resumable after restart — the lease is released on process death, so
the earlier ownership conflict cannot persist across a reboot.
