/**
 * NPH Command Center - Route Configuration
 * 
 * Defines all application routes with lazy loading for code splitting.
 */

import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { CommandCenter } from './pages/CommandCenter';
import './Router.css';

// Lazy load pages for code splitting
const Services = lazy(() => import('./pages/Services').then(m => ({ default: m.Services })));
const Hosts = lazy(() => import('./pages/Hosts').then(m => ({ default: m.Hosts })));
const Storage = lazy(() => import('./pages/Storage').then(m => ({ default: m.Storage })));
const AI = lazy(() => import('./pages/AI').then(m => ({ default: m.AI })));
const Projects = lazy(() => import('./pages/Projects').then(m => ({ default: m.Projects })));
const Activity = lazy(() => import('./pages/Activity').then(m => ({ default: m.Activity })));
const Alerts = lazy(() => import('./pages/Alerts').then(m => ({ default: m.Alerts })));
const Settings = lazy(() => import('./pages/Settings').then(m => ({ default: m.Settings })));
const About = lazy(() => import('./pages/About').then(m => ({ default: m.About })));

function PageSkeleton() {
  return (
    <div className="page-skeleton">
      <div className="skeleton-header" />
      <div className="skeleton-content">
        <div className="skeleton-card" />
        <div className="skeleton-card" />
        <div className="skeleton-card" />
      </div>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Routes>
        <Route path="/" element={<CommandCenter />} />
        <Route path="/services" element={<Services />} />
        <Route path="/hosts" element={<Hosts />} />
        <Route path="/storage" element={<Storage />} />
        <Route path="/ai" element={<AI />} />
        <Route path="/ai/*" element={<AI />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/deployments" element={<Projects />} />
        <Route path="/roadmap" element={<Projects />} />
        <Route path="/activity" element={<Activity />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
