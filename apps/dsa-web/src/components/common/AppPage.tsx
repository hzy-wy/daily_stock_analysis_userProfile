import type React from 'react';
import { cn } from '../../utils/cn';

interface AppPageProps {
  children: React.ReactNode;
  className?: string;
}

export const AppPage: React.FC<AppPageProps> = ({ children, className = '' }) => {
  return (
    <main className={cn('app-page mx-auto min-h-full w-full max-w-[1600px] px-3 pb-8 pt-3 sm:px-4 md:px-5 lg:px-6', className)}>
      {children}
    </main>
  );
};
