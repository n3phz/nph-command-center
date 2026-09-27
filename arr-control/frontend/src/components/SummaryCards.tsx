interface SummaryProps {
  active: number;
  attention: number;
  completedToday: number;
  failed: number;
}

export const SummaryCards: React.FC<SummaryProps> = ({ active, attention, completedToday, failed }) => {
  return (
    <div className="summary">
      <div className="summary-card">
        <div className="value">{active}</div>
        <div className="label">Active</div>
      </div>
      <div className="summary-card attention">
        <div className="value">{attention}</div>
        <div className="label">Attention</div>
      </div>
      <div className="summary-card completed">
        <div className="value">{completedToday}</div>
        <div className="label">Completed Today</div>
      </div>
      <div className="summary-card failed">
        <div className="value">{failed}</div>
        <div className="label">Failed</div>
      </div>
    </div>
  );
};

export default SummaryCards;