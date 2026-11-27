import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const target = process.env.VITE_API_TARGET || 'http://127.0.0.1';

export default defineConfig({
  base: '/ui/',
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      '/api': { target, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // Разделяем тяжёлые библиотеки: один JS-бандл на 720 КБ мешает кэшу
    // и грузится целиком даже при открытии простого раздела.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return;
          if (id.includes('lightweight-charts')) return 'charts';
          if (id.includes('@tanstack')) return 'query';
          // React, radix, zod и прочее оставляем вместе: попытка выделить
          // react отдельно создаёт цикл vendor ↔ react из-за scheduler/radix.
          return 'vendor';
        },
      },
    },
  },
});
