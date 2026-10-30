import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser only talks to /api; Vite proxies it to the FastAPI backend in development.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': process.env.VITE_API_TARGET || 'http://localhost:8000' } },  // VITE_API_TARGET lets a second dev stack point at another backend
})
