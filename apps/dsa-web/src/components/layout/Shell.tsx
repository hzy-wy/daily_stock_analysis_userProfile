import type React from 'react';
import { Outlet } from 'react-router-dom';
import { FloatingStockAssistant } from '../assistant';
import { CommandNavigation } from './CommandNavigation';

type ShellProps = {
  children?: React.ReactNode;
};

export const Shell: React.FC<ShellProps> = ({ children }) => {
  return (
    <div className="app-shell min-h-screen bg-background text-foreground">
      <div className="app-shell__ambient" aria-hidden="true">
        <span className="app-shell__grid" />
        <span className="app-shell__orb app-shell__orb--cyan" />
        <span className="app-shell__orb app-shell__orb--violet" />
        <span className="app-shell__scan" />
      </div>
      <div className="app-shell__frame mx-auto min-h-screen w-full max-w-[1920px] px-2.5 pb-24 pt-2.5 sm:px-4 sm:pt-4 xl:pb-5 xl:px-5">
        <CommandNavigation />
        <main className="app-shell__content min-h-0 min-w-0 touch-pan-y">
          {children ?? <Outlet />}
        </main>
      </div>
      <FloatingStockAssistant />
    </div>
  );
};
