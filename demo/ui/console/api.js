// @ts-check
/** The admin API of appendix A, with the operator's token and its error body.
 *
 * A.0 promises `{"error": {code, message, details}}` on every refusal, so every
 * failure the console shows comes from that body; a network failure and an
 * unparseable body are the only two exceptions and both get a code of their own.
 */

const TOKEN_KEY = "s2s.admin.token";

/** Header the server reads to name the human behind a token. */
const ACTOR_HEADER = "X-Operator";

export class ApiError extends Error {
  /**
   * @param {number} status
   * @param {string} code
   * @param {string} message
   * @param {unknown[]} [details]
   */
  constructor(status, code, message, details = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** One-line summary for a toast. */
  get summary() {
    return this.status ? `${this.code}（HTTP ${this.status}）：${this.message}` : `${this.code}：${this.message}`;
  }
}

/** @type {(() => string)|null} */
let askForToken = null;

/** app.js installs the prompt; api.js must not know what a dialog is. */
export function useTokenPrompt(prompt) {
  askForToken = prompt;
}

export function token() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

/** @param {string} value */
export function setToken(value) {
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: the console still works for the read-only views */
  }
}

/**
 * @param {string} method
 * @param {string} path
 * @param {unknown} [body]
 * @param {boolean} [retried]
 * @returns {Promise<any>}
 */
async function call(method, path, body, retried = false) {
  /** @type {Record<string,string>} */
  const headers = { Accept: "application/json" };
  const bearer = token();
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  const actor = sessionStorage.getItem("s2s.admin.actor");
  if (actor) headers[ACTOR_HEADER] = actor;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError(0, "network_error", `连不上 ${path}`, [String(cause)]);
  }

  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }

  if (response.status === 401 && !retried && askForToken) {
    // An expired or wrong token: ask once, then replay the request. Without this
    // every view would need its own "please log in again" branch.
    const entered = await askForToken();
    if (entered) return call(method, path, body, true);
  }

  if (!response.ok) {
    const error = payload && typeof payload === "object" ? payload.error : null;
    throw new ApiError(
      response.status,
      (error && error.code) || `http_${response.status}`,
      (error && error.message) || text || response.statusText,
      (error && error.details) || [],
    );
  }
  return payload;
}

const qs = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
};

const profilePath = (profile, suffix) => `/admin/profiles/${encodeURIComponent(profile)}${suffix}`;

export const api = {
  status: () => call("GET", "/admin/status"),

  /** @param {{exposure?: string, stage?: string, backend?: string}} query */
  catalog: (query = {}) => call("GET", `/admin/catalog${qs(query)}`),

  /** @param {string} profile */
  draft: (profile) => call("GET", profilePath(profile, "/draft")),

  /**
   * @param {string} profile
   * @param {Record<string, unknown>} patch
   * @param {number|null} baseVersion
   */
  saveDraft: (profile, patch, baseVersion) =>
    call("POST", profilePath(profile, "/draft"), { patch, base_version: baseVersion }),

  /** @param {string} profile */
  discardDraft: (profile) => call("DELETE", profilePath(profile, "/draft")),

  /**
   * @param {string} profile
   * @param {number|null} baseVersion
   * @param {string} note
   */
  publish: (profile, baseVersion, note) =>
    call("POST", profilePath(profile, "/publish"), { base_version: baseVersion, note }),

  /**
   * @param {string} profile
   * @param {number} targetVersion
   * @param {string} note
   */
  rollback: (profile, targetVersion, note) =>
    call("POST", profilePath(profile, "/rollback"), { target_version: targetVersion, note }),

  /** @param {string} profile @param {number} [limit] */
  versions: (profile, limit = 50) => call("GET", profilePath(profile, `/versions${qs({ limit })}`)),

  /** @param {string} profile @param {number} [limit] */
  audit: (profile, limit = 50) => call("GET", profilePath(profile, `/audit${qs({ limit })}`)),

  /** @param {string} profile */
  instances: (profile) => call("GET", `/admin/instances${qs({ profile })}`),

  /**
   * @param {string} profile
   * @param {{scope: string, target?: unknown, session: Record<string, unknown>}} payload
   */
  hotUpdate: (profile, payload) => call("POST", `/admin/sessions/update${qs({ profile })}`, payload),
};

/** The operator's own name, sent as `X-Operator` so the audit names a human. */
export const actor = {
  get: () => sessionStorage.getItem("s2s.admin.actor") || "",
  set: (/** @type {string} */ value) => sessionStorage.setItem("s2s.admin.actor", value || ""),
};
