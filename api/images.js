export default async function handler(req, res) {
  const name = String(req.query?.name || "").trim();
  if (!name) return res.status(400).json({ error: "Falta el nombre" });

  const serperKey = process.env.SERPER_API_KEY;
  const serpApiKey = process.env.SERPAPI_KEY;

  try {
    if (serperKey) {
      const r = await fetch("https://google.serper.dev/images", {
        method: "POST",
        headers: { "X-API-KEY": serperKey, "Content-Type": "application/json" },
        body: JSON.stringify({ q: name + " perfume bottle", gl: "co", hl: "es" })
      });
      if (r.ok) {
        const data = await r.json();
        const items = data.images || [];
        const clean = items.find(x => x.imageUrl && !/instagram|facebook|tiktok|pinterest/i.test(String(x.source || "") + " " + String(x.link || ""))) || items[0];
        if (clean?.imageUrl) {
          res.setHeader("Cache-Control", "s-maxage=86400, stale-while-revalidate=604800");
          return res.status(200).json({ image: clean.imageUrl, url: clean.link || null, source: clean.source || "Google Images", title: clean.title || name });
        }
      }
    }

    if (serpApiKey) {
      const u = new URL("https://serpapi.com/search.json");
      u.searchParams.set("engine", "google_images");
      u.searchParams.set("q", name + " perfume bottle");
      u.searchParams.set("gl", "co");
      u.searchParams.set("hl", "es");
      u.searchParams.set("api_key", serpApiKey);
      const r = await fetch(u);
      if (r.ok) {
        const data = await r.json();
        const items = data.images_results || [];
        const clean = items.find(x => x.original && !/instagram|facebook|tiktok|pinterest/i.test(String(x.source || "") + " " + String(x.link || ""))) || items[0];
        if (clean?.original) {
          res.setHeader("Cache-Control", "s-maxage=86400, stale-while-revalidate=604800");
          return res.status(200).json({ image: clean.original, url: clean.link || null, source: clean.source || "Google Images", title: clean.title || name });
        }
      }
    }

    return res.status(404).json({ error: "No hay proveedor de Google Images configurado", configure: ["SERPER_API_KEY", "SERPAPI_KEY"] });
  } catch (e) {
    return res.status(500).json({ error: "Error consultando imágenes" });
  }
}