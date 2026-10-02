/**
 * NPH Command Center - AI Page
 * 
 * AI gateway status, model routing, and provider management.
 */

import { useState, useEffect } from 'react';
import { AICommandCenter } from '../types/infrastructure';
import { getAICommandCenter } from '../services/command-center';
import { AICommandCenterPanel } from '../components/ai/AICommandCenterPanel';
import './AI.css';

export function AI() {
  const [ai, setAI] = useState<AICommandCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAI = async () => {
    try {
      setLoading(true);
      const data = await getAICommandCenter();
      setAI(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load AI data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAI();
  }, []);

  if (loading) {
    return (
      <div className="ai-page loading">
        <div className="loading-skeleton">
          <div className="skeleton-header" />
          <div className="skeleton-panel" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="ai-page error">
        <div className="error-state">
          <h2>Failed to Load AI Gateway</h2>
          <p>{error}</p>
          <button onClick={loadAI} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-page">
      <header className="page-header">
        <h1>AI Gateway</h1>
        <p className="page-subtitle">
          {ai?.providers.length || 0} providers • 
          {ai?.currentRoute ? `${ai.currentRoute.provider} / ${ai.currentRoute.model}` : 'No route configured'}
        </p>
      </header>

      <AICommandCenterPanel ai={ai} />
    </div>
  );
}
