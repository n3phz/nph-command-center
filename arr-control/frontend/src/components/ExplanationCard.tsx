interface ExplanationProps {
  reason: string;
  evidence: string[];
  confidence?: 'HIGH' | 'MEDIUM' | 'LOW';
  guardarrEvidence?: string[];
}

export const ExplanationCard: React.FC<ExplanationProps> = ({ reason, evidence, confidence, guardarrEvidence }) => {
  const confidenceColors: Record<string, string> = {
    HIGH: '#00b894',
    MEDIUM: '#fdcb6e',
    LOW: '#d63031',
  };

  return (
    <div className="detail-explanation">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <h3 style={{ margin: 0 }}>WHY?</h3>
        {confidence && (
          <span
            style={{
              padding: '0.125rem 0.5rem',
              borderRadius: '0.25rem',
              fontSize: '0.75rem',
              fontWeight: 'bold',
              background: confidenceColors[confidence],
              color: '#fff',
            }}
          >
            {confidence}
          </span>
        )}
      </div>
      <p>{reason}</p>
      {evidence.length > 0 && (
        <ul style={{ marginTop: '1rem', paddingLeft: '1.5rem', fontSize: '0.875rem', color: '#888' }}>
          {evidence.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
      {guardarrEvidence && guardarrEvidence.length > 0 && (
        <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid #333' }}>
          <h4 style={{ margin: '0 0 0.5rem 0', color: '#0abde3' }}>Guardarr Evidence</h4>
          <ul style={{ paddingLeft: '1.5rem', fontSize: '0.875rem', color: '#888' }}>
            {guardarrEvidence.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default ExplanationCard;