import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3001,
    host: '0.0.0.0',
    open: true,
    allowedHosts: ['wy.igeewa.com', 'wy.igeewa.com'],
    proxy: {
      '/api': {
        // 在 Docker Compose 中，前端后端在同一容器内，使用 localhost
        // 容器内部后端运行在 5001 端口
        target: 'http://localhost:5001',
        changeOrigin: true,
        secure: false,
        // 不需要 rewrite，后端路由本身就是 /api/graph/*
        timeout: 300000,
        proxyTimeout: 300000
      }
    }
  }
})
