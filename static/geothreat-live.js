/**
 * AEGLOS Analytics Pro — Live Data Connector
 * All data is fetched from the local API. No demo or fallback data.
 */

const API_BASE = '';  // same-origin: all requests proxy through Flask
const POLL_INTERVAL_MS = 30_000;

let liveMode = false;
let pollTimer = null;

// ── Connection status (topbar indicator) ──────────────────────────────────────
function showBanner(live) {
  const el = document.getElementById('live-status');
  if (!el) return;
  el.style.display = 'block';
  if (live) {
    el.textContent = 'LIVE';
    el.style.background = 'rgba(239,68,68,.15)';
    el.style.color = 'var(--critical, #ef4444)';
    el.style.border = '1px solid rgba(239,68,68,.35)';
  } else {
    el.textContent = 'OFFLINE';
    el.style.background = 'rgba(100,116,139,.15)';
    el.style.color = 'var(--muted, #64748b)';
    el.style.border = '1px solid rgba(100,116,139,.3)';
  }
}

function showSectionError(elementId, message) {
  const el = document.getElementById(elementId);
  if (el) el.innerHTML = `<div style="color:#ef4444;text-align:center;padding:3rem;font-size:.8rem;font-family:'IBM Plex Mono',monospace;">${message}</div>`;
}

// ── API helpers ───────────────────────────────────────────────────────────────
async function checkApiAvailability() {
  try {
    const r = await fetch('/health', { signal: AbortSignal.timeout(15000) });
    return r.ok;
  } catch {
    return false;
  }
}

async function apiFetch(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const r = await fetch(url.toString(), { signal: AbortSignal.timeout(15_000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function triggerIngest() {
  try {
    await fetch('/api/v1/geothreat/ingest', { method: 'POST', signal: AbortSignal.timeout(45_000) });
  } catch { /* non-fatal */ }
}

// ── Live updaters ─────────────────────────────────────────────────────────────
async function updateStats() {
  const data = await apiFetch('/api/v1/geothreat/statistics');
  window.dispatchEvent(new CustomEvent('geothreat:stats', { detail: data }));
}

async function updateEvents() {
  const data = await apiFetch('/api/v1/geothreat/stories', { limit: 200, translate: true });
  window.dispatchEvent(new CustomEvent('geothreat:events', { detail: data }));
}

async function updateSources() {
  const data = await apiFetch('/api/v1/geothreat/sources');
  window._lastSources = data.sources || [];
  window.dispatchEvent(new CustomEvent('geothreat:sources', { detail: data }));
}

async function updateRegions() {
  const data = await apiFetch('/api/v1/geothreat/regions');
  window.dispatchEvent(new CustomEvent('geothreat:regions', { detail: data }));
}

async function updateForecast() {
  const data = await apiFetch('/api/v1/geothreat/forecast');
  window.dispatchEvent(new CustomEvent('geothreat:forecast', { detail: data }));
}

async function updatePatterns() {
  const data = await apiFetch('/api/v1/geothreat/patterns');
  window.dispatchEvent(new CustomEvent('geothreat:patterns', { detail: data }));
}

async function updateCorrelation() {
  const data = await apiFetch('/api/v1/geothreat/correlation');
  window.dispatchEvent(new CustomEvent('geothreat:correlation', { detail: data }));
}

// ── Poll cycle ────────────────────────────────────────────────────────────────
async function pollLiveData() {
  if (!liveMode) return;
  const results = await Promise.allSettled([
    updateStats(),
    updateEvents(),
    updateSources(),
    updateRegions(),
    updateForecast(),
    updatePatterns(),
    updateCorrelation(),
  ]);
  const anyFailed = results.some(r => r.status === 'rejected');
  if (anyFailed) {
    results.forEach((r, i) => {
      if (r.status === 'rejected') {
        const names = ['stats','stories','sources','regions','forecast','patterns','correlation'];
        console.warn(`[AEGLOS] ${names[i]} update failed:`, r.reason?.message);
      }
    });
    const alive = await checkApiAvailability();
    if (!alive) {
      liveMode = false;
      showBanner(false);
      clearInterval(pollTimer);
      ['feed-items','alerts-container','source-cards','region-cards'].forEach(id =>
        showSectionError(id, 'API CONNECTION LOST — ATTEMPTING RECONNECT')
      );
      setTimeout(init, 10_000);
    }
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  const alive = await checkApiAvailability();
  liveMode = alive;
  showBanner(alive);

  if (alive) {
    triggerIngest(); // fire-and-forget background ingest
    await pollLiveData();
    pollTimer = setInterval(pollLiveData, POLL_INTERVAL_MS);
  } else {
    ['feed-items','alerts-container','source-cards','region-cards'].forEach(id =>
      showSectionError(id, 'API OFFLINE — WAITING FOR CONNECTION')
    );
    setTimeout(init, 10_000);
  }
}

document.addEventListener('DOMContentLoaded', init);
