const CTRL_BASE = "http://127.0.0.1:9080/__xai";

function setMsg(text, isErr = false) {
  const el = document.getElementById("msg");
  el.textContent = text || "";
  el.classList.toggle("err", !!isErr);
  if (text) {
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function storageGet(keys) {
  return new Promise((resolve, reject) => {
    chrome.storage.local.get(keys, (data) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(data || {});
    });
  });
}

function storageSet(data) {
  return new Promise((resolve, reject) => {
    chrome.storage.local.set(data, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

function sendMessage(msg) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(resp);
    });
  });
}

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const txt = await res.text();
  let data = {};
  try {
    data = JSON.parse(txt || "{}");
  } catch {
    throw new Error(`Bad JSON (${res.status}): ${txt.slice(0, 200)}`);
  }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function sanitizeDomain(v) {
  return String(v || "").trim().toLowerCase();
}

let backendProfiles = {};

function renderDomains(domains) {
  const body = document.getElementById("domainsBody");
  body.innerHTML = "";
  const list = Array.isArray(domains) ? domains : [];
  if (list.length === 0) {
    body.innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--muted);padding:16px">No rules registered.</td></tr>`;
    return;
  }
  for (const d of list) {
    const tr = document.createElement("tr");
    const tdDomain = document.createElement("td");
    tdDomain.textContent = d;
    const tdAct = document.createElement("td");
    const btn = document.createElement("button");
    btn.textContent = "Remove";
    btn.className = "btn-danger";
    btn.onclick = async () => {
      try {
        const current = await storageGet(["localDomains", "proxyEnabled"]);
        const set = new Set((current.localDomains || []).map((x) => String(x).toLowerCase()));
        set.delete(d);
        const localDomains = Array.from(set);
        const proxyEnabled = current.proxyEnabled !== undefined ? !!current.proxyEnabled : true;
        await storageSet({ localDomains, proxyEnabled });
        await sendMessage({ type: "updatePac", localDomains, proxyEnabled });
        await refreshAll();
      } catch (e) {
        setMsg(String(e.message || e), true);
      }
    };
    tdAct.appendChild(btn);
    tr.appendChild(tdDomain);
    tr.appendChild(tdAct);
    body.appendChild(tr);
  }
}

async function refreshAll() {
  try {
    const state = await sendMessage({ type: "getState" });
    if (!state || !state.ok) throw new Error("Failed to read extension state");
    document.getElementById("proxyEnabled").checked = !!state.proxyEnabled;
    renderDomains(state.localDomains || []);
    setMsg(`Loaded ${state.localDomains.length || 0} local domains. Proxy: ${state.proxyEnabled ? "enabled" : "disabled"}`);
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

async function saveProxyState() {
  try {
    const enabled = !!document.getElementById("proxyEnabled").checked;
    const data = await storageGet(["localDomains"]);
    const localDomains = Array.isArray(data.localDomains) ? data.localDomains : [];
    await storageSet({ localDomains, proxyEnabled: enabled });
    await sendMessage({ type: "updatePac", localDomains, proxyEnabled: enabled });
    setMsg(`Proxy routing ${enabled ? "enabled" : "disabled"}.`);
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

async function addDomain() {
  const v = sanitizeDomain(document.getElementById("newDomain").value);
  if (!v) return;
  try {
    const data = await storageGet(["localDomains", "proxyEnabled"]);
    const set = new Set((data.localDomains || []).map((x) => String(x).toLowerCase()));
    set.add(v);
    const localDomains = Array.from(set);
    const proxyEnabled = data.proxyEnabled !== undefined ? !!data.proxyEnabled : true;
    await storageSet({ localDomains, proxyEnabled });
    await sendMessage({ type: "updatePac", localDomains, proxyEnabled });
    document.getElementById("newDomain").value = "";
    await refreshAll();
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

async function clearDomains() {
  try {
    const data = await storageGet(["proxyEnabled"]);
    const proxyEnabled = data.proxyEnabled !== undefined ? !!data.proxyEnabled : true;
    await storageSet({ localDomains: [], proxyEnabled });
    await sendMessage({ type: "updatePac", localDomains: [], proxyEnabled });
    await refreshAll();
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

async function loadSiteConfig() {
  const domain = sanitizeDomain(document.getElementById("cfgDomain").value);
  if (!domain) return;
  try {
    const cfg = await fetchJson(`${CTRL_BASE}/site-config?domain=${encodeURIComponent(domain)}`);
    document.getElementById("cfgEntry").value = cfg.entry || "index.html";
    document.getElementById("cfgBackend").value = cfg.backendOrigin || "";
    document.getElementById("cfgBackendType").value = cfg.backendType || "";
    document.getElementById("cfgBackendProfile").value = cfg.backendProfile || "";
    document.getElementById("cfgHealthPath").value = cfg.backendHealthPath || "";
    document.getElementById("cfgWsPath").value = cfg.backendWsPath || "";
    setMsg(`Loaded config for ${domain}.`);
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

async function saveSiteConfig(clearBackend = false) {
  const domain = sanitizeDomain(document.getElementById("cfgDomain").value);
  if (!domain) {
    setMsg("Domain is required for config save.", true);
    return;
  }
  const entry = (document.getElementById("cfgEntry").value || "index.html").trim() || "index.html";
  const backendOrigin = clearBackend ? "" : (document.getElementById("cfgBackend").value || "").trim();
  const backendType = (document.getElementById("cfgBackendType").value || "").trim();
  const backendProfile = (document.getElementById("cfgBackendProfile").value || "").trim();
  const backendHealthPath = (document.getElementById("cfgHealthPath").value || "").trim();
  const backendWsPath = (document.getElementById("cfgWsPath").value || "").trim();
  try {
    await fetchJson(`${CTRL_BASE}/site-config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain, entry, backendOrigin, backendType, backendProfile, backendHealthPath, backendWsPath })
    });
    if (clearBackend) document.getElementById("cfgBackend").value = "";
    setMsg(`Saved config for ${domain}.`);
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

async function loadMetrics() {
  try {
    const m = await fetchJson(`${CTRL_BASE}/metrics?top=15`);
    document.getElementById("metricsOut").textContent = JSON.stringify(m, null, 2);
    setMsg("Metrics loaded.");
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

async function loadDashboardStats() {
  try {
    const m = await fetchJson(`${CTRL_BASE}/metrics?top=5`);
    const total = m.requestsTotal || 0;
    const avg = total > 0 ? (m.latencyMsTotal / total) : 0;
    document.getElementById("stat-total-req").textContent = total;
    document.getElementById("stat-avg-latency").textContent = `${avg.toFixed(1)} ms`;
  } catch (e) {
    console.error("Dashboard stats failed:", e);
  }
}

async function loadProfiles() {
  try {
    const data = await fetchJson(`${CTRL_BASE}/backend-profiles`);
    backendProfiles = data.profiles || {};
    const sel = document.getElementById("cfgBackendProfile");
    sel.innerHTML = '<option value="">(none)</option>';
    Object.keys(backendProfiles).sort().forEach((k) => {
      const opt = document.createElement("option");
      opt.value = k;
      opt.textContent = k;
      sel.appendChild(opt);
    });
  } catch (e) {
    setMsg(`Profile load failed: ${String(e.message || e)}`, true);
  }
}

function applySelectedProfile() {
  const key = (document.getElementById("cfgBackendProfile").value || "").trim();
  if (!key || !backendProfiles[key]) return;
  const p = backendProfiles[key];
  document.getElementById("cfgBackendType").value = p.type || "";
  if (!document.getElementById("cfgHealthPath").value) {
    document.getElementById("cfgHealthPath").value = p.healthPath || "";
  }
  if (!document.getElementById("cfgWsPath").value) {
    document.getElementById("cfgWsPath").value = p.wsPath || "";
  }
  setMsg(`Applied profile ${key}.`);
}

async function probeBackend() {
  const domain = sanitizeDomain(document.getElementById("cfgDomain").value);
  if (!domain) {
    setMsg("Domain is required for backend probe.", true);
    return;
  }
  const wsPath = String(document.getElementById("probeWsPath").value || "").trim();
  try {
    const u = `${CTRL_BASE}/backend-probe?domain=${encodeURIComponent(domain)}&wsPath=${encodeURIComponent(wsPath)}`;
    const data = await fetchJson(u);
    document.getElementById("probeOut").textContent = JSON.stringify(data, null, 2);
    setMsg("Backend probe loaded.");
  } catch (e) {
    document.getElementById("probeOut").textContent = String(e.message || e);
    setMsg(String(e.message || e), true);
  }
}

async function loadHealth() {
  const domains = String(document.getElementById("healthDomains").value || "").trim();
  const wsPath = String(document.getElementById("healthWsPath").value || "").trim();
  try {
    const q = new URLSearchParams();
    if (domains) q.set("domains", domains);
    if (wsPath) q.set("wsPath", wsPath);
    q.set("max", "80");
    const data = await fetchJson(`${CTRL_BASE}/health?${q.toString()}`);
    document.getElementById("healthOut").textContent = JSON.stringify(data, null, 2);
    setMsg("Health loaded.");
  } catch (e) {
    document.getElementById("healthOut").textContent = String(e.message || e);
    setMsg(String(e.message || e), true);
  }
}

// --- Tethered Devices Functions ---
let serverLanIp = "127.0.0.1";

async function loadLanIp() {
  try {
    const res = await fetchJson(`${CTRL_BASE}/status?domain=www.google.com`);
    serverLanIp = res.lanIp || "127.0.0.1";
    document.getElementById("tether-lan-ip").textContent = serverLanIp;
    
    // Update link texts
    document.querySelectorAll(".lan-ip-text").forEach(el => el.textContent = serverLanIp);
    const portalLink = document.getElementById("tether-portal-link");
    portalLink.href = `http://${serverLanIp}:9080/__xai/portal?domain=www.google.com`;
    portalLink.innerHTML = `http://${serverLanIp}:9080/__xai/portal`;

    const caLink = document.getElementById("tether-ca-link");
    if (caLink) {
      caLink.href = `http://${serverLanIp}:9080/__xai/ca`;
      caLink.innerHTML = `http://${serverLanIp}:9080/__xai/ca`;
    }

    const qrImg = document.getElementById("tether-qr-img");
    if (qrImg) {
      qrImg.src = `http://${serverLanIp}:9080/__xai/qr?text=${encodeURIComponent(`http://${serverLanIp}:9080/__xai/ca`)}`;
    }
  } catch (err) {
    console.error("Failed to load LAN IP:", err);
  }
}

async function loadClientOverrides() {
  try {
    const data = await fetchJson(`${CTRL_BASE}/client-overrides`);
    const body = document.getElementById("clientOverridesBody");
    body.innerHTML = "";
    const overrides = data.overrides || {};
    
    let hasKeys = false;
    for (const ip of Object.keys(overrides)) {
      const domains = overrides[ip] || {};
      for (const d of Object.keys(domains)) {
        hasKeys = true;
        const mode = domains[d];
        const tr = document.createElement("tr");
        
        tr.innerHTML = `
          <td style="font-family:'JetBrains Mono',monospace;color:#a5b4fc">${ip}</td>
          <td style="font-family:'JetBrains Mono',monospace;color:#fbbf24">${d}</td>
          <td><span class="pill" style="color:${mode === 'proxy' ? '#4ade80' : '#818cf8'};background:rgba(255,255,255,0.03);text-transform:uppercase">${mode}</span></td>
          <td><button class="btn-danger btn-sm-remove" data-ip="${ip}" data-domain="${d}">Remove</button></td>
        `;
        body.appendChild(tr);
      }
    }
    
    if (!hasKeys) {
      body.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:24px">No active overrides registered.</td></tr>`;
      return;
    }
    
    // Wire up delete buttons
    body.querySelectorAll(".btn-sm-remove").forEach(btn => {
      btn.onclick = async () => {
        const ip = btn.getAttribute("data-ip");
        const domain = btn.getAttribute("data-domain");
        try {
          await fetchJson(`${CTRL_BASE}/client-overrides?clientIp=${encodeURIComponent(ip)}&domain=${encodeURIComponent(domain)}`, {
            method: "DELETE"
          });
          setMsg(`Override cleared for ${ip} -> ${domain}`);
          loadClientOverrides();
        } catch (e) {
          setMsg(String(e.message || e), true);
        }
      };
    });
  } catch (err) {
    console.error("Overrides load failed:", err);
  }
}

async function addClientOverride() {
  const ip = document.getElementById("clientIpInput").value.trim();
  const domain = sanitizeDomain(document.getElementById("clientDomainInput").value);
  const mode = document.getElementById("clientModeSelect").value;
  
  if (!ip || !domain) {
    setMsg("Device IP and Intercepted Domain are required.", true);
    return;
  }
  
  try {
    await fetchJson(`${CTRL_BASE}/client-overrides`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clientIp: ip, domain, mode })
    });
    setMsg(`Override registered successfully: ${ip} -> ${domain} [${mode}]`);
    document.getElementById("clientIpInput").value = "";
    document.getElementById("clientDomainInput").value = "";
    loadClientOverrides();
  } catch (e) {
    setMsg(String(e.message || e), true);
  }
}

// --- GitHub Functions ---
async function ghCall(path, body) {
  const opts = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }
    : undefined;
  return fetchJson(`${CTRL_BASE}${path}`, opts);
}

function ghShow(text) {
  document.getElementById("ghOut").textContent = text || "(none)";
}

async function ghList() {
  try {
    const r = await ghCall("/github/list");
    ghShow(r.output || "(empty)");
    setMsg("GitHub list loaded.");
  } catch (e) {
    ghShow(String(e.message || e));
    setMsg(String(e.message || e), true);
  }
}

async function ghStatus() {
  try {
    const r = await ghCall("/github/status");
    ghShow(r.output || "(empty)");
    setMsg("GitHub status loaded.");
  } catch (e) {
    ghShow(String(e.message || e));
    setMsg(String(e.message || e), true);
  }
}

async function ghAdd() {
  const domain = sanitizeDomain(document.getElementById("ghDomain").value);
  const repoUrl = String(document.getElementById("ghRepo").value || "").trim();
  const branch = String(document.getElementById("ghBranch").value || "main").trim() || "main";
  if (!domain || !repoUrl) {
    setMsg("GitHub add needs domain and repo URL.", true);
    return;
  }
  try {
    const r = await ghCall("/github/add", { domain, repoUrl, branch });
    ghShow(r.output || "ok");
    setMsg("GitHub source added/updated.");
  } catch (e) {
    ghShow(String(e.message || e));
    setMsg(String(e.message || e), true);
  }
}

async function ghPull() {
  const domain = sanitizeDomain(document.getElementById("ghDomain").value);
  if (!domain) {
    setMsg("GitHub pull needs a domain.", true);
    return;
  }
  try {
    const r = await ghCall("/github/pull", { domain });
    ghShow(r.output || "ok");
    setMsg("GitHub pull complete.");
  } catch (e) {
    ghShow(String(e.message || e));
    setMsg(String(e.message || e), true);
  }
}

async function ghPullAll() {
  try {
    const r = await ghCall("/github/pull-all", {});
    ghShow(r.output || "ok");
    setMsg("GitHub pull-all complete.");
  } catch (e) {
    ghShow(String(e.message || e));
    setMsg(String(e.message || e), true);
  }
}

async function ghRemove() {
  const domain = sanitizeDomain(document.getElementById("ghDomain").value);
  if (!domain) {
    setMsg("GitHub remove needs a domain.", true);
    return;
  }
  const keepFiles = !!document.getElementById("ghKeepFiles").checked;
  try {
    const r = await ghCall("/github/remove", { domain, keepFiles });
    ghShow(r.output || "ok");
    setMsg("GitHub mapping removed.");
  } catch (e) {
    ghShow(String(e.message || e));
    setMsg(String(e.message || e), true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // Navigation Sidebar
  const tabs = document.querySelectorAll(".sidebar-item");
  const sections = document.querySelectorAll(".dashboard-section");
  const pageTitle = document.getElementById("page-title");
  const pageSubtitle = document.getElementById("page-subtitle");

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      sections.forEach(s => s.classList.remove("active"));

      tab.classList.add("active");
      const targetId = tab.getAttribute("data-target");
      const targetSection = document.getElementById(targetId);
      if (targetSection) targetSection.classList.add("active");

      // Update titles
      const spanText = tab.querySelector("span").textContent;
      pageTitle.textContent = spanText;

      if (spanText === "Console Dashboard") {
        pageSubtitle.textContent = "Real-time HTTP requests diagnostics stream.";
        loadDashboardStats();
      } else if (spanText === "Local DNS Rules") {
        pageSubtitle.textContent = "Manage proxy bypass PAC domains dynamically.";
      } else if (spanText === "Backend Config") {
        pageSubtitle.textContent = "Configure port mappings and local proxy profiles.";
      } else if (spanText === "Tethered Devices") {
        pageSubtitle.textContent = "Intercept local network devices bypass override.";
        loadClientOverrides();
        loadLanIp();
      } else if (spanText === "GitHub Repos") {
        pageSubtitle.textContent = "Map GitHub remote origins to host templates.";
      }
    });
  });

  document.getElementById("saveProxy").addEventListener("click", saveProxyState);
  document.getElementById("refreshAll").addEventListener("click", () => {
    refreshAll();
    loadDashboardStats();
    loadClientOverrides();
  });
  document.getElementById("addDomain").addEventListener("click", addDomain);
  document.getElementById("clearDomains").addEventListener("click", clearDomains);
  document.getElementById("loadCfg").addEventListener("click", loadSiteConfig);
  document.getElementById("saveCfg").addEventListener("click", () => saveSiteConfig(false));
  document.getElementById("clearBackend").addEventListener("click", () => saveSiteConfig(true));
  document.getElementById("applyProfile").addEventListener("click", applySelectedProfile);
  document.getElementById("probeBackend").addEventListener("click", probeBackend);
  document.getElementById("loadMetrics").addEventListener("click", loadMetrics);
  document.getElementById("loadHealth").addEventListener("click", loadHealth);
  document.getElementById("ghList").addEventListener("click", ghList);
  document.getElementById("ghStatus").addEventListener("click", ghStatus);
  document.getElementById("ghAdd").addEventListener("click", ghAdd);
  document.getElementById("ghPull").addEventListener("click", ghPull);
  document.getElementById("ghPullAll").addEventListener("click", ghPullAll);
  document.getElementById("ghRemove").addEventListener("click", ghRemove);
  document.getElementById("addClientOverrideBtn").addEventListener("click", addClientOverride);

  // Initial Load
  loadProfiles();
  refreshAll();
  loadDashboardStats();
  loadLanIp();

  // Poller for dashboard stats
  setInterval(() => {
    if (document.getElementById("sec-dashboard").classList.contains("active")) {
      loadDashboardStats();
    }
  }, 3000);

  // --- Live Request Dashboard SSE ---
  let eventSource = null;

  function streamStatusText(text) {
    const el = document.getElementById("streamStatus");
    if (el) el.textContent = text;
  }

  function addStreamRow(entry) {
    const body = document.getElementById("streamBody");
    if (!body) return;
    const tr = document.createElement("tr");

    const time = new Date(entry.ts || Date.now()).toLocaleTimeString();
    const statusColor = entry.status < 300 ? "#10b981" : entry.status < 400 ? "#fbbf24" : "#ef4444";
    const modeColor = entry.mode === "local" ? "#6366f1" : "#9ca3af";

    tr.innerHTML = `
      <td style="font-family:'JetBrains Mono',monospace;color:var(--muted)">${time}</td>
      <td style="font-weight:600;color:var(--fg)">${entry.domain || "-"}</td>
      <td><span class="pill" style="color:${modeColor};text-transform:uppercase">${entry.mode || "-"}</span></td>
      <td><span style="color:${statusColor};font-weight:700">${entry.status || "-"}</span></td>
      <td style="text-align:right;font-family:'JetBrains Mono',monospace;color:var(--muted)">${(entry.latencyMs || 0).toFixed(1)} ms</td>
    `;
    body.insertBefore(tr, body.firstChild);

    // Cap visible rows
    while (body.children.length > 200) {
      body.removeChild(body.lastChild);
    }
  }

  document.getElementById("startStream").addEventListener("click", () => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    try {
      eventSource = new EventSource(`${CTRL_BASE}/stream-logs`);
      streamStatusText("streaming...");
      eventSource.onmessage = (ev) => {
        try {
          const entry = JSON.parse(ev.data);
          addStreamRow(entry);
        } catch {}
      };
      eventSource.onerror = () => {
        streamStatusText("disconnected");
        eventSource.close();
        eventSource = null;
      };
    } catch (e) {
      streamStatusText("error: " + String(e.message || e));
    }
  });

  document.getElementById("stopStream").addEventListener("click", () => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    streamStatusText("stopped");
  });

  document.getElementById("clearStream").addEventListener("click", () => {
    const body = document.getElementById("streamBody");
    if (body) body.innerHTML = "";
  });
});
