# web/ — Vercel frontend

Static UI (`public/index.html`) + a serverless proxy (`api/[...path].js`) that forwards `/api/*`
to the metal control plane. The browser only ever talks HTTPS-to-Vercel (no mixed content); the
token stays server-side in the proxy.

## Deploy

```bash
cd web
vercel --prod
```

## Make it live (requires authorizing backend exposure)

The metal API is IP-locked by default. To let Vercel reach it you must expose it — **this is a
deliberate security decision** because the control plane can spawn microVMs:

1. Expose the metal API over HTTPS *without* opening the EC2 SG broadly — e.g. an outbound tunnel
   (`cloudflared tunnel --url http://localhost:8080`) which yields an `https://…` URL.
2. Set Vercel env vars:
   ```bash
   vercel env add METAL_URL production   # the https tunnel URL
   vercel env add CW_TOKEN  production    # the token the metal API enforces
   vercel --prod
   ```

Until `METAL_URL` is set, the UI loads and shows a "backend unreachable" banner (proxy returns 503).
