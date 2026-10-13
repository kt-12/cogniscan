import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Built output is served by the FastAPI server at /static/dist/; `npm run dev` proxies the API to it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/static/dist/',
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  build: { outDir: '../server/static/dist', emptyOutDir: true, chunkSizeWarningLimit: 3000 },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8787',
      '/surf': 'http://127.0.0.1:8787',
    },
  },
})
