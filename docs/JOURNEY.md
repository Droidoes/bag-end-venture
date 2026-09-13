# Bag End — Journey

**Purpose.** The lessons-and-decisions arc of this repo: not *what* was built
(that is the ledger and the North Star), but *what we learned about how to
work* — the corrections, the reversals, and the rules that now exist because
something went wrong first. `docs/TASKS.md` is the ledger; `docs/CODEBASE_OVERVIEW.md`
is the architecture North Star; this file is the method's memory.

**Owner:** Joe · **Author:** Roth (COS) · **Started:** 2026-09-12 (backfilled from
the session handoffs, the ledger, and the ratified charter).

---

## 1. Custody and the native-read rule

The earliest structural decision was that **Drive is canonical custody and SQLite
is a compute layer** — `private/books.db` is rebuildable from Drive at any time
(and gitignored), so the store can never become the only copy.

The lesson that forced the *native-read rule* came from a real defect: exporting
a native Google Sheet to xlsx corrupted it — padding rows appeared, years were
re-inferred, chart tabs crashed the reader. The rule now in the charter:
**read every source through the path it was born in.** A conversion is not a
neutral step; it is damage that later looks like a data-quality problem and gets
blamed on Joe's files.

**Carried forward:** `tools/bagend.py` is the single entrypoint, and
`_provenance.tsv` — not a filename — is the authority on what a local file
actually is.

## 2. Evidence over assertion — and flag-only toward the sources

Two habits were adopted together and have held:

- **Provenance invariants on every ingested row** (`_source_path`, `_drive_id`,
  `_ingested_at`), so any number can be traced back to the object it came from.
- **Flag-only toward the sources.** A defect in Joe's live Sheets is reported
  with an evidence pointer; it is never silently repaired. Stewardship honesty
  is structural here: *reported*, *derived*, and *planned* stay distinguishable,
  and unknown is never zero.

**Carried forward:** a stale or unreconciled figure carries a visible `[verify]`
tag, and **no recommendation may rest on a tagged figure** until it is re-checked.

## 3. The panel: flash legs, convergence, and two layers of independence

The review method was ratified as: **flash models take multiple hits of the same
task; pro models review finished artifacts afterwards and never join the build.**
Disagreement between hits marks ambiguity in the *task*, not noise to average
away — and findings are graded by agreement (`n/n` load-bearing, `(n-1)/n` strong
consensus, `1/n` a unique catch still worth surfacing).

The subtlety that took two owner rulings to settle: **independence has two
layers.**
1. **Instance independence** — a leg is always a fresh instance with a
   self-contained brief, so it cannot echo the COS's framing. A leg on the
   chair's own model still verifies the COS *instance* genuinely.
2. **Model independence** — identical weights share identical blind spots, so
   agreement between same-model legs can be correlated error. Safeguard: every
   batch keeps at least one **cross-family** leg.

**Carried forward:** the COS chair is excluded from post-hoc pro review of
artifacts built under it. "In the build" is a disqualifier, not a detail.

## 4. Verification pays for itself

On 2026-09-10 a **verifier teammate found a material defect in a parser's
artifact**: the query path opened `books.db` read-write with no `mode=ro` and no
`commit()`, so DDL persisted — a stray `DROP` would destroy the store — while DML
rolled back on close. The COS reproduced it independently. It became Task #19(a)
and landed on 2026-09-12 (`_connect_ro()`, plus a row-factory-agnostic
`assert_schema`).

**The lesson is not "add tests". It is that an adversarial leg pointed at another
leg's output finds things the author cannot see** — the defect was in the
author's own happy path.

## 5. Every number needs a definition

On 2026-09-06 two legs reported different row counts for the same tab. Both were
correct: one counted date-typed cells, the other counted all populated cells. The
COS then "resolved" it with a check that measured a *third* thing and published a
wrong verdict — after already relaying a phantom gap that was a strict-parse
artifact.

**Carried forward:** before a number reaches Joe, (1) state what each figure
counted, (2) re-derive with the most tolerant method available — a number that
changes when the parser gets smarter is a *tool* defect, not a data defect — and
(3) publish the definition alongside the number. An unreconciled disagreement is
unfinished work, not a finding to report.

## 6. Harness findings are provisional — retest after every upgrade

A hard constraint was recorded on 2026-09-10 against dsh 0.1.5-rc.1: *workflow
`agent()` children cannot use tools* (a tool-using child resolved to `null`). It
was written into two template headers as `DO NOT RUN YET`, and the working path
was documented as Team teammates.

On **2026-09-12 it was retired**: workflow children on the then-current build both
accepted explicit `provider`/`model` and executed real tool calls — proved by
having two children on two routes write unique nonce files to disk and confirming
them from the COS shell, rather than trusting a printable success string.

**The lesson cuts both ways.** A printable success signal is not evidence (the
first probe's `echo` output could have been hallucinated), and a recorded
limitation is not permanent. **Annotate the version and the date, and retest.**

## 7. Vocabulary is load-bearing

Four turns of a 2026-09-12 session went into untangling harness terminology
before any finding could land. The cause was measurable: the delegation path has
**two objects and about six names**, and the word **"provider" carries three
unrelated meanings** (the child-creator `spawn`/`fork`; the model vendor
`zai-payg`; and a plugin's own `providerName` field). "Tool" was likewise
overloaded between the package and a mounted instance.

**Carried forward:** use only the code's four terms —
`SubagentProvider`, `ctx.subagents`, the tool name, and the LLM route — and say
*which* "provider" is meant. Slang invented mid-explanation ("backend",
"front-end", "tool instance", "plain subagent") gets reasoned with as if it were
real, and that is how a four-turn detour happens.

## 8. Boundaries are logged, never silent

`AGENTS.md` §5.4 keeps the Obsidian vault read-only from this repo. Twice now the
owner has directly instructed a vault write (2026-09-11 Agent Teams write-up;
2026-09-12 subagent architecture note), and twice it has been logged as a
one-off, owner-directed exception per §5.6 rather than quietly performed.

**The rule:** a boundary crossing that is not logged is indistinguishable from a
boundary that does not exist.

## 9. What changed on 2026-09-12 (capability)

Model-pinned, tool-using fan-out became available: `subagent` calls can name
`provider` + `model` (+ `reasoning_effort`), and `workflow` `agent()` children can
use tools. All four flash routes were verified end to end.

Two operational notes that will outlive the day:
- **The binding is per session, at session start.** Enabling the setting
  mid-session — or restarting dsh and resuming an old conversation — leaves the
  old tool schema in place. The fix is a **new conversation**.
- **Steerability differs by door.** `subagent`/`subagent_fork` children are
  `continuable` and answer `send_message`; `workflow` children are `one-shot` and
  must be re-dispatched instead.

Full record: `tools/PANEL.md` §3 ("Delegation doors") and
`~/Obsidian/AIML/dsh/dsh-subagent-architecture-2026-09-12.md`.

## 10. A constraint we chose *not* to fix — `gws` under the sandbox

`gws` **writes on every token acquisition** — it sets permissions on its token
directory and rewrites `token_cache.json`. Under the dsh `workspace-write`
sandbox the only writable roots are the session workspace and `/tmp`, and `/tmp`
is a per-command private tmpfs (a file written in one bash call is gone in the
next). So `~/.config/gws` can never be writable, and the writable set is
**hardcoded** — no settings key, no env var, no path allowlist. The symptom is
misleading: `gws auth status` works (keyring read, persists nothing) while
`gws tasks …` fails with `os error 30` / `authError` even when auth is perfectly
healthy.

Three options were weighed on 2026-09-12 and the owner chose the do-nothing path:

| Option | Verdict |
|---|---|
| **A — batch every `gws` read into one escalated call per session** | **CHOSEN.** One approval per session; no posture change. |
| B — point `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` at the workspace | Rejected: would move Drive/Gmail/Calendar credentials into the repo tree. |
| C — launch dsh with `DSH_PERMISSION_MODE=danger-full-access` | Rejected: also sets the approval policy to `never`, disabling ask-before-writes house-wide. |

**The lesson is the decision, not the workaround.** A tooling constraint that
cannot be removed cleanly should be *decided once, recorded with its rejected
alternatives, and never re-litigated* — otherwise every session re-pays the same
investigation. The working rule now lives in the `session-catchup` skill: batch
the reads, take one approval, and report the failure cause instead of letting it
look like an empty result list.

**Addendum, same day.** The owner later switched the session itself to
`danger-full-access` with approvals disabled, which removes the constraint at the
session level rather than at the tool level. So the rule above is now
**conditional**: it governs *sandboxed* sessions only. In a full-access session
`gws` is called normally, with no batching and no escalation. The underlying
finding stands — the writable set is hardcoded, so no amount of configuration
makes `~/.config/gws` writable under `workspace-write`.

---

## See also

- `AGENTS.md` — the charter (doctrine, data architecture, hard boundaries).
- `docs/TASKS.md` — the ledger.
- `docs/CODEBASE_OVERVIEW.md` — the North Star.
- `docs/session-handoff-*.md` — per-session state.
- `tools/PANEL.md` + `tools/panel_routes.json` — the fan-out protocol.
