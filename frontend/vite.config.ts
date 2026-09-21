/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // shared/ holds presets and templates read by both frontend and backend (plan §6)
    alias: { '@shared': fileURLToPath(new URL('../shared', import.meta.url)) },
  },
  server: {
    fs: { allow: ['..'] },
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'node',
  },
})
