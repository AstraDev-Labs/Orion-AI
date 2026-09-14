import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';

// Set by the Tauri CLI while it runs beforeBuildCommand / beforeDevCommand.
const isTauriBuild = Boolean(process.env.TAURI_ENV_PLATFORM);

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      // The desktop app ships its interface inside the executable, so an
      // offline cache only gets in the way: the service worker kept serving
      // the previous version's interface after an install or update. Desktop
      // builds get a worker that unregisters itself and deletes that cache,
      // which also cleans up installs that already have the old one.
      selfDestroying: isTauriBuild,
      manifest: {
        name: 'Orion',
        short_name: 'Orion',
        description: 'On-device AI assistant',
        theme_color: '#161618',
        background_color: '#161618',
        display: 'standalone',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg}'],
        navigateFallbackDenylist: [/^\/v1\//, /^\/health/, /^\/dashboard/, /^\/api\//],
      },
    }),
  ],
  build: {
    outDir: '../src/orion/server/static',
    emptyOutDir: true,
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          markdown: ['react-markdown', 'rehype-highlight', 'remark-gfm'],
          charts: ['recharts'],
          router: ['react-router'],
          // three + the R3F wrappers dominate the bundle and are only needed by
          // the holo HUD. Splitting them keeps the entry chunk under workbox's
          // 2 MiB precache limit (the PWA build failed outright once the entry
          // crossed it) and stops every visitor downloading the 3D stack before
          // the first paint.
          three: ['three'],
          fiber: ['@react-three/fiber', '@react-three/drei'],
          vision: ['@mediapipe/tasks-vision'],
          math: ['katex', 'rehype-katex', 'remark-math'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/v1': process.env.VITE_API_URL || 'http://localhost:8000',
      '/health': process.env.VITE_API_URL || 'http://localhost:8000',
      '/api': process.env.VITE_API_URL || 'http://localhost:8000',
    },
  },
});
