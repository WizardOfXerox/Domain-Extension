const CTRL_BASE = "http://127.0.0.1:9080/__xai";
const FAKE_TLDS = [".fake", ".test", ".custom", ".ssx"];

function isFakeTld(domain) {
  return FAKE_TLDS.some((tld) => domain.endsWith(tld));
}

function setStatus(dotClass, text, msg, isError = false) {
  const dot = document.getElementById("serverDot");
  const st = document.getElementById("serverText");
  const m = document.getElementById("msg");

  dot.classList.remove("ok", "bad");
  if (dotClass) dot.classList.add(dotClass);
  st.textContent = text;
  m.textContent = msg || "";
  m.classList.toggle("err", !!isError);
}

function chromeTabsQuery(queryInfo) {
  return new Promise((resolve, reject) => {
    chrome.tabs.query(queryInfo, (tabs) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(tabs);
    });
  });
}

function chromeTabsReload(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabs.reload(tabId, { bypassCache: true }, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

function chromeStorageGet(keys) {
  return new Promise((resolve, reject) => {
    chrome.storage.local.get(keys, (data) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(data || {});
    });
  });
}

function chromeStorageSet(obj) {
  return new Promise((resolve, reject) => {
    chrome.storage.local.set(obj, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

function chromeRuntimeSendMessage(msg) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(resp);
    });
  });
}

function chromeBrowsingDataRemove(options, dataToRemove) {
  return new Promise((resolve, reject) => {
    chrome.browsingData.remove(options, dataToRemove, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

async function disableProxyAndReload() {
  const msgEl = document.getElementById("msg");
  try {
    const resp = await chromeRuntimeSendMessage({ type: "disableProxy" });
    if (!resp || !resp.ok) {
      msgEl.textContent = `Disable proxy failed: ${(resp && resp.error) || "unknown error"}`;
      msgEl.classList.add("err");
      return;
    }
    msgEl.textContent = "Proxy routing disabled (DIRECT). Reloading tab...";
    msgEl.classList.remove("err");

    const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
    const tabId = tabs && tabs[0] ? tabs[0].id : null;
    if (tabId != null) {
      await chromeTabsReload(tabId);
    }
    await refresh();
  } catch (e) {
    msgEl.textContent = String(e.message || e);
    msgEl.classList.add("err");
  }
}

async function enableProxyAndReload() {
  const msgEl = document.getElementById("msg");
  try {
    const data = await chromeStorageGet(["localDomains"]);
    const localDomains = Array.isArray(data.localDomains) ? data.localDomains : [];
    const resp = await chromeRuntimeSendMessage({ type: "updatePac", localDomains, proxyEnabled: true });
    if (!resp || !resp.ok) {
      msgEl.textContent = `Enable proxy failed: ${(resp && resp.error) || "unknown error"}`;
      msgEl.classList.add("err");
      return;
    }
    msgEl.textContent = "Proxy routing enabled. Reloading tab...";
    msgEl.classList.remove("err");

    const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
    const tabId = tabs && tabs[0] ? tabs[0].id : null;
    if (tabId != null) {
      await chromeTabsReload(tabId);
    }
    await refresh();
  } catch (e) {
    msgEl.textContent = String(e.message || e);
    msgEl.classList.add("err");
  }
}

async function resetLocalsAndReload() {
  const msgEl = document.getElementById("msg");
  try {
    await chromeStorageSet({ localDomains: [] });
    const resp = await chromeRuntimeSendMessage({ type: "updatePac", localDomains: [], proxyEnabled: true });
    if (!resp || !resp.ok) {
      msgEl.textContent = `Reset locals failed: ${(resp && resp.error) || "unknown error"}`;
      msgEl.classList.add("err");
      return;
    }
    msgEl.textContent = "Local allowlist cleared. Reloading tab...";
    msgEl.classList.remove("err");

    const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
    const tabId = tabs && tabs[0] ? tabs[0].id : null;
    if (tabId != null) {
      await chromeTabsReload(tabId);
    }
    await refresh();
  } catch (e) {
    msgEl.textContent = String(e.message || e);
    msgEl.classList.add("err");
  }
}

async function getActiveDomain() {
  const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
  if (!tabs || !tabs[0] || !tabs[0].url) return null;
  try {
    const u = new URL(tabs[0].url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return u.hostname;
  } catch {
    return null;
  }
}

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`Bad JSON from server (${res.status}): ${text.slice(0, 200)}`);
  }
  if (!res.ok) {
    throw new Error(data && data.error ? data.error : `HTTP ${res.status}`);
  }
  return data;
}

async function refresh() {
  const domainEl = document.getElementById("domain");
  const localSiteEl = document.getElementById("localSite");
  const modeEl = document.getElementById("mode");
  const hostsMappedEl = document.getElementById("hostsMapped");
  const proxyStateEl = document.getElementById("proxyState");
  const toggleRow = document.getElementById("toggleRow");
  const toggle = document.getElementById("modeToggle");
  const toggleNote = document.getElementById("toggleNote");
  const msgEl = document.getElementById("msg");
  const metricsSummaryEl = document.getElementById("metricsSummary");
  const backendOriginInput = document.getElementById("backendOriginInput");
  const saveBackendBtn = document.getElementById("saveBackendBtn");
  const clearBackendBtn = document.getElementById("clearBackendBtn");
  const clearSiteDataBtn = document.getElementById("clearSiteDataBtn");

  let domain = null;
  try {
    domain = await getActiveDomain();
  } catch (e) {
    setStatus("bad", "error", String(e.message || e), true);
  }

  domainEl.textContent = domain || "(no page)";
  toggle.disabled = true;
  msgEl.textContent = "";

  // Quick-add row: show for real domains, hide for fake TLDs and non-pages.
  const quickAddRow = document.getElementById("quickAddRow");
  const quickAddBtn = document.getElementById("quickAddBtn");

  if (!domain) {
    localSiteEl.textContent = "(unknown)";
    modeEl.textContent = "(unknown)";
    hostsMappedEl.textContent = "(unknown)";
    proxyStateEl.textContent = "(unknown)";
    metricsSummaryEl.textContent = "(unknown)";
    backendOriginInput.value = "";
    saveBackendBtn.disabled = true;
    clearBackendBtn.disabled = true;
    clearSiteDataBtn.disabled = true;
    if (document.getElementById("serverText").textContent === "checking") {
      setStatus("bad", "no tab", "Open a normal website tab (not chrome:// pages) to use the toggle.", true);
    }
    return;
  }

  clearSiteDataBtn.disabled = false;
  clearSiteDataBtn.onclick = async () => {
    try {
      await chromeBrowsingDataRemove(
        { since: 0, origins: [`https://${domain}`] },
        {
          cache: true,
          cookies: true,
          localStorage: true,
          indexedDB: true,
          serviceWorkers: true
        }
      );
      msgEl.textContent = `Cleared site data for https://${domain}`;
      msgEl.classList.remove("err");
      const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
      const tabId = tabs && tabs[0] ? tabs[0].id : null;
      if (tabId != null) await chromeTabsReload(tabId);
    } catch (e) {
      msgEl.textContent = `Clear site data failed: ${String(e.message || e)}`;
      msgEl.classList.add("err");
    }
  };

  // Always fetch SW/PAC state first. This is the source of truth for switching.
  let swState = null;
  try {
    swState = await chromeRuntimeSendMessage({ type: "getState" });
  } catch {
    swState = null;
  }

  const proxyEnabled = !!(swState && swState.ok && swState.proxyEnabled);
  const localDomains = swState && swState.ok && Array.isArray(swState.localDomains) ? swState.localDomains : [];
  const isLocalByPac = proxyEnabled && localDomains.map((s) => String(s).toLowerCase()).includes(domain.toLowerCase());

  try {
    const status = await fetchJson(`${CTRL_BASE}/status?domain=${encodeURIComponent(domain)}`);

    setStatus("ok", "online", "");

    localSiteEl.textContent = status.hasLocalSite ? "present" : "missing";
    if (isFakeTld(domain) || status.isFakeTld) modeEl.textContent = "local";
    else modeEl.textContent = isLocalByPac ? "local" : "proxy";
    hostsMappedEl.textContent = status.hostsMapped ? "yes" : "no";
    if (swState && swState.ok) {
      proxyStateEl.textContent = swState.proxyEnabled ? `enabled (${swState.proxy})` : "disabled";
    } else {
      proxyStateEl.textContent = "(unknown)";
    }

    // Quick-add button visibility
    if (quickAddRow && quickAddBtn) {
      if (isFakeTld(domain) || status.isFakeTld) {
        quickAddRow.style.display = "none";
      } else {
        quickAddRow.style.display = "flex";
        if (isLocalByPac) {
          quickAddBtn.textContent = "➖ Remove from local list";
          quickAddBtn.style.background = "#3a1a0f";
          quickAddBtn.style.borderColor = "#92400e";
          quickAddBtn.style.color = "#fbbf24";
        } else {
          quickAddBtn.textContent = "➕ Add current domain";
          quickAddBtn.style.background = "#0f3a1a";
          quickAddBtn.style.borderColor = "#166534";
          quickAddBtn.style.color = "#4ade80";
        }
      }
    }

    try {
      const m = await fetchJson(`${CTRL_BASE}/metrics?top=5`);
      metricsSummaryEl.textContent = `${m.requestsTotal || 0} req, avg ${(m.avgLatencyMs || 0).toFixed(1)} ms`;
    } catch {
      metricsSummaryEl.textContent = "(unavailable)";
    }

    try {
      const cfg = await fetchJson(`${CTRL_BASE}/site-config?domain=${encodeURIComponent(domain)}`);
      backendOriginInput.value = cfg.backendOrigin || "";
      saveBackendBtn.disabled = false;
      clearBackendBtn.disabled = false;
      saveBackendBtn.onclick = async () => {
        try {
          const backendOrigin = (backendOriginInput.value || "").trim();
          await fetchJson(`${CTRL_BASE}/site-config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ domain, backendOrigin })
          });
          msgEl.textContent = backendOrigin ? "Backend saved." : "Backend cleared.";
          msgEl.classList.remove("err");
          const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
          const tabId = tabs && tabs[0] ? tabs[0].id : null;
          if (tabId != null) await chromeTabsReload(tabId);
        } catch (e) {
          msgEl.textContent = `Save backend failed: ${String(e.message || e)}`;
          msgEl.classList.add("err");
        }
      };
      clearBackendBtn.onclick = async () => {
        backendOriginInput.value = "";
        try {
          await fetchJson(`${CTRL_BASE}/site-config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ domain, backendOrigin: "" })
          });
          msgEl.textContent = "Backend cleared.";
          msgEl.classList.remove("err");
          const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
          const tabId = tabs && tabs[0] ? tabs[0].id : null;
          if (tabId != null) await chromeTabsReload(tabId);
        } catch (e) {
          msgEl.textContent = `Clear backend failed: ${String(e.message || e)}`;
          msgEl.classList.add("err");
        }
      };
    } catch {
      backendOriginInput.value = "";
      saveBackendBtn.disabled = true;
      clearBackendBtn.disabled = true;
    }

    // With PAC routing, hosts mapping is not required. If a user still has hosts overrides enabled,
    // it can reintroduce DNS-cache weirdness; point them to stop_all.bat.
    if (status.hostsMapped) {
      msgEl.textContent = "Note: hosts is mapped for this domain. Recommended: run stop_all.bat to disable hosts overrides and rely on proxy routing.";
    }

    if (isFakeTld(domain) || status.isFakeTld) {
      toggleRow.style.opacity = "0.65";
      toggle.disabled = true;
      toggle.checked = true;
      toggleNote.textContent = "auto";
      return;
    }

    toggleRow.style.opacity = "1";
    toggle.disabled = !proxyEnabled;
    toggle.checked = isLocalByPac;
    toggleNote.textContent = "";

    // If proxy routing is disabled, the local toggle can't take effect.
    if (swState && swState.ok && !swState.proxyEnabled) {
      toggle.disabled = true;
      toggleRow.style.opacity = "0.65";
      toggleNote.textContent = "enable proxy";
    }

    toggle.onchange = async () => {
      toggle.disabled = true;
      const newMode = toggle.checked ? "local" : "proxy";
      try {
        // Update PAC allowlist for instant routing (single source of truth).
        const data = await chromeStorageGet(["localDomains", "proxyEnabled"]);
        const enabled = data.proxyEnabled !== undefined ? !!data.proxyEnabled : true;
        const current = Array.isArray(data.localDomains) ? data.localDomains : [];
        const set = new Set(current.map((s) => String(s).toLowerCase()));
        if (newMode === "local") set.add(domain.toLowerCase());
        else set.delete(domain.toLowerCase());
        const localDomains = Array.from(set);
        await chromeStorageSet({ localDomains, proxyEnabled: enabled });
        const pacResp = await chromeRuntimeSendMessage({ type: "updatePac", localDomains, proxyEnabled: enabled });
        if (!pacResp || !pacResp.ok) {
          msgEl.textContent = `Proxy routing update failed: ${(pacResp && pacResp.error) || "unknown error"}`;
        }

        try {
          await fetchJson(`${CTRL_BASE}/client-mode?domain=${encodeURIComponent(domain)}&mode=${newMode}`, { method: "POST" });
        } catch (err_srv) {
          // ignore server registration failure when toggling locally
        }

        // Refresh UI immediately.
        await refresh();


        // Reload active tab to apply the mode.
        const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
        const tabId = tabs && tabs[0] ? tabs[0].id : null;
        if (tabId != null) {
          await chromeTabsReload(tabId);
        }
      } catch (e) {
        toggle.disabled = false;
        setStatus("bad", "error", String(e.message || e), true);
      }
    };
  } catch (e) {
    // Server offline: still show proxy state and allow turning Local off (DIRECT fallback).
    setStatus("bad", "offline", "Server is offline. You can still disable proxy routing to recover.", true);
    localSiteEl.textContent = "(unknown)";
    hostsMappedEl.textContent = "(unknown)";
    metricsSummaryEl.textContent = "(offline)";
    if (isFakeTld(domain)) modeEl.textContent = "local";
    else modeEl.textContent = isLocalByPac ? "local" : "proxy";
    if (swState && swState.ok) {
      proxyStateEl.textContent = swState.proxyEnabled ? `enabled (${swState.proxy})` : "disabled";
    } else {
      proxyStateEl.textContent = "(unknown)";
    }
    backendOriginInput.value = "";
    saveBackendBtn.disabled = true;
    clearBackendBtn.disabled = true;

    if (isFakeTld(domain)) {
      toggleRow.style.opacity = "0.65";
      toggle.disabled = true;
      toggle.checked = true;
      toggleNote.textContent = "auto";
      return;
    }

    toggleRow.style.opacity = proxyEnabled ? "1" : "0.65";
    toggle.disabled = !proxyEnabled;
    toggle.checked = isLocalByPac;
    toggleNote.textContent = proxyEnabled ? "" : "enable proxy";

    toggle.onchange = async () => {
      toggle.disabled = true;
      const newMode = toggle.checked ? "local" : "proxy";
      try {
        const data = await chromeStorageGet(["localDomains", "proxyEnabled"]);
        const enabled = data.proxyEnabled !== undefined ? !!data.proxyEnabled : true;
        const current = Array.isArray(data.localDomains) ? data.localDomains : [];
        const set = new Set(current.map((s) => String(s).toLowerCase()));
        if (newMode === "local") set.add(domain.toLowerCase());
        else set.delete(domain.toLowerCase());
        const localDomains = Array.from(set);
        await chromeStorageSet({ localDomains, proxyEnabled: enabled });
        await chromeRuntimeSendMessage({ type: "updatePac", localDomains, proxyEnabled: enabled });

        await refresh();

        const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
        const tabId = tabs && tabs[0] ? tabs[0].id : null;
        if (tabId != null) await chromeTabsReload(tabId);
      } catch (err) {
        toggle.disabled = false;
        setStatus("bad", "error", String(err.message || err), true);
      }
    };
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // If this never updates, the popup script isn't loading (reload the extension in chrome://extensions).
  const disableBtn = document.getElementById("disableProxyBtn");
  if (disableBtn) {
    disableBtn.addEventListener("click", () => {
      disableProxyAndReload();
    });
  }
  const enableBtn = document.getElementById("enableProxyBtn");
  if (enableBtn) {
    enableBtn.addEventListener("click", () => {
      enableProxyAndReload();
    });
  }
  const resetBtn = document.getElementById("resetLocalBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      resetLocalsAndReload();
    });
  }
  const optBtn = document.getElementById("openOptionsBtn");
  if (optBtn) {
    optBtn.addEventListener("click", () => {
      chrome.runtime.openOptionsPage();
    });
  }

  // Quick-add domain button: adds the current tab's domain to localDomains in one click.
  const quickAddBtn = document.getElementById("quickAddBtn");
  if (quickAddBtn) {
    quickAddBtn.addEventListener("click", async () => {
      const msgEl = document.getElementById("msg");
      try {
        const domain = await getActiveDomain();
        if (!domain) return;
        const data = await chromeStorageGet(["localDomains", "proxyEnabled"]);
        const set = new Set((data.localDomains || []).map((s) => String(s).toLowerCase()));
        if (set.has(domain.toLowerCase())) {
          // Already added – remove it instead
          set.delete(domain.toLowerCase());
        } else {
          set.add(domain.toLowerCase());
        }
        const localDomains = Array.from(set);
        const proxyEnabled = data.proxyEnabled !== undefined ? !!data.proxyEnabled : true;
        await chromeStorageSet({ localDomains, proxyEnabled });
        await chromeRuntimeSendMessage({ type: "updatePac", localDomains, proxyEnabled });

        const isAdded = set.has(domain.toLowerCase());
        try {
          const srvMode = isAdded ? "local" : "proxy";
          await fetchJson(`${CTRL_BASE}/client-mode?domain=${encodeURIComponent(domain)}&mode=${srvMode}`, { method: "POST" });
        } catch (e) {
          // ignore offline server
        }

        msgEl.textContent = isAdded ? `Added ${domain} to local list.` : `Removed ${domain} from local list.`;

        msgEl.classList.remove("err");
        const tabs = await chromeTabsQuery({ active: true, currentWindow: true });
        const tabId = tabs && tabs[0] ? tabs[0].id : null;
        if (tabId != null) await chromeTabsReload(tabId);
        await refresh();
      } catch (e) {
        msgEl.textContent = String(e.message || e);
        msgEl.classList.add("err");
      }
    });
  }

  refresh();
});
