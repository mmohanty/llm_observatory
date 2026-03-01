import { useEffect, useMemo, useState } from "react";

const FLOW_TTL_MS = 10000;

const ingress = [
  { id: "user", x: 80, y: 110, label: "User Prompt" },
  { id: "mongo", x: 80, y: 230, label: "MongoDB" },
  { id: "oracle", x: 80, y: 350, label: "Oracle" }
];

const hub = { x: 420, y: 245, r: 72, label: "Orchestrator" };
const EGRESS_TOP = 138;
const EGRESS_BOTTOM = 434;
const EGRESS_CARD_W = 136;
const EGRESS_CARD_H = 34;
const ARMOR_WINDOW_MS = 60000;

function ingressCurve(node) {
  return {
    p0: { x: node.x + 52, y: node.y },
    p1: { x: 230, y: node.y },
    p2: { x: 290, y: hub.y },
    p3: { x: hub.x - hub.r, y: hub.y }
  };
}

function egressCurve(node) {
  return {
    p0: { x: hub.x + hub.r, y: hub.y },
    p1: { x: 620, y: hub.y },
    p2: { x: node.x - 180, y: node.y },
    p3: { x: node.x - 72, y: node.y }
  };
}

function toPathD(curve) {
  const { p0, p1, p2, p3 } = curve;
  return `M ${p0.x} ${p0.y} C ${p1.x} ${p1.y}, ${p2.x} ${p2.y}, ${p3.x} ${p3.y}`;
}

function cubicPoint(curve, t) {
  const { p0, p1, p2, p3 } = curve;
  const mt = 1 - t;
  const mt2 = mt * mt;
  const t2 = t * t;

  const x = p0.x * mt2 * mt + 3 * p1.x * mt2 * t + 3 * p2.x * mt * t2 + p3.x * t2 * t;
  const y = p0.y * mt2 * mt + 3 * p1.y * mt2 * t + 3 * p2.y * mt * t2 + p3.y * t2 * t;
  return { x, y };
}

function formatModelLabel(modelId) {
  if (modelId === "armor") return "Model Armor";
  const label = String(modelId);
  return label.length > 14 ? `${label.slice(0, 13)}…` : label;
}

function riskToColor(risk, thresholds = { warm: 0.2, degrading: 0.5, critical: 0.8 }) {
  if (risk < thresholds.warm) return "#68f0c3";
  if (risk < thresholds.degrading) return "#ffd166";
  if (risk < thresholds.critical) return "#ff9f43";
  return "#ff6b6b";
}

function buildEgressNodes(modelMetrics, events, modelCatalog, maxVisibleModels, focusedModel) {
  const metricModelIds = modelMetrics
    .slice()
    .sort((a, b) => b.request_rate_rps - a.request_rate_rps)
    .map((m) => m.model_id);
  const eventModelIds = events.filter((e) => e.service === "router").map((e) => e.model_id);
  const catalogModelIds = (modelCatalog || []).map((m) => m.model_id);

  const merged = [];
  for (const id of [...metricModelIds, ...eventModelIds, ...catalogModelIds]) {
    if (!id || merged.includes(id)) continue;
    merged.push(id);
  }

  let modelIds = merged.slice(0, Math.max(1, maxVisibleModels || 20));
  if (focusedModel && !modelIds.includes(focusedModel)) {
    modelIds = [focusedModel, ...modelIds].slice(0, Math.max(1, maxVisibleModels || 20));
  }

  const range = EGRESS_BOTTOM - EGRESS_TOP;
  const maxRows = Math.max(1, Math.floor(range / (EGRESS_CARD_H + 8)) + 1);
  const cols = Math.min(3, Math.max(1, Math.ceil(modelIds.length / maxRows)));
  const colX = cols === 1 ? [900] : cols === 2 ? [835, 1030] : [780, 960, 1140];
  const rows = Math.ceil(modelIds.length / cols);
  const gap = rows > 1 ? range / (rows - 1) : 0;

  const modelNodes = modelIds.map((id, idx) => {
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    return {
      id,
      x: colX[Math.min(col, colX.length - 1)],
      y: Math.round(EGRESS_TOP + row * gap),
      label: formatModelLabel(id)
    };
  });

  return [{ id: "armor", x: 760, y: 78, label: "Model Armor" }, ...modelNodes];
}

function motionDots(activeEvents, now, egress) {
  const dots = [];

  for (let i = 0; i < activeEvents.length; i += 1) {
    const e = activeEvents[i];
    const base = e._arrivedAt || now;
    const bad = e.status === "failure";

    if (e.service === "mongo" || e.service === "oracle") {
      const source = ingress.find((n) => n.id === e.service);
      if (source) {
        const t = (now - base) / 1600;
        if (t >= 0 && t <= 1) {
          dots.push({ key: `${e.request_id}-${e.service}-${i}`, point: cubicPoint(ingressCurve(source), t), bad });
        }
      }
      continue;
    }

    if (e.service === "armor") {
      const target = egress.find((n) => n.id === "armor");
      if (target) {
        const t = (now - base) / 1800;
        if (t >= 0 && t <= 1) {
          dots.push({ key: `${e.request_id}-${e.service}-${i}`, point: cubicPoint(egressCurve(target), t), bad });
        }
      }
      continue;
    }

    if (e.service === "router") {
      const source = ingress.find((n) => n.id === "user");
      const target = egress.find((n) => n.id === e.model_id);

      if (source) {
        const tIn = (now - base) / 1600;
        if (tIn >= 0 && tIn <= 1) {
          dots.push({ key: `${e.request_id}-router-in-${i}`, point: cubicPoint(ingressCurve(source), tIn), bad });
        }
      }

      if (target) {
        const outStart = base + 650;
        const tOut = (now - outStart) / 2200;
        if (tOut >= 0 && tOut <= 1) {
          dots.push({ key: `${e.request_id}-router-out-${i}`, point: cubicPoint(egressCurve(target), tOut), bad });
        }
      }
    }
  }

  return dots;
}

function edgeStyle(node, metricsMap, armorRisk, thresholds) {
  if (node.id === "armor") {
    const color = riskToColor(armorRisk, thresholds);
    return { stroke: color, strokeWidth: 5.5, opacity: 0.82 };
  }
  const metric = metricsMap.get(node.id);
  if (!metric) {
    return { stroke: "#2f6a82", strokeWidth: 3, opacity: 0.48 };
  }
  return {
    stroke: metric.health_color || "#2f6a82",
    strokeWidth: Math.min(14, Math.max(2.5, metric.edge_width || 4)),
    opacity: 0.74
  };
}

function nodeStyle(node, metricsMap, focusedModel, armorRisk, thresholds) {
  if (node.id === "armor") {
    const color = riskToColor(armorRisk, thresholds);
    return {
      fill: `${color}2b`,
      stroke: color,
      strokeWidth: 1.8
    };
  }
  const metric = metricsMap.get(node.id);
  const isFocused = focusedModel && node.id === focusedModel;
  if (!metric) {
    return {
      fill: "rgba(94, 213, 245, 0.12)",
      stroke: isFocused ? "#ffd166" : "rgba(130, 223, 250, 0.35)",
      strokeWidth: isFocused ? 2.1 : 1.0
    };
  }
  return {
    fill: `${metric.health_color}22`,
    stroke: isFocused ? "#ffd166" : metric.health_color,
    strokeWidth: isFocused ? 2.4 : 1.1
  };
}

export default function FlowCanvas({
  events,
  modelMetrics,
  modelCatalog = [],
  maxVisibleModels = 20,
  focusedModel = "",
  healthThresholds = { warm: 0.2, degrading: 0.5, critical: 0.8 },
}) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 33);
    return () => clearInterval(id);
  }, []);

  const metricsMap = useMemo(
    () => new Map((modelMetrics || []).map((m) => [m.model_id, m])),
    [modelMetrics]
  );

  const egress = useMemo(
    () => buildEgressNodes(modelMetrics || [], events || [], modelCatalog || [], maxVisibleModels, focusedModel),
    [modelMetrics, events, modelCatalog, maxVisibleModels, focusedModel]
  );

  const activeEvents = useMemo(
    () =>
      events
        .filter((e) => !e._historical && now - (e._arrivedAt || 0) < FLOW_TTL_MS)
        .slice(0, 80),
    [events, now]
  );

  const armorRisk = useMemo(() => {
    const recentArmor = events.filter(
      (e) => e.service === "armor" && now - (e._arrivedAt || 0) <= ARMOR_WINDOW_MS
    );
    if (!recentArmor.length) return 0;
    const failures = recentArmor.filter((e) => e.status === "failure").length;
    const latest = recentArmor[0];
    const burstPenalty = latest && latest.status === "failure" ? 0.25 : 0;
    return Math.min(1, failures / recentArmor.length + burstPenalty);
  }, [events, now]);

  const dots = useMemo(() => motionDots(activeEvents, now, egress), [activeEvents, now, egress]);

  return (
    <div className="panel flow-wrap">
      <svg viewBox="0 0 1260 500" className="flow-svg">
        <text x="120" y="40" className="title" textAnchor="middle">Ingress</text>
        <text x="420" y="40" className="title" textAnchor="middle">Route + Read Config</text>
        <text x="980" y="40" className="title" textAnchor="middle">Outgoing Calls</text>
        <text x="630" y="480" className="node-label" textAnchor="middle">
          Active Flows: {dots.length} | Showing Top {Math.max(0, egress.length - 1)} Models (by req/s)
        </text>

        {ingress.map((node) => {
          const curve = ingressCurve(node);
          return (
            <g key={node.id}>
              <path d={toPathD(curve)} className="flow-path" />
              <rect x={node.x - 46} y={node.y - 24} width="92" height="48" rx="12" className="node" />
              <text x={node.x} y={node.y + 5} textAnchor="middle" className="node-label">{node.label}</text>
            </g>
          );
        })}

        <circle cx={hub.x} cy={hub.y} r={hub.r} className="hub" />
        <text x={hub.x} y={hub.y + 5} textAnchor="middle" className="hub-label">{hub.label}</text>

        {egress.map((node) => {
          const curve = egressCurve(node);
          const style = nodeStyle(node, metricsMap, focusedModel, armorRisk, healthThresholds);
          const edge = edgeStyle(node, metricsMap, armorRisk, healthThresholds);
          return (
            <g key={node.id}>
              <path d={toPathD(curve)} style={edge} fill="none" />
              <rect
                x={node.x - EGRESS_CARD_W / 2}
                y={node.y - EGRESS_CARD_H / 2}
                width={EGRESS_CARD_W}
                height={EGRESS_CARD_H}
                rx="12"
                className="node"
                style={style}
              />
              <text x={node.x} y={node.y + 5} textAnchor="middle" className="node-label">{node.label}</text>
            </g>
          );
        })}

        {dots.map((dot) => (
          <circle
            key={dot.key}
            cx={dot.point.x}
            cy={dot.point.y}
            r="6"
            className={dot.bad ? "dot bad" : "dot"}
          />
        ))}
      </svg>
    </div>
  );
}
