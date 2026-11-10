// @ts-check
/** The sessions tab: chain B of spec §5, the change that skips a restart.
 *
 * Four fields go hot (§2.2) and nothing else does, so this form can only build
 * those four; `model` and `voice` have no control here because asking for them
 * would be asking for a restart with extra steps. Everything unfilled is left
 * out of the payload rather than sent as a default — the server merges only the
 * fields it is given, so "not sent" and "sent null" mean different things.
 */

import { api } from "./api.js";
import { html, render } from "./html.js";

/** What `target` means for each scope; §5.3 gives the three shapes. */
const TARGET_LABEL = { pipeline: "pipeline 序号", session: "session id" };

/** Server codes that have a better sentence than the one in the error body. */
const HINTS = {
  not_implemented:
    "这个 pipeline 镜像还没有 /admin/sessions/update；请走「参数 → 发布」（重启链路）",
  hot_update_disabled: "pipeline 服务没有配置 S2S_ADMIN_TOKEN，热更新被关闭",
  pool_unreachable: "连不上 pipeline 服务；容器可能还没起来，看「实例」页",
  invalid_session_type: "目标是一条 transcription 会话，热更新只对 realtime 会话生效",
  hot_update_unauthorized: "pipeline 服务不认这个 S2S_ADMIN_TOKEN，检查两侧是否同一个值",
};

/**
 * @param {{toast: (message: string, kind?: string) => void}} deps
 */
export function createSessionsView({ toast }) {
  const scope = /** @type {HTMLSelectElement} */ (document.getElementById("hot-scope"));
  const targetField = /** @type {HTMLElement} */ (document.getElementById("hot-target-field"));
  const targetLabel = /** @type {HTMLElement} */ (document.getElementById("hot-target-label"));
  const target = /** @type {HTMLInputElement} */ (document.getElementById("hot-target"));
  const instructions = /** @type {HTMLTextAreaElement} */ (
    document.getElementById("hot-instructions")
  );
  const language = /** @type {HTMLInputElement} */ (document.getElementById("hot-language"));
  const interrupt = /** @type {HTMLSelectElement} */ (document.getElementById("hot-interrupt"));
  const extensions = /** @type {HTMLTextAreaElement} */ (
    document.getElementById("hot-extensions")
  );
  const applyBtn = /** @type {HTMLButtonElement} */ (document.getElementById("hot-apply"));
  const result = /** @type {HTMLElement} */ (document.getElementById("hot-result"));

  let profile = "";

  function syncScope() {
    const needsTarget = scope.value !== "all";
    targetField.hidden = !needsTarget;
    targetLabel.textContent = TARGET_LABEL[scope.value] || "target";
    target.placeholder = scope.value === "pipeline" ? "如 0" : "如 sess_8f2c…";
    target.inputMode = scope.value === "pipeline" ? "numeric" : "text";
  }

  /** The `session` object to send, or null when the form cannot be read. */
  function collect() {
    /** @type {Record<string, unknown>} */
    const session = {};

    const text = instructions.value.trim();
    if (text) session.instructions = text;

    const languageValue = language.value.trim();
    const interruptValue = interrupt.value;
    if (languageValue || interruptValue) {
      /** @type {{transcription?: {language: string}, turn_detection?: {interrupt_response: boolean}}} */
      const input = {};
      if (languageValue) input.transcription = { language: languageValue };
      // `""` is "leave it alone"; the server merges only what it is given.
      if (interruptValue) input.turn_detection = { interrupt_response: interruptValue === "true" };
      session.audio = { input };
    }

    const raw = extensions.value.trim();
    if (raw) {
      try {
        session.extensions = JSON.parse(raw);
      } catch {
        toast("extensions 不是合法 JSON，没有发送", "bad");
        return null;
      }
    }
    return session;
  }

  /** The whole request, or a reason it cannot be built. */
  function request() {
    const session = collect();
    if (!session) return null;
    if (!Object.keys(session).length) {
      toast("至少填一项再应用，空请求会改掉所有连接的空字段", "bad");
      return null;
    }
    /** @type {{scope: string, target?: unknown, session: Record<string, unknown>}} */
    const payload = { scope: scope.value, session };
    if (scope.value === "pipeline") {
      const index = Number(target.value.trim());
      if (!Number.isInteger(index) || index < 0) {
        toast("pipeline 序号必须是非负整数", "bad");
        return null;
      }
      payload.target = index;
    } else if (scope.value === "session") {
      const id = target.value.trim();
      if (!id) {
        toast("scope=session 需要填一个 session id", "bad");
        return null;
      }
      payload.target = id;
    }
    return payload;
  }

  /** @param {any} answer */
  function showAnswer(answer) {
    const updated = answer.updated || [];
    const failed = answer.failed || [];
    result.hidden = false;
    result.className = `result ${failed.length ? "bad" : ""}`;
    render(
      result,
      html`<div>
          <strong>${updated.length}</strong> 条连接已更新${failed.length
            ? html`，<strong>${failed.length}</strong> 条失败`
            : ""}
          <span class="hint">（scope=${answer.scope}${answer.audit_id ? ` · 审计 #${answer.audit_id}` : ""}）</span>
        </div>
        ${updated.length
          ? html`<p class="hint">${updated.join("、")}</p>`
          : html`<p class="hint">没有活跃连接可改；空闲 unit 要等有人连上，或者直接走发布。</p>`}
        ${failed.length
          ? html`<ul>
              ${failed.map(
                (item) => html`<li><code>${item.session_id || "?"}</code>：${item.error || "未知错误"}</li>`,
              )}
            </ul>
            <p class="hint">部分失败不回滚：成功的连接已经改了。修好原因后重试即可（覆盖写是幂等的）。</p>`
          : ""}`,
    );
  }

  async function apply() {
    const payload = request();
    if (!payload) return;
    applyBtn.disabled = true;
    applyBtn.textContent = "应用中…";
    try {
      const answer = await api.hotUpdate(profile, payload);
      showAnswer(answer);
      const failed = (answer.failed || []).length;
      toast(failed ? `已更新 ${answer.updated.length} 条，失败 ${failed} 条` : `已更新 ${answer.updated.length} 条连接`, failed ? "bad" : "ok");
    } catch (error) {
      result.hidden = false;
      result.className = "result bad";
      const hint = HINTS[error.code];
      render(
        result,
        html`<div>${hint || error.summary}</div>
          ${hint ? html`<p class="hint">${error.code}：${error.message}</p>` : ""}
          ${(error.details || []).map(
            (detail) => html`<p class="hint"><code>${detail.field || detail.session_id || "?"}</code> ${detail.error || ""}</p>`,
          )}`,
      );
      toast(error.summary, "bad");
    } finally {
      applyBtn.disabled = false;
      applyBtn.textContent = "应用";
    }
  }

  scope.addEventListener("change", syncScope);
  applyBtn.addEventListener("click", apply);
  syncScope();

  return {
    /** Chain B keeps no state server-side, so switching profile only re-points it. */
    async load(name) {
      profile = name;
      result.hidden = true;
    },
  };
}
