export default function FilterBar({ filters, onChange, modelOptions, serviceOptions }) {
  return (
    <section className="panel filter-panel">
      <div className="filter-bar">
      <input
        placeholder="user_id"
        value={filters.user_id}
        onChange={(e) => onChange("user_id", e.target.value)}
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
