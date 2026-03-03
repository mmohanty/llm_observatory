import { useEffect, useMemo, useState } from "react";

const PAGE_SIZES = [10, 20, 50];

function norm(v) {
  return String(v || "").toLowerCase();
}

export default function RecentRequestsGrid({ events, onFiltersChange }) {
  const [query, setQuery] = useState("");
  const [requestId, setRequestId] = useState("");
  const [status, setStatus] = useState("");
  const [service, setService] = useState("");
  const [model, setModel] = useState("");
  const [usecaseId, setUsecaseId] = useState("");
  const [timeMode, setTimeMode] = useState("all");
  const [timeFrom, setTimeFrom] = useState("");
  const [timeTo, setTimeTo] = useState("");
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);

  const serviceOptions = useMemo(() => Array.from(new Set(events.map((e) => e.service))).sort(), [events]);
  const modelOptions = useMemo(() => Array.from(new Set(events.map((e) => e.model_id))).sort(), [events]);
  const usecaseOptions = useMemo(
    () => Array.from(new Set(events.map((e) => e.usecase_id || e.tenant_id || "default"))).sort(),
    [events]
  );

  const rows = useMemo(() => {
    const q = norm(query.trim());
    const fromMs = timeFrom ? new Date(timeFrom).getTime() : null;
    const toMs = timeTo ? new Date(timeTo).getTime() : null;
    const sorted = [...events].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
    return sorted.filter((e) => {
      const ts = new Date(e.timestamp).getTime();
      if (status && e.status !== status) return false;
      if (service && e.service !== service) return false;
      if (model && e.model_id !== model) return false;
      const eventUsecase = e.usecase_id || e.tenant_id || "default";
      if (usecaseId && eventUsecase !== usecaseId) return false;
      if (requestId && e.request_id !== requestId) return false;
      if (timeMode === "after" && fromMs !== null && ts < fromMs) return false;
      if (timeMode === "before" && toMs !== null && ts > toMs) return false;
      if (timeMode === "range") {
        if (fromMs !== null && ts < fromMs) return false;
        if (toMs !== null && ts > toMs) return false;
      }
      if (!q) return true;
      const blob = [
        e.request_id,
        eventUsecase,
        e.model_id,
        e.service,
        e.status,
        e.provider,
        e.region,
        e.tenant_id,
        e.error
      ]
        .map(norm)
        .join(" ");
      return blob.includes(q);
    });
  }, [events, query, requestId, status, service, model, usecaseId, timeMode, timeFrom, timeTo]);

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, totalPages);

  const stats = useMemo(() => {
    const success = rows.filter((r) => r.status === "success").length;
    const failure = rows.length - success;
    const input = rows.reduce((sum, r) => sum + Number(r.input_tokens || 0), 0);
    const output = rows.reduce((sum, r) => sum + Number(r.output_tokens || 0), 0);
    return { events: rows.length, success, failure, input, output };
  }, [rows]);

  const paged = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return rows.slice(start, start + pageSize);
  }, [rows, currentPage, pageSize]);

  const from = rows.length === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const to = Math.min(rows.length, currentPage * pageSize);

  useEffect(() => {
    if (!onFiltersChange) return;
    onFiltersChange({
      query,
      requestId,
      status,
      service,
      model,
      usecaseId,
      timeMode,
      timeFrom,
      timeTo,
    });
  }, [onFiltersChange, query, requestId, status, service, model, usecaseId, timeMode, timeFrom, timeTo]);

  return (
    <section className="panel table-panel">
      <h3>Recent Requests</h3>

      <div className="rr-stats">
        <div className="rr-card"><span>Events</span><b>{stats.events}</b></div>
        <div className="rr-card"><span>Success</span><b>{stats.success}</b></div>
        <div className="rr-card"><span>Failure</span><b>{stats.failure}</b></div>
        <div className="rr-card"><span>Input Tokens</span><b>{stats.input}</b></div>
        <div className="rr-card"><span>Output Tokens</span><b>{stats.output}</b></div>
      </div>

      <div className="grid-toolbar">
        <input
          className="grid-search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
          placeholder="Search request id, usecase_id, model, service, provider..."
        />

        <input
          value={requestId}
          onChange={(e) => {
            setRequestId(e.target.value.trim());
            setPage(1);
          }}
          placeholder="request_id"
        />

        <select value={usecaseId} onChange={(e) => { setUsecaseId(e.target.value); setPage(1); }}>
          <option value="">all usecases</option>
          {usecaseOptions.map((u) => <option key={u} value={u}>{u}</option>)}
        </select>

        <select value={model} onChange={(e) => { setModel(e.target.value); setPage(1); }}>
          <option value="">all models</option>
          {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>

        <select value={service} onChange={(e) => { setService(e.target.value); setPage(1); }}>
          <option value="">all services</option>
          {serviceOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">all statuses</option>
          <option value="success">success</option>
          <option value="failure">failure</option>
        </select>

        <select value={timeMode} onChange={(e) => { setTimeMode(e.target.value); setPage(1); }}>
          <option value="all">time: all</option>
          <option value="after">time: &gt;= from</option>
          <option value="before">time: &lt;= to</option>
          <option value="range">time: range</option>
        </select>

        <input
          type="datetime-local"
          value={timeFrom}
          onChange={(e) => { setTimeFrom(e.target.value); setPage(1); }}
          placeholder="from"
          disabled={timeMode === "all" || timeMode === "before"}
        />
        <input
          type="datetime-local"
          value={timeTo}
          onChange={(e) => { setTimeTo(e.target.value); setPage(1); }}
          placeholder="to"
          disabled={timeMode === "all" || timeMode === "after"}
        />
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>time</th>
              <th>request_id</th>
              <th>usecase_id</th>
              <th>model</th>
              <th>service</th>
              <th>status</th>
              <th>provider</th>
              <th>region</th>
              <th>tenant</th>
              <th>in</th>
              <th>out</th>
              <th>latency(ms)</th>
              <th>cost($)</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((e) => (
              <tr key={`${e.request_id}-${e.service}-${e.timestamp}`}>
                <td>{new Date(e.timestamp).toLocaleTimeString()}</td>
                <td title={e.request_id}>{e.request_id}</td>
                <td>{e.usecase_id || e.tenant_id || "default"}</td>
                <td>{e.model_id}</td>
                <td>{e.service}</td>
                <td className={e.status === "failure" ? "bad-text" : "good-text"}>{e.status}</td>
                <td>{e.provider || "-"}</td>
                <td>{e.region || "-"}</td>
                <td>{e.tenant_id || "-"}</td>
                <td>{e.input_tokens}</td>
                <td>{e.output_tokens}</td>
                <td>{e.latency_ms}</td>
                <td>{Number(e.cost_usd || 0).toFixed(4)}</td>
              </tr>
            ))}
            {paged.length === 0 ? (
              <tr>
                <td colSpan="13" className="empty-row">No requests match current filters.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="grid-pagination">
        <div className="grid-summary">Showing {from}-{to} of {rows.length}</div>

        <div className="grid-controls">
          <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}/page</option>)}
          </select>

          <button type="button" className="density-btn" disabled={currentPage <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            Prev
          </button>
          <span className="page-indicator">{currentPage} / {totalPages}</span>
          <button type="button" className="density-btn" disabled={currentPage >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
