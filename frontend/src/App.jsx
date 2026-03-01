import { useEffect, useMemo, useRef, useState } from "react";
import FlowCanvas from "./components/FlowCanvas";
import GalaxyCanvas from "./components/GalaxyCanvas";
import RecentRequestsGrid from "./components/RecentRequestsGrid";
import { useEventStream } from "./hooks/useEventStream";
import { useModelCatalog } from "./hooks/useModelCatalog";
import { useModelMetrics } from "./hooks/useModelMetrics";

export default function App() {
  const [topModelCount, setTopModelCount] = useState(20);
  const [viewMode, setViewMode] = useState("galaxy");
  const [windowSeconds, setWindowSeconds] = useState(60);
  const [riskThreshold, setRiskThreshold] = useState(0.8);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [alertTone, setAlertTone] = useState("siren");
  const [tonePauseSeconds, setTonePauseSeconds] = useState(30);
  const [showEventDetails, setShowEventDetails] = useState(true);
  const [showModelIntel, setShowModelIntel] = useState(true);
  const [showModelNames, setShowModelNames] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [riskInfoOpen, setRiskInfoOpen] = useState(false);
  const [latencySloMs, setLatencySloMs] = useState(1200);
  const [tokenSloTps, setTokenSloTps] = useState(120);
  const [healthThresholds, setHealthThresholds] = useState({
    warm: 0.2,
    degrading: 0.5,
    critical: 0.8,
  });
  const [gridFilters, setGridFilters] = useState({
    query: "",
    status: "",
    service: "",
    model: "",
    user: "",
    timeMode: "all",
    timeFrom: "",
    timeTo: "",
  });

  const settingsRef = useRef(null);
  const riskInfoRef = useRef(null);
  const audioCtxRef = useRef(null);
  const lastAlertAtRef = useRef(0);
  const prevAboveRef = useRef(false);

  const { events, connected } = useEventStream({});
  const { models: modelCatalog } = useModelCatalog();
  const metricsOptions = useMemo(
    () => ({
      user: gridFilters.user,
      model: gridFilters.model,
      service: gridFilters.service,
      status: gridFilters.status,
      timeMode: gridFilters.timeMode,
      timeFrom: gridFilters.timeFrom,
      timeTo: gridFilters.timeTo,
      latencySloMs,
      tokenSloTps,
      healthThresholds,
    }),
    [gridFilters, latencySloMs, tokenSloTps, healthThresholds]
  );
  const { metrics, updatedAt } = useModelMetrics(windowSeconds, metricsOptions);

  const maxRisk = useMemo(
    () => (metrics.length ? Math.max(...metrics.map((m) => Number(m.risk_score || 0))) : 0),
    [metrics]
  );

  const highRiskCount = useMemo(
    () => metrics.filter((m) => Number(m.risk_score || 0) >= riskThreshold).length,
    [metrics, riskThreshold]
  );

  const riskTooltip = useMemo(() => {
    const top = [...metrics]
      .sort((a, b) => Number(b.risk_score || 0) - Number(a.risk_score || 0))
      .slice(0, 5)
      .map((m) => `${m.model_id}: ${Number(m.risk_score || 0).toFixed(2)}`)
      .join(" | ");
    return `Threshold >= ${riskThreshold}. Max risk: ${maxRisk.toFixed(2)}. Top: ${top || "no data"}`;
  }, [metrics, riskThreshold, maxRisk]);
  const topRiskRows = useMemo(
    () =>
      [...metrics]
        .sort((a, b) => Number(b.risk_score || 0) - Number(a.risk_score || 0))
        .slice(0, 5),
    [metrics]
  );
  const riskConfigTooltip =
    "Risk score formula: 0.5*failure_rate + 0.3*normalized_p95_latency + 0.2*normalized_token_rate. " +
    `SLO caps: latency=${latencySloMs}ms, token_rate=${tokenSloTps} tps. ` +
    `Health thresholds: healthy<${healthThresholds.warm}, warm<${healthThresholds.degrading}, degrading<${healthThresholds.critical}, critical>=${healthThresholds.critical}. ` +
    "Alert triggers when any model risk_score >= selected threshold.";

  function playAlertSound(durationSec = 10) {
    try {
      if (!audioCtxRef.current) return;
      const ctx = audioCtxRef.current;
      const start = ctx.currentTime;

      if (alertTone === "bell") {
        const makeBell = (t, base, len = 1.15) => {
          const o1 = ctx.createOscillator();
          const o2 = ctx.createOscillator();
          const g = ctx.createGain();
          o1.type = "triangle";
          o2.type = "sine";
          o1.frequency.value = base;
          o2.frequency.value = base * 2.01;
          g.gain.setValueAtTime(0.0001, t);
          g.gain.exponentialRampToValueAtTime(0.16, t + 0.01);
          g.gain.exponentialRampToValueAtTime(0.0001, t + len);
          o1.connect(g);
          o2.connect(g);
          g.connect(ctx.destination);
          o1.start(t);
          o2.start(t);
          o1.stop(t + len + 0.05);
          o2.stop(t + len + 0.05);
        };
        let t = 0;
        while (t < durationSec) {
          makeBell(start + t, 880);
          makeBell(start + t + 0.42, 987);
          t += 1.6;
        }
      } else if (alertTone === "alert") {
        const duration = durationSec;
        const oscMain = ctx.createOscillator();
        const oscSub = ctx.createOscillator();
        const gain = ctx.createGain();
        oscMain.type = "sawtooth";
        oscSub.type = "sine";
        oscSub.frequency.value = 110;

        const cycle = 2.6;
        for (let t = 0; t <= duration + cycle; t += cycle) {
          const t0 = start + t;
          oscMain.frequency.setValueAtTime(360, t0);
          oscMain.frequency.linearRampToValueAtTime(920, t0 + cycle / 2);
          oscMain.frequency.linearRampToValueAtTime(360, t0 + cycle);
        }

        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.12, start + 0.08);
        gain.gain.setValueAtTime(0.12, start + duration - 0.12);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

        oscMain.connect(gain);
        oscSub.connect(gain);
        gain.connect(ctx.destination);
        oscMain.start(start);
        oscSub.start(start);
        oscMain.stop(start + duration);
        oscSub.stop(start + duration);
      } else if (alertTone === "emergency") {
        const duration = durationSec;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sawtooth";
        const step = 0.16;
        for (let t = 0; t <= duration; t += step) {
          const f = Math.floor(t / step) % 2 === 0 ? 630 : 1180;
          osc.frequency.setValueAtTime(f, start + t);
        }
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.095, start + 0.04);
        gain.gain.setValueAtTime(0.095, start + duration - 0.08);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(start);
        osc.stop(start + duration);
      } else {
        const duration = durationSec;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "square";
        const step = 0.28;
        for (let t = 0; t <= duration; t += step) {
          const f = Math.floor(t / step) % 2 === 0 ? 740 : 980;
          osc.frequency.setValueAtTime(f, start + t);
        }
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.09, start + 0.04);
        gain.gain.setValueAtTime(0.09, start + duration - 0.08);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(start);
        osc.stop(start + duration);
      }
    } catch {
      // best-effort alert only
    }
  }

  async function ensureAudioReady() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return false;
    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioCtx();
    }
    if (audioCtxRef.current.state === "suspended") {
      try {
        await audioCtxRef.current.resume();
      } catch {
        return false;
      }
    }
    return audioCtxRef.current.state === "running";
  }

  async function toggleSound() {
    if (!soundEnabled) {
      const ok = await ensureAudioReady();
      if (ok) {
        setSoundEnabled(true);
        playAlertSound();
        return;
      }
    }
    setSoundEnabled((v) => !v);
  }

  async function testSound() {
    const ok = await ensureAudioReady();
    if (ok) playAlertSound();
  }

  useEffect(() => {
    const above = metrics.some((m) => Number(m.risk_score || 0) >= riskThreshold);
    const nowMs = Date.now();
    const ringMs = 10000;
    const breakMs = Math.max(1, Number(tonePauseSeconds || 30)) * 1000;
    const cycleMs = ringMs + breakMs;
    const crossing = above && !prevAboveRef.current;
    const cooled = above && nowMs - lastAlertAtRef.current >= cycleMs;
    if (soundEnabled && (crossing || cooled)) {
      playAlertSound(10);
      lastAlertAtRef.current = nowMs;
    }
    if (!above) {
      lastAlertAtRef.current = 0;
    }
    prevAboveRef.current = above;
  }, [metrics, riskThreshold, soundEnabled, tonePauseSeconds]);

  useEffect(() => {
    if (!settingsOpen) return undefined;

    const onDocClick = (evt) => {
      if (!settingsRef.current?.contains(evt.target)) {
        setSettingsOpen(false);
      }
    };
    const onKey = (evt) => {
      if (evt.key === "Escape") setSettingsOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [settingsOpen]);

  useEffect(() => {
    if (!riskInfoOpen) return undefined;
    const onDocClick = (evt) => {
      if (!riskInfoRef.current?.contains(evt.target)) {
        setRiskInfoOpen(false);
      }
    };
    const onKey = (evt) => {
      if (evt.key === "Escape") setRiskInfoOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [riskInfoOpen]);

  function setHealthThresholdValue(key, rawValue) {
    const parsed = Number(rawValue);
    if (!Number.isFinite(parsed)) return;
    const clamped = Math.max(0, Math.min(1, parsed));
    setHealthThresholds((prev) => {
      const next = { ...prev, [key]: clamped };
      if (next.warm >= next.degrading) next.degrading = Math.min(0.99, next.warm + 0.01);
      if (next.degrading >= next.critical) next.critical = Math.min(1, next.degrading + 0.01);
      if (next.critical <= next.degrading) next.degrading = Math.max(0, next.critical - 0.01);
      if (next.degrading <= next.warm) next.warm = Math.max(0, next.degrading - 0.01);
      return next;
    });
  }

  return (
    <main className="app">
      <header>
        <div className="header-row">
          <h1>LLM Traffic Observatory</h1>
          <div className="live-pill">
            <span className="status-dot" data-connected={connected} />
            <span>{connected ? "Live" : "Reconnecting"}</span>
          </div>
        </div>
        <p>Real-time ingress, transform, and egress telemetry</p>
      </header>

      <section className="panel ux-controls">
        <div className="control-group">
          <span className="control-label">Mode</span>
          <select className="control-select" value={viewMode} onChange={(e) => setViewMode(e.target.value)}>
            <option value="flow">Flow</option>
            <option value="galaxy">Galaxy</option>
          </select>

          <span className="control-label">Model Density</span>
          <select
            className="control-select"
            value={topModelCount}
            onChange={(e) => setTopModelCount(Number(e.target.value))}
          >
            <option value={8}>Top 8</option>
            <option value={12}>Top 12</option>
            <option value={20}>Top 20</option>
          </select>

          <span className="control-label">Window</span>
          <select
            className="control-select"
            value={windowSeconds}
            onChange={(e) => setWindowSeconds(Number(e.target.value))}
          >
            <option value={30}>30s</option>
            <option value={60}>60s</option>
            <option value={300}>5m</option>
          </select>

          <span className="control-label">Risk Alert</span>
          <select
            className="control-select"
            value={riskThreshold}
            onChange={(e) => setRiskThreshold(Number(e.target.value))}
          >
            <option value={0.6}>&gt;= 0.6</option>
            <option value={0.8}>&gt;= 0.8</option>
            <option value={0.9}>&gt;= 0.9</option>
          </select>

          <span className="control-label">Tone</span>
          <select className="control-select" value={alertTone} onChange={(e) => setAlertTone(e.target.value)}>
            <option value="siren">Siren</option>
            <option value="bell">Bell</option>
            <option value="emergency">Emergency</option>
            <option value="alert">Alert</option>
          </select>

          <div className="settings-wrap" ref={settingsRef}>
            <button
              type="button"
              className={`settings-gear ${settingsOpen ? "active" : ""}`}
              onClick={() => setSettingsOpen((v) => !v)}
              title="Settings"
              aria-label="Open settings"
            >
              ⚙
            </button>
            {settingsOpen ? (
              <div className="settings-menu">
                <button
                  type="button"
                  className={`density-btn ${soundEnabled ? "active" : ""}`}
                  onClick={toggleSound}
                >
                  {soundEnabled ? "Sound On" : "Sound Off"}
                </button>
                <button type="button" className="density-btn" onClick={testSound}>
                  Test Sound
                </button>
                <div className="settings-field">
                  <label>Tone pause (sec)</label>
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={tonePauseSeconds}
                    onChange={(e) => setTonePauseSeconds(Math.max(1, Number(e.target.value) || 1))}
                  />
                </div>
                <div className="settings-field">
                  <label>SLO latency (ms)</label>
                  <input
                    type="number"
                    min={100}
                    step={50}
                    value={latencySloMs}
                    onChange={(e) => setLatencySloMs(Math.max(100, Number(e.target.value) || 100))}
                  />
                </div>
                <div className="settings-field">
                  <label>SLO token/s</label>
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={tokenSloTps}
                    onChange={(e) => setTokenSloTps(Math.max(1, Number(e.target.value) || 1))}
                  />
                </div>
                <div className="settings-thresholds">
                  <div className="settings-mini-title">Health thresholds</div>
                  <div className="settings-threshold-row">
                    <label>Warm</label>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={healthThresholds.warm}
                      onChange={(e) => setHealthThresholdValue("warm", e.target.value)}
                    />
                  </div>
                  <div className="settings-threshold-row">
                    <label>Degrading</label>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={healthThresholds.degrading}
                      onChange={(e) => setHealthThresholdValue("degrading", e.target.value)}
                    />
                  </div>
                  <div className="settings-threshold-row">
                    <label>Critical</label>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={healthThresholds.critical}
                      onChange={(e) => setHealthThresholdValue("critical", e.target.value)}
                    />
                  </div>
                </div>
                {viewMode === "galaxy" ? (
                  <>
                    <button
                      type="button"
                      className={`density-btn ${showEventDetails ? "active" : ""}`}
                      onClick={() => setShowEventDetails((v) => !v)}
                    >
                      Event Details
                    </button>
                    <button
                      type="button"
                      className={`density-btn ${showModelIntel ? "active" : ""}`}
                      onClick={() => setShowModelIntel((v) => !v)}
                    >
                      Model Intelligence
                    </button>
                    <button
                      type="button"
                      className={`density-btn ${showModelNames ? "active" : ""}`}
                      onClick={() => setShowModelNames((v) => !v)}
                    >
                      {showModelNames ? "Hide Model Names" : "Show Model Names"}
                    </button>
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>

        <div className="legend">
          <span className="legend-group">
            <span className="legend-item"><i style={{ background: "#68f0c3" }} /> Healthy (&lt;{healthThresholds.warm.toFixed(2)})</span>
            <span className="legend-item"><i style={{ background: "#ffd166" }} /> Warm (&lt;{healthThresholds.degrading.toFixed(2)})</span>
            <span className="legend-item"><i style={{ background: "#ff9f43" }} /> Degrading (&lt;{healthThresholds.critical.toFixed(2)})</span>
            <span className="legend-item"><i style={{ background: "#ff6b6b" }} /> Critical (&gt;={healthThresholds.critical.toFixed(2)})</span>
          </span>
          <span className={`legend-item alert-chip ${highRiskCount > 0 ? "hot" : ""}`}>
            <span>
              Risk Breaches: {highRiskCount} | Max Risk: {maxRisk.toFixed(2)}
            </span>
            <button
              type="button"
              className="info-icon"
              aria-label="Risk score formula"
              onClick={(e) => {
                e.stopPropagation();
                setRiskInfoOpen((v) => !v);
              }}
            >
              i
            </button>
            {riskInfoOpen ? (
              <div className="risk-popover" ref={riskInfoRef}>
                <div className="tt-title">Risk Score Info</div>
                <div className="tt-row"><span>Threshold</span><b>&gt;= {riskThreshold}</b></div>
                <div className="tt-row"><span>Max Risk</span><b>{maxRisk.toFixed(2)}</b></div>
                <div className="tt-row"><span>Formula</span><b>0.5*fail + 0.3*p95 + 0.2*tokens</b></div>
                <div className="risk-detail">{riskConfigTooltip}</div>
                <div className="risk-detail">
                  token_rate_tps = (input_tokens + output_tokens) / window_seconds
                </div>
                <div className="risk-detail">
                  normalized_token_rate = min(1, token_rate_tps / token_slo_tps), token_slo_tps = {tokenSloTps}
                </div>
                <div className="risk-detail">
                  normalized_p95_latency = min(1, p95_latency_ms / latency_slo_ms), latency_slo_ms = {latencySloMs}
                </div>
                <div className="risk-detail">
                  Top Risks: {topRiskRows.map((m) => `${m.model_id}(${Number(m.risk_score || 0).toFixed(2)})`).join(", ") || "no data"}
                </div>
                <div className="risk-detail muted">{riskTooltip}</div>
              </div>
            ) : null}
          </span>
        </div>
      </section>

      {viewMode === "flow" ? (
        <FlowCanvas
          events={events}
          modelMetrics={metrics}
          modelCatalog={modelCatalog}
          maxVisibleModels={topModelCount}
          focusedModel=""
          healthThresholds={healthThresholds}
        />
      ) : (
        <GalaxyCanvas
          events={events}
          modelMetrics={metrics}
          modelCatalog={modelCatalog}
          maxVisibleModels={topModelCount}
          windowSeconds={windowSeconds}
          showEventDetails={showEventDetails}
          showModelIntel={showModelIntel}
          showModelNames={showModelNames}
        />
      )}

      {viewMode === "flow" ? (
        <section className="panel metrics-panel">
          <h3>Model Health ({windowSeconds >= 300 ? "5m" : `${windowSeconds}s`})</h3>
          <div className="metrics-meta">
            Updated: {updatedAt ? new Date(updatedAt).toLocaleTimeString() : "loading"}
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>model</th>
                  <th>provider</th>
                  <th>req/s</th>
                  <th>tokens/s</th>
                  <th>failure%</th>
                  <th>p95(ms)</th>
                  <th>risk</th>
                </tr>
              </thead>
              <tbody>
                {metrics.slice(0, 20).map((m) => (
                  <tr key={m.model_id}>
                    <td>{m.model_id}</td>
                    <td>{m.provider}</td>
                    <td>{m.request_rate_rps.toFixed(2)}</td>
                    <td>{m.token_rate_tps.toFixed(1)}</td>
                    <td>{(m.failure_rate * 100).toFixed(1)}</td>
                    <td>{m.p95_latency_ms.toFixed(0)}</td>
                    <td>
                      <span className="risk-pill" style={{ backgroundColor: `${m.health_color}33`, borderColor: m.health_color }}>
                        {m.risk_score.toFixed(2)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <RecentRequestsGrid events={events} onFiltersChange={setGridFilters} />
    </main>
  );
}
