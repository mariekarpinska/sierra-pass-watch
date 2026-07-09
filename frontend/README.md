# frontend

Vite + React + TypeScript SPA. See the [root README](../README.md) for how to
run the whole stack; the interceptor-based HTTP layer is documented in
[src/api/client.ts](src/api/client.ts).

```bash
npm install
npm run dev        # dev server, proxies /api to the backend
npm test           # Vitest + Testing Library
npm run lint       # oxlint
npm run build      # type-check + production bundle
```
