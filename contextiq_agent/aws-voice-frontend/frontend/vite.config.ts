import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    https: {
      key: './localhost-key.pem',
      cert: './localhost.pem',
    },
    hmr: {
      protocol: 'wss',
      host: 'localhost',
      port: 5173,
    },
    proxy: {
      // Proxy API requests to the local AgentCore backend
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        ws: true,
        secure: false, // Allow proxying from https to http for local dev
      },
    },
  },
  define: {
    // Fix for Node.js packages that expect 'global' to be defined
    global: 'globalThis',
  },
  optimizeDeps: {
    // Pre-bundle these dependencies to avoid issues
    include: ['amazon-cognito-identity-js'],
  },
  worker: {
    format: 'es',
  },
  build: {
    assetsInlineLimit: 0,
    rollupOptions: {
      output: {
        // Ensure worklet files are treated as separate chunks
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith('.worklet.ts')) {
            return 'assets/[name]-[hash][extname]';
          }
          return 'assets/[name]-[hash][extname]';
        },
      },
    },
  },
});
