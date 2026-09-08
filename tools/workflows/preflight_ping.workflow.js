// Bag End pre-flight ping gate — canonical template.
//
// HOW THE COS RUNS IT: pass this file's body to the workflow tool as `script`,
// with `args` = { routes: [{ label, provider, model }] }. No edits to the body.
//
//   args = { routes: [
//     { label: "qwen3.8-flash", provider: "qwencloud-payg", model: "qwen3.8-flash" },
//     { label: "glm-5.3-flash", provider: "zai-payg",       model: "glm-5.3-flash" },
//   ]}
//
// Rule (tools/PANEL.md §3): every fan-out that uses more than one route starts
// with this gate. Each child quotes the model name from its own system prompt,
// so a route that resolves to the wrong catalog is caught as a mismatch, not
// trusted as a PONG.

const routes = (args && args.routes) || [];
if (!routes.length) throw new Error("preflight: args.routes required (label, provider, model)");

const schema = {
  type: "object",
  properties: {
    pong: { type: "boolean" },
    model: { type: "string" },
    effort: { type: "string" },
  },
  required: ["pong", "model"],
};

phase("Ping routes");
const results = await parallel(routes.map(r => () =>
  agent(
    "Pre-flight liveness check for an orchestration ping gate. Do not use any tools. " +
    "Reply ONLY with JSON matching the schema: pong=true, model = the exact model name " +
    "from the line in your own system prompt that reads 'powered by the <model> model' " +
    "(quote it verbatim; if absent, answer 'unknown'), effort = your stated reasoning " +
    "effort if your prompt states one, else 'unknown'.",
    { label: `ping:${r.label}`, phase: "Ping routes", provider: r.provider, model: r.model, schema }
  ).then(v => v && { route: r.label, provider: r.provider, expect: r.model, ...v })
));

const report = results.map((v, i) =>
  v || { route: routes[i].label, provider: routes[i].provider, pong: false,
         note: "child failed or returned no structured output (dead leg)" });

const dead = report.filter(r => !r.pong || r.model !== r.expect);
for (const r of report) log(`ping ${r.route}: ${r.pong ? "PONG" : "DEAD"}${r.model ? " model=" + r.model : ""}`);

return {
  all_live: dead.length === 0,
  live: report.filter(r => r.pong && r.model === r.expect).map(r => r.route),
  dead: dead.map(r => ({ route: r.route, why: r.note || `identity mismatch: got ${r.model}` })),
  report,
};
