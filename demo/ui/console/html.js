// @ts-check
/** Templating and formatting shared by the console views.
 *
 * `html` escapes every interpolation, so a catalog name, a note or an error
 * message from the server cannot become markup. Nesting works without `raw`
 * because a template returns a `Raw` whose `toString` is the escaped text.
 */

const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** @param {unknown} value @returns {string} */
export function esc(value) {
  return String(value).replace(/[&<>"']/g, (char) => ENTITIES[/** @type {keyof ENTITIES} */ (char)]);
}

class Raw {
  /** @param {string} text */
  constructor(text) {
    this.text = text;
  }

  toString() {
    return this.text;
  }
}

/**
 * @param {unknown} value
 * @returns {string}
 */
function flatten(value) {
  if (value instanceof Raw) return value.text;
  if (Array.isArray(value)) return value.map(flatten).join("");
  if (value === null || value === undefined || value === false) return "";
  return esc(value);
}

/**
 * @param {TemplateStringsArray} strings
 * @param {...unknown} values
 * @returns {Raw}
 */
export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((value, index) => {
    out += flatten(value) + strings[index + 1];
  });
  return new Raw(out);
}

/** Mark text as already-escaped HTML. @param {string} text @returns {Raw} */
export const raw = (text) => new Raw(text);

/** Set an element's markup from a template. */
export function render(element, template) {
  element.innerHTML = String(template);
}

/** @param {number|null|undefined} epoch seconds since the Unix epoch */
export function fmtTime(epoch) {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("zh-CN", { hour12: false });
}

/** @param {number|null|undefined} seconds */
export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 90) return `${seconds.toFixed(1)} s`;
  return `${Math.round(seconds / 60)} min`;
}

/** @param {number|null|undefined} bytes */
export function fmtBytes(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** A short label for a value in a table cell. @param {unknown} value */
export function fmtValue(value) {
  if (value === null || value === undefined) return "默认值";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * @param {string} text
 * @param {string} [kind] extra class for colour
 * @returns {Raw}
 */
export const badge = (text, kind = "") => html`<span class="badge ${kind}">${text}</span>`;

/** The exposure ladder's four levels, colour-coded. @param {string} level */
export const exposureBadge = (level) => badge(level, level);

/** @param {{effect?: string, change_cost?: string}} entry */
export function effectBadge(entry) {
  if (!entry.effect) return "";
  const cost = entry.change_cost ? ` · ${entry.change_cost}` : "";
  // `hot` is the only effect that does not need a restart; saying so on every
  // row would make the one that matters disappear into the noise.
  return entry.effect === "hot" ? badge("热更新", "live") : badge(`重启${cost}`);
}
