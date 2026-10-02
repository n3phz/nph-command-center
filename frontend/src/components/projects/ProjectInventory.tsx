/**
 * NPH Command Center - Project Inventory Component
 * 
 * Displays projects with status, repository, and deployment info.
 */

import { Project } from '../../types/infrastructure';
import { ProjectCard } from './ProjectCard';
import './ProjectInventory.css';

interface ProjectInventoryProps {
  projects: Project[];
  maxItems?: number;
}

export function ProjectInventory({ projects, maxItems = 8 }: ProjectInventoryProps) {
  const displayProjects = projects.slice(0, maxItems);

  const statusCounts = projects.reduce((acc, p) => {
    acc[p.status] = (acc[p.status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  if (!projects.length) {
    return (
      <div className="project-inventory empty">
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          <span>No projects discovered</span>
          <p>Projects will appear here when configured</p>
        </div>
      </div>
    );
  }

  return (
    <div className="project-inventory">
      <div className="project-summary">
        <span className={`summary-item ${statusCounts.ACTIVE ? 'active' : ''}`}>
          {statusCounts.ACTIVE || 0} active
        </span>
        <span className={`summary-item ${statusCounts.DEPLOYED ? 'deployed' : ''}`}>
          {statusCounts.DEPLOYED || 0} deployed
        </span>
        <span className={`summary-item ${statusCounts.DEVELOPMENT ? 'development' : ''}`}>
          {statusCounts.DEVELOPMENT || 0} dev
        </span>
        <span className={`summary-item ${statusCounts.ATTENTION ? 'attention' : ''}`}>
          {statusCounts.ATTENTION || 0} attention
        </span>
        <span className="summary-item total">{projects.length} total</span>
      </div>
      
      <div className="project-grid" role="list" aria-label="Projects">
        {displayProjects.map(project => (
          <ProjectCard key={project.id} project={project} />
        ))}
      </div>
      
      {projects.length > maxItems && (
        <div className="inventory-footer">
          <span>+{projects.length - maxItems} more projects</span>
        </div>
      )}
    </div>
  );
}
