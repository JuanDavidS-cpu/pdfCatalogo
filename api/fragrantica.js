export default async function handler(req, res) {
  const name = String(req.query?.name || "").trim();
  if (!name) return res.status(400).json({ error: "Falta el nombre" });

  try {
    const url = "https://www.fragrantica.com/search/?query=" + encodeURIComponent(name);
    const response = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; ZUASH-Catalog/1.0)",
        "Accept-Language": "en-US,en;q=0.9"
      }
    });

    if (!response.ok) return res.status(502).json({ error: "No se pudo consultar Fragrantica" });
    const html = await response.text();

    const links = [...html.matchAll(/href=["'](\/perfume\/[^"'#?]+\.html)["']/gi)]
      .map(m => m[1])
      .filter((v, i, a) => a.indexOf(v) === i);

    const normalized = name.toLowerCase().replace(/[^a-z0-9áéíóúüñ]+/gi, " ").trim();
    const score = href => {
      const slug = decodeURIComponent(href).toLowerCase().replace(/[-_]+/g, " ");
      const words = normalized.split(/\s+/).filter(Boolean);
      return words.reduce((n, w) => n + (slug.includes(w) ? 1 : 0), 0);
    };

    links.sort((a, b) => score(b) - score(a));
    const href = links[0];
    if (!href) return res.status(404).json({ error: "No se encontró una coincidencia" });

    const parts = href.split("/").filter(Boolean);
    const rawSlug = parts[parts.length - 1].replace(/\.html$/i, "");
    const id = rawSlug.match(/-(\d+)$/)?.[1] || "";
    const titleSlug = rawSlug.replace(/-\d+$/, "").replace(/-/g, " ").trim();
    const title = titleSlug.replace(/\b\w/g, c => c.toUpperCase());
    const fullUrl = "https://www.fragrantica.com" + href;

    res.setHeader("Cache-Control", "s-maxage=86400, stale-while-revalidate=604800");
    return res.status(200).json({ name: title, url: fullUrl, id });
  } catch (e) {
    return res.status(500).json({ error: "Error consultando Fragrantica" });
  }
}
