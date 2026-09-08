/* Bag End financial page — shared core JS (framework, 2026-09-08).
   Data comes ONLY from a connected finpage.json (built by
   `bagend.py export finpage`). No financial values live in this file. */
"use strict";

/* ---------- formatting ---------- */

const fmtUsd = (v, digits = 0) =>
  v === null || v === undefined || !isFinite(v)
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
        maximumFractionDigits: digits }).format(v);
const fmtNum = (v, digits = 2) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(v);

/* ---------- model (mirrors tools/bagend/finpage.py; parity-tested) ---------- */

function ladder(balance, spend0, yield_, escalate, ssSchedule, startYear, born, zeroAge) {
  let bal = balance, s = spend0, minBal = Infinity, brokeAt = null;
  for (let y = startYear; y <= born + zeroAge; y++) {
    bal = (bal - s + (ssSchedule[y] || 0)) * (1 + yield_);
    if (bal < 0) { brokeAt = y; break; }
    minBal = Math.min(minBal, bal);
    s *= (1 + escalate);
  }
  return { minBalance: brokeAt === null ? minBal : null,
           brokeAt, endBalance: brokeAt === null ? bal : null };
}

function ssSchedule(monthly, rate, goBrokeYear, firstFullYear, born, zeroAge, stepChange) {
  const out = {};
  if (stepChange) {
    for (let y = firstFullYear; y < goBrokeYear; y++) out[y] = monthly * 12;
  }
  const start = stepChange ? goBrokeYear : firstFullYear;
  for (let y = start; y <= born + zeroAge; y++) out[y] = monthly * rate * 12;
  return out;
}

function aMax(balance, yield_, ssSched, startYear, born, zeroAge) {
  let lo = 0, hi = balance * 1.5;
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2;
    const r = ladder(balance, mid, yield_, 0, ssSched, startYear, born, zeroAge);
    if (r.brokeAt !== null || (r.endBalance || 0) < 0) hi = mid; else lo = mid;
  }
  return (lo + hi) / 2;
}

/* ---------- dom helpers (tolerate missing elements for node smoke tests) ---------- */

const $ = (id) => (typeof document !== "undefined" ? document.getElementById(id) : null);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function setStatus(msg, ok) {
  const s = $("status");
  if (!s) return;
  s.textContent = msg;
  s.classList.toggle("ok", !!ok);
}

/* ---------- connect flow (Homepage-DB pattern) ---------- */

function saveHandle(h) {
  try {
    const req = indexedDB.open("bagend-finpage", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("kv");
    req.onsuccess = () => {
      const tx = req.result.transaction("kv", "readwrite");
      tx.objectStore("kv").put(h, "handle");
      tx.objectStore("kv").put(h.name || "finpage.json", "name");
      // ask for durable permission so later loads re-grant silently
      if (h.queryPermission) h.queryPermission({ mode: "read" }).then(p => {
        if (p !== "granted" && h.requestPermission) h.requestPermission({ mode: "read" });
      });
    };
  } catch (_) { /* best-effort */ }
}

async function storedHandle() {
  const db = await new Promise((res, rej) => {
    const req = indexedDB.open("bagend-finpage", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("kv");
    req.onsuccess = () => res(req.result);
    req.onerror = () => rej(req.error);
  });
  const got = (k) => new Promise((res) => {
    const tx = db.transaction("kv", "readonly");
    const g = tx.objectStore("kv").get(k);
    g.onsuccess = () => res(g.result);
    g.onerror = () => res(undefined);
  });
  const h = await got("handle");
  const name = await got("name");
  if (!h || !h.getFile) return null;
  return { h, name };
}

async function tryRestore() {
  if (!window.showOpenFilePicker) return; // file:// without FSA: manual only
  try {
    const saved = await storedHandle();
    if (!saved) return;
    let perm = await saved.h.queryPermission({ mode: "read" });
    if (perm !== "granted") {
      try { perm = await saved.h.requestPermission({ mode: "read" }); } catch (_) { perm = "denied"; }
    }
    if (perm === "granted") {
      const file = await saved.h.getFile();
      applyPayload(JSON.parse(await file.text()), saved.h.name);
      return;
    }
    setStatus("Saved connection (" + (saved.name || "finpage.json") + ") needs a permission refresh", false);
    openPicker(); // self-heal: one picker, no dir walk (browser reopens last folder)
  } catch (_) {
    setStatus("Saved connection unavailable — reconnect", false);
    openPicker();
  }
}

async function openPicker() {
  try {
    if (window.showOpenFilePicker) {
      const [handle] = await window.showOpenFilePicker({
        types: [{ description: "JSON", accept: { "application/json": [".json"] } }],
        startIn: "documents",
      });
      saveHandle(handle);
      const file = await handle.getFile();
      applyPayload(JSON.parse(await file.text()), handle.name);
      return;
    }
  } catch (err) {
    if (err && err.name === "AbortError") return;
  }
  $("fileInput").click();
}

function connectPicker() { openPicker(); }

function applyPayload(data, label) {
  if (!data || data.meta?.page_protocol !== 2) throw new Error("Not a Bag End finpage.json (protocol 2)");
  FinPages.payload = data;
  FinPages.label = label;
  setStatus("Connected: " + label + " — " + FinPages.activeTitle() +
            (data.meta?.generated_at ? " · generated " + data.meta.generated_at.slice(0, 10) : ""), true);
  $("main").hidden = false;
  FinPages.renderActive();
}

function bindConnect() {
  const btn = $("btnConnect");
  if (btn) btn.addEventListener("click", connectPicker);
  const fi = $("fileInput");
  if (fi) fi.addEventListener("change", (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    const rd = new FileReader();
    rd.onload = () => {
      try { applyPayload(JSON.parse(rd.result), file.name); }
      catch (e) { setStatus("Load failed: " + e.message, false); }
    };
    rd.readAsText(file);
  });
}

/* ---------- page registry + router ---------- */

const FinPages = {
  registry: [],
  payload: null,
  label: null,
  register(page) {
    this.registry.push(page);
    this.registry.sort((a, b) => (a.order || 0) - (b.order || 0));
  },
  activeId() {
    const h = (window.location.hash || "").replace(/^#/, "");
    return this.registry.some(p => p.id === h) ? h : this.registry[0].id;
  },
  activeTitle() {
    const p = this.registry.find(p => p.id === this.activeId());
    return p ? p.title : "";
  },
  renderActive() {
    for (const p of this.registry) {
      const root = $("page-" + p.id);
      if (!root) continue;
      root.hidden = p.id !== this.activeId();
      if (p.id === this.activeId()) p.render(root, this.payload);
    }
    for (const tab of document.querySelectorAll(".nav a")) {
      tab.classList.toggle("active", (tab.getAttribute("href") || "") === "#" + this.activeId());
    }
    if (!this.payload) $("main").hidden = true;
  },
};

function boot() {
  if (typeof document === "undefined") return;
  const nav = $("nav");
  const main = $("main");
  for (const p of FinPages.registry) {
    const a = el("a");
    a.href = "#" + p.id;
    a.textContent = p.title;
    nav.appendChild(a);
    const container = el("div", "page");
    container.id = "page-" + p.id;
    container.hidden = true;
    main.appendChild(container);
  }
  window.addEventListener("hashchange", () => FinPages.renderActive());
  bindConnect();
  FinPages.renderActive();
  tryRestore();
}
