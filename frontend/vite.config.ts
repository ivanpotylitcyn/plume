import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  // На проде фронт отдаёт Django через WhiteNoise из /static/ — ассеты в index.html
  // должны ссылаться на /static/assets/*. В dev Vite сам отдаёт SPA и public (шрифты)
  // из корня, поэтому base '/static/' только для сборки — иначе прокси /static
  // перехватил бы сам шелл приложения.
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  server: {
    port: 5173,
    // Проксируем на Django dev-сервер только API и админку; статику и SPA
    // в dev отдаёт сам Vite.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
    },
  },
}))
