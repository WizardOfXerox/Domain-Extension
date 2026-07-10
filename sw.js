const CTRL_BASE = "http://127.0.0.1:9080/__xai";

const STORAGE_KEYS = {
  localDomains: "localDomains",
  proxyEnabled: "proxyEnabled"
};

const DEFAULTS = {
  localDomains: [],
  proxyEnabled: true
};

const PROXY_HOST = "127.0.0.1";
const PROXY_PORT = 9081;

const FAKE_TLDS = [".fake", ".test", ".custom", ".ssx"];

function uniqLower(list) {
  const out = [];
  const seen = new Set();
  for (const v of list || []) {
    if (!v) continue;
    const s = String(v).trim().toLowerCase();
    if (!s) continue;
    if (seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

/**
 * Check if a domain entry is a wildcard pattern (e.g., "*.google.com").
 */
function isWildcard(entry) {
  return entry.startsWith("*.");
}

/**
 * Build PAC script with support for:
 * - Fake TLDs (always proxied)
 * - Exact domain matches
 * - Wildcard/subdomain matches (e.g., *.google.com matches sub.google.com and google.com)
 */
function buildPac(localDomains, proxyEnabled) {
  const domains = uniqLower(localDomains);

  const exactDomains = domains.filter((d) => !isWildcard(d));
  const wildcardDomains = domains.filter((d) => isWildcard(d));

  const fakeChecks = FAKE_TLDS.map((tld) => `shExpMatch(host, "*${tld}")`).join(" || ") || "false";

  // Exact domain checks
  const exactChecks = exactDomains.map((d) => `host === "${d}"`).join(" || ") || "false";

  // Wildcard subdomain checks using dnsDomainIs for *.example.com
  // This matches both "sub.example.com" and "example.com" itself.
  const wildcardChecks = wildcardDomains
    .map((d) => {
      const base = d.slice(2); // Remove "*."
      return `(dnsDomainIs(host, ".${base}") || host === "${base}")`;
    })
    .join(" || ") || "false";

  const proxyOnly = `PROXY ${PROXY_HOST}:${PROXY_PORT}`;
  const proxyThenDirect = `PROXY ${PROXY_HOST}:${PROXY_PORT}; DIRECT`;
  const direct = "DIRECT";

  const enabledCheck = proxyEnabled ? "true" : "false";

  return `
function FindProxyForURL(url, host) {
  host = (host || "").toLowerCase();
  if (!${enabledCheck}) return "${direct}";

  // Always proxy fake TLDs.
  if (${fakeChecks}) return "${proxyOnly}";

  // Proxy exact real domains when they are in local mode.
  if (${exactChecks}) return "${proxyThenDirect}";

  // Proxy wildcard subdomain matches.
  if (${wildcardChecks}) return "${proxyThenDirect}";

  return "${direct}";
}
`.trim();
}

function setProxyPac(pacData) {
  return new Promise((resolve, reject) => {
    chrome.proxy.settings.set(
      {
        value: { mode: "pac_script", pacScript: { data: pacData } },
        scope: "regular"
      },
      () => {
        const err = chrome.runtime.lastError;
        if (err) reject(new Error(err.message));
        else resolve();
      }
    );
  });
}

function setDirect() {
  return new Promise((resolve, reject) => {
    chrome.proxy.settings.set({ value: { mode: "direct" }, scope: "regular" }, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

async function applyFromStorage() {
  const data = await chrome.storage.local.get([STORAGE_KEYS.localDomains, STORAGE_KEYS.proxyEnabled]);
  const localDomains = uniqLower(data[STORAGE_KEYS.localDomains] ?? DEFAULTS.localDomains);
  const proxyEnabled = data[STORAGE_KEYS.proxyEnabled] ?? DEFAULTS.proxyEnabled;

  if (!proxyEnabled) {
    await setDirect();
    return { proxyEnabled, localDomains };
  }

  const pac = buildPac(localDomains, true);
  // Force a config flip to reduce "sticky" routing behavior in Chrome.
  await setDirect();
  await setProxyPac(pac);
  return { proxyEnabled, localDomains };
}

chrome.runtime.onInstalled.addListener(() => {
  // Do not clobber existing state on update; just ensure proxy settings match storage.
  applyFromStorage().catch(() => {});
});

chrome.runtime.onStartup?.addListener(() => {
  // Default behavior: do NOT persist real-domain local toggles across browser restarts.
  // Fake TLDs are still forced via PAC, but real domains start as DIRECT unless re-enabled.
  chrome.storage.local
    .set({ [STORAGE_KEYS.localDomains]: [] })
    .then(() => applyFromStorage())
    .catch(() => {
      applyFromStorage().catch(() => {});
    });
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (!msg || typeof msg !== "object") return sendResponse({ ok: false, error: "bad message" });

    if (msg.type === "updatePac") {
      const localDomains = uniqLower(msg.localDomains || []);
      const proxyEnabled = msg.proxyEnabled !== undefined ? !!msg.proxyEnabled : true;

      await chrome.storage.local.set({
        [STORAGE_KEYS.localDomains]: localDomains,
        [STORAGE_KEYS.proxyEnabled]: proxyEnabled
      });

      const pac = buildPac(localDomains, proxyEnabled);
      if (proxyEnabled) {
        // Force a config flip to reduce "sticky" routing behavior in Chrome.
        await setDirect();
        await setProxyPac(pac);
      }
      else await setDirect();

      return sendResponse({ ok: true });
    }

    if (msg.type === "getState") {
      const data = await chrome.storage.local.get([STORAGE_KEYS.localDomains, STORAGE_KEYS.proxyEnabled]);
      return sendResponse({
        ok: true,
        localDomains: uniqLower(data[STORAGE_KEYS.localDomains] ?? DEFAULTS.localDomains),
        proxyEnabled: data[STORAGE_KEYS.proxyEnabled] ?? DEFAULTS.proxyEnabled,
        proxy: `${PROXY_HOST}:${PROXY_PORT}`
      });
    }

    if (msg.type === "disableProxy") {
      await chrome.storage.local.set({ [STORAGE_KEYS.proxyEnabled]: false });
      await setDirect();
      return sendResponse({ ok: true });
    }

    return sendResponse({ ok: false, error: "unknown message" });
  })().catch((e) => sendResponse({ ok: false, error: String(e?.message || e) }));

  return true;
});
