import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Local development configuration (HTTP, no SSL certificates needed)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Use HTTP for simpler local development (no SSL certs needed)
    // Note: Some browsers require HTTPS for microphone access
    // If you encounter mic issues, generate SSL certs with:
    // mkcert -install && mkcert localhost
    proxy: {
      // Proxy /api requests to our local Python backend on port 8080
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        ws: true, // Enable WebSocket proxying
        secure: false,
      },
    },
  },
  define: {
    global: 'globalThis',
  },
  optimizeDeps: {
    include: ['amazon-cognito-identity-js'],
  },
  worker: {
    format: 'es',
  },
  build: {
    assetsInlineLimit: 0,
    rollupOptions: {
      output: {
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
