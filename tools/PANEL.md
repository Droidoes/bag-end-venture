# Bag End Review Panel — Standing Protocol

**Version:** 1.0 · **Status:** RATIFIED (owner ruling, 2026-09-06) · **Owner:** COS
**Promote into:** `AGENTS.md` §3 (engagement) and §7 (session protocol) at charter writing.

## 1. Method

Flash models take **multiple hits of the same task** to surface the best way
forward; disagreement between hits marks ambiguity in the *task*, not in the
models. **Pro models review results afterwards and never participate in the
build.** Pro review is initiated manually by the owner in separate sessions,
which is what makes it independent.

```
COS (deepseek-flash, owner ruling 2026-09-08) → fan out N flash legs on the same batch
                           → legs write full reports to private/, return compact summaries
                           → COS reconciles by convergence (n/n, (n-1)/n, 1/n)
                           → schema/charter draft
                           → [owner-initiated] pro review of the artifacts
```

## 2. Seats

| Seat | Model | Provider | Notes |
|---|---|---|---|
| **COS** | `deepseek-flash` (display name **DeepSeek-V41-Flash**) — **owner ruling 2026-09-08: V41-Flash holds the COS seat, superseding the 2026-09-07 pro-chair ruling** | `deepseek-official` | Holding the chair counts as *in the build* (independence note below). Owner-facing behavior per the `cos-role` skill. Decomposition, briefs, reconciliation, spot-verification, filing. |
| Extraction leg | `deepseek-flash` | `deepseek-official` | PONG ✓ 2026-09-08 (V41-Flash, identity + schema verified). **Priority 1**. Separate instance from the COS with a self-contained brief — independent of the COS instance. |
| Extraction leg | `glm-5.3-flash` | `zai-payg` | PONG ✓ 2026-09-08. **Priority 1** (owner ruling 2026-09-08). Cross-family leg — the independence workhorse. |
| Extraction leg | `qwen3.8-flash` | `qwencloud-payg` | PONG ✓ 2026-09-08 (3-attempt rule). **Priority 2**. Plain flash seat — no clone role. |
| Extraction leg | `gpt-5.6-luna` | `openai` | PONG ✓ 2026-09-08 (owner fix; canonical schema ping verified — see run log for the outage history). **Priority 3**. Schema-capable. |
| Reviewer (external) | Qwen3.8-Max · GLM-5.3 · Grok-4.6 · GPT-5.6-Sol — **not DeepSeek-V41-Flash (`deepseek-flash`), which holds the COS chair and doubles as a priority-1 leg** | owner-run | Reviews finished artifacts in separate sessions; feedback absorbed per §5. |

The COS is `deepseek-flash` — **DeepSeek-V41-Flash** (owner ruling 2026-09-08;
the older `deepseek-v4-pro`/`deepseek-v4-flash` ids are retired from this
table). Worker seats stay flash-only, in owner-assigned priority order:
**`deepseek-flash` + `glm-5.3-flash` (priority 1) · `qwen3.8-flash`
(priority 2) · `gpt-5.6-luna` (priority 3)**. Assign routes by priority; fall
through to a lower priority only when the higher-priority routes are exhausted
or unsuitable for the batch. Seats are **cheap and unlimited by design** — run
multiple independent legs per model on the same batch rather than treating one
model per batch as the unit of work.

**Independence note (owner rulings 2026-09-07/08):** independence has two
layers, and the panel covers both.

1. **Instance/context independence.** Every leg is a *fresh instance* driven by
   a *self-contained brief* — it never sees the COS conversation, so it cannot
   echo the COS's framing or conclusion. A `deepseek-flash` leg therefore
   verifies the COS instance genuinely, even though the chair runs the same
   model (owner clarification 2026-09-08).
2. **Model independence.** Same weights share the same blind spots, so
   agreement between same-model legs can be correlated error rather than
   confirmation. Safeguard: **every batch keeps at least one cross-family leg**
   (`glm-5.3-flash`, or `qwen3.8-flash`/`gpt-5.6-luna`).

The COS chair (`deepseek-flash`) is *in the build* and stays **excluded from the
post-hoc pro-review roster**. Default remaining reviewers: `qwen3.8-max`,
`glm-5.3`, and any other owner-run seat.

## 3. Routing rules (inherited from the 10x playbook, non-negotiable)

1. **Explicit provider on every delegated call.** Never rely on a default
   route — implicit defaults have silently killed legs in past fan-outs.
2. **Mandatory pre-flight ping** before any fan-out that uses more than one
   route: one PONG agent per route, checked before real work. A non-PONG is
   handled loudly (drop the route and record it, or abort) — never silently.
3. **Identity verification:** each ping child quotes the model name from its
   own system prompt line "powered by the <model> model". The COS compares
   it against the requested model; a mismatch is a routing bug, not noise.
4. **Structured output** on every leg (schema-constrained), so reconciliation
   is mechanical and a failed leg is detectable as `null`.
5. **Retry before condemning a leg: up to 3 attempts per route.** A single
   `null` return is *ambiguous* — transient failure, structured-output contract
   failure, and true route death are indistinguishable from one result. On
   2026-09-06 a first ping scored `gpt-5.6-luna` dead; a retest showed it alive
   and schema-capable. Never drop working capacity on a hiccup.
6. **Log every run:** write down every ping attempt, the routes used, and any
   dropped or substituted leg in the batch report — so a later reader can see
   exactly who did what and when.

Routes are **data, not improvisation**: `tools/panel_routes.json` is the
canonical provider/model table. Copy from it; never hand-compose a pair in a
delegation prompt. Reusable scripts:
`tools/workflows/preflight_ping.workflow.js` (the gate) and
`tools/workflows/survey_fanout.workflow.js` (structure survey).

### Delegation doors (verified 2026-09-12)

Three doors create children. All of them hand a request to the same
`ctx.subagents` registry; each door is welded to one provider backend at
composition time.

| Door | Backend | Model pinning | Child |
|---|---|---|---|
| `subagent` | spawn | ✅ per call | fresh — zero parent context |
| `subagent_fork` | fork | ❌ schema carries no `provider`/`model` | seeded with the parent's completed turns |
| `workflow` `agent()` | spawn (worker thread) | ✅ per call | fresh; script-orchestrated |

**Vocabulary — say which "provider".** The code's words: `SubagentProvider`
(`spawn`/`fork`), `ctx.subagents` (the registry), the tool name, and the **LLM
route** (`provider` + `model`). "Provider" alone is ambiguous — it names the
child-creator in a tool's *config* and the model vendor in a tool *call*.

- **Verified live 2026-09-12:** all four flash routes pinned on `subagent`; each
  child quoted its own identity line verbatim and executed bash + read + glob.
  `workflow` `agent()` pinned two routes and used tools — proved by having two
  children write unique nonce files to disk, confirmed from the COS shell.
- **`reasoning_effort` pinning is UNTESTED** — children do not report their
  effort, so the identity check cannot confirm it. Test per route before relying
  on it, especially `gpt-5.6-luna` (effort-value sensitive). `workflow`
  `agent()` rejects `reasoning_effort` outright: effort pinning is
  `subagent`-only.
- **Model selection binds per session, at session start.** Enabling
  `subagent-model-selection` mid-session — or restarting dsh and resuming an *old*
  conversation — leaves the old tool schema in place, and the call fails with
  `Error: child model selection is disabled for this tool instance`. The fix is a
  **new conversation**; a restart is not enough.
- **Steerability differs by door.** `subagent` and `subagent_fork` children are
  `continuable` and answer `send_message`; `workflow` children are `one-shot` and
  **cannot** be steered mid-run — re-dispatch instead.
- The 2026-09-10 finding that `workflow` `agent()` children cannot use tools is
  **retired**; both previously parked templates are runnable again.
- Full architecture map, term mapping and GUI reading guide:
  `~/Obsidian/AIML/dsh/dsh-subagent-architecture-2026-09-12.md`.

## 4. Brief discipline

A delegated brief is **self-contained** — specialists never see the COS
conversation. Every brief carries: the exact question, the assigned files
(local paths only), the output shape, and the honesty rules.

**Hard rule — no figures in briefs.** Delegates receive file *paths* and are
asked for *structure* (tabs, headers, row counts, date ranges, layout
quirks). Financial values never enter a prompt, a delegate's report, or a
committed file. Delegates write to `private/` and return compact summaries,
so bulk detail stays on disk and out of the COS context.

**Pre-fetch before fan-out.** Legs read from `private/raw/`, never from
Drive — no per-leg auth, no repeated API calls, no sandbox elevation needed
inside sub-agents.

## 5. Convergence & absorption

Findings are graded by agreement, not by confidence rhetoric:

| Grade | Meaning | Action |
|---|---|---|
| **n/n** | unanimous across all legs on the batch | **load-bearing** — must be resolved before proceeding |
| **(n-1)/n** | strong consensus | fold in; note the dissenter |
| **1/n** | unique catch | surface it explicitly — a lone correct observation is still correct |

Severity per finding: `BLOCKER` / `MAJOR` / `MINOR` / `NIT`, each with an
evidence pointer (file, tab, line/column region). The COS **spot-verifies
every load-bearing item against the source file** — never a skip.

All reviewer feedback (internal or pro-tier) is logged, categorized by
convergence, and folded into the next version. No `n/n` finding may be
deferred without an explicit owner override.

### Disagreement is work to finish — reconcile before reporting

Legs disagreeing is **not** a result to report — it is work to finish. Before
any reconciled number reaches the owner:

1. **State what each figure counted.** On 2026-09-06 two legs reported 2,577 vs
   2,731 rows for one tab. Both were correct: one counted *date-typed cells*, the
   other *all populated cells* (154 of them text-formatted dates). The COS
   "resolved" it by a check that measured yet a third thing and published a wrong
   verdict — and had already relayed a phantom "155-day hole" that was pure
   strict-parse artifact.
2. **Re-derive under a tolerant method** before calling a source defective. A
   figure that changes when the parser gets smarter is a tool defect, not data.
3. **Never surface an internal leg conflict as a finding** unless it survives
   steps 1–2 or genuinely changes a decision the owner must make. Unreconciled
   disagreement in the report is noise the owner pays for.
4. **Report the definition alongside the number**, every time
   (`dated rows, typed = 2,577` / `dated rows, typed + text = 2,731`).

## 6. Steering, scratch space, and layering

**Steer live legs.** `send_message` (dsh ≥ 0.1.2 — this session runs 0.1.2-rc.1)
lets the COS correct, narrow, or extend a running first-level sub-agent, and
lets a leg ask back. This is what converts delegation from a gamble into a
managed process, and it is the direct answer to the "agents cannot coordinate
in real time" objection: they can, through the COS. Use it rather than killing
and re-dispatching a leg that drifted. Prefer `subagent_fork` when a leg needs
this conversation's reasoning; plain `subagent` when the brief is self-contained.
**Caveat (2026-09-12):** steering works only through the `continuable` doors —
`subagent` and `subagent_fork`. `workflow` `agent()` children are `one-shot` and
**cannot** be steered mid-run; re-dispatch those instead. See "Delegation doors"
in §3.

**Scratch convention.** Leg working files and drafts go in **`.scratch/`**
(gitignored, ephemeral, safe to wipe). Persistent data artifacts — fetched
sources, censuses, the DB — stay in **`private/`**. Neither is ever committed.

**Fail loudly.** A null leg, a dropped route, a parse that yields 14 rows where
999 exist, a figure without provenance — surfaced immediately, never absorbed
into a tidy summary. Silent success is the most expensive failure mode here.

**Layering.** The owner-facing availability contract (never block the channel,
1-minute delegation threshold, queue discipline, the confidence to say no)
lives in the global **`cos-role`** skill. This file is Bag End's per-project
layer: roster, routing, briefs, convergence. The global skill sets how the COS
behaves toward Joe; this file sets how the COS behaves toward its team here.

## 7. Loop-breaking

The COS declares *stop-and-ask* when: a required source is missing or
unreadable, a route is dead and no substitute exists, the briefs would have
to embed figures to be answerable (a privacy boundary), or two `n/n`
findings conflict in a way that changes the schema rather than its details.
Fan-out depth is never a reason to keep spinning.
