// Bag End structural survey — multi-hit flash fan-out (tools/PANEL.md §1-§5).
//
// !! HARNESS CONSTRAINT (verified 2026-09-10, dsh 0.1.5-rc.1) — LEGS CANNOT RUN.
// Workflow children cannot use tools in this build: a tool-using child resolves
// to `null`; tool-free children on the same route succeed (controlled probe:
// qwen3.8-flash tool-free PONG vs + `echo` → null). This template's legs are told
// to run `bagend.py inspect` and write reports, so every leg nulls out. Same for
// `header_proposal.workflow.js`. WORKING PATH TODAY: Team teammates
// (`spawn_teammate`) with self-contained briefs. Re-test after a harness upgrade.
//
// HOW THE COS RUNS IT: pass this body to the workflow tool as `script`, with
// `args` = { routes: [{label, provider, model}], batches: [{name, files:[localPath]}] }.
// Pre-flight the routes with preflight_ping.workflow.js FIRST; a dead leg here is
// reported, not hidden.
//
// What a leg does: reads structure ONLY, via the repo's own inspect command
// (no cell values, no Drive auth, no elevation), writes its full report to
// private/survey/<batch>__<leg>__<n>.md, and returns a compact JSON summary.
// Multiple legs per batch (different models, and repeats of the same model)
// so disagreement marks genuine ambiguity in the source layout.

const routes = (args && args.routes) || [];
const batches = (args && args.batches) || [];
const hits = (args && args.hitsPerBatch) || 2;
if (!routes.length || !batches.length) throw new Error("survey: args.routes and args.batches required");

const schema = {
  type: "object",
  properties: {
    batch: { type: "string" },
    leg: { type: "string" },
    report_path: { type: "string" },
    files: {
      type: "array",
      items: {
        type: "object",
        properties: {
          path: { type: "string" },
          tabs: { type: "array", items: { type: "string" } },
          layout: { type: "string" },
          grain: { type: "string" },
          entity_dimension: { type: "boolean" },
          date_field: { type: "string" },
          parse_risks: { type: "array", items: { type: "string" } },
          proposed_table: { type: "string" },
        },
        required: ["path", "tabs", "layout", "grain", "parse_risks", "proposed_table"],
      },
    },
    batch_findings: { type: "array", items: { type: "string" } },
  },
  required: ["batch", "leg", "report_path", "files"],
};

function brief(batch, leg, hit) {
  const filelist = batch.files.map(p => `  - ${p}`).join("\n");
  return [
    "You are one independent leg of a structural survey for a personal-capital",
    "data store. Survey ONLY the files listed. Never open or report financial",
    "values; if a value is visible, do not transcribe it.",
    "",
    `Batch: ${batch.name}   Leg: ${leg.label}   Hit: ${hit}`,
    "",
    "Files (local, already fetched):",
    filelist,
    "",
    "For each file run the repo's structure survey tool (no cell values):",
    "  python3 tools/bagend.py inspect <path> --md",
    "",
    "Determine, per file: tab names; layout (clean header row? preamble rows?",
    "merged/repeated section headers? multiple blocks stacked in one tab? pivot",
    "layout with dates as columns?); grain (one row per what?); whether an",
    "entity/owner/account dimension is present; the date field and its format;",
    "parse risks (what will silently produce wrong data); and a proposed",
    "normalised table shape (name + key columns).",
    "",
    "Write your FULL report to private/survey/" + `${batch.name}__${leg.label}__${hit}.md` +
    " (create dirs as needed), then return ONLY the compact JSON summary per the",
    "schema. In batch_findings, list the 2-5 observations that most affect a",
    "schema decision, each with an evidence pointer (file + tab + region).",
    "",
    "Rules: do not contact Google Drive; do not modify the source files; do not",
    "invent columns you did not see; report 'unclear' rather than guessing.",
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
if (!live.length) throw new Error("survey: every leg failed the pre-flight ping — aborting");

phase("Survey batches");
const jobs = [];
for (const b of batches) {
  for (let h = 1; h <= hits; h++) {
    const leg = live[(h - 1) % live.length];
    jobs.push({ batch: b, leg, hit: h });
  }
}

const summaries = await parallel(jobs.map(j => () =>
  agent(brief(j.batch, j.leg, j.hit),
        { label: `survey:${j.batch.name}#${j.hit}`, phase: "Survey batches",
          provider: j.leg.provider, model: j.leg.model, schema })
));

const got = summaries.map((v, i) => v && { ...v, _route: jobs[i].leg.label, _batch: jobs[i].batch.name });
const failed = jobs.filter((_, i) => !summaries[i]).map(j => `${j.batch.name}#${j.hit}(${j.leg.label})`);

return {
  routes_used: live.map(r => r.label),
  legs_dropped: dropped,
  legs_failed: failed,
  batches: batches.map(b => b.name),
  reports: got.filter(Boolean),
};
