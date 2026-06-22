// Vercel serverless proxy: browser -> (HTTPS, same origin) -> here -> metal control plane.
// Keeps the token server-side and avoids mixed-content. Set METAL_URL + CW_TOKEN as Vercel env vars.
export default async function handler(req, res) {
  const base = process.env.METAL_URL;
  const token = process.env.CW_TOKEN || "";
  if (!base) {
    res.status(503).json({ error: "METAL_URL not configured — backend not exposed yet" });
    return;
  }
  // robustly reconstruct the sub-path after /api/, across Vercel runtimes
  let sub;
  const seg = req.query && req.query.path;
  if (Array.isArray(seg) && seg.length) sub = seg.join("/");
  else if (typeof seg === "string" && seg) sub = seg;
  else {
    const u = (req.url || "").split("?")[0].replace(/^\/+/, "");
    sub = u.replace(/^api\//, "");
  }
  const target = base.replace(/\/$/, "") + "/api/" + sub;
  if (req.query && req.query.__debug !== undefined) {
    res.status(200).json({ url: req.url, query: req.query, sub, target, method: req.method });
    return;
  }
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
