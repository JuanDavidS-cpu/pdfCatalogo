import os,re,json,time,uuid,threading
import fitz,requests,ollama
from bs4 import BeautifulSoup
from fastapi import FastAPI,File,UploadFile,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
try: from ddgs import DDGS
except Exception: DDGS=None
MODEL=os.getenv("QWEN_MODEL","qwen3:8b"); HOST=os.getenv("OLLAMA_HOST","http://127.0.0.1:11434")
app=FastAPI(title="ZUASH Text AI Engine",version="3.0.0"); app.mount("/web",StaticFiles(directory="web"),name="web")
J={}; L=threading.Lock()
PROMPT="""Analiza SOLO el texto de un catalogo de perfumes. Identifica unicamente perfumes/fragrancias vendibles. Ignora precios, SKU, telefonos, Instagram, WhatsApp, direcciones, proveedores, descuentos, tamanos como 100 ML, categorias y publicidad. Conserva numeros legitimos (212, 1 Million, 9PM) y variantes EDT, EDP, Elixir, Parfum. Corrige errores evidentes de OCR. No inventes. Devuelve SOLO JSON: {"perfumes":[{"name":"","brand":"","variant":"","confidence":0}]}"""
def upd(j,p,s,d="",**x):
 with L:
  if j in J:J[j].update(percent=int(p),stage=s,detail=d,**x)
def extract(data,j):
 d=fitz.open(stream=data,filetype="pdf"); out=[]
 for i,page in enumerate(d,1):
  blocks=page.get_text("blocks",sort=True); t="\n".join(b[4].strip() for b in blocks if len(b)>4 and b[4].strip())
  out.append({"page":i,"text":t}); upd(j,8+int(i/max(len(d),1)*27),f"Texto · pagina {i}/{len(d)}",f"{len(t)} caracteres")
 d.close(); return out
def clean(s):
 s=re.sub(r"https?://\S+|www\.\S+|@\w+"," ",str(s),flags=re.I)
 s=re.sub(r"(instagram|whatsapp|phone|telefono|tel)\s*[:#-]?\s*\S+"," ",s,flags=re.I)
 s=re.sub(r"^\s*\d{1,4}[\s.)_-]+","",s)
 return re.sub(r"\s+"," ",s).strip(" -:;,.|")
def identify(t):
 r=ollama.Client(host=HOST).chat(model=MODEL,messages=[{"role":"user","content":PROMPT+"\n\n"+t[:30000]}],options={"temperature":0})
 raw=r["message"]["content"].replace(chr(96),"")
 m=re.search(r'\{\s*"perfumes"\s*:\s*\[.*\]\s*\}',raw,re.S)
 if not m: raise ValueError("Qwen no devolvio JSON")
 out=[]; seen=set()
 for x in json.loads(m.group())["perfumes"]:
  n,b,v=clean(x.get("name","")),clean(x.get("brand","")),clean(x.get("variant",""))
  if not n or len(n)>120 or any(w in n.lower() for w in ["instagram","whatsapp","proveedor","precio","catalogo","catalogo"]): continue
  k=(n+" "+v).lower()
  if k in seen: continue
  seen.add(k); out.append({"name":n,"brand":b,"variant":v,"confidence":float(x.get("confidence",0) or 0)})
 return out
def fragrantica(q):
 urls=[]; h={"User-Agent":"Mozilla/5.0 Chrome/154 Safari/537.36"}
 if DDGS:
  try:
   with DDGS() as d:
    for r in d.text(f'site:fragrantica.com/perfume/ "{q}"',max_results=5):
     u=r.get("href") or r.get("url","")
     if "fragrantica.com/perfume/" in u: urls.append(u.split("?")[0])
  except Exception: pass
 try:
  s=BeautifulSoup(requests.get("https://www.fragrantica.com/search/?query="+requests.utils.quote(q),headers=h,timeout=15).text,"html.parser")
  for a in s.select('a[href*="/perfume/"]'):
   u=a["href"]; urls.append(("https://www.fragrantica.com"+u if u.startswith("/") else u).split("?")[0])
 except Exception: pass
 for u in dict.fromkeys(urls):
  try:
   s=BeautifulSoup(requests.get(u,headers=h,timeout=15).text,"html.parser"); im=s.find("meta",{"property":"og:image"}); tt=s.find("meta",{"property":"og:title"})
   return {"fragrantica_url":u,"image_url":im.get("content","") if im else "","matched_title":tt.get("content","") if tt else "","found":True}
  except Exception: pass
 return {"fragrantica_url":"","image_url":"","matched_title":"","found":False}
def run(j,data):
 try:
  upd(j,2,"Recibiendo PDF","Archivo recibido",status="running"); pages=extract(data,j); allp=[]
  for i,p in enumerate(pages,1):
   if not p["text"]: continue
   upd(j,38+int((i-1)/max(len(pages),1)*27),f"IA · pagina {i}/{len(pages)}","Qwen analiza texto")
   try: ps=identify(p["text"])
   except Exception as e: ps=[]; upd(j,40,f"IA · pagina {i}",str(e))
   for x in ps: x["page"]=i; allp.append(x)
   upd(j,min(65,40+int(i/max(len(pages),1)*25)),f"Pagina {i}/{len(pages)} procesada",f"{len(ps)} perfumes identificados")
  m={}
  for p in allp:
   k=(p["name"]+" "+p["variant"]).lower()
   if k not in m: m[k]=p.copy(); m[k]["pages"]=[p["page"]]
   elif p["page"] not in m[k]["pages"]: m[k]["pages"].append(p["page"])
  items=list(m.values()); res=[]
  for i,p in enumerate(items,1):
   upd(j,67+int((i-1)/max(len(items),1)*27),f"Buscando {i}/{len(items)}",p["name"])
   p.update(fragrantica(" ".join(x for x in [p["name"],p["variant"],p["brand"]] if x))); res.append(p)
  result={"products":res,"stats":{"pages":len(pages),"detected":len(allp),"unique":len(res),"found":sum(x["found"] for x in res)}}
  with L:J[j].update(status="done",percent=100,stage="Completado",detail="Analisis terminado",result=result)
 except Exception as e:
  with L:J[j].update(status="error",percent=100,stage="Error",detail=str(e))
@app.get("/")
def root(): return FileResponse("web/index.html")
@app.get("/api/health")
def health():
 try: ms=[x.get("name") for x in ollama.Client(host=HOST).list().get("models",[])]; ok=True
 except Exception: ms=[]; ok=False
 return {"ok":True,"ollama":ok,"qwen_model":MODEL,"models":ms}
@app.post("/api/analyze-pdf")
async def analyze(file:UploadFile=File(...)):
 if not file.filename.lower().endswith(".pdf"): raise HTTPException(400,"Solo PDF")
 data=await file.read(); j=uuid.uuid4().hex
 with L: J[j]={"status":"queued","percent":0,"stage":"Preparando","detail":"","started_at":time.time()}
 threading.Thread(target=run,args=(j,data),daemon=True).start(); return {"job_id":j}
@app.get("/api/analyze-pdf/{j}")
def status(j:str):
 with L: x=dict(J.get(j,{}))
 if not x: raise HTTPException(404,"Trabajo no encontrado")
 x["elapsed_seconds"]=round(time.time()-x["started_at"],1); return x
