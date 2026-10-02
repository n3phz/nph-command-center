/**
 * NPH Command Center - Project Card Component
 * 
 * Compact project display with status, repository, and deployment info.
 */

import { Project } from '../../types/infrastructure';
import './ProjectCard.css';

interface ProjectCardProps {
  project: Project;
}

const STATUS_CONFIG = {
  ACTIVE: { label: 'Active', color: 'var(--status-healthy)' },
  DEPLOYED: { label: 'Deployed', color: 'var(--accent-primary)' },
  DEVELOPMENT: { label: 'Development', color: 'var(--status-warning)' },
  ATTENTION: { label: 'Attention', color: 'var(--status-critical)' },
  ARCHIVED: { label: 'Archived', color: 'var(--status-unknown)' },
  UNKNOWN: { label: 'Unknown', color: 'var(--status-unknown)' },
} as const;

export function ProjectCard({ project }: ProjectCardProps) {
  const config = STATUS_CONFIG[project.status] || STATUS_CONFIG.UNKNOWN;

  return (
    <article className={`project-card ${project.status.toLowerCase()}`} role="listitem">
      <div className="project-header">
        <div className="project-identity">
          <span className="project-status-dot" style={{ backgroundColor: config.color }} />
          <div>
            <h3 className="project-name">{project.name}</h3>
            {project.repository && (
              <a href={project.repository} target="_blank" rel="noopener noreferrer" className="project-repo">
                {new URL(project.repository).pathname.slice(1)}
              </a>
            )}
          </div>
        </div>
        <span className="project-status-badge" style={{ backgroundColor: config.color }}>
          {config.label}
        </span>
      </div>

      <div className="project-details">
        {project.description && (
          <p className="project-description">{project.description}</p>
        )}

        <div className="project-meta-grid">
          {project.technology && project.technology.length > 0 && (
            <div className="meta-item">
              <span className="meta-label">Tech</span>
              <div className="tech-tags">
                {project.technology.slice(0, 4).map(tech => (
                  <span key={tech} className="tech-tag">{tech}</span>
                ))}
                {project.technology.length > 4 && (
                  <span className="tech-tag more">+{project.technology.length - 4}</span>
                )}
              </div>
            </div>
          )}

          {project.deploymentUrl && (
            <div className="meta-item">
              <span className="meta-label">Deployment</span>
              <span className="meta-value">{project.deploymentUrl}</span>
            </div>
          )}

          {project.lastChange && (
            <div className="meta-item">
              <span className="meta-label">Last Change</span>
              <time className="meta-value" dateTime={project.lastChange}>
                {formatRelativeTime(project.lastChange)}
              </time>
            </div>
          )}

          {project.url && (
            <div className="meta-item">
              <span className="meta-label">URL</span>
              <a href={project.url} target="_blank" rel="noopener noreferrer" className="meta-value link">
                {new URL(project.url).hostname}
              </a>
            </div>
          )}
        </div>

        {project.attentionItem && (
          <div className="project-attention">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12.01" y2="9" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            <span>{project.attentionItem}</span>
          </div>
        )}

        <div className="project-footer">
          <time className="last-update" dateTime={project.lastChange || new Date().toISOString()}>
            Updated {project.lastChange ? formatRelativeTime(project.lastChange) : 'recently'}
          </time>
          {project.url && (
            <a href={project.url} target="_blank" rel="noopener noreferrer" className="btn-secondary">
              Open
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
          )}
        </div>
      </div>
    </article>
  );
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}
