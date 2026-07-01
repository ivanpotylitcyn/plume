import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  // На проде фронт отдаёт Django через WhiteNoise из /static/ — ассеты в index.html
  // должны ссылаться на /static/assets/*. В dev-сервере Vite это на раздачу не влияет.
  base: '/static/',
  plugins: [react()],
  server: {
    port: 5173,
    // /api и /admin проксируем на Django dev-сервер (локально, волна 1).
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
      '/static': 'http://127.0.0.1:8000',
    },
  },
})
