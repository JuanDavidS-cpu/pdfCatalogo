export default async function handler(req, res) {
  const name = String(req.query?.name || "").trim();
  if (!name) return res.status(400).json({ error: "Falta el nombre" });

  try {
    const searchUrl = "https://www.fragrantica.com/search/?query=" + encodeURIComponent(name);
    const response = await fetch(searchUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; ZUASH-Catalog/1.1)",
        "Accept-Language": "en-US,en;q=0.9"
      }
    });
    if (!response.ok) return res.status(502).json({ error: "No se pudo consultar Fragrantica" });
    const html = await response.text();

    const links = [...html.matchAll(/href=["'](\/perfume\/[^"'#?]+\.html)["']/gi)]
      .map(m => m[1]).filter((v,i,a)=>a.indexOf(v)===i);

    const normalized = name.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g," ").trim();
    const words = normalized.split(/\s+/).filter(w=>w.length>1);
    const score = href => {
      const slug = decodeURIComponent(href).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[-_]+/g," ");
      return words.reduce((n,w)=>n+(slug.includes(w)?1:0),0);
    };
    links.sort((a,b)=>score(b)-score(a));
    const href=links[0];
    if(!href)return res.status(404).json({error:"No se encontró una coincidencia"});

    const fullUrl="https://www.fragrantica.com"+href;
    let detail="";
    try{
      const detailResponse=await fetch(fullUrl,{headers:{"User-Agent":"Mozilla/5.0 (compatible; ZUASH-Catalog/1.1)","Accept-Language":"en-US,en;q=0.9"}});
      if(detailResponse.ok)detail=await detailResponse.text();
    }catch(_){}

    const og=(prop)=>{const re=new RegExp('<meta[^>]+(?:property|name)=["\\\']'+prop+'["\\\'][^>]+content=["\\\']([^"\\\']+)["\\\']','i');const m=detail.match(re);return m?m[1]:null};
    const ogImage=og("og:image");
    const ogTitle=og("og:title");
    const parts=href.split("/").filter(Boolean),rawSlug=parts[parts.length-1].replace(/\.html$/i,"");
    const id=rawSlug.match(/-(\d+)$/)?.[1]||"";
    const title=ogTitle?ogTitle.replace(/\s*[-|].*$/,"").trim():rawSlug.replace(/-\d+$/,"").replace(/-/g," ").replace(/\b\w/g,c=>c.toUpperCase());

    res.setHeader("Cache-Control","s-maxage=86400, stale-while-revalidate=604800");
    return res.status(200).json({name:title,url:fullUrl,id,image:ogImage||null,confidence:"texto"});
  }catch(e){
    return res.status(500).json({error:"Error consultando Fragrantica"});
  }
}