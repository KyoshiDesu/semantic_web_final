// The JSON API client: one error type, the 503 retry for reads, and URLs for links and downloads.
export class ApiError extends Error {
  constructor(status, body) {
    super(body.message || `HTTP ${status}`);
    this.status = status;
    this.code = body.error || "internal";
    this.details = body.details || [];
  }
}

export function url(path, params = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== "") q.set(k, v);
  }
  const s = q.toString();
  return `/api${path}${s ? `?${s}` : ""}`;
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function request(method, path, { params, json, form, text = false } = {}) {
  const init = { method, headers: {} };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers["Content-Type"] = "application/json";
  }
  if (form) init.body = form;
  for (let attempt = 0; ; attempt++) {
    let res;
    try {
      res = await fetch(url(path, params), init);
    } catch {
      throw new ApiError(0, { error: "offline", message: "the server is not running" });
    }
    // Only reads are retried: a resent import or correction could apply twice.
    if (res.status === 503 && method === "GET" && attempt < 3) {
      await sleep(1000 * Number(res.headers.get("Retry-After") || 2));
      continue;
    }
    if (!res.ok) {
      let body;
      try {
        body = await res.json();
      } catch {
        body = { message: res.statusText };
      }
      throw new ApiError(res.status, body);
    }
    return text ? res.text() : res.json();
  }
}

export const api = {
  get: (path, params) => request("GET", path, { params }),
  text: (path, params) => request("GET", path, { params, text: true }),
  post: (path, json, params) => request("POST", path, { json, params }),
  put: (path, json) => request("PUT", path, { json }),
  form: (path, form, params) => request("POST", path, { form, params }),
};
