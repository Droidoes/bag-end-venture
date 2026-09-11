// Bag End header-row proposal survey — multi-hit flash fan-out (tools/PANEL.md §1-§5).
//
// !! HARNESS CONSTRAINT (verified 2026-09-10, dsh 0.1.5-rc.1) — DO NOT RUN YET.
// Workflow children (`agent(...)` in a workflow script) cannot use tools in this
// build: a child that calls bash/read resolves to `null`, while tool-free
// children on the same route succeed (controlled within-run probe: qwen3.8-flash
// tool-free PONG vs qwen3.8-flash + `echo` → null). Every leg of this template
// needs `inspect` + a report file, so all legs return null and the run reports
// `legs_failed` for every batch. Same limitation applies to
// `survey_fanout.workflow.js`. WORKING PATH TODAY: run the legs as Team
// teammates (`spawn_teammate`) with self-contained briefs — that is how Task #3
// was executed on 2026-09-10 (see private/layouts/task3-proposal-2026-09-10.md).
// Re-test this template after any harness upgrade.
//
// WHY THIS EXISTS: the allow-list is the ingest gate and `header_row` is
// authoritative, not heuristic (tools/manifests/layouts.schema.md rules 1-2).
// A tab whose header could not be established is written as "unresolved" and
// the tool refuses to ingest it. This template collects independent proposals
// for those unresolved entries, each with structural evidence, so the COS can
// reconcile them and Joe can confirm before any ingest.
//
// HOW THE COS RUNS IT: pre-flight the routes with preflight_ping.workflow.js
// FIRST (tools/PANEL.md §3), then pass this body to the workflow tool as
// `script` with:
//
//   args = {
//     routes: [{ label, provider, model }],          // copied from tools/panel_routes.json
//     hitsPerBatch: 2,
//     batches: [{ name, tabs: [{ file, key, alias, role, note? }] }],
//   }
//
// What a leg does: reads STRUCTURE ONLY (row indices, non-empty counts, cell
// type patterns, column labels) through the repo's own read-only inspect
// command; never transcribes a cell value. It writes its full report to
// .scratch/task3/legs/<batch>__<leg>__<hit>.md and returns a compact JSON
// summary. Several legs per batch, on different routes, so disagreement marks
// genuine ambiguity in the source layout rather than one model's guess.

const routes = (args && args.routes) || [];
const batches = (args && args.batches) || [];
const hits = (args && args.hitsPerBatch) || 2;
if (!routes.length || !batches.length) throw new Error("header-proposal: args.routes and args.batches required");

const schema = {
  type: "object",
  properties: {
    batch: { type: "string" },
    leg: { type: "string" },
    hit: { type: "number" },
    report_path: { type: "string" },
    tabs: {
      type: "array",
      items: {
        type: "object",
        properties: {
          file: { type: "string" },
          key: { type: "string" },
          physical_tab: { type: "string" },
          role: { type: "string" },
          decision: { type: "string", enum: ["header_row", "exclude", "unclear"] },
          header_row: { type: "number" },
          header_confirmed: { type: "boolean" },
          evidence: { type: "string" },
          risks: { type: "array", items: { type: "string" } },
        },
        required: ["file", "key", "role", "decision", "header_row", "evidence"],
      },
    },
    batch_findings: { type: "array", items: { type: "string" } },
  },
  required: ["batch", "leg", "hit", "report_path", "tabs"],
};

function brief(batch, leg, hit) {
  const tablist = batch.tabs.map(t =>
    `  - ${t.file}\n      allow-list key: "${t.key}"   alias: ${t.alias}   declared role: ${t.role}` +
    (t.note ? `\n      COS note: ${t.note}` : "")).join("\n");
  return [
    "You are one independent leg of a header-row survey for a personal-capital",
    "data store. Work ONLY on the files listed. Report STRUCTURE ONLY: row",
    "indices, counts, cell type patterns, and column labels. Never transcribe a",
    "financial value, account number, plan code or other cell content; if a value",
    "is visible, do not copy it.",
    "",
    `Batch: ${batch.name}   Leg: ${leg.label}   Hit: ${hit}`,
    "",
    "Assigned tabs (local files, already fetched):",
    tablist,
    "",
    "Method, per assigned tab:",
    "1. Survey the file with the repo's read-only tool (it never writes):",
    "     python3 tools/bagend.py inspect <path> --md",
    "   For a workbook, the tool surveys every tab; identify the assigned tab by",
    "   exact title and note if the allow-list key does not match any real tab.",
    "2. Inspect the top of the tab STRUCTURALLY - never the values. A safe helper",
    "   prints, for the first 20 rows: row index, count of non-empty cells, and the",
    "   type pattern of those cells (t=text, n=number, d=date, b=blank). Example:",
    "     python3 - <<'PY'",
    "     import csv,sys,datetime",
    "     rows=list(csv.reader(open('<path>', newline='', encoding='utf-8-sig')))",
    "     def kind(v):",
    "         v=v.strip()",
    "         if not v: return 'b'",
    "         for f in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y'):",
    "             try: datetime.datetime.strptime(v,f); return 'd'",
    "             except ValueError: pass",
    "         try: float(v.replace(',','').replace('$','')); return 'n'",
    "         except ValueError: return 't'",
    "     for i,r in enumerate(rows[:20],1):",
    "         pat=''.join(kind(c) for c in r)",
    "         print(i, sum(1 for c in r if c.strip()), pat[:40])",
    "     PY",
    "3. Decide, honouring the declared role:",
    "   - role raw -> propose the 1-based `header_row` whose cells name the columns.",
    "   - role derived/scratch/worksheet/duplicate -> decision \"exclude\", stating",
    "     which structural rows convince you it is not raw data.",
    "   - genuinely ambiguous -> decision \"unclear\" and say what evidence is missing.",
    "4. Confirm a header_row proposal by re-running with it explicit:",
    "     python3 tools/bagend.py inspect <path> --header-row N --md",
    "   Report header_confirmed=true only if the run resolves the header without",
    "   an unresolved-header warning.",
    "",
    "Write your FULL report to " + `.scratch/task3/legs/${batch.name}__${leg.label}__${hit}.md` +
    " (create the directory), then return ONLY the compact JSON per the schema.",
    "In evidence, give the row indices and counts that justify the decision. In",
    "batch_findings, list the 2-5 observations that most affect the allow-list,",
    "each with an evidence pointer (file + tab + row region).",
    "",
    "Rules: do not contact Google Drive; do not modify any source or repo file",
    "other than your report path; no cell values in the report; do not invent",
    "columns or tabs you did not see; report \"unclear\" rather than guessing. Use",
    "header_row = 0 when the decision is not header_row.",
  ].join("\n");
}

phase("Ping legs");
const pinged = await parallel(routes.map(r => () =>
  agent("Reply with JSON only: pong=true, model=<the model named in your system prompt 'powered by' line>.",
        { label: `ping:${r.label}`, phase: "Ping routes", provider: r.provider, model: r.model,
          schema: { type: "object", properties: { pong: { type: "boolean" }, model: { type: "string" } },
                    required: ["pong", "model"] } })
    .then(v => (v && v.pong) ? r : null)
));

const live = pinged.filter(Boolean);
const dropped = routes.filter((r, i) => !pinged[i]).map(r => r.label);
if (dropped.length) log(`dropped dead legs: ${dropped.join(", ")} (provenance: routes_used below)`);
if (!live.length) throw new Error("header-proposal: every leg failed the pre-flight ping — aborting");

phase("Header proposals");
const jobs = [];
for (const b of batches) {
  for (let h = 1; h <= hits; h++) {
    const leg = live[(h - 1) % live.length];
    jobs.push({ batch: b, leg, hit: h });
  }
}

const summaries = await parallel(jobs.map(j => () =>
  agent(brief(j.batch, j.leg, j.hit),
        { label: `header:${j.batch.name}#${j.hit}`, phase: "Header proposals",
          provider: j.leg.provider, model: j.leg.model, schema })
));

const got = summaries.map((v, i) => v && { ...v, _route: jobs[i].leg.label, _batch: jobs[i].batch.name });
const failed = jobs.filter((_, i) => !summaries[i]).map(j => `${j.batch.name}#${j.hit}(${j.leg.label})`);

return {
  routes_used: live.map(r => r.label),
  legs_dropped: dropped,
  legs_failed: failed,
  batches: batches.map(b => b.name),
  proposal_tabs: got.filter(Boolean).reduce((n, v) => n + v.tabs.length, 0),
  reports: got.filter(Boolean),
};
