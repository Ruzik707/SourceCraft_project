import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  // Для публикации в подпапке (например, GitHub Pages) базовый путь задаётся
  // переменной: VITE_BASE_PATH=/yandex_sourcecraft/ npm run build
  base: process.env.VITE_BASE_PATH ?? '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // В dev запросы к бэку идут через прокси, поэтому фронт не зависит от CORS.
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  // fileURLToPath, а не .pathname: путь проекта может содержать не-ASCII символы
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: { outDir: 'dist', sourcemap: true },
});
