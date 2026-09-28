import http from 'node:http'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser only ever talks to this dev server. Vite proxies /api to FastAPI, which
// is why there is no CORS configuration in the backend and no mixed-content problem:
// as far as the page is concerned, everything is same-origin.
//
// Inside compose the target is the `api` service on the internal network; running
// `npm run dev` on the host it falls back to localhost.
const API_TARGET = process.env.API_TARGET ?? 'http://localhost:8000'

// Compose always sets PUBLIC_HOST, empty when there is no tunnel. An empty list is not
// the same as no list: Vite reads `[]` as "accept no hostname at all".
const PUBLIC_HOSTS = (process.env.PUBLIC_HOST ?? '')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // reachable from outside the container
    port: 5173,
    // Vite refuses requests whose Host it does not recognise (the DNS-rebinding fix,
    // CVE-2025-24010). The public hostnames are deployment configuration, not code, so
    // they arrive through the environment - a domain migration needs the old and the new
    // name accepted at once. Unset, nothing changes and localhost still works.
    allowedHosts: PUBLIC_HOSTS.length > 0 ? PUBLIC_HOSTS : undefined,
    // Bind mounts do not deliver inotify events reliably across the boundary, so the
    // watcher polls. Slightly more CPU, but hot reload actually works in Docker.
    watch: { usePolling: true },
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // Both ends have to agree about connection reuse, or the proxy answers 502.
        // Symptom: roughly half the dashboard's polls failed at random while curl never
        // did - because curl opens a fresh connection every time and the proxy pools.
        // Cause: uvicorn closes idle keep-alive sockets after 5s (its default), and the
        // pool kept handing back sockets the server had already closed.
        // Fix: keep the pool, and raise the server's timeout past the client's idle
        // window (see --timeout-keep-alive in docker-compose.yml). Turning keep-alive
        // off also worked, but traded a 50% failure rate for socket churn and a
        // residual ~1%.
        agent: new http.Agent({ keepAlive: true, keepAliveMsecs: 15_000, maxSockets: 24 }),
      },
    },
  },
})
