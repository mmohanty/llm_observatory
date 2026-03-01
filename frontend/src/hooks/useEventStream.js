import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function useEventStream(filters) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    return params.toString();
  }, [filters]);

  useEffect(() => {
    let cancelled = false;
    const seen = new Set();
    const recentUrl = `${API_BASE}/api/events/recent?limit=120`;

    const eventKey = (item) =>
      `${item.request_id || "na"}::${item.service || "na"}::${item.timestamp || "na"}`;

    const normalize = (item, historical = false) => ({
      ...item,
      _arrivedAt: Date.now(),
      _historical: historical
    });

    fetch(recentUrl)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (!cancelled && Array.isArray(data)) {
          data.forEach((item) => seen.add(eventKey(item)));
          setEvents(data.map((item) => normalize(item, true)));
        }
      })
      .catch(() => {});

    const url = `${API_BASE}/api/stream${query ? `?${query}` : ""}`;
    const source = new EventSource(url);

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    const appendEvent = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const key = eventKey(payload);
        if (seen.has(key)) return;
        seen.add(key);
        setEvents((prev) =>
          [
            normalize(payload, false),
            ...prev
          ].slice(0, 180)
        );
      } catch {
        // ignore malformed chunks such as heartbeats
      }
    };

    source.addEventListener("telemetry", (event) => {
      appendEvent(event);
    });
    source.onmessage = appendEvent;

    const pollId = setInterval(() => {
      fetch(recentUrl)
        .then((res) => (res.ok ? res.json() : []))
        .then((data) => {
          if (cancelled || !Array.isArray(data) || data.length === 0) return;
          const unseen = data.filter((item) => {
            const key = eventKey(item);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          });
          if (unseen.length === 0) return;
          setEvents((prev) => [...unseen.map((item) => normalize(item, false)), ...prev].slice(0, 180));
        })
        .catch(() => {});
    }, 1000);

    return () => {
      cancelled = true;
      clearInterval(pollId);
      source.close();
      setConnected(false);
    };
  }, [query]);

  return { events, connected };
}
