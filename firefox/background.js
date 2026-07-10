const PROXY_HOST = "127.0.0.1";
const PROXY_PORT = 9081;
const FAKE_TLDS = [".fake", ".test", ".custom", ".ssx"];

let state = {
  proxyEnabled: true,
  localDomains: []
};

function uniqLower(list) {
  const out = [];
  const seen = new Set();
  for (const v of list || []) {
    const s = String(v || "").trim().toLowerCase();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

function isFake(host) {
  return FAKE_TLDS.some((t) => host.endsWith(t));
}

/**
 * Check if a host matches any of the local domains, including wildcard patterns.
 * Supports exact match and wildcard subdomain match (e.g., *.google.com).
 */
function matchesLocalDomain(host, domains) {
  for (const entry of domains) {
    if (entry.startsWith("*.")) {
      const base = entry.slice(2);
      if (host === base || host.endsWith("." + base)) return true;
    } else {
      if (host === entry) return true;
    }
  }
  return false;
}

function loadState() {
  return browser.storage.local.get(["proxyEnabled", "localDomains"]).then((d) => {
    state.proxyEnabled = d.proxyEnabled !== undefined ? !!d.proxyEnabled : true;
    state.localDomains = uniqLower(d.localDomains || []);
  });
}

function applyProxyListener() {
  try {
    browser.proxy.onRequest.removeListener(handleProxyRequest);
  } catch (_) {}
  browser.proxy.onRequest.addListener(handleProxyRequest, { urls: ["<all_urls>"] });
}

function handleProxyRequest(details) {
  try {
    const u = new URL(details.url);
    const host = (u.hostname || "").toLowerCase();
    if (!state.proxyEnabled) return { type: "direct" };
    if (isFake(host)) return { type: "http", host: PROXY_HOST, port: PROXY_PORT };
    if (matchesLocalDomain(host, state.localDomains)) return { type: "http", host: PROXY_HOST, port: PROXY_PORT };
    return { type: "direct" };
  } catch (_) {
    return { type: "direct" };
  }
}

function setState(next) {
  state.proxyEnabled = next.proxyEnabled !== undefined ? !!next.proxyEnabled : state.proxyEnabled;
  if (next.localDomains) state.localDomains = uniqLower(next.localDomains);
  return browser.storage.local.set({
    proxyEnabled: state.proxyEnabled,
    localDomains: state.localDomains
  });
}

browser.runtime.onMessage.addListener((msg) => {
  if (!msg || typeof msg !== "object") return Promise.resolve({ ok: false, error: "bad message" });
  if (msg.type === "getState") return Promise.resolve({ ok: true, ...state, proxy: `${PROXY_HOST}:${PROXY_PORT}` });
  if (msg.type === "updateState") {
    return setState(msg).then(() => ({ ok: true })).catch((e) => ({ ok: false, error: String(e) }));
  }
  return Promise.resolve({ ok: false, error: "unknown message" });
});

loadState().then(applyProxyListener).catch(() => applyProxyListener());
