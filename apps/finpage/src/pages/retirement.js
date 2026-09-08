/* Bag End financial page — Retirement dashboard (page module).
   Rendered into its page container by the shared core. */
"use strict";

FinPages.register({
  id: "retirement",
  title: "Retirement",
  order: 1,

  render(root, payload) {
    if (!payload) return;
    const r = payload.pages.retirement;
    const a = r.annuity;
    root.innerHTML = `
      <section>
        <h2>Vitals</h2>
        <div class="cards">
          <div class="card"><div class="label">Net worth</div><div class="value" id="c-nw">—</div><div class="hint" id="h-nw"></div></div>
          <div class="card"><div class="label">Annuity ceiling (A_max)</div><div class="value" id="c-amax">—</div><div class="hint" id="h-amax">flat, zero at age 100</div></div>
          <div class="card"><div class="label">Planned spending</div><div class="value" id="c-plan">—</div><div class="hint" id="h-plan"></div></div>
          <div class="card"><div class="label">Headroom</div><div class="value" id="c-head">—</div><div class="hint" id="h-head">ceiling ÷ plan</div></div>
        </div>
      </section>

      <section>
        <h2>Effective annuity — play with the plan</h2>
        <div class="controls">
          <div class="ctl">Yield
            <input type="range" id="s-yield" min="0" max="5" step="0.25" value="3">
            <output id="o-yield">3.0%</output>
          </div>
          <div class="ctl">SS claim age
            <select id="s-claim"></select>
          </div>
          <div class="ctl">SS after go-broke year
            <input type="range" id="s-rate" min="60" max="100" step="1" value="78">
            <output id="o-rate">78%</output>
          </div>
          <div class="ctl">Spending ×
            <input type="range" id="s-mult" min="100" max="300" step="5" value="200">
            <output id="o-mult">2.00×</output>
          </div>
        </div>
        <div class="annuity-readout">
          <div class="card"><div class="label">A_max / year</div><div class="value" id="w-amax-y">—</div></div>
          <div class="card"><div class="label">A_max / month</div><div class="value" id="w-amax-m">—</div></div>
          <div class="card"><div class="label">Min balance on the path</div><div class="value" id="w-min">—</div></div>
          <div class="card"><div class="label">At plan spend, age-100 balance</div><div class="value" id="w-end">—</div></div>
        </div>
        <p class="note">Ladder is flat nominal (the owner's model): balance − spend + SS, × (1+yield), SS from the first full year after the claim age, haircut from the Trustees go-broke year. Store reference below.</p>
      </section>

      <section>
        <h2>Store reference (precomputed from books.db)</h2>
        <table id="t-ref">
          <thead><tr><th>Variant</th><th>Yield</th><th>A_max/yr</th><th>Plan end @100</th></tr></thead>
          <tbody></tbody>
        </table>
      </section>

      <section>
        <h2>Net worth</h2>
        <svg class="chart" id="chart" viewBox="0 0 1000 220" preserveAspectRatio="none"></svg>
        <p class="note" id="chart-note"></p>
      </section>

      <section>
        <h2>Top positions (by account consolidation)</h2>
        <table id="t-hold">
          <thead><tr><th>Ticker</th><th>Market value</th><th>Weight</th></tr></thead>
          <tbody></tbody>
        </table>
      </section>

      <section>
        <h2>Filed tax history</h2>
        <table id="t-tax">
          <thead><tr><th>Year</th><th>Status</th><th>AGI</th><th>Taxable</th><th>Fed tax</th><th>NJ tax</th><th>Bracket</th><th>Std ded</th></tr></thead>
          <tbody></tbody>
        </table>
        <p class="note">Std ded 0 = itemized (no standard deduction taken); — = not printed. Brackets from the preparer's Tax History Report; 2023–2025 status derived (flagged in store).</p>
      </section>

      <section>
        <h2>Definitions</h2>
        <ul class="defs">
          <li><b>A_max (ceiling):</b> the flat annual withdrawal that lands the ladder at ~$0 at age 100 — "Effective Annuity (max)", an upper bound, not planned spending.</li>
          <li><b>Planned spending:</b> current-year actual × the plan multiplier (owner ruling).</li>
          <li><b>SS:</b> store estimates; base case pays the go-broke rate of scheduled benefits from the Trustees go-broke year onward.</li>
          <li><b>Yield:</b> long-term nominal yield assumption, registered in the store.</li>
        </ul>
      </section>`;

    this._bind(a);
    this._renderAll(r);
  },

  _renderAll(r) {
    const a = r.annuity;
    // vitals
    $("c-nw").textContent = fmtUsd(r.networth.total);
    $("h-nw").textContent = "as of " + r.networth.as_of;
    const sched = ssSchedule(a.ss67_monthly, a.go_broke_rate, a.go_broke_year,
                             a.born_year + 67 + 1, a.born_year, a.zero_age, false);
    const am = aMax(a.balance, a.yield_long_term, sched, a.start_year, a.born_year, a.zero_age);
    $("c-amax").textContent = fmtUsd(am);
    $("h-amax").textContent = "claim 67 · " + fmtUsd(am / 12) + "/mo";
    $("c-plan").textContent = fmtUsd(a.spending.planned);
    $("h-plan").textContent = fmtUsd(a.spending.current_2025) + " × " + fmtNum(a.spending.multiplier);
    $("c-head").textContent = fmtNum(am / a.spending.planned) + "×";
    $("h-head").textContent = "at store yield " + fmtNum(a.yield_long_term * 100, 1) + "%";

    // widget
    this._renderWidget(a);

    // store reference
    const tb = $("t-ref").querySelector("tbody");
    tb.innerHTML = "";
    for (const row of a.reference) {
      const tr = el("tr");
      const end = row.plan_end_at_100 === null ? "broke " + row.plan_broke_at : fmtUsd(row.plan_end_at_100);
      tr.innerHTML = "<td>" + row.variant + "</td><td>" + row.yield_label + " (" +
        fmtNum(row.yield * 100, 1) + "%)</td><td>" + fmtUsd(row.a_max) + "</td><td>" + end + "</td>";
      tb.appendChild(tr);
    }

    // net worth chart
    const nw = r.networth;
    const svg = $("chart");
    const W = 1000, H = 220, pad = 8;
    const xs = nw.as_ofs, ys = nw.totals;
    if (xs.length) {
      let lo = Math.min(...ys), hi = Math.max(...ys);
      if (lo === hi) { lo -= 1; hi += 1; }
      const X = i => pad + (W - 2 * pad) * i / Math.max(1, xs.length - 1);
      const Y = v => H - pad - (H - 2 * pad) * (v - lo) / (hi - lo);
      let grid = "", pts = "";
      for (let g = 0; g <= 4; g++) {
        const gy = pad + (H - 2 * pad) * g / 4;
        grid += '<line x1="' + pad + '" y1="' + gy + '" x2="' + (W - pad) +
                '" y2="' + gy + '" stroke="rgba(127,140,160,0.12)" stroke-width="1"/>';
      }
      ys.forEach((v, i) => { pts += (i ? " " : "") + X(i).toFixed(1) + "," + Y(v).toFixed(1); });
      svg.innerHTML = grid +
        '<polyline points="' + pts + '" fill="none" stroke="#d4a94e" stroke-width="2"/>' +
        '<text x="' + (W - pad) + '" y="' + (H - 4) + '" fill="#8595a8" font-size="11" text-anchor="end">' +
        xs[xs.length - 1] + " · " + fmtUsd(ys[ys.length - 1]) + '</text>';
      $("chart-note").textContent = "Range " + xs[0] + " → " + xs[xs.length - 1] +
        " · min " + fmtUsd(lo) + " · max " + fmtUsd(hi);
    }

    // holdings
    const th = $("t-hold").querySelector("tbody");
    th.innerHTML = "";
    for (const h of r.holdings_top || []) {
      const tr = el("tr");
      tr.innerHTML = "<td>" + h.symbol + "</td><td>" + fmtUsd(h.market_value) +
        "</td><td>" + fmtNum(h.weight_pct, 1) + "%</td>";
      th.appendChild(tr);
    }

    // tax
    const tt = $("t-tax").querySelector("tbody");
    tt.innerHTML = "";
    for (const t of r.tax) {
      const tr = el("tr");
      if (t.needs_verify) tr.classList.add("dim");
      const std = t.std_deduction === null ? "—" : fmtUsd(t.std_deduction);
      tr.innerHTML = "<td>" + t.tax_year + (t.needs_verify ? " *" : "") + "</td><td>" +
        t.filing_status + "</td><td>" + fmtUsd(t.agi) + "</td><td>" +
        fmtUsd(t.taxable_income) + "</td><td>" + fmtUsd(t.total_tax) + "</td><td>" +
        fmtUsd(t.state_income_tax) + "</td><td>" + (t.marginal_bracket || "—") +
        "</td><td>" + std + "</td>";
      tt.appendChild(tr);
    }
  },

  _renderWidget(a) {
    const age = Number($("s-claim").value);
    const rate = Number($("s-rate").value) / 100;
    const mult = Number($("s-mult").value) / 100;
    const yld = Number($("s-yield").value) / 100;
    const monthly = a.ss_by_age[age] || 0;
    const firstFullYear = a.born_year + age + 1;
    const sched = ssSchedule(monthly, rate, a.go_broke_year, firstFullYear,
                             a.born_year, a.zero_age, true);
    const plan = a.spending.current_2025 * mult;
    const am = aMax(a.balance, yld, sched, a.start_year, a.born_year, a.zero_age);
    const run = ladder(a.balance, plan, yld, 0, sched, a.start_year, a.born_year, a.zero_age);
    $("w-amax-y").textContent = fmtUsd(am);
    $("w-amax-m").textContent = fmtUsd(am / 12);
    $("w-min").textContent = run.minBalance === null ? "broke " + run.brokeAt : fmtUsd(run.minBalance);
    $("w-end").textContent = run.endBalance === null ? "broke " + run.brokeAt : fmtUsd(run.endBalance);
  },

  _bind(a) {
    const claimSel = $("s-claim");
    claimSel.innerHTML = "";
    Object.keys(a.ss_by_age).map(Number).sort((x, y) => x - y).forEach(age => {
      const opt = document.createElement("option");
      opt.value = String(age);
      opt.textContent = "Age " + age + " (" + fmtUsd(a.ss_by_age[age] * 12, 0) + "/yr)";
      if (age === 67) opt.selected = true;
      claimSel.appendChild(opt);
    });
    $("o-yield").value = String(a.yield_long_term);
    $("s-yield").value = String(a.yield_long_term * 100);
    $("o-rate").value = Math.round(a.go_broke_rate * 100) + "%";
    $("s-rate").value = String(Math.round(a.go_broke_rate * 100));
    $("o-mult").value = fmtNum(a.spending.multiplier) + "×";
    $("s-mult").value = String(Math.round(a.spending.multiplier * 100));

    const onInput = (id) => {
      $(id).addEventListener("input", () => {
        const v = Number($(id).value);
        $("o-" + id.slice(2)).value =
          id === "s-yield" ? fmtNum(v, 2) + "%" :
          id === "s-rate" ? v + "%" : fmtNum(v / 100) + "×";
        this._renderWidget(a);
      });
    };
    ["s-yield", "s-rate", "s-mult"].forEach(onInput);
    claimSel.addEventListener("change", () => this._renderWidget(a));
  },
});
