import { LitElement, css, html } from "https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm";

/**
 * Lit web component, loaded straight from a CDN - no build step, no npm.
 *
 * The one design decision that matters: pass, fail and *unmeasured* are three
 * visually distinct states. Collapsing "we did not check" into either of the
 * other two is exactly the failure the audit itself exists to prevent, and a
 * UI that drew it as a green tick would undo the whole argument.
 */
class AuditView extends LitElement {
  static properties = {
    data: { state: true },
    error: { state: true },
    busy: { state: true },
    expanded: { state: true },
  };

  static styles = css`
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
    .pill.inconclusive, .pill\\.na { background:transparent; color:var(--unknown);
      border:1px dashed var(--line) }
    .pill.na { background:transparent; color:var(--unknown); border:1px dashed var(--line) }
    .repo { cursor:pointer }
    .repo:hover { background:color-mix(in srgb,var(--accent) 6%,transparent) }
    .detail { font-family:var(--mono); font-size:.78rem; color:var(--muted) }
    .err { border:1px solid var(--fail); border-radius:8px; padding:.8rem; color:var(--fail) }
    .note { color:var(--muted); font-size:.82rem; margin-top:.6rem }
  `;

  constructor() {
    super();
    this.data = null;
    this.error = "";
    this.busy = false;
    this.expanded = null;
    this.path = "C:\\src";
  }

  async run() {
    this.busy = true;
    this.error = "";
    this.data = null;
    try {
      const response = await fetch(`/api/audit?path=${encodeURIComponent(this.path)}`);
      const payload = await response.json();
      if (payload.error) this.error = payload.error;
      else this.data = payload;
    } catch (err) {
      this.error = String(err);
    } finally {
      this.busy = false;
    }
  }

  pill(status) {
    const cls = status === "n/a" ? "na" : status;
    return html`<span class="pill ${cls}">${status}</span>`;
  }

  renderControls() {
    const entries = Object.entries(this.data.by_control).sort(
      (a, b) => a[1].passed / a[1].of - b[1].passed / b[1].of
    );
    return html`
      <h2>By control</h2>
      <table>
        <thead><tr><th>Control</th><th class="num">Passed</th><th>Rate</th></tr></thead>
        <tbody>
          ${entries.map(([id, v]) => {
            const rate = v.passed / v.of;
            return html`<tr>
              <td>
                <div>${id}</div>
                <div class="policy">${this.data.policies?.[id] ?? ""}</div>
              </td>
              <td class="num">${v.passed}/${v.of}</td>
              <td>
                <div>${Math.round(rate * 100)}%</div>
                <div class="bar"><i style="width:${rate * 100}%"></i></div>
              </td>
            </tr>`;
          })}
        </tbody>
      </table>
    `;
  }

  renderRepos() {
    const repos = [...this.data.repos].sort((a, b) => a.rate - b.rate);
    return html`
      <h2>Repositories</h2>
      <table>
        <thead><tr><th>Repository</th><th class="num">Rate</th><th>Failures</th></tr></thead>
        <tbody>
          ${repos.map(
            (repo) => html`
              <tr class="repo" @click=${() =>
                (this.expanded = this.expanded === repo.name ? null : repo.name)}>
                <td>${repo.name}</td>
                <td class="num">${Math.round(repo.rate * 100)}%</td>
                <td>${repo.results.filter((r) => r.status === "fail").map((r) => r.control).join(", ") || "-"}</td>
              </tr>
              ${this.expanded === repo.name
                ? html`<tr><td colspan="3">
                    <table>
                      <tbody>
                        ${repo.results.map(
                          (r) => html`<tr>
                            <td>${this.pill(r.status)}</td>
                            <td>${r.control}</td>
                            <td class="detail">${r.detail}${r.artefact ? ` (${r.artefact})` : ""}</td>
                          </tr>`
                        )}
                      </tbody>
                    </table>
                  </td></tr>`
                : ""}
            `
          )}
        </tbody>
      </table>
    `;
  }

  render() {
    return html`
      <div class="row">
        <input
          .value=${this.path}
          @input=${(e) => (this.path = e.target.value)}
          placeholder="folder of repositories"
        />
        <button @click=${this.run} ?disabled=${this.busy}>
          ${this.busy ? "Auditing..." : "Audit"}
        </button>
      </div>

      ${this.error ? html`<div class="err">${this.error}</div>` : ""}

      ${this.data
        ? html`
            <div class="stats">
              <div class="stat">
                <div class="v">${this.data.repositories}</div>
                <div class="k">repositories</div>
              </div>
              <div class="stat">
                <div class="v">${Math.round(this.data.rate * 100)}%</div>
                <div class="k">controls passed</div>
              </div>
              <div class="stat">
                <div class="v">${this.data.controls_passed}/${this.data.controls_counted}</div>
                <div class="k">pass / measured</div>
              </div>
              <div class="stat">
                <div class="v">${this.data.unmeasured ?? 0}</div>
                <div class="k">unmeasured, excluded</div>
              </div>
            </div>
            <p class="note">
              Unmeasured controls are excluded from the rate. Counting them as passes is how
              an audit reports a high number having checked a fraction of what it claimed.
            </p>
            ${this.renderControls()} ${this.renderRepos()}
          `
        : ""}
    `;
  }
}

customElements.define("audit-view", AuditView);
