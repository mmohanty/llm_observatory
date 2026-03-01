function Card({ label, value }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

export default function StatCards({ events }) {
  const success = events.filter((e) => e.status === "success").length;
  const failure = events.length - success;
  const inTokens = events.reduce((sum, e) => sum + (e.input_tokens || 0), 0);
  const outTokens = events.reduce((sum, e) => sum + (e.output_tokens || 0), 0);

  return (
    <div className="stats-grid">
      <Card label="Events" value={events.length} />
      <Card label="Success" value={success} />
      <Card label="Failure" value={failure} />
      <Card label="Input Tokens" value={inTokens} />
      <Card label="Output Tokens" value={outTokens} />
    </div>
  );
}
