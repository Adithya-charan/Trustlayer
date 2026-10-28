import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser only talks to /api; Vite proxies it to the FastAPI backend in development.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
})
