'use client';

import React, { useState, useEffect } from 'react';
import { Menu, X } from 'lucide-react';
import { useIsMobile, useIsTablet } from '@/hooks/useMediaQuery';
import { motion, AnimatePresence } from 'framer-motion';

interface ResponsiveLayoutProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode;
  rightPanel?: React.ReactNode;
}

export default function ResponsiveLayout({ 
  children, 
  sidebar, 
  rightPanel 
}: ResponsiveLayoutProps) {
  const isMobile = useIsMobile();
  const isTablet = useIsTablet();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);

  // Close sidebars when switching to desktop
  useEffect(() => {
    if (!isMobile && !isTablet) {
      setSidebarOpen(false);
      setRightPanelOpen(false);
    }
  }, [isMobile, isTablet]);

  const toggleSidebar = () => {
    setSidebarOpen(!sidebarOpen);
    if (rightPanelOpen) setRightPanelOpen(false);
  };

  const toggleRightPanel = () => {
    setRightPanelOpen(!rightPanelOpen);
    if (sidebarOpen) setSidebarOpen(false);
  };

  return (
    <div className="relative h-full flex">
      {/* Mobile Menu Button */}
      {(isMobile || isTablet) && (
        <button
          onClick={toggleSidebar}
          className="fixed top-4 left-4 z-50 p-2 bg-white dark:bg-gray-800 rounded-lg shadow-lg lg:hidden"
        >
          {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      )}

      {/* Overlay for mobile */}
      <AnimatePresence>
        {(isMobile || isTablet) && (sidebarOpen || rightPanelOpen) && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black bg-opacity-50 z-40 lg:hidden"
            onClick={() => {
              setSidebarOpen(false);
              setRightPanelOpen(false);
            }}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      {sidebar && (
        <>
          {/* Desktop Sidebar */}
          <div className="hidden lg:block w-80 border-r border-[var(--border)]">
            {sidebar}
          </div>

          {/* Mobile/Tablet Sidebar */}
          <AnimatePresence>
            {(isMobile || isTablet) && sidebarOpen && (
              <motion.div
                initial={{ x: '-100%' }}
                animate={{ x: 0 }}
                exit={{ x: '-100%' }}
                transition={{ type: 'tween', duration: 0.3 }}
                className="fixed left-0 top-0 h-full w-80 bg-[var(--background)] z-50 lg:hidden"
              >
                {sidebar}
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {children}
      </div>

      {/* Right Panel */}
      {rightPanel && (
        <>
          {/* Desktop Right Panel */}
          <div className="hidden lg:block w-72 border-l border-[var(--border)]">
            {rightPanel}
          </div>

          {/* Mobile/Tablet Right Panel Button */}
          {(isMobile || isTablet) && (
            <button
              onClick={toggleRightPanel}
              className="fixed top-4 right-4 z-50 p-2 bg-white dark:bg-gray-800 rounded-lg shadow-lg lg:hidden"
            >
              {rightPanelOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          )}

          {/* Mobile/Tablet Right Panel */}
          <AnimatePresence>
            {(isMobile || isTablet) && rightPanelOpen && (
              <motion.div
                initial={{ x: '100%' }}
                animate={{ x: 0 }}
                exit={{ x: '100%' }}
                transition={{ type: 'tween', duration: 0.3 }}
                className="fixed right-0 top-0 h-full w-72 bg-[var(--background)] z-50 lg:hidden"
              >
                {rightPanel}
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
