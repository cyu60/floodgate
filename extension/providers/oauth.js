// OAuth 2.1 for MCP servers that only take OAuth (hosted GBrain): discovery (RFC 9728 + RFC 8414), dynamic client
// registration (RFC 7591), authorization code + PKCE S256 through chrome.identity, refresh tokens, revoke.
// The extension is a public client: no secret. Tokens live in chrome.storage.local under "oauth:<id>", never in settings.
import { getJson } from "./http.js";

const KEY = (id) => `oauth:${id}`;
const b64url = (buf) =>
  btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
const random = (n = 32) => b64url(crypto.getRandomValues(new Uint8Array(n)));
const sha256 = async (s) => b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));

async function load(id) {
  return (await chrome.storage.local.get(KEY(id)))[KEY(id)] || null;
}
const save = (id, rec) => chrome.storage.local.set({ [KEY(id)]: rec });

async function postForm(url, fields) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: new URLSearchParams(Object.entries(fields).filter(([, v]) => v != null)),
    signal: AbortSignal.timeout(15000),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${body.error_description || body.error || `HTTP ${r.status}`} (${new URL(url).pathname})`);
  return body;
}

/** Find the authorization server for an MCP resource URL, with the conventional paths as a fallback. */
export async function discover(resource) {
  const u = new URL(resource);
  let issuer = u.origin;
  try {
    const pr = await getJson(`${u.origin}/.well-known/oauth-protected-resource${u.pathname.replace(/\/$/, "")}`, { timeoutMs: 8000 });
    if (pr.authorization_servers?.[0]) issuer = pr.authorization_servers[0].replace(/\/$/, "");
  } catch {
    // no metadata: assume the resource's origin is the authorization server
  }
  let m = {};
  try {
    m = await getJson(`${issuer}/.well-known/oauth-authorization-server`, { timeoutMs: 8000 });
  } catch {
    // fall back to the conventional paths below
  }
  return {
    authorization_endpoint: m.authorization_endpoint || `${issuer}/oauth/authorize`,
    token_endpoint: m.token_endpoint || `${issuer}/oauth/token`,
    registration_endpoint: m.registration_endpoint || `${issuer}/oauth/register`,
    revocation_endpoint: m.revocation_endpoint || `${issuer}/oauth/revoke`,
  };
}

/** Interactive sign-in. Run it from an extension page (a button click): chrome.identity opens the provider's login. */
export async function signIn(id, { resource, scope, clientName = "Floodgate" }) {
  const meta = await discover(resource);
  const redirectUri = chrome.identity.getRedirectURL("oauth");
  const prev = await load(id);
  let clientId = prev?.redirectUri === redirectUri && prev?.resource === resource ? prev.clientId : null;
  if (!clientId) {
    const r = await fetch(meta.registration_endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        client_name: clientName,
        redirect_uris: [redirectUri],
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
        token_endpoint_auth_method: "none",
        scope,
      }),
      signal: AbortSignal.timeout(15000),
    });
    const reg = await r.json().catch(() => ({}));
    if (!r.ok || !reg.client_id) throw new Error(`could not register Floodgate with the server (${reg.error_description || reg.error || `HTTP ${r.status}`})`);
    clientId = reg.client_id;
  }
  const verifier = random(48);
  const state = random(16);
  const auth = new URL(meta.authorization_endpoint);
  Object.entries({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri,
    scope,
    state,
    code_challenge: await sha256(verifier),
    code_challenge_method: "S256",
    resource,
  }).forEach(([k, v]) => auth.searchParams.set(k, v));
  const back = new URL(await chrome.identity.launchWebAuthFlow({ url: auth.href, interactive: true }));
  if (back.searchParams.get("error")) throw new Error(back.searchParams.get("error_description") || back.searchParams.get("error"));
  if (back.searchParams.get("state") !== state) throw new Error("sign-in response did not match (state), try again");
  const tok = await postForm(meta.token_endpoint, {
    grant_type: "authorization_code",
    code: back.searchParams.get("code"),
    redirect_uri: redirectUri,
    client_id: clientId,
    code_verifier: verifier,
    resource,
  });
  const rec = { clientId, redirectUri, resource, meta, scope: tok.scope || scope, ...tokens(tok) };
  await save(id, rec);
  return rec;
}

const tokens = (t) => ({ access_token: t.access_token, refresh_token: t.refresh_token, expires_at: Date.now() + (Number(t.expires_in) || 3600) * 1000 - 60_000 });

/** A valid access token for this resource (refreshed if needed), or null when not signed in. */
export async function accessToken(id, resource, { force = false } = {}) {
  const rec = await load(id);
  if (!rec?.access_token || rec.resource !== resource) return null;
  if (!force && rec.expires_at > Date.now()) return rec.access_token;
  if (!rec.refresh_token) return null;
  try {
    const t = await postForm(rec.meta.token_endpoint, { grant_type: "refresh_token", refresh_token: rec.refresh_token, client_id: rec.clientId, resource });
    const next = { ...rec, ...tokens(t), refresh_token: t.refresh_token || rec.refresh_token };
    await save(id, next);
    return next.access_token;
  } catch {
    await save(id, { ...rec, access_token: null });
    return null;
  }
}

export async function status(id, resource) {
  const rec = await load(id);
  return { signedIn: !!(rec?.access_token || rec?.refresh_token) && rec.resource === resource, scope: rec?.scope || "" };
}

export async function signOut(id) {
  const rec = await load(id);
  if (rec?.meta?.revocation_endpoint && (rec.refresh_token || rec.access_token)) {
    await postForm(rec.meta.revocation_endpoint, { token: rec.refresh_token || rec.access_token, client_id: rec.clientId }).catch(() => {});
  }
  await chrome.storage.local.remove(KEY(id));
}
