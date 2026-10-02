/**
 * NPH Command Center - Projects Page
 * 
 * Full project inventory with status, repository, and deployment info.
 */

import { useState, useMemo, useEffect } from 'react';
import { Project, ProjectStatus } from '../types/infrastructure';
import { getProjects } from '../services/command-center';
import { ProjectInventory } from '../components/projects/ProjectInventory';
import './Projects.css';

export function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<ProjectStatus | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const loadProjects = async () => {
    try {
      setLoading(true);
      const data = await getProjects();
      setProjects(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProjects();
  }, []);

  const filteredProjects = useMemo(() => {
    return projects.filter(project => {
      if (statusFilter !== 'all' && project.status !== statusFilter) return false;
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!project.name.toLowerCase().includes(query) &&
            !project.description?.toLowerCase().includes(query) &&
            !project.repository?.toLowerCase().includes(query) &&
            !project.technology?.some(t => t.toLowerCase().includes(query))) {
          return false;
        }
      }
      return true;
    });
  }, [projects, statusFilter, searchQuery]);

  const statusCounts = useMemo(() => {
    return projects.reduce((acc, p) => {
      acc[p.status] = (acc[p.status] || 0) + 1;
      return acc;
    }, {} as Record<ProjectStatus, number>);
  }, [projects]);

  if (loading) {
    return (
      <div className="projects-page loading">
        <div className="loading-skeleton">
          <div className="skeleton-header" />
          <div className="skeleton-filters" />
          <div className="skeleton-grid">
            {[...Array(6)].map((_, i) => <div key={i} className="skeleton-card" />)}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="projects-page error">
        <div className="error-state">
          <h2>Failed to Load Projects</h2>
          <p>{error}</p>
          <button onClick={loadProjects} className="btn-primary">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="projects-page">
      <header className="page-header">
        <h1>Projects</h1>
        <div className="page-stats">
          <span className="stat active">{statusCounts.ACTIVE || 0} Active</span>
          <span className="stat deployed">{statusCounts.DEPLOYED || 0} Deployed</span>
          <span className="stat development">{statusCounts.DEVELOPMENT || 0} Development</span>
          <span className="stat attention">{statusCounts.ATTENTION || 0} Attention</span>
        </div>
      </header>

      <div className="filters-bar">
        <div className="filter-group search-group">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Search projects..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="filter-input"
          />
        </div>

        <div className="filter-group">
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as ProjectStatus | 'all')}
            className="filter-select"
          >
            <option value="all">All Statuses</option>
            {(['ACTIVE', 'DEPLOYED', 'DEVELOPMENT', 'ATTENTION', 'ARCHIVED', 'UNKNOWN'] as ProjectStatus[]).map(status => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </div>
      </div>

      <ProjectInventory projects={filteredProjects} maxItems={100} />
    </div>
  );
}
