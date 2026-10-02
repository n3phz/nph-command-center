/**
 * NPH Command Center - Application Shell
 * 
 * Main layout component with sidebar, top bar, and content area.
 * Responsive design with mobile navigation drawer.
 */

import { useState, useEffect, useCallback } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { MobileNavDrawer } from './MobileNavDrawer';
import { CommandPalette } from '../search/CommandPalette';
import './Shell.css';

interface ShellProps {
  quickActions: any[];
}

export function Shell({ quickActions }: ShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const location = useLocation();

  // Close mobile nav on route change
  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd/Ctrl + K for command palette
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(true);
      }
      // Escape to close modals
      if (e.key === 'Escape') {
        setCommandPaletteOpen(false);
        setMobileNavOpen(false);
      }
      // Forward slash for search (when not in input)
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault();
        setCommandPaletteOpen(true);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen(prev => !prev);
  }, []);

  return (
    <div className="shell">
      <Sidebar 
        open={sidebarOpen} 
        onToggle={toggleSidebar}
      />
      
      <div className="shell-main" style={{ marginLeft: sidebarOpen ? '280px' : '72px' }}>
        <TopBar 
          onMenuClick={toggleSidebar}
          onSearchClick={() => setCommandPaletteOpen(true)}
          quickActions={quickActions}
        />
        
        <main className="shell-content" role="main">
          <Outlet />
        </main>
      </div>

      <MobileNavDrawer 
        open={mobileNavOpen} 
        onClose={() => setMobileNavOpen(false)}
      />

      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
      />
    </div>
  );
}
