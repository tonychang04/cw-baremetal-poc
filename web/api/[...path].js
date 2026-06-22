// Vercel serverless proxy: browser -> (HTTPS, same origin) -> here -> metal control plane.
// Keeps the token server-side and avoids mixed-content. Set METAL_URL + CW_TOKEN as Vercel env vars.
// METAL_URL is the metal API base reachable from Vercel (e.g. an authorized tunnel URL).
export default async function handler(req, res) {
  const base = process.env.METAL_URL;
  const token = process.env.CW_TOKEN || "";
  if (!base) {
    res.status(503).json({ error: "METAL_URL not configured — backend not exposed yet" });
    return;
  }
  const target = base.replace(/\/$/, "") + req.url; // req.url = /api/...
  const init = {
    method: req.method,
    headers: { "Content-Type": "application/json", "X-CW-Token": token },
  };
  if (!["GET", "HEAD"].includes(req.method)) init.body = JSON.stringify(req.body || {});
  try {
    const r = await fetch(target, init);
    const text = await r.text();
    res.status(r.status).setHeader("Content-Type", "application/json").send(text);
  } catch (e) {
    res.status(502).json({ error: "backend unreachable", detail: String(e) });
  }
}
