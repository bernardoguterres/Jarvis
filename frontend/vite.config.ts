import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    // Vite 6's DNS-rebinding protection rejects any request whose Host
    // header isn't localhost/127.0.0.1 by default — which blocks the dev
    // server the moment it's reached through VS Code's devcontainer port
    // forwarding (a different Host header). Safe here: this only ever
    // runs against a local/preview dev server, never a public deployment.
    allowedHosts: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
  },
})
