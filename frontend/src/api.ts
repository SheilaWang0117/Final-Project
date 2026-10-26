// Thin fetch wrapper. All data comes from the local FastAPI backend.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle(res: Response): Promise<Json> {
  const text = await res.text();
  let body: Json = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    if (body && typeof body === "object" && "detail" in body) {
      msg = Array.isArray(body.detail)
        ? body.detail.map((d: Json) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ")
        : String(body.detail);
    }
    throw new ApiError(res.status, msg);
  }
  return body;
}

export const api = {
  get: (path: string) => fetch(path).then(handle),
  post: (path: string, body?: Json) =>
    fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) }).then(handle),
  put: (path: string, body?: Json) =>
    fetch(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) }).then(handle),
  patch: (path: string, body?: Json) =>
    fetch(path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) }).then(handle),
  del: (path: string) => fetch(path, { method: "DELETE" }).then(handle),
  upload: (path: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(path, { method: "POST", body: fd }).then(handle);
  },
};

// Poll a background job until it finishes.
export async function waitForJob(jobId: number, onUpdate?: (j: Json) => void, timeoutMs = 300000): Promise<Json> {
  const start = Date.now();
  for (;;) {
    const j = await api.get(`/api/jobs/${jobId}`);
    onUpdate?.(j);
    if (!["queued", "running"].includes(j.status)) return j;
    if (Date.now() - start > timeoutMs) return j;
    await new Promise((r) => setTimeout(r, 1500));
  }
}
