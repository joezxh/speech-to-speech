// @ts-check
/** The console shell: profile picker, status pill, tabs, token dialog, toast.
 *
 * Each of the five tabs is its own module below this one
 * (`params.js`, `sessions.js`, `versions.js`, `instances.js`, `audit.js`) and
 * owns its DOM; this file only decides which one is visible, which profile they
 * read, and what a refusal looks like. `console.html` declares the markup, so
 * every id here has a matching element there — nothing is created at runtime.
 *
 * Two rules it keeps:
 *
 *   * A read failure is rendered where the data would have been, not only as a
 *     toast: a console whose versions tab is silently empty after a 401 looks
 *     like a deployment with no history. That rendering lives in each view.
 *   * Nothing is refreshed optimistically. Every write reloads the panel it
 *     touched, because publish and rollback both change more than the row the
 *     operator clicked.
 */

import { actor, api, ApiError, setToken, token, useTokenPrompt } from "./api.js";
import { html, render } from "./html.js";
import { createAuditView } from "./audit.js";
import { createInstancesView } from "./instances.js";
import { createParamsView } from "./params.js";
import { createSessionsView } from "./sessions.js";
import { createVersionsView } from "./versions.js";

const TOAST_MS = 3200;

/** @type {HTMLElement} */
const banner = /** @type {HTMLElement} */ (document.getElementById("banner"));
const statusPill = /** @type {HTMLElement} */ (document.getElementById("status-pill"));
const profileSelect = /** @type {HTMLSelectElement} */ (document.getElementById("profile"));
const toastBox = /** @type {HTMLElement} */ (document.getElementById("toast"));

const tokenDialog = /** @type {HTMLDialogElement} */ (document.getElementById("token-dialog"));
const tokenInput = /** @type {HTMLInputElement} */ (document.getElementById("token-input"));
const actorInput = /** @type {HTMLInputElement} */ (document.getElementById("actor-input"));

/** @type {string} */
let activeTab = "params";
let toastTimer = 0;

// ── toast and banner ─────────────────────────────────────────────────────────

/** @param {string} message @param {"ok"|"bad"|""} [kind] */
function toast(message, kind = "") {
  toastBox.hidden = false;
  toastBox.textContent = message;
  toastBox.className = `toast ${kind}`.trim();
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastBox.hidden = true;
  }, TOAST_MS);
}

/** One sentence for anything thrown by a view or `api.`
 * @param {unknown} error
 * @returns {string}
 */
function summaryOf(error) {
  return error instanceof ApiError ? error.summary : String(/** @type {any} */ (error)?.message || error);
}

/** @param {string[]} lines */
function showBanner(lines) {
  if (!lines.length) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  render(banner, html`${lines.map((line) => html`<div>${line}</div>`)}`);
}

/** @param {"ok"|"warn"|"bad"} kind @param {string} text */
function setPill(kind, text) {
  statusPill.className = `pill ${kind}`;
  statusPill.textContent = text;
}

// ── views ────────────────────────────────────────────────────────────────────

function currentProfile() {
  return profileSelect.value || "";
}

const sessionsView = createSessionsView({ toast });
const versionsView = createVersionsView({ toast });
const instancesView = createInstancesView({ toast });
const auditView = createAuditView({ toast });

const paramsView = createParamsView({
  toast,
  // A save moves `base_version` and a publish creates a version row, so the
  // panel the operator is *not* looking at is stale. Tabs reload on every
  // switch anyway, so only a visible one is worth a request here.
  onChange: () => {
    const profile = currentProfile();
    if (!profile) return;
    if (activeTab === "versions") versionsView.load(profile);
    if (activeTab === "audit") auditView.load(profile);
  },
});

/** @param {string} name */
async function refresh(name) {
  const profile = currentProfile();
  // Chain B (hot update) keeps no state server-side, so its form is usable
  // before a profile is picked — the request is what needs one.
  if (name === "sessions") return sessionsView.load(profile);
  if (!profile) return;
  if (name === "params") {
    try {
      await paramsView.load(profile);
    } catch (error) {
      toast(summaryOf(error), "bad");
    }
    return;
  }
  if (name === "versions") return versionsView.load(profile);
  if (name === "instances") return instancesView.load(profile);
  if (name === "audit") return auditView.load(profile);
}

/** @param {string} name */
function showTab(name) {
  activeTab = name;
  for (const tab of document.querySelectorAll(".tab[data-tab]")) {
    tab.setAttribute("aria-selected", String(/** @type {HTMLElement} */ (tab).dataset.tab === name));
  }
  for (const panel of document.querySelectorAll(".panel[data-panel]")) {
    /** @type {HTMLElement} */ (panel).hidden =
      /** @type {HTMLElement} */ (panel).dataset.panel !== name;
  }
  refresh(name);
}

for (const tab of document.querySelectorAll(".tab[data-tab]")) {
  tab.addEventListener("click", () => showTab(/** @type {HTMLElement} */ (tab).dataset.tab || "params"));
}

// ── token dialog ─────────────────────────────────────────────────────────────

// Persisted first, so `askForToken`'s own close listener already reads the new
// value when it resolves.
tokenDialog.addEventListener("close", () => {
  if (tokenDialog.returnValue !== "save") return;
  setToken(tokenInput.value.trim());
  actor.set(actorInput.value.trim());
});

/** Opens the dialog and resolves with the token to retry with, or "" to give up. */
function askForToken() {
  return new Promise((resolve) => {
    const done = () => {
      tokenDialog.removeEventListener("close", done);
      resolve(tokenDialog.returnValue === "save" ? token() : "");
    };
    tokenDialog.addEventListener("close", done);
    tokenInput.value = token();
    actorInput.value = actor.get();
    tokenDialog.showModal();
  });
}

// 401 on any endpoint reopens the dialog once and replays the request (api.js).
useTokenPrompt(askForToken);

document.getElementById("token-btn")?.addEventListener("click", () => {
  askForToken().then((entered) => {
    if (!entered) return;
    toast("令牌已更新", "ok");
    refresh(activeTab);
  });
});

// ── bootstrap ────────────────────────────────────────────────────────────────

/** The two facts the console needs before it can render anything (A.7 status). */
async function start() {
  /** @type {any} */
  let boot;
  try {
    boot = await api.status();
  } catch (error) {
    setPill("bad", "连不上");
    showBanner([
      `读不到 /admin/status：${summaryOf(error)}`,
      "服务没起，或者反向代理没有把 /admin 转过来。",
    ]);
    return;
  }

  setPill(boot.writes_enabled ? "ok" : "warn", boot.writes_enabled ? "可写" : "只读");

  const profiles = boot.profiles || [];
  render(
    profileSelect,
    html`${profiles.length
      ? profiles.map((name) => html`<option value="${name}">${name}</option>`)
      : html`<option value="">（无 profile）</option>`}`,
  );

  /** @type {string[]} */
  const lines = [];
  if (!profiles.length) {
    lines.push(`config_dir（${boot.config_dir}）下没有 <profile>.yaml，先建一个再回来。`);
  }
  if (!boot.catalog.available) {
    lines.push(`参数目录不可用：${boot.catalog.hint}`);
  }
  if (!boot.compose.available) {
    lines.push(`compose 不可用（${boot.compose.detail}）：参数目录仍可读，但发布会被拒绝。`);
  }
  if (!boot.writes_enabled) {
    lines.push("ADMIN_TOKEN 未配置：写操作关闭，只读视图仍可用。");
  }
  showBanner(lines);

  profileSelect.addEventListener("change", () => refresh(activeTab));

  if (!profiles.length) return;
  showTab("params");
}

start();
