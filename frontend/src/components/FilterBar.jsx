export default function FilterBar({ filters, onChange, modelOptions, serviceOptions }) {
  return (
    <section className="panel filter-panel">
      <div className="filter-bar">
      <input
        placeholder="usecase_id"
        value={filters.usecase_id || ""}
        onChange={(e) => onChange("usecase_id", e.target.value)}
      />
      <input
        placeholder="request_id"
        value={filters.request_id || ""}
        onChange={(e) => onChange("request_id", e.target.value)}
      />
      <select value={filters.model_id} onChange={(e) => onChange("model_id", e.target.value)}>
        <option value="">all models</option>
        {modelOptions.map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
      <select value={filters.service} onChange={(e) => onChange("service", e.target.value)}>
        <option value="">all services</option>
        {serviceOptions.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
      <select value={filters.status} onChange={(e) => onChange("status", e.target.value)}>
        <option value="">all statuses</option>
        <option value="success">success</option>
        <option value="failure">failure</option>
      </select>
      </div>
    </section>
  );
}
