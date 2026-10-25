// @ts-check
/** The audit tab: who changed what, when, and what came of it.
 *
 * Spec §10.1 asks for operator, version, field diff, result and duration on
 * every write, and §A.0 asks for the secret-free promise: the detail column
 * holds field names and counts, never a value — `store.record_audit` is written
 * that way, and the console does not pretend otherwise by pretty-printing a
 * payload it never received.
 */

import { api } from "./api.js";
import { badge, fmtDuration, fmtTime, html, render } from "./html.js";

/** Result strings the platform writes; anything else is shown as-is. */
const RESULT_BADGE = { ok: "live", partial: "rolled_back", failed: "failed" };

/**
 * @param {{toast: (message: string, kind?: string) => void}} deps
 */
export function createAuditView({ toast }) {
  const wrap = /** @type {HTMLElement} */ (document.getElementById("audit-table"));
  const refreshBtn = /** @type {HTMLButtonElement} */ (document.getElementById("audit-refresh"));

  let profile = "";

  /** @param {Record<string, unknown>} detail */
  function detailCell(detail) {
    const keys = Object.keys(detail || {});
    if (!keys.length) return html`—`;
    const text = JSON.stringify(detail, null, 0);
    return html`<details>
      <summary>${keys.length} 项</summary>
      <code>${text}</code>
    </details>`;
  }

  /** @param {any[]} entries */
  function draw(entries) {
    if (!entries.length) {
      render(wrap, html`<p class="empty">还没有写操作。保存草稿之后这里会出现第一条。</p>`);
      return;
    }
    render(
      wrap,
      html`<table>
        <thead>
          <tr>
            <th>时间</th><th>动作</th><th>操作人</th><th>版本</th>
            <th>结果</th><th>耗时</th><th>详情</th>
          </tr>
        </thead>
        <tbody>
          ${entries.map(
            (entry) => html`<tr>
              <td class="mono">${fmtTime(entry.created_at)}</td>
              <td class="mono">${entry.action}</td>
              <td class="mono">${entry.actor || "—"}</td>
              <td class="mono">${entry.version ? `v${entry.version}` : "—"}</td>
              <td>${badge(entry.result || "—", RESULT_BADGE[entry.result] ?? "")}</td>
              <td class="mono">${fmtDuration((entry.duration_ms || 0) / 1000)}</td>
              <td>${detailCell(entry.detail)}</td>
            </tr>`,
          )}
        </tbody>
      </table>`,
    );
  }

  async function load(name) {
    profile = name;
    try {
      const answer = await api.audit(name);
      draw(answer.entries || []);
    } catch (error) {
      render(wrap, html`<p class="empty">${error.summary}</p>`);
      toast(error.summary, "bad");
    }
  }

  refreshBtn.addEventListener("click", () => load(profile));

  return { load };
}
