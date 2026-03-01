import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function useModelMetrics(windowSeconds = 60, options = {}) {
  const [metrics, setMetrics] = useState([]);
  const [updatedAt, setUpdatedAt] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const {
      user,
      model,
      service,
      status,
      timeMode,
      timeFrom,
      timeTo,
      latencySloMs,
      tokenSloTps,
      healthThresholds,
    } = options || {};

    const load = () => {
      const params = new URLSearchParams();
      params.set("window_seconds", String(windowSeconds));
      if (user) params.set("user_id", user);
      if (model) params.set("model_id", model);
      if (service) params.set("service", service);
      if (status) params.set("status", status);
      if (timeMode === "after" || timeMode === "range") {
        if (timeFrom) params.set("time_from", new Date(timeFrom).toISOString());
      }
      if (timeMode === "before" || timeMode === "range") {
        if (timeTo) params.set("time_to", new Date(timeTo).toISOString());
      }
      if (typeof latencySloMs === "number" && Number.isFinite(latencySloMs)) {
        params.set("latency_slo_ms", String(latencySloMs));
      }
      if (typeof tokenSloTps === "number" && Number.isFinite(tokenSloTps)) {
        params.set("token_slo_tps", String(tokenSloTps));
      }
      if (healthThresholds) {
        params.set("warm_threshold", String(healthThresholds.warm));
        params.set("degrading_threshold", String(healthThresholds.degrading));
        params.set("critical_threshold", String(healthThresholds.critical));
      }
      fetch(`${API_BASE}/api/models/metrics?${params.toString()}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((payload) => {
          if (cancelled || !payload) return;
          setMetrics(Array.isArray(payload.models) ? payload.models : []);
          setUpdatedAt(payload.generated_at || null);
        })
        .catch(() => {});
    };

    load();
    const id = setInterval(load, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [windowSeconds, options]);

  return { metrics, updatedAt };
}
