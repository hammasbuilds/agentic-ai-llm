/**
 * The audit view, as a plain custom element.
 *
 * This was a Lit component importing `lit@3.2.1` from `cdn.jsdelivr.net`, which made the
 * one page of a project whose badge reads `runtime deps 0` and whose README says
 * "Installed: nothing" depend on a third-party framework and a working internet
 * connection. The repository's own `_ui_kinds()` classifier looked for a `package.json`
 * or a Python framework import and found neither, so this UI was listed as needing
 * nothing at all.
 *
 * Nothing here needs a framework: one element, four pieces of state, two tables.
 *
 * The one design decision that matters is unchanged: pass, fail and *unmeasured* are
 * three visually distinct states. Collapsing "we did not check" into either of the other
 * two is exactly the failure the audit exists to prevent, and a UI that drew it as a
 * green tick would undo the whole argument.
 */

/** Escape text for HTML. Lit did this on every interpolation; a template string does not,
 *  and the values here are repository names, control ids and collector details read off
 *  disk - someone else's file names ending up in this page's markup. */
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

const pct = (n) => Math.round(n * 100);

const STYLES = `
  :host { display: block; }
  .row { display:flex; gap:.75rem; align-items:center; margin-bottom:1.25rem; flex-wrap:wrap }
  input, button { font:inherit; padding:.45rem .7rem; border-radius:8px;
    border:1px solid var(--line); background:var(--panel); color:var(--ink) }
  input { flex:1; min-width:16rem }
  button { background:var(--accent); color:#fff; border-color:transparent; cursor:pointer }
  button:disabled { opacity:.5; cursor:default }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
    gap:.7rem; margin-bottom:1.5rem }
  .stat { border:1px solid var(--line); border-radius:10px; padding:.85rem;
    background:var(--panel) }
  .stat .v { font-size:1.5rem; font-weight:650 }
  .stat .k { font-size:.74rem; color:var(--muted) }
  h2 { font-size:.78rem; text-transform:uppercase; letter-spacing:.08em;
    color:var(--muted); margin:2rem 0 .7rem }
  table { width:100%; border-collapse:collapse; background:var(--panel);
    border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:.86rem }
  th,td { text-align:left; padding:.5rem .75rem; border-bottom:1px solid var(--line);
    vertical-align:top }
  th { font-size:.7rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted) }
  tr:last-child td { border-bottom:none }
  td.num { text-align:right; font-variant-numeric:tabular-nums }
  .bar { height:5px; background:var(--line); border-radius:3px; overflow:hidden; min-width:70px }
  .bar > i { display:block; height:100%; background:var(--accent) }
  .policy { color:var(--muted); font-size:.82rem }
  .pill { display:inline-block; padding:.08rem .45rem; border-radius:999px;
    font-size:.67rem; font-weight:650; text-transform:uppercase }
  .pill.pass { background:color-mix(in srgb,var(--pass) 18%,transparent); color:var(--pass) }
  .pill.fail { background:color-mix(in srgb,var(--fail) 18%,transparent); color:var(--fail) }
  /* Unmeasured: no fill and a dashed edge, so it cannot be mistaken for either outcome
     at a glance. The old stylesheet carried an escaped duplicate of this rule
     (\\.pill\\\\.na) that matched nothing; one rule, written once. */
  .pill.inconclusive, .pill.na { background:transparent; color:var(--unknown);
    border:1px dashed var(--line) }
  .repo { cursor:pointer }
  .repo:hover { background:color-mix(in srgb,var(--accent) 6%,transparent) }
  .detail { font-family:var(--mono); font-size:.78rem; color:var(--muted) }
  .err { border:1px solid var(--fail); border-radius:8px; padding:.8rem; color:var(--fail) }
  .note { color:var(--muted); font-size:.82rem; margin-top:.6rem }
`;

class AuditView extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.data = null;
    this.error = "";
    this.busy = false;
    this.expanded = null;
    this.path = "C:\\src";
  }

  connectedCallback() {
    this.render();
  }

  async run() {
    this.busy = true;
    this.error = "";
    this.data = null;
    this.render();
    try {
      const response = await fetch(`/api/audit?path=${encodeURIComponent(this.path)}`);
      const payload = await response.json();
      if (payload.error) this.error = payload.error;
      else this.data = payload;
    } catch (err) {
      this.error = String(err);
    } finally {
      this.busy = false;
      this.render();
    }
  }

  pill(status) {
    const cls = status === "n/a" ? "na" : esc(status);
    return `<span class="pill ${cls}">${esc(status)}</span>`;
  }

  controlsTable() {
    const entries = Object.entries(this.data.by_control).sort(
      (a, b) => a[1].passed / a[1].of - b[1].passed / b[1].of
    );
    const rows = entries
      .map(([id, v]) => {
        const rate = v.passed / v.of;
        return `<tr>
          <td>
            <div>${esc(id)}</div>
            <div class="policy">${esc(this.data.policies?.[id] ?? "")}</div>
          </td>
          <td class="num">${esc(v.passed)}/${esc(v.of)}</td>
          <td>
            <div>${pct(rate)}%</div>
            <div class="bar"><i style="width:${pct(rate)}%"></i></div>
          </td>
        </tr>`;
      })
      .join("");
    return `<h2>By control</h2>
      <table>
        <thead><tr><th>Control</th><th class="num">Passed</th><th>Rate</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  reposTable() {
    const repos = [...this.data.repos].sort((a, b) => a.rate - b.rate);
    const rows = repos
      .map((repo) => {
        const failures =
          repo.results
            .filter((r) => r.status === "fail")
            .map((r) => esc(r.control))
            .join(", ") || "-";
        // `data-repo` rather than an inline handler: the listener is attached once after
        // render, so there is no string of code in the markup to escape correctly.
        const head = `<tr class="repo" data-repo="${esc(repo.name)}">
            <td>${esc(repo.name)}</td>
            <td class="num">${pct(repo.rate)}%</td>
            <td>${failures}</td>
          </tr>`;
        if (this.expanded !== repo.name) return head;
        const detail = repo.results
          .map(
            (r) => `<tr>
              <td>${this.pill(r.status)}</td>
              <td>${esc(r.control)}</td>
              <td class="detail">${esc(r.detail)}${r.artefact ? ` (${esc(r.artefact)})` : ""}</td>
            </tr>`
          )
          .join("");
        return `${head}<tr><td colspan="3"><table><tbody>${detail}</tbody></table></td></tr>`;
      })
      .join("");
    return `<h2>Repositories</h2>
      <table>
        <thead><tr><th>Repository</th><th class="num">Rate</th><th>Failures</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  summary() {
    const d = this.data;
    return `<div class="stats">
        <div class="stat"><div class="v">${esc(d.repositories)}</div>
          <div class="k">repositories</div></div>
        <div class="stat"><div class="v">${pct(d.rate)}%</div>
          <div class="k">controls passed</div></div>
        <div class="stat"><div class="v">${esc(d.controls_passed)}/${esc(d.controls_counted)}</div>
          <div class="k">pass / measured</div></div>
        <div class="stat"><div class="v">${esc(d.unmeasured ?? 0)}</div>
          <div class="k">unmeasured, excluded</div></div>
      </div>
      <p class="note">
        Unmeasured controls are excluded from the rate. Counting them as passes is how an
        audit reports a high number having checked a fraction of what it claimed.
      </p>`;
  }

  render() {
    const body = this.data ? this.summary() + this.controlsTable() + this.reposTable() : "";
    this.shadowRoot.innerHTML = `<style>${STYLES}</style>
      <div class="row">
        <input id="path" value="${esc(this.path)}" placeholder="folder of repositories">
        <button id="go"${this.busy ? " disabled" : ""}>${this.busy ? "Auditing…" : "Audit"}</button>
      </div>
      ${this.error ? `<div class="err">${esc(this.error)}</div>` : ""}
      ${body}`;

    const input = this.shadowRoot.getElementById("path");
    // The value is read back on submit rather than re-rendering per keystroke. Lit kept
    // the caret across re-renders; replacing innerHTML does not, so a render on every
    // `input` event would move the cursor to the end of the box as you typed.
    input.addEventListener("input", (e) => { this.path = e.target.value; });
    this.shadowRoot.getElementById("go").addEventListener("click", () => this.run());

    for (const row of this.shadowRoot.querySelectorAll(".repo")) {
      row.addEventListener("click", () => {
        const name = row.dataset.repo;
        this.expanded = this.expanded === name ? null : name;
        this.render();
      });
    }
  }
}

customElements.define("audit-view", AuditView);
