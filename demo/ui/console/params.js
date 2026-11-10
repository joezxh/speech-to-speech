// @ts-check
/** The parameters tab: the catalog on the left, the draft on the right.
 *
 * The draft is a patch, not a document (drafts.py). So the editor keeps two
 * things apart: `saved` is what the server holds, `working` is what the form
 * shows. Only the difference between them is ever POSTed, which is what makes a
 * `***` secret survive an edit to an unrelated field.
 */

import { api } from "./api.js";
import { badge, effectBadge, exposureBadge, fmtValue, html, render } from "./html.js";

/** Mirror of param_api._SECRET_NAME: the catalog has no `secret` flag. */
const SECRET_NAME = /(api_key|_key|token|secret|password)$/i;

const isSecret = (key) => SECRET_NAME.test(key.split(".").pop() || "");

const jsonish = (type) => type === "object" || type === "array" || type === "list";

/** @param {unknown} a @param {unknown} b */
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/**
 * @param {{toast: Function, onChange?: Function}} deps
 */
export function createParamsView({ toast, onChange }) {
  const search = /** @type {HTMLInputElement} */ (document.getElementById("catalog-search"));
  const exposure = /** @type {HTMLSelectElement} */ (document.getElementById("catalog-exposure"));
  const count = document.getElementById("catalog-count");
  const tree = document.getElementById("catalog-tree");
  const rows = document.getElementById("draft-rows");
  const empty = document.getElementById("draft-empty");
  const meta = document.getElementById("draft-meta");
  const validation = document.getElementById("validation");
  const note = /** @type {HTMLInputElement} */ (document.getElementById("note"));
  const saveBtn = /** @type {HTMLButtonElement} */ (document.getElementById("save"));
  const discardBtn = /** @type {HTMLButtonElement} */ (document.getElementById("discard"));
  const publishBtn = /** @type {HTMLButtonElement} */ (document.getElementById("publish"));

  let profile = "";
  /** @type {any} */
  let catalog = null;
  /** @type {{values: Record<string, unknown>, base_version: number, updated_at?: string, updated_by?: string, masked?: string[]}} */
  let saved = { values: {}, base_version: 0 };
  /** @type {Record<string, unknown>} */
  let working = {};
  /** Keys the operator removed locally; they become `null` (fall back to default). */
  let removed = new Set();

  /** @type {Record<string, any>} */
  let index = {};

  const entryFor = (key) => index[key] || { key, name: key, type: "string", exposure: "expert" };

  function dirty() {
    /** @type {Record<string, unknown>} */
    const patch = {};
    for (const [key, value] of Object.entries(working)) {
      if (!(key in saved.values) || !same(value, saved.values[key])) patch[key] = value;
    }
    for (const key of removed) {
      if (key in saved.values && !(key in working)) patch[key] = null;
    }
    return patch;
  }

  const dirtyCount = () => Object.keys(dirty()).length;

  // ── catalog ──────────────────────────────────────────────────────────────

  function renderTree() {
    if (!catalog) return;
    const term = search.value.trim().toLowerCase();
    const groups = new Map();
    for (const entry of catalog.parameters) {
      if (term) {
        const haystack = `${entry.key} ${entry.backend || ""} ${entry.risk || ""}`.toLowerCase();
        if (!haystack.includes(term)) continue;
      }
      if (!groups.has(entry.stage)) groups.set(entry.stage, []);
      groups.get(entry.stage).push(entry);
    }

    count.textContent = `${catalog.parameters.length} / 共 ${catalog.total} 条${
      catalog.variant_keys.length ? ` · ${catalog.variant_keys.length} 个多后端字段` : ""
    }`;

    const parts = [];
    for (const [stage, entries] of groups) {
      parts.push(html`<details class="tree-group" open><summary>${stage}</summary>`);
      for (const entry of entries) {
        const active = entry.key in working;
        parts.push(html`<button type="button" class="tree-item ${active ? "in-draft" : ""}"
            data-key="${entry.key}" title="${entry.risk || entry.key}">
            <span class="name">${entry.name}</span>
            ${exposureBadge(entry.exposure)}
          </button>`);
      }
      parts.push(html`</details>`);
    }
    render(tree, parts.length ? html`${parts}` : html`<p class="empty">没有匹配的参数</p>`);
  }

  // ── draft rows ───────────────────────────────────────────────────────────

  /** @param {any} entry @param {unknown} value */
  function control(entry, value) {
    const key = entry.key;

    if (entry.type === "fixed") {
      return html`<span class="badge" title="源码里是固定值，不能改">固定 ${fmtValue(value ?? entry.default)}</span>`;
    }
    if (entry.type === "boolean") {
      return html`<label class="check"><input type="checkbox" data-key="${key}" ${value === true ? "checked" : ""} /><span>${value === true ? "开" : "关"}</span></label>`;
    }
    if (entry.choices && entry.choices.length) {
      const options = entry.choices.map(
        (choice) => html`<option value="${choice}" ${String(value) === String(choice) ? "selected" : ""}>${choice}</option>`,
      );
      return html`<select data-key="${key}">
        ${value === null || value === undefined ? html`<option value="" selected>（默认 ${fmtValue(entry.default)}）</option>` : ""}
        ${options}
      </select>`;
    }
    if (isSecret(key)) {
      const shown = typeof value === "string" && value !== "***" ? value : "";
      return html`<input type="password" data-key="${key}" autocomplete="off" spellcheck="false"
        value="${shown}" placeholder="${value === "***" ? "已设置（改成新值才会写入）" : "未设置"}" />`;
    }
    if (entry.type === "integer" || entry.type === "float") {
      const step = entry.type === "integer" ? "1" : "any";
      return html`<input type="number" data-key="${key}" step="${step}" value="${value === null || value === undefined ? "" : value}"
        placeholder="${fmtValue(entry.default)}" />`;
    }
    if (jsonish(entry.type)) {
      const text = value === null || value === undefined ? "" : JSON.stringify(value);
      return html`<input type="text" data-key="${key}" spellcheck="false" value="${text}" placeholder="JSON" />`;
    }
    return html`<input type="text" data-key="${key}" value="${value === null || value === undefined ? "" : value}"
      placeholder="${fmtValue(entry.default)}" />`;
  }

  function renderDraft() {
    const keys = Object.keys(working).sort();
    empty.hidden = keys.length > 0;
    const patchCount = Object.keys(dirty()).length;
    meta.textContent = `基于 v${saved.base_version} · ${keys.length} 个字段${
      patchCount ? ` · ${patchCount} 项未保存` : ""
    }`;
    // Publishing reads the stored draft, so it is only useful when there is one.
    saveBtn.disabled = patchCount === 0;
    publishBtn.disabled = patchCount === 0 && keys.length === 0;

    const parts = keys.map((key) => {
      const entry = entryFor(key);
      const value = working[key];
      const changed = !(key in saved.values) || !same(value, saved.values[key]);
      return html`<div class="row ${changed ? "modified" : ""}" data-row="${key}">
        <div class="row-main">
          <span class="row-key" title="${entry.source_ref || key}">${key}</span>
          <div class="row-meta">
            ${exposureBadge(entry.exposure)}
            ${effectBadge(entry)}
            ${entry.backend ? badge(entry.backend) : ""}
            ${entry.required ? badge("必填") : ""}
            ${value === null ? badge("用默认值") : ""}
            ${entry.risk ? badge("风险", "ops") : ""}
          </div>
          ${entry.risk ? html`<p class="hint">${entry.risk}</p>` : ""}
        </div>
        <div class="row-control">${control(entry, value)}</div>
        <div class="row-actions">
          <button class="icon-btn" type="button" data-action="default" data-key="${key}" title="恢复为目录默认值">↺</button>
          <button class="icon-btn" type="button" data-action="remove" data-key="${key}" title="从草稿里去掉">×</button>
        </div>
      </div>`;
    });
    render(rows, html`${parts}`);
  }

  function addKey(key) {
    const entry = entryFor(key);
    working[key] = entry.type === "fixed" ? entry.default : (key in working ? working[key] : entry.default);
    removed.delete(key);
    renderTree();
    renderDraft();
  }

  /** @param {Event} event */
  function onControl(event) {
    const target = /** @type {HTMLInputElement} */ (event.target);
    const key = target.dataset.key;
    if (!key) return;
    const entry = entryFor(key);
    if (entry.type === "boolean") {
      working[key] = target.checked;
    } else if (entry.type === "integer" || entry.type === "float") {
      const raw = target.value.trim();
      if (!raw) working[key] = null;
      else if (Number.isNaN(Number(raw))) return;
      else working[key] = Number(raw);
    } else if (jsonish(entry.type)) {
      const raw = target.value.trim();
      if (!raw) working[key] = null;
      else {
        try {
          working[key] = JSON.parse(raw);
        } catch {
          working[key] = raw; // the server's renderer will refuse it with a field name
        }
      }
    } else {
      working[key] = target.value === "" ? null : target.value;
    }
    renderDraft();
  }

  /** @param {Event} event */
  function onAction(event) {
    const target = /** @type {HTMLElement} */ (event.target);
    const button = target.closest("button[data-action]");
    if (!button) return;
    const key = /** @type {HTMLButtonElement} */ (button).dataset.key || "";
    const action = /** @type {HTMLButtonElement} */ (button).dataset.action;
    if (action === "default") {
      working[key] = entryFor(key).default;
    } else if (action === "remove") {
      delete working[key];
      removed.add(key);
    }
    renderTree();
    renderDraft();
  }

  // ── actions ──────────────────────────────────────────────────────────────

  function showValidation(result) {
    const info = result && result.validation;
    if (!info) {
      validation.hidden = true;
      return;
    }
    validation.hidden = false;
    validation.className = `validation ${info.ok ? "ok" : "bad"}`;
    const warnings = info.warnings || [];
    render(
      validation,
      html`<div>
        ${info.ok ? "校验通过" : "校验未通过"} · ${info.mode === "runtime" ? "完整解析" : "仅结构校验（容器里没有运行时包）"}
        ${info.resolved_pipelines && info.resolved_pipelines.length
          ? html` · pipelines: ${info.resolved_pipelines.join(", ")}`
          : ""}
        ${info.expected_pool_size ? html` · 预期 pool size ${info.expected_pool_size}` : ""}
      </div>
      ${(result.skipped_masked || []).length
        ? html`<p class="hint">保留了这些已设置的密钥（提交上来的是 ***）：${result.skipped_masked.join("、")}</p>`
        : ""}
      ${warnings.length ? html`<ul>${warnings.map((warning) => html`<li>${warning}</li>`)}</ul>` : ""}`,
    );
  }

  async function save({ quiet = false } = {}) {
    const patch = dirty();
    if (!Object.keys(patch).length) {
      if (!quiet) toast("草稿没有改动", "ok");
      return true;
    }
    saveBtn.disabled = true;
    try {
      const result = await api.saveDraft(profile, patch, saved.base_version);
      saved = { ...result, values: result.draft, base_version: result.base_version };
      working = { ...saved.values };
      removed = new Set();
      showValidation(result);
      renderDraft();
      if (!quiet) toast(`已保存（基于 v${saved.base_version}）`, "ok");
      if (onChange) onChange();
      return true;
    } catch (error) {
      // A 422 from the renderer names the field; leave the draft as typed so the
      // operator can fix it rather than retype everything.
      validation.hidden = false;
      validation.className = "validation bad";
      render(validation, html`<div>${error.code}：${error.message}</div>
        ${(error.details || []).map((detail) => html`<p class="hint">${fmtValue(detail)}</p>`)}`);
      toast(error.summary, "bad");
      return false;
    } finally {
      renderDraft();
    }
  }

  async function discard() {
    try {
      await api.discardDraft(profile);
      saved = { values: {}, base_version: saved.base_version };
      working = {};
      removed = new Set();
      validation.hidden = true;
      renderTree();
      renderDraft();
      toast("草稿已放弃", "ok");
      if (onChange) onChange();
    } catch (error) {
      toast(error.summary, "bad");
    }
  }

  async function publish() {
    // Publishing reads the *stored* draft, so an unsaved edit would silently be
    // left out of the version. Save first, and stop if the save was refused.
    if (!(await save({ quiet: true }))) return;
    publishBtn.disabled = true;
    publishBtn.textContent = "发布中…";
    try {
      const result = await api.publish(profile, saved.base_version, note.value.trim());
      const health = result.healthcheck || {};
      const ok = result.status === "live";
      toast(
        ok
          ? `已发布 v${result.version}，${result.duration_s}s，pool ${health.pool_size ?? "?"}（在用 ${health.in_use ?? "?"}）`
          : `v${result.version} 探活失败，已回滚到上一版`,
        ok ? "ok" : "bad",
      );
      saved = { values: {}, base_version: result.version };
      working = {};
      removed = new Set();
      note.value = "";
      validation.hidden = true;
      renderDraft();
      if (onChange) onChange();
    } catch (error) {
      // A publish that failed and rolled back still created a version, so the
      // console has to reload rather than pretend nothing happened.
      toast(error.summary, "bad");
      validation.hidden = false;
      validation.className = "validation bad";
      render(validation, html`<div>${error.code}：${error.message}</div>
        ${(error.details || []).map((detail) => html`<p class="hint">${fmtValue(detail)}</p>`)}`);
      if (onChange) onChange();
    } finally {
      publishBtn.textContent = "发布";
      renderDraft();
    }
  }

  // ── wiring ───────────────────────────────────────────────────────────────

  search.addEventListener("input", renderTree);
  exposure.addEventListener("change", () => loadCatalog());
  tree.addEventListener("click", (event) => {
    const button = /** @type {HTMLElement} */ (event.target).closest("button[data-key]");
    if (button) addKey(/** @type {HTMLButtonElement} */ (button).dataset.key || "");
  });
  rows.addEventListener("change", onControl);
  rows.addEventListener("click", onAction);
  saveBtn.addEventListener("click", () => save());
  discardBtn.addEventListener("click", discard);
  publishBtn.addEventListener("click", publish);

  async function loadCatalog() {
    catalog = await api.catalog({ exposure: exposure.value });
    index = {};
    for (const entry of catalog.parameters) index[entry.key] = entry;
    renderTree();
    renderDraft();
  }

  return {
    /** @param {string} name */
    async load(name) {
      profile = name;
      const [catalogResponse, draft] = await Promise.all([
        api.catalog({ exposure: exposure.value }),
        api.draft(name),
      ]);
      catalog = catalogResponse;
      index = {};
      for (const entry of catalog.parameters) index[entry.key] = entry;
      saved = { ...draft, values: draft.draft };
      working = { ...saved.values };
      removed = new Set();
      validation.hidden = true;
      renderTree();
      renderDraft();
    },
    loadCatalog,
    get profile() {
      return profile;
    },
  };
}
