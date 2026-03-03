import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const USECASE_PAGE_SIZE = 8;
const REQUEST_PAGE_SIZE = 10;

function fmtTime(value) {
  return value ? new Date(value).toLocaleTimeString() : "-";
}

function fmtDateTime(value) {
  return value ? new Date(value).toLocaleString() : "-";
}

function resolveTimeRange(windowKey, customFrom, customTo) {
  if (windowKey === "all") return { fromIso: "", toIso: "" };
  if (windowKey === "custom") {
    return {
      fromIso: customFrom ? new Date(customFrom).toISOString() : "",
      toIso: customTo ? new Date(customTo).toISOString() : "",
    };
  }
  const now = Date.now();
  const minute = 60 * 1000;
  const map = {
    "15m": 15 * minute,
    "1h": 60 * minute,
    "6h": 6 * 60 * minute,
    "24h": 24 * 60 * minute,
  };
  const lookbackMs = map[windowKey] || 0;
  if (!lookbackMs) return { fromIso: "", toIso: "" };
  return { fromIso: new Date(now - lookbackMs).toISOString(), toIso: new Date(now).toISOString() };
}

function buildTraceTree(spans) {
  if (!Array.isArray(spans) || spans.length === 0) return [];
  const byId = new Map();
  for (const span of spans) {
    byId.set(span.span_id, { ...span, children: [] });
  }
  const roots = [];
  for (const node of byId.values()) {
    if (node.parent_span_id && byId.has(node.parent_span_id)) {
      byId.get(node.parent_span_id).children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortByTime = (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime();
  const sortRec = (nodes) => {
    nodes.sort(sortByTime);
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

function TraceTreeNode({ node, selectedSpanId, onSelect }) {
  return (
    <div className="trace-tree-node-wrap">
      <button
        type="button"
        className={`trace-step ${selectedSpanId === node.span_id ? "active" : ""} ${node.status}`}
        onClick={() => onSelect(node.span_id)}
      >
        <b>{node.stage}</b>
        <small>{node.component}</small>
        <small>{node.duration_ms}ms</small>
      </button>
      {node.children.length ? (
        <div className="trace-children">
          {node.children.map((child) => (
            <TraceTreeNode
              key={child.span_id}
              node={child}
              selectedSpanId={selectedSpanId}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function TraceExplorer() {
  const [usecaseQuery, setUsecaseQuery] = useState("");
  const [timeWindow, setTimeWindow] = useState("1h");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [usecases, setUsecases] = useState([]);
  const [selectedUsecaseId, setSelectedUsecaseId] = useState("");
  const [requests, setRequests] = useState([]);
  const [usecasePage, setUsecasePage] = useState(1);
  const [requestPage, setRequestPage] = useState(1);
  const [selectedTraceId, setSelectedTraceId] = useState("");
  const [traceDetail, setTraceDetail] = useState(null);
  const [selectedSpanId, setSelectedSpanId] = useState("");
  const [requestStatus, setRequestStatus] = useState("");
  const [requestIdQuery, setRequestIdQuery] = useState("");
  const [collapseUsecases, setCollapseUsecases] = useState(false);
  const [collapseRequests, setCollapseRequests] = useState(false);

  const timeRange = useMemo(
    () => resolveTimeRange(timeWindow, customFrom, customTo),
    [timeWindow, customFrom, customTo]
  );

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams();
    if (usecaseQuery.trim()) params.set("q", usecaseQuery.trim());
    if (timeRange.fromIso) params.set("time_from", timeRange.fromIso);
    if (timeRange.toIso) params.set("time_to", timeRange.toIso);
    params.set("limit", "300");
    fetch(`${API_BASE}/api/traces/usecases?${params.toString()}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (cancelled || !Array.isArray(data)) return;
        setUsecases(data);
        setUsecasePage(1);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [usecaseQuery, timeRange]);

  useEffect(() => {
    if (!usecases.length) {
      setSelectedUsecaseId("");
      return;
    }
    if (!usecases.some((u) => u.usecase_id === selectedUsecaseId)) {
      const next = usecases[0];
      setSelectedUsecaseId(next.usecase_id);
    }
  }, [usecases, selectedUsecaseId]);

  useEffect(() => {
    if (!selectedUsecaseId) {
      setRequests([]);
      setSelectedTraceId("");
      return;
    }
    let cancelled = false;
    const params = new URLSearchParams();
    params.set("usecase_id", selectedUsecaseId);
    if (requestStatus) params.set("status", requestStatus);
    if (requestIdQuery.trim()) params.set("request_id", requestIdQuery.trim());
    if (timeRange.fromIso) params.set("time_from", timeRange.fromIso);
    if (timeRange.toIso) params.set("time_to", timeRange.toIso);
    params.set("limit", "300");
    fetch(`${API_BASE}/api/traces/requests?${params.toString()}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (cancelled || !Array.isArray(data)) return;
        setRequests(data);
        setRequestPage(1);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedUsecaseId, requestStatus, requestIdQuery, timeRange]);

  useEffect(() => {
    if (!requests.length) {
      setSelectedTraceId("");
      return;
    }
    if (!requests.some((r) => r.trace_id === selectedTraceId)) {
      setSelectedTraceId(requests[0].trace_id);
    }
  }, [requests, selectedTraceId]);

  useEffect(() => {
    if (!selectedTraceId) {
      setTraceDetail(null);
      setSelectedSpanId("");
      return;
    }
    let cancelled = false;
    fetch(`${API_BASE}/api/traces/${encodeURIComponent(selectedTraceId)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setTraceDetail(data);
        const firstSpan = Array.isArray(data.spans) && data.spans.length ? data.spans[0].span_id : "";
        setSelectedSpanId(firstSpan);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedTraceId]);

  const selectedUsecase = useMemo(
    () => usecases.find((u) => u.usecase_id === selectedUsecaseId) || null,
    [usecases, selectedUsecaseId]
  );

  const spans = traceDetail?.spans || [];
  const traceTree = useMemo(() => buildTraceTree(spans), [spans]);
  const selectedSpan = spans.find((s) => s.span_id === selectedSpanId) || spans[0] || null;
  const usecaseTotalPages = Math.max(1, Math.ceil(usecases.length / USECASE_PAGE_SIZE));
  const requestTotalPages = Math.max(1, Math.ceil(requests.length / REQUEST_PAGE_SIZE));
  const visibleUsecasePage = Math.min(usecasePage, usecaseTotalPages);
  const visibleRequestPage = Math.min(requestPage, requestTotalPages);
  const pagedUsecases = useMemo(() => {
    const start = (visibleUsecasePage - 1) * USECASE_PAGE_SIZE;
    return usecases.slice(start, start + USECASE_PAGE_SIZE);
  }, [usecases, visibleUsecasePage]);
  const pagedRequests = useMemo(() => {
    const start = (visibleRequestPage - 1) * REQUEST_PAGE_SIZE;
    return requests.slice(start, start + REQUEST_PAGE_SIZE);
  }, [requests, visibleRequestPage]);

  return (
    <section className="panel trace-shell">
      <div className="trace-toolbar">
        <h3>Trace Explorer</h3>
        <input
          value={usecaseQuery}
          onChange={(e) => setUsecaseQuery(e.target.value)}
          placeholder="Search usecase_id..."
        />
        <select value={timeWindow} onChange={(e) => setTimeWindow(e.target.value)}>
          <option value="15m">window: 15m</option>
          <option value="1h">window: 1h</option>
          <option value="6h">window: 6h</option>
          <option value="24h">window: 24h</option>
          <option value="custom">window: custom</option>
          <option value="all">window: all</option>
        </select>
        {timeWindow === "custom" ? (
          <>
            <input
              type="datetime-local"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              placeholder="from"
            />
            <input
              type="datetime-local"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              placeholder="to"
            />
          </>
        ) : null}
        <select value={requestStatus} onChange={(e) => setRequestStatus(e.target.value)}>
          <option value="">all statuses</option>
          <option value="success">success</option>
          <option value="failure">failure</option>
        </select>
        <input
          value={requestIdQuery}
          onChange={(e) => setRequestIdQuery(e.target.value)}
          placeholder="Filter request_id..."
        />
      </div>

      <div className={`trace-grid ${collapseUsecases ? "users-collapsed" : ""} ${collapseRequests ? "requests-collapsed" : ""}`}>
        <aside className={`trace-users ${collapseUsecases ? "collapsed" : ""}`}>
          <div className="trace-col-head">
            <div className="trace-col-title">Usecase IDs</div>
          </div>
          <div className="trace-list">
            {pagedUsecases.map((u) => (
              <button
                key={u.usecase_id}
                type="button"
                className={`trace-user ${u.usecase_id === selectedUsecaseId ? "active" : ""}`}
                onClick={() => {
                  setSelectedUsecaseId(u.usecase_id);
                }}
              >
                <div>{u.usecase_id}</div>
                <small>{u.request_count} reqs</small>
              </button>
            ))}
          </div>
          <div className="trace-col-foot">
            {!collapseUsecases ? (
              <div className="trace-pager">
                <button
                  type="button"
                  className="trace-page-btn"
                  disabled={visibleUsecasePage <= 1}
                  onClick={() => setUsecasePage((p) => Math.max(1, p - 1))}
                >
                  Prev
                </button>
                <span>{visibleUsecasePage}/{usecaseTotalPages}</span>
                <button
                  type="button"
                  className="trace-page-btn"
                  disabled={visibleUsecasePage >= usecaseTotalPages}
                  onClick={() => setUsecasePage((p) => Math.min(usecaseTotalPages, p + 1))}
                >
                  Next
                </button>
              </div>
            ) : null}
            <button
              type="button"
              className="trace-collapse-btn icon"
              onClick={() => setCollapseUsecases((v) => !v)}
              aria-label={collapseUsecases ? "Expand usecases panel" : "Collapse usecases panel"}
              title={collapseUsecases ? "Expand" : "Collapse"}
            >
              {collapseUsecases ? "»" : "«"}
            </button>
          </div>
        </aside>

        <section className={`trace-requests ${collapseRequests ? "collapsed" : ""}`}>
          <div className="trace-col-head">
            <div className="trace-col-title">Requests ({requests.length})</div>
          </div>
          <div className="trace-req-head">
            <span>time</span>
            <span>request_id</span>
            <span>model</span>
            <span>status</span>
            <span>dur</span>
          </div>
          <div className="trace-req-table">
            {pagedRequests.map((r) => (
              <button
                key={r.trace_id}
                type="button"
                className={`trace-req-row ${r.trace_id === selectedTraceId ? "active" : ""}`}
                onClick={() => setSelectedTraceId(r.trace_id)}
              >
                <span>{fmtTime(r.started_at)}</span>
                <span title={r.request_id}>{`...${String(r.request_id || "").slice(-4)}`}</span>
                <span>{r.model_id}</span>
                <span className={r.status === "failure" ? "bad-text" : "good-text"}>{r.status}</span>
                <span>{r.duration_ms}ms</span>
              </button>
            ))}
            {!requests.length ? <div className="trace-empty">No requests for this usecase_id in selected window.</div> : null}
          </div>
          <div className="trace-col-foot">
            {!collapseRequests ? (
              <div className="trace-pager">
                <button
                  type="button"
                  className="trace-page-btn"
                  disabled={visibleRequestPage <= 1}
                  onClick={() => setRequestPage((p) => Math.max(1, p - 1))}
                >
                  Prev
                </button>
                <span>{visibleRequestPage}/{requestTotalPages}</span>
                <button
                  type="button"
                  className="trace-page-btn"
                  disabled={visibleRequestPage >= requestTotalPages}
                  onClick={() => setRequestPage((p) => Math.min(requestTotalPages, p + 1))}
                >
                  Next
                </button>
              </div>
            ) : null}
            <button
              type="button"
              className="trace-collapse-btn icon"
              onClick={() => setCollapseRequests((v) => !v)}
              aria-label={collapseRequests ? "Expand requests panel" : "Collapse requests panel"}
              title={collapseRequests ? "Expand" : "Collapse"}
            >
              {collapseRequests ? "»" : "«"}
            </button>
          </div>
        </section>

        <section className="trace-detail">
          <div className="trace-col-title">End-to-End Trace</div>
          {traceDetail ? (
            <div className="trace-detail-layout">
              <div className="trace-flow-pane">
              <div className="trace-summary">
                <span>trace: {traceDetail.trace_id.slice(0, 10)}...</span>
                <span>{traceDetail.model_id}</span>
                <span className={traceDetail.status === "failure" ? "bad-text" : "good-text"}>{traceDetail.status}</span>
                <span>{traceDetail.duration_ms}ms</span>
              </div>

              <div className="trace-flow">
                <div className="trace-tree">
                  {traceTree.map((root) => (
                    <TraceTreeNode
                      key={root.span_id}
                      node={root}
                      selectedSpanId={selectedSpanId}
                      onSelect={setSelectedSpanId}
                    />
                  ))}
                </div>
              </div>
              </div>

              <div className="trace-node-pane">
                {selectedSpan ? (
                <div className="trace-node-info">
                  <h4>Node Details</h4>
                  <div className="trace-kv"><span>Stage</span><b>{selectedSpan.stage}</b></div>
                  <div className="trace-kv"><span>Component</span><b>{selectedSpan.component}</b></div>
                  <div className="trace-kv"><span>Service</span><b>{selectedSpan.service}</b></div>
                  <div className="trace-kv"><span>Status</span><b>{selectedSpan.status}</b></div>
                  <div className="trace-kv"><span>Started</span><b>{fmtDateTime(selectedSpan.started_at)}</b></div>
                  <div className="trace-kv"><span>Ended</span><b>{fmtDateTime(selectedSpan.ended_at)}</b></div>
                  <div className="trace-kv"><span>Duration</span><b>{selectedSpan.duration_ms}ms</b></div>
                  <div className="trace-kv"><span>Input Tokens</span><b>{selectedSpan.input_tokens}</b></div>
                  <div className="trace-kv"><span>Output Tokens</span><b>{selectedSpan.output_tokens}</b></div>
                  <div className="trace-kv"><span>Usecase ID</span><b>{selectedUsecase?.usecase_id || traceDetail?.usecase_id || "-"}</b></div>
                  <div className="trace-kv"><span>Error</span><b>{selectedSpan.error || "-"}</b></div>
                  <pre className="trace-json">{JSON.stringify(selectedSpan.details || {}, null, 2)}</pre>
                </div>
                ) : (
                  <div className="trace-empty">Select a node to view details.</div>
                )}
              </div>
            </div>
          ) : (
            <div className="trace-empty">Select a request to inspect full trace.</div>
          )}
        </section>
      </div>
    </section>
  );
}
