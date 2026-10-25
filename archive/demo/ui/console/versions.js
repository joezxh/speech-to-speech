// @ts-check
/** The versions tab: what ran when, and how to put an older one back.
 *
 * A.5 says a rollback *creates a new version* whose content equals the target,
 * so this table is append-only and "回滚到 v7" produces v9. The button is shown
 * only on versions the server will accept as a target (`store.ROLLBACKABLE`),
 * which is also why a version that never reached `live` has none: there is
 * nothing in it that ever worked to go back to.
 */

import { api } from "./api.js";
import { badge, fmtBytes, fmtTime, html, render } from "./html.js";

/** Mirror of `store.ROLLBACKABLE`; the server is still the one that decides. */
const ROLLBACKABLE = new Set(["live", "rolled_back"]);

/**
 * @param {{toast: (message: string, kind?: string) => void, onChanged?: () => void}} deps
 */
export function createVersionsView({ toast, onChanged }) {
  const wrap = /** @type {HTMLElement} */ (document.getElementById("versions-table"));
  const refreshBtn = /** @type {HTMLButtonElement} */ (
    document.getElementById("versions-refresh")
  );

  let profile = "";
  /** @type {{versions: any[], live_version: number}} */
  let state = { versions: [], live_version: 0 };
  let busy = false;

  function rows() {
    if (!state.versions.length) {
      return html`<p class="empty">这个 profile 还没有版本。第一次发布之后，这里会出现 v1。</p>`;
    }
    const body = state.versions.map((version) => {
      const isLive = version.version === state.live_version;
      const canRollback = ROLLBACKABLE.has(version.status) && !isLive;
      return html`<tr>
        <td class="mono">v${version.version}${isLive ? badge("当前", "live") : ""}</td>
        <td>${badge(version.status, version.status)}</td>
        <td class="mono">${fmtTime(version.created_at)}</td>
        <td class="mono">${version.actor || "—"}</td>
        <td>${version.note || (version.rolled_back_to ? `回滚到 v${version.rolled_back_to}` : "—")}</td>
        <td class="mono">${version.base_version ? `v${version.base_version}` : "—"}</td>
        <td class="mono">${fmtBytes(version.rendered_bytes)}</td>
        <td>
          ${canRollback
            ? html`<button class="btn ghost" type="button" data-rollback="${version.version}">回滚到此版本</button>`
            : ""}
        </td>
      </tr>
      ${version.error
        ? html`<tr><td colspan="8" class="hint">错误：${version.error}</td></tr>`
        : ""}`;
    });
    return html`<table>
      <thead>
        <tr>
          <th>版本</th><th>状态</th><th>时间</th><th>操作人</th>
          <th>说明</th><th>基于</th><th>体积</th><th></th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>`;
  }

  function draw() {
    render(wrap, rows());
  }

  /** @param {number} target */
  async function rollback(target) {
    if (busy) return;
    const note = `控制台回滚到 v${target}`;
    // A rollback restarts the deployment, so the question is not rhetorical.
    if (!window.confirm(`把 ${profile} 回滚到 v${target}？\n\n会重建容器，正在通话的用户会掉线。`)) {
      return;
    }
    busy = true;
    try {
      const result = await api.rollback(profile, target, note);
      const health = result.healthcheck || {};
      toast(
        result.status === "live"
          ? `已生成 v${result.version}，内容来自 v${target}；pool ${health.pool_size ?? "?"}`
          : `v${result.version} 探活失败，已回滚`,
        result.status === "live" ? "ok" : "bad",
      );
      if (onChanged) onChanged();
      await load(profile);
    } catch (error) {
      toast(error.summary, "bad");
      await load(profile);
    } finally {
      busy = false;
    }
  }

  async function load(name) {
    profile = name;
    try {
      state = await api.versions(name);
      draw();
    } catch (error) {
      // A version list that cannot be read is worth showing as a row of text
      // rather than an empty table that looks like "no versions yet".
      render(wrap, html`<p class="empty">${error.summary}</p>`);
    }
  }

  wrap.addEventListener("click", (event) => {
    const button = /** @type {HTMLElement} */ (event.target).closest("button[data-rollback]");
    if (!button) return;
    const target = Number(/** @type {HTMLButtonElement} */ (button).dataset.rollback);
    if (Number.isInteger(target)) rollback(target);
  });

  refreshBtn.addEventListener("click", () => load(profile));

  return { load };
}
