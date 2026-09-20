import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1', // 显式绑 IPv4：否则 Windows 上会绑到 IPv6 ::1，Tauri(devUrl) 连不上
    port: 5173,
    strictPort: true, // Tauri devUrl 固定指向 5173，端口被占用时直接报错而不是顺延
  },
})
