#!/usr/bin/env node
/**
 * IOTA Train at Home — telemetry poller (runs in GitHub Actions, no deps).
 *
 * Reads the Macrocosmos public API for two miners, computes detailed status,
 * and writes data/miners.json encrypted with the SAME scheme the watchdog
 * page already uses: { v:1, alg:"AES-256-CBC", salt, iv, data } where
 * key = PBKDF2(password, salt, 100000, SHA-256, 32 bytes), AES-256-CBC.
 *
 * Env:
 *   M3_HOTKEY, M1_HOTKEY        miner hotkeys (GitHub Secrets)
 *   M3_LABEL, M1_LABEL          display names (optional, defaults below)
 *   TELEMETRY_PASSWORD          page unlock password (GitHub Secret)
 *   OUTPUT_PATH                 default: data/miners.json
 *   PLAINTEXT=1                 write plaintext JSON instead (local testing only!)
 */
import { pbkdf2Sync, randomBytes, createCipheriv } from 'node:crypto';
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname } from 'node:path';

const API = 'https://iota-web.api.macrocosmos.ai/mainnet';
const TZ = 'America/Toronto';

async function getJSON(url) {
  const r = await fetch(url, { headers: { 'accept': 'application/json' } });
  if (!r.ok) throw new Error(`GET ${url} -> ${r.status}`);
  return r.json();
}

// The /runs list is the poller's single point of failure: without it nothing
// can be computed. Ride out transient API errors (5xx during network
// incidents) with a few retries before giving up.
async function getJSONWithRetry(url, attempts = 4) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await getJSON(url);
    } catch (e) {
      lastErr = e;
      console.error(`GET ${url} attempt ${i + 1}/${attempts} failed: ${e.message}`);
      if (i < attempts - 1) await new Promise(res => setTimeout(res, 5000 * (i + 1)));
    }
  }
  throw lastErr;
}

// ---------- Toronto settlement boundary (daily 20:00 local) ----------
const dtf = new Intl.DateTimeFormat('en-US', {
  timeZone: TZ, hour12: false,
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit',
});
function torontoParts(ms) {
  const p = {};
  for (const { type, value } of dtf.formatToParts(new Date(ms))) p[type] = value;
  return p;
}
function zonedToUTC(y, mo, d, h, mi) {
  const desired = Date.UTC(y, mo - 1, d, h, mi, 0); // target wall time read as UTC
  let guess = desired;
  for (let i = 0; i < 3; i++) {
    const p = torontoParts(guess);
    const asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, (+p.hour) % 24, +p.minute, +p.second);
    const diff = desired - asUTC;
    guess += diff;
    if (diff === 0) break;
  }
  return guess;
}
function lastSettlementMs(nowMs) {
  const p = torontoParts(nowMs);
  let y = +p.year, mo = +p.month, d = +p.day;
  let boundary = zonedToUTC(y, mo, d, 20, 0);
  if (boundary > nowMs) {
    const prev = new Date(Date.UTC(y, mo - 1, d) - 86400000);
    boundary = zonedToUTC(prev.getUTCFullYear(), prev.getUTCMonth() + 1, prev.getUTCDate(), 20, 0);
  }
  return boundary;
}

// ---------- per-miner analysis ----------
function valueAt(points, ms) {
  let v = null;
  for (const pt of points) {
    if (pt.timestamp * 1000 <= ms) v = pt.token_count; else break;
  }
  return v;
}
function analyzeSeries(points) {
  if (!points.length) return null;
  const last = points[points.length - 1];
  let maxTokens = 0;
  for (const pt of points) if (pt.token_count > maxTokens) maxTokens = pt.token_count;
  // most recent growth moment
  let growthTs = null;
  for (let i = points.length - 1; i > 0; i--) {
    if (points[i].token_count > points[i - 1].token_count) { growthTs = points[i].timestamp; break; }
  }
  const flatSec = growthTs ? (last.timestamp - growthTs) : null;
  let lastActiveTs = null;
  for (const pt of points) if (pt.token_count > 0) lastActiveTs = pt.timestamp;
  // pace over trailing hour (or longest available span up to 1h)
  const nowMs = last.timestamp * 1000;
  const hourAgoValue = valueAt(points, nowMs - 3600_000);
  let pacePerHour = null;
  if (hourAgoValue !== null && nowMs - 3600_000 >= points[0].timestamp * 1000) {
    pacePerHour = Math.round((last.token_count - hourAgoValue));
  } else if (points.length > 1) {
    const spanH = (last.timestamp - points[0].timestamp) / 3600;
    if (spanH > 0.05) pacePerHour = Math.round((last.token_count - points[0].token_count) / spanH);
  }
  return {
    latestTokens: last.token_count,
    latestTs: last.timestamp,
    latestFrac: last.contribution_fraction ?? null,
    maxTokens,
    lastActiveTs,
    growthTs,
    flatSec,
    pacePerHour,
  };
}

async function analyzeMiner(hotkey, runs, boundaryMs) {
  let best = null;      // current run (latest tokens > 0)
  let bestHist = null;  // run with highest historical max (for "last run" when out)
  const runMiners = {}; // run_id -> num_miners (run-wide, from any miner's response)
  for (const run of runs) {
    let resp;
    try {
      resp = await getJSON(`${API}/miners/${hotkey}/runs/${run.run_id}/tokens`);
    } catch (e) {
      continue;
    }
    if (resp.num_miners != null) runMiners[run.run_id] = resp.num_miners;
    const pts = (resp.data_points || []).slice().sort((a, b) => a.timestamp - b.timestamp);
    const a = analyzeSeries(pts);
    if (!a) continue;
    const rec = { run, a, rank: resp.rank ?? null, numMiners: resp.num_miners ?? null, points: pts };
    // Current run = the one whose tokens GREW most recently. A dead series keeps
    // emitting fresh flat samples, so last-sample time alone picks the wrong run.
    const growthKey = a.growthTs ?? (pts.length && pts[0].token_count > 0 ? pts[0].timestamp : a.latestTs);
    if (a.latestTokens > 0 && (!best || growthKey > best.growthKey)) best = { ...rec, growthKey };
    if (!bestHist || (a.lastActiveTs ?? -1) > (bestHist.a.lastActiveTs ?? -1)) bestHist = rec;
  }
  const chosen = best || bestHist;
  if (!chosen) return { status: 'unknown', runMiners };
  const { run, a } = chosen;
  const boundaryVal = valueAt(chosen.points, boundaryMs);
  const todayTokens = a.latestTokens > 0 && boundaryVal !== null
    ? Math.max(0, a.latestTokens - boundaryVal) : 0;
  let status;
  if (!best) status = 'out';                       // no run with tokens > 0
  else if (a.flatSec !== null && a.flatSec > 1800) status = 'stalled'; // in run, flat > 30 min
  else status = 'producing';
  return {
    status,
    run_id: best ? run.run_id : null,
    last_run_id: run.run_id,
    tier: run.tier,
    tokens: a.latestTokens,
    series_max: a.maxTokens,
    frac: a.latestFrac,
    rank: chosen.rank,
    num_miners: chosen.numMiners,
    pace_per_hour: a.pacePerHour,
    flat_minutes: a.flatSec !== null ? Math.round(a.flatSec / 60) : null,
    today_tokens: todayTokens,
    updated_ts: a.latestTs,
    runMiners,
  };
}

function tierOf(run) {
  const desc = run?.metadata?.description || '';
  const m = desc.match(/Tier\s*(\d+)\s*\(([^)]+)\)/i);
  if (m) return `Tier ${m[1]} ${m[2]}`;
  return desc || '';
}

// ---------- main ----------
// Config: secrets arrive via telemetry.config.json (created by the workflow
// from GitHub Secrets; never committed). Hotkeys may also come from env.
let cfg = {};
try { cfg = JSON.parse(readFileSync(new URL('./telemetry.config.json', import.meta.url), 'utf8')); } catch {}
const machines = [
  { id: 'm3', label: process.env.M3_LABEL || 'M3 Pro', hotkey: cfg.m3 || process.env.M3_HOTKEY },
  { id: 'm1', label: process.env.M1_LABEL || 'M1 Pro', hotkey: cfg.m1 || process.env.M1_HOTKEY },
].filter(m => m.hotkey);

if (!machines.length) { console.error('No hotkeys configured (M3_HOTKEY / M1_HOTKEY).'); process.exit(1); }

const runsResp = await getJSONWithRetry(`${API}/runs`);
const runs = (runsResp.runs || []).map(r => ({ ...r, tier: tierOf(r) }));
const boundaryMs = lastSettlementMs(Date.now());

const out = {
  v: 1,
  generated_at: new Date().toISOString(),
  settlement_last: new Date(boundaryMs).toISOString(),
  runs: [],
  machines: [],
};
const mergedRunMiners = {};
for (const m of machines) {
  const res = await analyzeMiner(m.hotkey, runs, boundaryMs);
  Object.assign(mergedRunMiners, res.runMiners || {});
  delete res.runMiners;
  out.machines.push({ id: m.id, label: m.label, hotkey_tail: m.hotkey.slice(-6), ...res });
  console.log(m.id, res.status, res.run_id || res.last_run_id, res.tokens);
}
out.runs = runs.map(r => ({
  run_id: r.run_id, tier: r.tier, state: r.state, is_default: !!r.is_default,
  num_miners: mergedRunMiners[r.run_id] ?? null,
}));
out.network = { active_runs: runs.length, num_miners: out.machines.find(m => m.num_miners)?.num_miners ?? null };

const outPath = process.env.OUTPUT_PATH || 'data/telemetry/miners.json';
mkdirSync(dirname(outPath), { recursive: true });

if (process.env.PLAINTEXT === '1') {
  writeFileSync(outPath, JSON.stringify(out, null, 2));
  console.log('Wrote PLAINTEXT (testing only):', outPath);
} else {
  const unlockKey = cfg.unlock || null;
  if (!unlockKey) { console.error('unlock key missing: create telemetry.config.json (see README section in workflow).'); process.exit(1); }
  const salt = randomBytes(16);
  const iv = randomBytes(16);
  const key = pbkdf2Sync(Buffer.from(unlockKey, 'utf8'), salt, 100000, 32, 'sha256');
  const cipher = createCipheriv('aes-256-cbc', key, iv);
  const ct = Buffer.concat([cipher.update(JSON.stringify(out), 'utf8'), cipher.final()]);
  const packet = {
    v: 1, alg: 'AES-256-CBC',
    salt: salt.toString('base64'), iv: iv.toString('base64'), data: ct.toString('base64'),
  };
  writeFileSync(outPath, JSON.stringify(packet));
  console.log('Wrote encrypted packet:', outPath);
}
