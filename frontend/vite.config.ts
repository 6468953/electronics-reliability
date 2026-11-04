import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期把 /api 代理到后端，避免 CORS 与硬编码域名。
// 部署时前端由任意静态服务器托管，改成同域反代 /api 即可，无需改代码。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1400,
    rollupOptions: {
      output: {
        // 把三个"半年才变一次"的大依赖拆出去：
        //   1) 首屏只下载 react + 业务代码，antd/echarts 由浏览器并行拉取并长期缓存；
        //   2) 改业务代码时不会让用户重新下载 700KB 的 antd；
        //   3) 单个 chunk 从 2.4MB 降到 ~1MB 级，构建告警消失。
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
          echarts: ['echarts'],
        },
      },
    },
  },
})
