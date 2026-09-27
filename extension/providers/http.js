// fetch helpers for providers: JSON in, JSON out, a timeout, and an error message that names the endpoint.

export async function postJson(url, body, { timeoutMs = 10000, headers = {} } = {}) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!r.ok) throw new Error(`${url} -> HTTP ${r.status}`);
  return r.json();
}

export async function getJson(url, { timeoutMs = 2500, headers = {} } = {}) {
  const r = await fetch(url, { headers, signal: AbortSignal.timeout(timeoutMs) });
  if (!r.ok) throw new Error(`${url} -> HTTP ${r.status}`);
  return r.json();
}

export const trimSlash = (u) => String(u || "").replace(/\/+$/, "");
