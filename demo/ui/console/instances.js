// @ts-check
/** The instances tab: A.7, "what is actually running".
 *
 * Every number here comes from the deployment itself — `compose ps` for the
 * container and `/v1/pool` for the units — never from the store, because the
 * store only knows what someone asked for. That is why a degraded read is still
 * rendered: "the container is exited" and "the pool does not answer" are the two
 * facts an operator most needs, and turning them into an error page hides them.
 */

import { api } from "./api.js";
import { badge, fmtDuration, fmtTime, html, render } from "./html.js";

/** Unit states `/v1/pool` can report (websocket_router._pool_snapshot). */
const UNIT_BADGE = { idle: "", active: "live", draining: "advanced", stuck: "failed" };

/**
 * `compose ps` reports nanoseconds in `StartedAt`; `Date.parse` takes at most
 * three fractional digits, so the rest is dropped before parsing.
 * @param {unknown} value
 * @returns {string}
 */
function startedAt(value) {
  if (!value) return "—";
  const epoch = Date.parse(String(value).replace(/\.\d+/, ""));
  return Number.isNaN(epoch) ? String(value) : fmtTime(epoch / 1000);
}

/**
 * @param {{toast: (message: string, kind?: string) => void}} deps
 */
export function createInstancesView({ toast }) {
  const body = /** @type {HTMLElement} */ (document.getElementById("instances-body"));
  const refreshBtn = /** @type {HTMLButtonElement} */ (
    document.getElementById("instances-refresh")
  );

  let profile = "";

  /** @param {any} unit */
  function unitRow(unit) {
    const state = String(unit.state || "unknown");
    return html`<tr>
      <td class="mono">${unit.index ?? "—"}</td>
      <td>${badge(state, UNIT_BADGE[state] ?? "")}</td>
      <td class="mono">${unit.session_id || "—"}</td>
      <td class="mono">${unit.draining_for_s ? fmtDuration(unit.draining_for_s) : "—"}</td>
      <td class="mono">${unit.stuck_for_s ? fmtDuration(unit.stuck_for_s) : "—"}</td>
    </tr>`;
  }

  /** @param {{label: string, value: unknown, dim?: boolean}} stat */
  const stat = ({ label, value, dim }) =>
    html`<div class="stat">
      <div class="stat-label">${label}</div>
      <div class="stat-value ${dim ? "dim" : ""}">${value ?? "—"}</div>
    </div>`;

  /** @param {any} data */
  function draw(data) {
    const container = data.container || {};
    const pool = data.pool || {};
    const units = pool.units || [];
    const alerts = data.alerts || [];

    render(
      body,
      html`${alerts.length
          ? html`<ul class="alert-list">${alerts.map((alert) => html`<li>${alert}</li>`)}</ul>`
          : ""}
        <div class="instance-grid">
          ${stat({ label: "版本", value: data.version ? `v${data.version}` : "未发布" })}
          ${stat({ label: "容器", value: container.name || "未知", dim: true })}
          ${stat({ label: "状态", value: badge(container.status || "unknown", container.status === "running" ? "live" : "failed") })}
          ${stat({ label: "启动时间", value: startedAt(container.started_at), dim: true })}
          ${stat({ label: "镜像", value: container.image || "—", dim: true })}
          ${stat({ label: "pool size", value: pool.reachable ? pool.size : "不可达" })}
          ${stat({ label: "in_use", value: pool.reachable ? pool.in_use : "—" })}
        </div>
        ${container.error ? html`<p class="hint">容器查询失败：${container.error}</p>` : ""}
        ${pool.reachable
          ? html`<div class="table-wrap">
              <table>
                <thead>
                  <tr><th>unit</th><th>状态</th><th>session</th><th>释放中</th><th>卡住</th></tr>
                </thead>
                <tbody>${units.map(unitRow)}</tbody>
              </table>
            </div>`
          : html`<p class="hint">
              读不到 /v1/pool：容器在但服务没起来时就是这样。新发布不应该以这个状态收尾。
            </p>`}`,
    );
  }

  async function load(name) {
    profile = name;
    try {
      draw(await api.instances(name));
    } catch (error) {
      render(body, html`<p class="empty">${error.summary}</p>`);
      toast(error.summary, "bad");
    }
  }

  refreshBtn.addEventListener("click", () => load(profile));

  return { load };
}
