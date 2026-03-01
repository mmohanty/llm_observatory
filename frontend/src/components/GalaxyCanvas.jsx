import { useEffect, useMemo, useState } from "react";

const FLOW_TTL_MS = 10000;

function normalizeProvider(value) {
  const raw = String(value || "unknown").trim().toLowerCase();
  if (!raw) return "unknown";
  if (["onprem", "on-prem", "on_prem", "self-hosted", "selfhosted"].includes(raw)) return "on-prem";
  return raw;
}

function titleCase(text) {
  return text
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function p95(values) {
  if (!values.length) return 0;
  const sorted = values.slice().sort((a, b) => a - b);
  const idx = Math.max(0, Math.floor(sorted.length * 0.95) - 1);
  return sorted[idx];
}

function buildModelUniverse(modelMetrics, events, modelCatalog, windowSeconds, now) {
  const grouped = new Map();
  const windowMs = Math.max(10, (windowSeconds || 60)) * 1000;

  for (const m of modelMetrics || []) {
    grouped.set(m.model_id, {
      model_id: m.model_id,
      provider: normalizeProvider(m.provider),
      request_rate_rps: m.request_rate_rps || 0,
      token_rate_tps: m.token_rate_tps || 0,
      failure_rate: m.failure_rate || 0,
      p95_latency_ms: m.p95_latency_ms || 0,
      cost_rate_usd_s: m.cost_rate_usd_s || 0,
      health_color: m.health_color || "#68f0c3",
      risk_score: m.risk_score || 0,
      _count: 0,
      _failures: 0,
      _latencies: []
    });
  }

  for (const e of events || []) {
    if (e.service !== "router") continue;
    if (now - (e._arrivedAt || 0) > windowMs) continue;
    if (!grouped.has(e.model_id)) {
      grouped.set(e.model_id, {
        model_id: e.model_id,
        provider: normalizeProvider(e.provider),
        request_rate_rps: 0,
        token_rate_tps: 0,
        failure_rate: 0,
        p95_latency_ms: 0,
        cost_rate_usd_s: 0,
        health_color: "#68f0c3",
        risk_score: 0,
        _count: 0,
        _failures: 0,
        _latencies: []
      });
    }
    const item = grouped.get(e.model_id);
    item.request_rate_rps += 1;
    item.token_rate_tps += (e.input_tokens || 0) + (e.output_tokens || 0);
    item.cost_rate_usd_s += Number(e.cost_usd || 0);
    item._count += 1;
    item._latencies.push(Number(e.latency_ms || 0));
    if (e.status === "failure") item._failures += 1;
  }

  const rows = Array.from(grouped.values()).map((r) => {
    const count = r._count || 0;
    const req = r.request_rate_rps / Math.max(1, windowSeconds || 60);
    const tok = r.token_rate_tps / Math.max(1, windowSeconds || 60);
    const cost = r.cost_rate_usd_s / Math.max(1, windowSeconds || 60);
    return {
      ...r,
      request_rate_rps: req,
      token_rate_tps: tok,
      failure_rate: count ? r._failures / count : r.failure_rate,
      p95_latency_ms: count ? p95(r._latencies) : r.p95_latency_ms,
      cost_rate_usd_s: cost,
      _count: undefined,
      _latencies: undefined,
      _failures: undefined
    };
  });

  for (const d of modelCatalog || []) {
    if (rows.find((r) => r.model_id === d.model_id)) continue;
    rows.push({
      model_id: d.model_id,
      provider: normalizeProvider(d.provider),
      request_rate_rps: 0,
      token_rate_tps: 0,
      failure_rate: 0,
      p95_latency_ms: 0,
      cost_rate_usd_s: 0,
      health_color: "#4aa7c6",
      risk_score: 0
    });
  }

  return rows.sort((a, b) => b.request_rate_rps - a.request_rate_rps);
}

function buildProviderClusters(models) {
  const grouped = new Map();
  for (const model of models) {
    const provider = normalizeProvider(model.provider);
    if (!grouped.has(provider)) {
      grouped.set(provider, { provider, models: [], requestRate: 0, failureWeight: 0, tokenRate: 0 });
    }
    const bucket = grouped.get(provider);
    bucket.models.push(model);
    bucket.requestRate += model.request_rate_rps || 0;
    bucket.failureWeight += model.failure_rate || 0;
    bucket.tokenRate += model.token_rate_tps || 0;
  }
  return Array.from(grouped.values()).sort((a, b) => b.requestRate - a.requestRate);
}

function polar(cx, cy, r, angle) {
  return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
}

export default function GalaxyCanvas({
  events,
  modelMetrics,
  modelCatalog = [],
  maxVisibleModels = 20,
  windowSeconds = 60,
  showEventDetails = true,
  showModelIntel = true,
  showModelNames = true
}) {
  const [now, setNow] = useState(Date.now());
  const [hovered, setHovered] = useState(null);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 33);
    return () => clearInterval(id);
  }, []);

  const allModels = useMemo(
    () => buildModelUniverse(modelMetrics, events, modelCatalog, windowSeconds, now),
    [modelMetrics, events, modelCatalog, windowSeconds, now]
  );

  const limit = Math.max(1, maxVisibleModels || 20);
  const visibleModels = useMemo(() => allModels.slice(0, limit), [allModels, limit]);
  const hiddenModels = useMemo(() => allModels.slice(limit), [allModels, limit]);

  const clusters = useMemo(() => {
    const base = buildProviderClusters(visibleModels);
    if (hiddenModels.length > 0) {
      const req = hiddenModels.reduce((s, m) => s + (m.request_rate_rps || 0), 0);
      const tok = hiddenModels.reduce((s, m) => s + (m.token_rate_tps || 0), 0);
      const fail = hiddenModels.reduce((s, m) => s + (m.failure_rate || 0), 0) / hiddenModels.length;
      const cost = hiddenModels.reduce((s, m) => s + (m.cost_rate_usd_s || 0), 0);
      const p95v = hiddenModels.length
        ? hiddenModels.reduce((s, m) => s + (m.p95_latency_ms || 0), 0) / hiddenModels.length
        : 0;
      base.push({
        provider: "others",
        models: [{
          model_id: `Others (${hiddenModels.length})`,
          provider: "others",
          request_rate_rps: req,
          token_rate_tps: tok,
          failure_rate: fail,
          p95_latency_ms: p95v,
          cost_rate_usd_s: cost,
          health_color: "#8a9db5",
          risk_score: 0,
          is_others: true,
          hidden_count: hiddenModels.length
        }],
        requestRate: req,
        failureWeight: fail,
        tokenRate: tok,
        is_others: true
      });
    }
    return base;
  }, [visibleModels, hiddenModels]);

  const activeRouterEvents = useMemo(
    () =>
      (events || [])
        .filter((e) => e.service === "router" && !e._historical && now - (e._arrivedAt || 0) < FLOW_TTL_MS)
        .slice(0, 120),
    [events, now]
  );

  const center = { x: 420, y: 258 };
  const providerRingRadius = 138;

  const clusterLayout = useMemo(() => {
    if (!clusters.length) return [];
    if (clusters.length === 1) {
      const pos = polar(center.x, center.y, providerRingRadius, 0);
      return [{ ...clusters[0], x: pos.x, y: pos.y, angle: 0 }];
    }
    return clusters.map((cluster, idx) => {
      const angle = -Math.PI / 2 + Math.PI / clusters.length + (idx * Math.PI * 2) / clusters.length;
      const pos = polar(center.x, center.y, providerRingRadius, angle);
      return { ...cluster, x: pos.x, y: pos.y, angle };
    });
  }, [clusters]);

  const providerPos = useMemo(() => {
    const map = new Map();
    for (const c of clusterLayout) map.set(c.provider, c);
    return map;
  }, [clusterLayout]);

  const modelNodes = useMemo(() => {
    const nodes = [];
    const maxTokenRate = Math.max(1, ...visibleModels.map((m) => m.token_rate_tps || 0));
    for (const cluster of clusterLayout) {
      const n = cluster.models.length;
      const baseRadius = cluster.is_others ? 48 : (n > 10 ? 48 : 38);
      for (let i = 0; i < n; i += 1) {
        const model = cluster.models[i];
        const orbitAngle = cluster.is_others
          ? -Math.PI / 4
          : ((Math.PI * 2) / Math.max(n, 1)) * i + (now / 3500) * 0.18;
        const orbit = polar(cluster.x, cluster.y, baseRadius, orbitAngle);
        const normalized = (model.token_rate_tps || 0) / maxTokenRate;
        const size = model.is_others ? 10 : 4 + normalized * 9;
        nodes.push({ ...model, x: orbit.x, y: orbit.y, size, provider: cluster.provider });
      }
    }
    return nodes;
  }, [clusterLayout, now, visibleModels]);

  const burstPulses = useMemo(() => {
    const t = now / 1000;
    return clusterLayout.map((cluster, idx) => {
      const intensity = Math.min(1, (cluster.requestRate || 0) / 8 + (cluster.failureWeight || 0) / 3);
      const phase = (t + idx * 0.31) % 2.6;
      const radius = 18 + phase * 22;
      const opacity = Math.max(0, (1 - phase / 2.6) * intensity * 0.7);
      return { provider: cluster.provider, x: cluster.x, y: cluster.y, radius, opacity };
    });
  }, [clusterLayout, now]);

  const requestBursts = useMemo(() => {
    const points = [];
    for (let i = 0; i < activeRouterEvents.length; i += 1) {
      const e = activeRouterEvents[i];
      const provider = normalizeProvider(e.provider);
      const cluster = providerPos.get(provider) || providerPos.get("others");
      if (!cluster) continue;
      const age = now - (e._arrivedAt || now);
      const t = Math.max(0, Math.min(1, age / 1800));
      points.push({
        key: `${e.request_id}-${i}`,
        x: center.x + (cluster.x - center.x) * t,
        y: center.y + (cluster.y - center.y) * t,
        bad: e.status === "failure"
      });
    }
    return points;
  }, [activeRouterEvents, providerPos, now]);

  const recentEvents = useMemo(
    () => [...(events || [])]
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 8),
    [events]
  );

  const serviceSummary = useMemo(() => {
    const map = new Map();
    for (const e of events || []) {
      if (!map.has(e.service)) map.set(e.service, { total: 0, failures: 0 });
      const row = map.get(e.service);
      row.total += 1;
      if (e.status === "failure") row.failures += 1;
    }
    return Array.from(map.entries()).map(([service, row]) => ({
      service,
      total: row.total,
      failures: row.failures,
      rate: row.total ? (row.failures / row.total) * 100 : 0
    })).sort((a, b) => b.total - a.total);
  }, [events]);

  const topRisk = useMemo(
    () => [...visibleModels].sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0)).slice(0, 7),
    [visibleModels]
  );

  const onEnterNode = (evt, node) => {
    const rect = evt.currentTarget.ownerSVGElement.getBoundingClientRect();
    setHovered({ x: evt.clientX - rect.left + 12, y: evt.clientY - rect.top + 10, node });
  };

  const shellClass = [
    "panel",
    "galaxy-shell",
    showEventDetails ? "" : "no-left",
    showModelIntel ? "" : "no-right"
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClass}>
      {showEventDetails ? (
        <aside className="galaxy-rail left">
        <h4>Event Details</h4>
        <div className="rail-block">
          <div className="rail-title">Service Health</div>
          {serviceSummary.slice(0, 6).map((s) => (
            <div key={s.service} className="rail-row">
              <span>{s.service}</span>
              <span>{s.total} / {s.failures} ({s.rate.toFixed(1)}%)</span>
            </div>
          ))}
        </div>
        <div className="rail-block">
          <div className="rail-title">Recent Events</div>
          {recentEvents.map((e) => (
            <div key={`${e.request_id}-${e.service}-${e.timestamp}`} className="event-row">
              <span className={e.status === "failure" ? "bad-text" : "good-text"}>{e.status}</span>
              <span>{e.model_id}</span>
              <span>{e.service}</span>
            </div>
          ))}
        </div>
        </aside>
      ) : null}

      <div className="flow-wrap galaxy-wrap center">
        <svg viewBox="0 0 900 540" className="flow-svg">
          <text x="420" y="34" className="title" textAnchor="middle">Model Galaxy</text>
          <text x="420" y="56" className="node-label" textAnchor="middle">
            Provider Clusters + On-Prem | Node Size = Token Rate ({windowSeconds >= 300 ? "5m" : `${windowSeconds}s`} window)
          </text>

          <circle cx={center.x} cy={center.y} r="166" className="galaxy-ring" />
          <circle cx={center.x} cy={center.y} r="48" className="hub" />
          <text x={center.x} y={center.y + 5} textAnchor="middle" className="hub-label">Router Core</text>

          {clusterLayout.map((cluster) => (
            <g key={cluster.provider}>
            <line x1={center.x} y1={center.y} x2={cluster.x} y2={cluster.y} className="galaxy-spoke" />
            <circle cx={cluster.x} cy={cluster.y} r={cluster.is_others ? "34" : "30"} className="provider-node" />
            <text x={cluster.x} y={cluster.y + 4} textAnchor="middle" className="provider-label">
              {cluster.is_others
                ? `Others (${cluster.models?.[0]?.hidden_count || 0})`
                : titleCase(cluster.provider)}
            </text>
          </g>
        ))}

          {burstPulses.map((pulse) => (
            <circle
              key={`pulse-${pulse.provider}`}
              cx={pulse.x}
              cy={pulse.y}
              r={pulse.radius}
              className="burst-ring"
              style={{ opacity: pulse.opacity }}
            />
          ))}

          {modelNodes.map((node) => (
            <g
              key={`${node.provider}-${node.model_id}`}
              onMouseEnter={(evt) => onEnterNode(evt, node)}
              onMouseMove={(evt) => onEnterNode(evt, node)}
              onMouseLeave={() => setHovered(null)}
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={node.size}
                className={node.is_others ? "model-node others-node" : "model-node"}
                style={{ fill: node.health_color || "#68f0c3" }}
              />
              {showModelNames && !node.is_others ? (
                <text x={node.x + node.size + 5} y={node.y + 3} className="galaxy-model-label">
                  {node.model_id}
                </text>
              ) : null}
            </g>
          ))}

          {requestBursts.map((dot) => (
            <circle key={dot.key} cx={dot.x} cy={dot.y} r="4.8" className={dot.bad ? "dot bad" : "dot"} />
          ))}

          <text x="420" y="522" className="node-label" textAnchor="middle">
            Providers: {clusterLayout.length} | Visible Models: {visibleModels.length} | Hidden in Others: {hiddenModels.length} | Active Requests: {requestBursts.length}
          </text>
        </svg>

        {hovered ? (
          <div className="galaxy-tooltip" style={{ left: hovered.x, top: hovered.y }}>
            <div className="tt-title">{hovered.node.model_id}</div>
            <div className="tt-row"><span>req/s</span><b>{(hovered.node.request_rate_rps || 0).toFixed(2)}</b></div>
            <div className="tt-row"><span>tokens/s</span><b>{(hovered.node.token_rate_tps || 0).toFixed(1)}</b></div>
            <div className="tt-row"><span>fail%</span><b>{((hovered.node.failure_rate || 0) * 100).toFixed(1)}</b></div>
            <div className="tt-row"><span>p95</span><b>{(hovered.node.p95_latency_ms || 0).toFixed(0)} ms</b></div>
            <div className="tt-row"><span>cost/s</span><b>${(hovered.node.cost_rate_usd_s || 0).toFixed(4)}</b></div>
          </div>
        ) : null}
      </div>

      {showModelIntel ? (
        <aside className="galaxy-rail right">
        <h4>Model Intelligence</h4>
        <div className="rail-block">
          <div className="rail-title">Top Risk Models</div>
          {topRisk.map((m) => (
            <div key={m.model_id} className="risk-row">
              <span>{m.model_id}</span>
              <span className="risk-pill" style={{ backgroundColor: `${m.health_color}33`, borderColor: m.health_color }}>
                {Number(m.risk_score || 0).toFixed(2)}
              </span>
            </div>
          ))}
        </div>
        <div className="rail-block">
          <div className="rail-title">Providers</div>
          {clusterLayout.map((c) => (
            <div key={`p-${c.provider}`} className="rail-row">
              <span>{c.provider === "others" ? "others" : titleCase(c.provider)}</span>
              <span>{c.models.length} models</span>
            </div>
          ))}
        </div>
        </aside>
      ) : null}
    </div>
  );
}
