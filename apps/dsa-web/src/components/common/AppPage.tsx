import type React from 'react';
import { cn } from '../../utils/cn';

interface AppPageProps {
  children: React.ReactNode;
  className?: string;
}

export const AppPage: React.FC<AppPageProps> = ({ children, className = '' }) => {
  return (
    <main className={cn('app-page mx-auto min-h-full w-full max-w-[1760px] px-1 pb-8 pt-3 sm:px-2 md:px-3 lg:px-4', className)}>
      {children}
    </main>
  );
};
