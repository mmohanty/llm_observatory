import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function useModelCatalog() {
  const [catalog, setCatalog] = useState({ models: [], providers: [], updatedAt: null });

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      fetch(`${API_BASE}/api/models/catalog`)
        .then((res) => (res.ok ? res.json() : null))
        .then((payload) => {
          if (cancelled || !payload) return;
          setCatalog({
            models: Array.isArray(payload.models) ? payload.models : [],
            providers: Array.isArray(payload.providers) ? payload.providers : [],
            updatedAt: payload.generated_at || null,
          });
        })
        .catch(() => {});
    };

    load();
    const id = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return catalog;
}

