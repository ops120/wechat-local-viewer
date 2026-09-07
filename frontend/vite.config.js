import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const FRONT_PORT = parseInt(process.env.WCVIEWER_FRONT_PORT || process.env.FRONT_PORT || '15713')
const BACK_PORT = process.env.WCVIEWER_PORT || process.env.API_PORT || '18787'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: FRONT_PORT,
    strictPort: false,
    proxy: {
      '/api': `http://127.0.0.1:${BACK_PORT}`,
      '/media': `http://127.0.0.1:${BACK_PORT}`,
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
