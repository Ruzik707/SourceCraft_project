import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { AuthProvider } from '@/auth/AuthProvider';
import { ErrorBoundary } from '@/components/layout/ErrorBoundary';
import { applyTheme, getStoredTheme } from '@/lib/theme';
import './styles/global.css';
import './styles/print.css';

// ?theme=dark|light позволяет открыть страницу в нужной теме (демо, скриншоты, печать)
const themeParam = new URLSearchParams(window.location.search).get('theme');
applyTheme(themeParam === 'dark' || themeParam === 'light' ? themeParam : getStoredTheme());

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={import.meta.env.BASE_URL}>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
