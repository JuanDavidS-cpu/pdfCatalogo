function cleanName(value) {
  let s = String(value || "").replace(/\s+/g, " ").trim();
  s = s.replace(/^\s*[#№]?\s*\d{1,4}[\s.):-]+/,"");
  s = s.replace(/\s+(?:ig|instagram|whatsapp|wa|tel(?:éfono)?|cel(?:ular)?)[\s:.-]*\S.*$/i,"");
  s = s.replace(/\s+@\w+.*$/,"");
  s = s.replace(/\s+(?:https?:\/\/|www\.)\S+$/i,"");
  return s.trim();
}

function boxFromGemini(raw, width, height) {
  if (!Array.isArray(raw) || raw.length !== 4) return null;
  const [y1, x1, y2, x2] = raw.map(Number);
  if (![y1, x1, y2, x2].every(Number.isFinite)) return null;
  const x = Math.max(0, Math.min(width, x1 / 1000 * width));
  const y = Math.max(0, Math.min(height, y1 / 1000 * height));
  const r = Math.max(0, Math.min(width, x2 / 1000 * width));
  const b = Math.max(0, Math.min(height, y2 / 1000 * height));
  if (r - x < width * 0.03 || b - y < height * 0.03) return null;
  return { x, y, w: r - x, h: b - y };
}

function boxFromPoly(poly, width, height) {
  const vertices = poly?.normalizedVertices || poly?.vertices;
  if (!Array.isArray(vertices) || vertices.length < 4) return null;
  const xs = vertices.map(v => v.x == null ? 0 : v.x <= 1 ? v.x * width : v.x);
  const ys = vertices.map(v => v.y == null ? 0 : v.y <= 1 ? v.y * height : v.y);
  const x = Math.max(0, Math.min(...xs));
  const y = Math.max(0, Math.min(...ys));
  const r = Math.min(width, Math.max(...xs));
  const b = Math.min(height, Math.max(...ys));
  if (r - x < width * 0.03 || b - y < height * 0.03) return null;
  return { x, y, w: r - x, h: b - y };
}

function iou(a, b) {
  const x = Math.max(a.x, b.x), y = Math.max(a.y, b.y);
  const r = Math.min(a.x + a.w, b.x + b.w), bot = Math.min(a.y + a.h, b.y + b.h);
  const inter = Math.max(0, r - x) * Math.max(0, bot - y);
  const union = a.w * a.h + b.w * b.h - inter;
  return union ? inter / union : 0;
}

function uniqueProducts(items) {
  const out = [];
  for (const item of items) {
    if (!item?.box) continue;
    const dup = out.find(x => iou(x.box, item.box) >= 0.55);
    if (!dup) out.push(item);
    else {
      if ((item.confidence || 0) > (dup.confidence || 0)) Object.assign(dup, item);
      dup.box = { x: Math.min(dup.box.x, item.box.x), y: Math.min(dup.box.y, item.box.y),
        w: Math.max(dup.box.x + dup.box.w, item.box.x + item.box.w) - Math.min(dup.box.x, item.box.x),
        h: Math.max(dup.box.y + dup.box.h, item.box.y + item.box.h) - Math.min(dup.box.y, item.box.y) };
    }
  }
  return out;
}

async function geminiDetect({ image, width, height, textHints }) {
  const key = process.env.GEMINI_API_KEY;
  if (!key) return [];
  const model = process.env.GEMINI_MODEL || "gemini-2.5-flash";
  const schema = {
    type: "object",
    properties: {
      products: {
        type: "array",
        items: {
          type: "object",
          properties: {
            name: { type: "string", description: "Nombre exacto o más probable del perfume. No incluyas número de catálogo, Instagram, teléfono, precio, ml u otros datos del proveedor." },
            box_2d: { type: "array", items: { type: "integer" }, description: "[ymin,xmin,ymax,xmax] en escala 0-1000." },
            confidence: { type: "number", description: "Confianza de que la caja corresponde a un perfume individual, de 0 a 1." },
            evidence: { type: "string", description: "Breve evidencia: nombre encima, etiqueta visible, botella/caja, etc." }
          },
          required: ["name", "box_2d", "confidence", "evidence"]
        }
      }
    },
    required: ["products"]
  };

  const prompt = [
    "Analiza esta página de un catálogo/proveedor de perfumes.",
    "Tu tarea es detectar TODOS los perfumes individuales que aparezcan, incluso si hay varios en una misma página.",
    "Cada producto debe tener una caja que encierre solamente su botella o caja/packaging del perfume, NO toda la página y NO el texto de contacto del proveedor.",
    "El texto que está directamente encima de cada imagen/botella suele ser el nombre del perfume. Asocia cada nombre con el producto que está justo debajo o más próximo verticalmente; si hay varios perfumes en la misma página, devuelve una entrada separada para cada uno.",
"Prioriza el nombre visible encima del perfume sobre números o códigos del proveedor. Un nombre puede contener números legítimos (por ejemplo 212 o 1 Million), así que no elimines números internos del nombre.",
"Si el texto está acompañado por un número de referencia, @usuario de Instagram, teléfono, WhatsApp, precio, código, SKU o nombre del proveedor, excluye esos datos del campo name."
    "No cuentes logos, Instagram, WhatsApp, teléfonos, precios, números de referencia ni adornos como productos.",
    "No inventes productos. Si una región no contiene un perfume individual, no la devuelvas.",
    "Puedes identificar el perfume por el texto visible o por la apariencia de la botella/caja.",
    "Devuelve una entrada separada para cada perfume. Las coordenadas box_2d son [ymin,xmin,ymax,xmax] sobre una escala 0-1000.",
    textHints ? ("Texto extraído del PDF para validar nombres: " + JSON.stringify(textHints.slice(0,80))) : ""
  ].join("\n");

  const response = await fetch(
    "https://generativelanguage.googleapis.com/v1beta/models/" + encodeURIComponent(model) + ":generateContent?key=" + encodeURIComponent(key),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{
          parts: [
            { text: prompt },
            { inline_data: { mime_type: "image/jpeg", data: image } }
          ]
        }],
        generationConfig: {
          temperature: 0.05,
          responseMimeType: "application/json",
          responseSchema: schema
        }
      })
    }
  );
  if (!response.ok) throw new Error("Gemini " + response.status + ": " + (await response.text()).slice(0,500));
  const data = await response.json();
  const raw = data?.candidates?.[0]?.content?.parts?.map(p => p.text || "").join("") || "{}";
  let parsed;
  try { parsed = JSON.parse(raw); } catch (_) { return []; }
  return (parsed.products || []).map(p => ({
    box: boxFromGemini(p.box_2d, width, height),
    name: cleanName(p.name),
    confidence: Math.max(0, Math.min(1, Number(p.confidence) || 0)),
    evidence: p.evidence || "",
    method: "Gemini Vision"
  })).filter(p => p.box);
}

async function googleAccessToken() {
  if (process.env.GOOGLE_ACCESS_TOKEN) return process.env.GOOGLE_ACCESS_TOKEN;
  const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!raw) return null;
  const { client_email, private_key } = JSON.parse(raw);
  const crypto = await import("node:crypto");
  const now = Math.floor(Date.now() / 1000);
  const header = Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT" })).toString("base64url");
  const claim = Buffer.from(JSON.stringify({
    iss: client_email,
    scope: "https://www.googleapis.com/auth/cloud-platform",
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600
  })).toString("base64url");
  const unsigned = header + "." + claim;
  const sign = crypto.createSign("RSA-SHA256");
  sign.update(unsigned);
  const signature = sign.sign(private_key, "base64url");
  const jwt = unsigned + "." + signature;
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion: jwt })
  });
  if (!r.ok) return null;
  const data = await r.json();
  return data.access_token || null;
}

async function productSearch({ image, width, height }) {
  const productSet = process.env.GOOGLE_PRODUCT_SET;
  if (!productSet) return [];
  const token = await googleAccessToken();
  if (!token) return [];

  const r = await fetch("https://vision.googleapis.com/v1/images:annotate", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: JSON.stringify({
      requests: [{
        image: { content: image },
        features: [{ type: "PRODUCT_SEARCH", maxResults: 20 }],
        imageContext: {
          productSearchParams: {
            productSet,
            productCategories: ["general-v1"]
          }
        }
      }]
    })
  });
  if (!r.ok) throw new Error("Product Search " + r.status + ": " + (await r.text()).slice(0,500));
  const data = await r.json();
  const groups = data?.responses?.[0]?.productSearchResults?.productGroupedResults || [];
  const results = [];
  for (const group of groups) {
    const box = boxFromPoly(group.boundingPoly, width, height);
    if (!box) continue;
    const best = (group.results || [])
      .filter(x => x.product)
      .sort((a,b) => Number(b.score || 0) - Number(a.score || 0))[0];
    if (!best) continue;
    results.push({
      box,
      name: cleanName(best.product.displayName || ""),
      confidence: Number(best.score || 0),
      method: "Google Product Search"
    });
  }
  return uniqueProducts(results);
}

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Usa POST." });
  try {
    const body = req.body || {};
    const image = String(body.image || "");
    const width = Number(body.width || 0), height = Number(body.height || 0);
    const textHints = Array.isArray(body.textHints) ? body.textHints : [];
    if (!image || !width || !height) return res.status(400).json({ error: "Faltan image, width y height." });

    const [vision, products] = await Promise.allSettled([
      geminiDetect({ image, width, height, textHints }),
      productSearch({ image, width, height })
    ]);

    const visionItems = vision.status === "fulfilled" ? vision.value : [];
    const productItems = products.status === "fulfilled" ? products.value : [];
    let merged = [...visionItems];

    for (const item of productItems) {
      const match = merged.find(x => iou(x.box, item.box) >= 0.20);
      if (match) {
        if (item.confidence >= match.confidence) {
          match.name = item.name || match.name;
          match.identity = item.name || match.identity;
          match.confidence = Math.max(match.confidence, item.confidence);
          match.method = "Gemini + Product Search";
        }
      } else {
        merged.push({ ...item, identity: item.name || null });
      }
    }

    merged = uniqueProducts(merged).sort((a,b) => a.box.y - b.box.y || a.box.x - b.box.x);
    res.setHeader("Cache-Control", "no-store");
    return res.status(200).json({
      products: merged,
      providers: {
        gemini: Boolean(process.env.GEMINI_API_KEY),
        productSearch: Boolean(process.env.GOOGLE_PRODUCT_SET && (process.env.GOOGLE_ACCESS_TOKEN || process.env.GOOGLE_SERVICE_ACCOUNT_JSON))
      }
    });
  } catch (e) {
    console.error(e);
    return res.status(500).json({ error: e.message || "Error analizando página." });
  }
}