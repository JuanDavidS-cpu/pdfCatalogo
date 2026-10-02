import os,re,json,time,uuid,threading,base64,io,shutil
import fitz,requests,ollama
from bs4 import BeautifulSoup
from fastapi import FastAPI,File,UploadFile,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image
try: from ddgs import DDGS
except Exception: DDGS=None

TEXT_MODEL=os.getenv("QWEN_MODEL","qwen3:8b")
HOST=os.getenv("OLLAMA_HOST","http://127.0.0.1:11434")
app=FastAPI(title="ZUASH PDF Text AI Engine",version="5.0.0")
app.mount("/web",StaticFiles(directory="web"),name="web")
J={}; L=threading.Lock(); OUT=os.path.join(os.path.dirname(__file__),"generated"); os.makedirs(OUT,exist_ok=True)

TEXT_PROMPT="""Analiza SOLO texto de catalogo de perfumes. Identifica unicamente perfumes/fragrancias vendibles. Ignora precios, SKU, telefonos, Instagram, WhatsApp, direcciones, proveedores, descuentos, tamanos y publicidad. Conserva numeros legitimos (212, 1 Million, 9PM) y variantes EDT, EDP, Elixir, Parfum. Corrige errores evidentes. No inventes. Devuelve SOLO JSON: {"perfumes":[{"name":"","brand":"","variant":"","confidence":0}]}"""

def upd(j,p,s,d="",**x):
    with L:
        if j in J: J[j].update(percent=int(max(0,min(100,p))),stage=s,detail=d,**x)

OCR_LANG=os.getenv("OCR_LANG","eng")
OCR_DPI=int(os.getenv("OCR_DPI","200"))
TESSERACT_CMD=os.getenv("TESSERACT_CMD","").strip()

def setup_tesseract():
    cmd=TESSERACT_CMD or shutil.which("tesseract")
    if not cmd:
        for p in [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]:
            if os.path.isfile(p):
                cmd=p; break
    if cmd:
        os.environ["TESSERACT_CMD"]=cmd
    return cmd

def extract_text(page):
    # Primero usa la capa de texto real. OCR solo es fallback para paginas
    # escaneadas o con una capa practicamente vacia. Nunca se usa vision.
    text=page.get_text("text",sort=True).strip()
    if text:
        return text,False
    blocks=page.get_text("blocks",sort=True)
    text="\n".join(b[4].strip() for b in blocks if len(b)>6 and b[6]==0 and b[4].strip())
    if text.strip():
        return text.strip(),False
    words=page.get_text("words",sort=True)
    return " ".join(w[4] for w in words if w[4].strip()).strip(),False

def extract_document(doc,j):
    pages=[]; total=len(doc); total_chars=0; empty_pages=[]; ocr_pages=[]
    tess=setup_tesseract()
    for i,page in enumerate(doc,1):
        text,_=extract_text(page)
        used_ocr=False
        if len(text.strip()) < 30 and tess:
            try:
                upd(j,5+int((i-1)/max(total,1)*25),f"OCR · pagina {i}/{total}",
                    f"Pagina con {len(text)} caracteres; intentando OCR")
                tp=page.get_textpage_ocr(language=OCR_LANG,dpi=OCR_DPI,full=True)
                ocr_text=page.get_text("text",textpage=tp,sort=True).strip()
                if len(ocr_text)>len(text):
                    text=ocr_text
                    used_ocr=True
                    ocr_pages.append(i)
            except Exception as e:
                print(f"[OCR] pagina {i}/{total}: {e}",flush=True)
        total_chars+=len(text)
        if not text: empty_pages.append(i)
        pages.append({"page":i,"text":text,"ocr":used_ocr})
        pct=5+int(i/max(total,1)*30)
        upd(j,pct,f"Extrayendo texto · pagina {i}/{total}",
            f"{len(text)} caracteres" + (" · OCR" if used_ocr else ""))
        print(f"[{pct:3d}%] Extrayendo pagina {i}/{total} · {len(text)} caracteres"
              + (" · OCR" if used_ocr else ""),flush=True)
    return pages,total_chars,empty_pages,ocr_pages,tess

def clean(s):
    s=re.sub(r"https?://\S+|www\.\S+|@\w+"," ",str(s),flags=re.I)
    s=re.sub(r"(instagram|whatsapp|phone|telefono|tel)\s*[:#-]?\s*\S+"," ",s,flags=re.I)
    return re.sub(r"\s+"," ",s).strip(" -:;,.|")

def parse_json(raw):
    raw=raw.replace(chr(96),"")
    m=re.search(r'\{\s*"perfumes"\s*:\s*\[.*?\]\s*\}',raw,re.S)
    if not m: raise ValueError("Qwen no devolvio JSON")
    data=json.loads(m.group())
    out=[]; seen=set()
    for x in data.get("perfumes",[]):
        n,b,v=clean(x.get("name","")),clean(x.get("brand","")),clean(x.get("variant",""))
        if not n or len(n)>120: continue
        if any(w in n.lower() for w in ["instagram","whatsapp","proveedor","precio","catalogo"]): continue
        k=(n+" "+b+" "+v).lower()
        if k in seen: continue
        seen.add(k); out.append({"name":n,"brand":b,"variant":v,"confidence":float(x.get("confidence",0) or 0)})
    return out

def text_identify(text):
    r=ollama.Client(host=HOST).chat(model=TEXT_MODEL,messages=[{"role":"user","content":TEXT_PROMPT+"\n\n"+text[:30000]}],options={"temperature":0})
    return parse_json(r["message"]["content"])

def page_png(page):
    pix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False)
    return pix.tobytes("png")

def vision_identify_removed(png):
    img=base64.b64encode(png).decode("ascii")
    r=ollama.Client(host=HOST).chat(model=VISION_MODEL,messages=[{"role":"user","content":VISION_PROMPT,"images":[img]}],options={"temperature":0})
    return parse_json(r["message"]["content"])

def fragrantica(q):
    urls=[]; h={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36"}
    if DDGS:
        try:
            with DDGS() as d:
                for r in d.text(f'site:fragrantica.com/perfume/ "{q}"',max_results=8):
                    u=r.get("href") or r.get("url","")
                    if "/perfume/" in u: urls.append(u.split("?")[0])
        except Exception: pass
    try:
        s=BeautifulSoup(requests.get("https://www.fragrantica.com/search/?query="+requests.utils.quote(q),headers=h,timeout=15).text,"html.parser")
        for a in s.select('a[href*="/perfume/"]'):
            u=a.get("href",""); urls.append(("https://www.fragrantica.com"+u if u.startswith("/") else u).split("?")[0])
    except Exception: pass
    for u in dict.fromkeys(urls):
        try:
            s=BeautifulSoup(requests.get(u,headers=h,timeout=15).text,"html.parser")
            im=s.find("meta",{"property":"og:image"}); tt=s.find("meta",{"property":"og:title"})
            return {"fragrantica_url":u,"fragrantica_image_url":im.get("content","") if im else "","matched_title":tt.get("content","") if tt else "","found":True}
        except Exception: pass
    return {"fragrantica_url":"","fragrantica_image_url":"","matched_title":"","found":False}

def google_image(q):
    h={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36"}
    try:
        u="https://www.google.com/search?tbm=isch&q="+requests.utils.quote(q+" perfume bottle")
        html=requests.get(u,headers=h,timeout=15).text
        m=re.search(r'https://encrypted-tbn0\.gstatic\.com/images\?[^"\\]+',html)
        if m: return m.group(0).replace("\\u003d","=")
    except Exception: pass
    return ""
def enrich(p):
    q=" ".join(x for x in [p["name"],p.get("variant",""),p.get("brand","")] if x)
    fr=fragrantica(q); p.update(fr)
    p["image_url"]=google_image(p.get("matched_title") or q) or p.get("fragrantica_image_url","")
    return p

def run(j,data):
    try:
        upd(j,2,"Recibiendo PDF","Archivo recibido",status="running")
        doc=fitz.open(stream=data,filetype="pdf")
        pages,total_chars,empty_pages,ocr_pages,tess=extract_document(doc,j); doc.close()
        if total_chars==0 and not tess:
            raise RuntimeError("El PDF no tiene capa de texto y no se encontro Tesseract para activar OCR. Instala Tesseract OCR o configura TESSERACT_CMD.")
        if total_chars==0:
            raise RuntimeError("OCR no pudo extraer texto de ninguna pagina. Revisa que Tesseract OCR este instalado y que OCR_LANG coincida con los idiomas disponibles.")
        upd(j,35,"Texto extraido",f"{total_chars:,} caracteres · {len(ocr_pages)} paginas con OCR · {len(empty_pages)} paginas sin texto")
        print(f"[ 35%] Texto listo · {total_chars:,} caracteres · OCR {len(ocr_pages)}/{len(pages)} paginas",flush=True)

        # Todo el PDF se analiza como texto. Se usan bloques de texto
        # para conservar el contexto de paginas sin analizar imagenes.
        chunks=[]; current=[]; chars=0; LIMIT=18000
        for p in pages:
            piece=f"\n[PAGINA {p['page']}]\n{p['text']}\n"
            if current and chars+len(piece)>LIMIT:
                chunks.append(current); current=[]; chars=0
            current.append(piece); chars+=len(piece)
        if current: chunks.append(current)

        allp=[]
        for ci,chunk in enumerate(chunks,1):
            pct=38+int((ci-1)/max(len(chunks),1)*24)
            upd(j,pct,f"Qwen3 · bloque {ci}/{len(chunks)}","Analizando texto extraido del PDF")
            print(f"[{pct:3d}%] Qwen3 · bloque {ci}/{len(chunks)}",flush=True)
            try: found=text_identify("".join(chunk))
            except Exception as e:
                found=[]; upd(j,40,f"Qwen3 · bloque {ci}",str(e))
            for x in found:
                page_nums=[]
                for p in pages:
                    terms=[x["name"],x.get("variant",""),x.get("brand","")]
                    if any(tok and len(tok)>2 and tok.lower() in p["text"].lower() for tok in terms):
                        page_nums.append(p["page"])
                x["pages"]=page_nums or [1]; x["page"]=x["pages"][0]; allp.append(x)

        # Dedupe global del documento.
        m={}
        for p in allp:
            k=re.sub(r"\s+"," ",(p["name"]+" "+p.get("brand","")+" "+p.get("variant","")).lower()).strip()
            if k not in m: m[k]=p.copy()
            else: m[k]["pages"]=sorted(set(m[k].get("pages",[])+p.get("pages",[])))

        items=list(m.values()); res=[]
        for i,p in enumerate(items,1):
            pct=62+int((i-1)/max(len(items),1)*36)
            upd(j,pct,f"Buscando {i}/{len(items)}","Fragrantica + imagen Google · "+p["name"])
            print(f"[{pct:3d}%] Buscando {i}/{len(items)} · {p['name']}",flush=True)
            try: res.append(enrich(p))
            except Exception:
                p.update({"found":False,"fragrantica_url":"","fragrantica_image_url":"","matched_title":"","image_url":""}); res.append(p)

        result={"products":res,"stats":{"pages":len(pages),"characters":total_chars,"ocr_pages":ocr_pages,"ocr_available":bool(tess),"empty_text_pages":empty_pages,"detected":len(allp),"unique":len(res),"found":sum(x.get("found",False) for x in res)}}
        print("[100%] Completado · analisis de texto terminado",flush=True)
        with L: J[j].update(status="done",percent=100,stage="Completado",detail="Analisis de texto + OCR terminado",result=result)
    except Exception as e:
        print(f"[ERROR] {e}",flush=True)
        with L: J[j].update(status="error",percent=100,stage="Error",detail=str(e))

def download_image(url):
    if not url: return None
    try:
        r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=15); r.raise_for_status()
        im=Image.open(io.BytesIO(r.content)).convert("RGB")
        return im
    except Exception: return None

def make_pdf(result,path):
    c=canvas.Canvas(path,pagesize=A4); W,H=A4
    products=result.get("products",[])
    margin=28; gap=12; cols=2; rows=4
    cw=(W-2*margin-gap)/cols; ch=(H-2*margin-70-(rows-1)*gap)/rows
    for idx,p in enumerate(products):
        slot=idx%8
        if slot==0:
            c.setFont("Helvetica-Bold",16); c.drawString(margin,H-30,"ZUASH · CATÁLOGO DE PERFUMES")
            c.setFont("Helvetica",8); c.drawRightString(W-margin,H-30,"8 por hoja")
        col=slot%2; row=slot//2; x=margin+col*(cw+gap); y=H-58-(row+1)*ch-row*gap
        c.roundRect(x,y,cw,ch,8,stroke=1,fill=0)
        im=download_image(p.get("image_url") or p.get("fragrantica_image_url",""))
        if im:
            iw,ih=im.size; scale=min((cw-18)/iw,(ch-55)/ih,1.0); dw,dh=iw*scale,ih*scale
            bio=io.BytesIO(); im.save(bio,format="JPEG",quality=88); bio.seek(0)
            c.drawImage(bio,x+(cw-dw)/2,y+30+(ch-55-dh)/2,width=dw,height=dh,preserveAspectRatio=True,mask="auto")
        c.setFont("Helvetica-Bold",9); c.drawCentredString(x+cw/2,y+17,p["name"][:52])
        if p.get("brand") or p.get("variant"):
            c.setFont("Helvetica",7); c.drawCentredString(x+cw/2,y+7," · ".join(v for v in [p.get("brand",""),p.get("variant","")] if v)[:68])
        if slot==7 or idx==len(products)-1: c.showPage()
    c.save()

@app.get("/")
def root(): return FileResponse("web/index.html")

@app.get("/api/health")
def health():
    try: models=[x.get("name") for x in ollama.Client(host=HOST).list().get("models",[])]; ok=True
    except Exception: models=[]; ok=False
    return {"ok":True,"ollama":ok,"text_model":TEXT_MODEL,"text_ready":TEXT_MODEL in models,
            "ocr_available":bool(setup_tesseract()),"ocr_lang":OCR_LANG,"models":models}

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

@app.post("/api/generate-pdf")
async def generate_pdf(payload:dict):
    result=payload.get("result")
    if not result or not result.get("products"): raise HTTPException(400,"No hay perfumes para generar")
    name="ZUASH_catalogo_"+uuid.uuid4().hex[:8]+".pdf"; path=os.path.join(OUT,name)
    make_pdf(result,path); return {"filename":name,"url":"/api/generated/"+name}

@app.get("/api/generated/{name}")
def generated(name:str):
    safe=os.path.basename(name); path=os.path.join(OUT,safe)
    if not os.path.isfile(path): raise HTTPException(404,"PDF no encontrado")
    return FileResponse(path,media_type="application/pdf",filename=safe)
