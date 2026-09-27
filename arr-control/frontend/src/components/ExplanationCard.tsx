interface ExplanationProps {
  reason: string;
  evidence: string[];
}

export const ExplanationCard: React.FC<ExplanationProps> = ({ reason, evidence }) => {
  return (
    <div className="detail-explanation">
      <h3>WHY?</h3>
      <p>{reason}</p>
      {evidence.length > 0 && (
        <ul style={{ marginTop: '1rem', paddingLeft: '1.5rem', fontSize: '0.875rem', color: '#888' }}>
          {evidence.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default ExplanationCard;