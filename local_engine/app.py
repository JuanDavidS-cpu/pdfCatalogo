import os,re,json,time,uuid,threading,base64,io,shutil
from dotenv import load_dotenv
load_dotenv()
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

TEXT_MODEL=os.getenv("QWEN_MODEL","qwen3-vl:8b").strip()
HOST=os.getenv("OLLAMA_BASE_URL",os.getenv("OLLAMA_HOST","http://127.0.0.1:11434")).strip().rstrip("/")
app=FastAPI(title="ZUASH PDF Text AI Engine",version="5.0.0")
app.mount("/web",StaticFiles(directory="web"),name="web")
J={}; L=threading.Lock(); OUT=os.path.join(os.path.dirname(__file__),"generated"); os.makedirs(OUT,exist_ok=True)

TEXT_PROMPT="""Analiza SOLO el texto extraido de un catalogo de perfumes. Cada bloque [PAGINA N] puede contener UNO O VARIOS perfumes. Identifica todos los nombres de perfumes/fragrancias vendibles, incluso si el texto viene de OCR y contiene errores menores. El nombre suele aparecer cerca del producto y puede estar en una linea separada. Ignora precios, SKU, telefonos, Instagram, WhatsApp, direcciones, proveedores, descuentos, tamanos y publicidad. Conserva numeros legitimos del nombre (212, 1 Million, 9PM) y variantes EDT, EDP, Elixir, Parfum. Corrige solo errores evidentes de OCR; no inventes. Si no puedes determinar la marca, deja brand vacio pero conserva el nombre. Devuelve TODOS los candidatos razonables y SOLO JSON: {"perfumes":[{"name":"","brand":"","variant":"","confidence":0,"pages":[1]}]}"""

def upd(j,p,s,d="",**x):
    with L:
        if j in J: J[j].update(percent=int(max(0,min(100,p))),stage=s,detail=d,**x)

OCR_LANG=os.getenv("OCR_LANG","eng+spa")
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
        folder=os.path.dirname(cmd)
        if folder and folder not in os.environ.get("PATH","").split(os.pathsep):
            os.environ["PATH"]=folder+os.pathsep+os.environ.get("PATH","")
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
    # HIBRIDO: conserva la capa de texto del PDF y ADEMAS ejecuta OCR sobre
    # la pagina completa. Esto cubre catalogos donde el nombre del perfume
    # esta dibujado dentro de una imagen aunque exista texto basura oculto.
    pages=[]; total=len(doc); total_chars=0; empty_pages=[]; ocr_pages=[]
    tess=setup_tesseract()
    for i,page in enumerate(doc,1):
        native,_=extract_text(page)
        text=native.strip()
        used_ocr=False
        ocr_text=""
        if tess:
            try:
                pct=5+int((i-1)/max(total,1)*30)
                upd(j,pct,f"OCR · pagina {i}/{total}",
                    f"Reconociendo texto de imagen · {len(native)} caracteres nativos")
                print(f"[{pct:3d}%] OCR pagina {i}/{total}",flush=True)
                tp=page.get_textpage_ocr(language=OCR_LANG,dpi=OCR_DPI,full=True)
                ocr_text=page.get_text("text",textpage=tp,sort=True).strip()
                if ocr_text:
                    used_ocr=True
                    ocr_pages.append(i)
            except Exception as e:
                print(f"[OCR] pagina {i}/{total}: {e}",flush=True)

        # No descartamos el texto nativo: Qwen recibe ambas fuentes y puede
        # decidir cual contiene el nombre real del perfume.
        if ocr_text and native.strip():
            text="[TEXTO PDF]\n"+native.strip()+"\n[OCR DE IMAGEN]\n"+ocr_text
        elif ocr_text:
            text="[OCR DE IMAGEN]\n"+ocr_text
        elif native.strip():
            text="[TEXTO PDF]\n"+native.strip()

        total_chars+=len(text)
        if len(text.strip())==0: empty_pages.append(i)
        pages.append({"page":i,"text":text,"ocr":used_ocr,"native_chars":len(native),"ocr_chars":len(ocr_text)})
        pct=5+int(i/max(total,1)*30)
        upd(j,pct,f"Extrayendo texto · pagina {i}/{total}",
            f"{len(text)} caracteres" + (" · OCR" if used_ocr else ""))
        print(f"[{pct:3d}%] Pagina {i}/{total} · nativo {len(native)} · OCR {len(ocr_text)}",flush=True)
    return pages,total_chars,empty_pages,ocr_pages,tess

def clean(s):
    s=re.sub(r"https?://\S+|www\.\S+|@\w+"," ",str(s),flags=re.I)
    s=re.sub(r"(instagram|whatsapp|phone|telefono|tel)\s*[:#-]?\s*\S+"," ",s,flags=re.I)
    return re.sub(r"\s+"," ",s).strip(" -:;,.|")

def parse_json(raw):
    """Parsea respuestas JSON de Qwen con tolerancia a wrappers y claves alternativas."""
    raw=str(raw or "").strip()
    if not raw:
        raise ValueError("Qwen devolvio una respuesta vacia")
    candidates=[raw]
    cleaned=re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$","",raw,flags=re.I|re.S).strip()
    if cleaned!=raw: candidates.append(cleaned)
    for key in ("perfumes","products","items","results"):
        pos=raw.find("{"+chr(34)+key+chr(34))
        if pos>=0: candidates.append(raw[pos:])
    data=None
    for candidate in candidates:
        try:
            obj,_=json.JSONDecoder().raw_decode(candidate)
            if isinstance(obj,dict):
                arr=None
                for key in ("perfumes","products","items","results"):
                    if isinstance(obj.get(key),list):
                        arr=obj[key]; break
                if arr is not None:
                    data={"perfumes":arr}; break
        except Exception:
            pass
    if data is None:
        m=re.search(r'\{\s*"?(?:perfumes|products|items|results)"?\s*:\s*\[.*?\]\s*\}',raw,re.S|re.I)
        if m:
            try:
                obj=json.loads(m.group())
                arr=next((obj.get(k) for k in ("perfumes","products","items","results") if isinstance(obj.get(k),list)),None)
                if arr is not None: data={"perfumes":arr}
            except Exception:
                pass
    if data is None:
        raise ValueError("Qwen no devolvio JSON valido: "+raw[:500])
    out=[]; seen=set()
    for x in data["perfumes"]:
        if isinstance(x,str): x={"name":x}
        if not isinstance(x,dict): continue
        n=clean(x.get("name") or x.get("perfume") or x.get("title") or "")
        b=clean(x.get("brand") or x.get("marca") or "")
        v=clean(x.get("variant") or x.get("version") or "")
        raw_pages=x.get("pages",x.get("page",[]))
        if isinstance(raw_pages,int): raw_pages=[raw_pages]
        if not isinstance(raw_pages,list): raw_pages=[]
        pages=[]
        for pv in raw_pages:
            try:
                if int(pv)>0: pages.append(int(pv))
            except Exception: pass
        if not n or len(n)>120: continue
        low=n.lower()
        junk=("instagram","whatsapp","proveedor","precio","catalogo","telefono","tel.","contacto","www.")
        if any(w in low for w in junk): continue
        if re.fullmatch(r"[\d\s+().-]{5,}",n): continue
        k=re.sub(r"\s+"," ",(n+" "+b+" "+v).lower()).strip()
        if k in seen: continue
        seen.add(k)
        try: conf=float(x.get("confidence",x.get("confianza",0)) or 0)
        except Exception: conf=0
        out.append({"name":n,"brand":b,"variant":v,"confidence":conf,"pages":sorted(set(pages))})
    return out

def page_candidates(text):
    """Reduce OCR ruidoso a lineas con alta probabilidad de contener nombres."""
    raw=re.sub(r"\r","",str(text or ""))
    lines=[]
    for line in raw.split("\n"):
        line=re.sub(r"\s+"," ",line).strip(" -|:;,. ")
        if not line or len(line)<2 or len(line)>100: continue
        low=line.lower()
        if re.search(r"https?://|www\.|@[a-z0-9_]+",low): continue
        if re.search(r"\b(whatsapp|instagram|facebook|tiktok|telegram|proveedor|distribuidor|contacto|telefono|tel)\b",low): continue
        digits=sum(c.isdigit() for c in line)
        letters=sum(c.isalpha() for c in line)
        if letters<3: continue
        if digits>=6 and digits>letters: continue
        if re.fullmatch(r"[\d\W_]+",line): continue
        lines.append(line)
    uniq=[]; seen=set()
    for line in lines:
        k=line.lower()
        if k not in seen:
            seen.add(k); uniq.append(line)
    return uniq[:35]

def text_identify(text):
    prompt="""Eres un extractor de nombres de perfumes. Analiza SOLO el texto OCR/PDF.
Cada [PAGINA N] es una pagina independiente. Identifica nombres comerciales de perfumes/fragrancias que aparezcan realmente en el texto. El OCR puede tener errores de una o dos letras: corrige solo errores evidentes. Conserva numeros legitimos como 212, 9PM, 1 Million y variantes EDT, EDP, Parfum, Elixir, Intense, Absolu, etc.
IGNORA precios, telefonos, codigos SKU, Instagram, WhatsApp, direcciones, nombres de proveedores, descuentos, mililitros y publicidad.
Si solo puedes determinar el nombre y no la marca, deja brand vacio. NO inventes perfumes que no aparezcan.
Devuelve TODOS los candidatos razonables. Devuelve SOLO este JSON:
{"perfumes":[{"name":"","brand":"","variant":"","confidence":0.0,"pages":[1]}]}
La confianza debe estar entre 0 y 1.
"""
    client=ollama.Client(host=HOST)
    diagnostics=[]
    try:
        r=client.chat(model=TEXT_MODEL,messages=[{"role":"user","content":prompt+"\n\n"+text}],options={"temperature":0},format="json",think=False,keep_alive="10m")
        raw=r.get("message",{}).get("content","")
        diagnostics.append(("main",raw[:1000]))
        found=parse_json(raw)
        if found: return found,diagnostics
    except Exception as e:
        diagnostics.append(("main_error",str(e)))
    retry="""Extrae SOLO nombres de perfumes del siguiente texto OCR. Devuelve JSON exacto {"perfumes":[{"name":"","brand":"","variant":"","confidence":0.0,"pages":[1]}]}.
Una linea que sea claramente un nombre de fragancia cuenta aunque la marca no sea visible. Ignora numeros de telefono, precios, redes sociales, SKU y proveedores. Corrige errores OCR evidentes pero no inventes nombres.
TEXTO:
"""+text
    try:
        r2=client.chat(model=TEXT_MODEL,messages=[{"role":"user","content":retry}],options={"temperature":0},format="json",think=False,keep_alive="10m")
        raw2=r2.get("message",{}).get("content","")
        diagnostics.append(("retry",raw2[:1000]))
        return parse_json(raw2),diagnostics
    except Exception as e:
        diagnostics.append(("retry_error",str(e)))
        return [],diagnostics
def page_png(page):
    pix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False)
    return pix.tobytes("png")

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

        # PRIMER PASO DE IDENTIFICACION: resumimos OCR por pagina antes de Qwen.
        compact_pages=[]
        for p in pages:
            cand=page_candidates(p["text"])
            compact_pages.append(f"\n[PAGINA {p['page']}]\n"+"\n".join(cand))
        chunks=[]; current=[]; chars=0; LIMIT=6500
        for piece in compact_pages:
            if current and chars+len(piece)>LIMIT:
                chunks.append(current); current=[]; chars=0
            current.append(piece); chars+=len(piece)
        if current: chunks.append(current)

        allp=[]; qwen_diag=[]
        for ci,chunk in enumerate(chunks,1):
            pct=38+int((ci-1)/max(len(chunks),1)*24)
            upd(j,pct,f"Qwen3 · bloque {ci}/{len(chunks)}","Identificando nombres a partir del OCR")
            print(f"[{pct:3d}%] Qwen3 · bloque {ci}/{len(chunks)}",flush=True)
            try:
                found,diag=text_identify("".join(chunk))
                qwen_diag.extend([{"block":ci,"type":t,"response":v} for t,v in diag])
            except Exception as e:
                found=[]; qwen_diag.append({"block":ci,"type":"exception","response":str(e)})
                print(f"[QWEN ERROR] bloque {ci}: {e}",flush=True)
            for x in found:
                page_nums=[n for n in x.get("pages",[]) if 1 <= n <= len(pages)]
                if not page_nums:
                    terms=[x["name"],x.get("variant",""),x.get("brand","")]
                    for p in pages:
                        if any(tok and len(tok)>2 and tok.lower() in p["text"].lower() for tok in terms):
                            page_nums.append(p["page"])
                x["pages"]=sorted(set(page_nums))
                if x["pages"]:
                    x["page"]=x["pages"][0]
                    allp.append(x)

        # Segundo pase compacto si el primero no produjo ningun candidato.
        if not allp:
            print("[QWEN FALLBACK] No hubo candidatos; ejecutando segundo pase compacto",flush=True)
            fallback=[]
            for p in pages:
                cand=page_candidates(p["text"])
                if cand:
                    fallback.append(f"[PAGINA {p['page']}] "+" | ".join(cand[:18]))
            for start in range(0,len(fallback),8):
                block="\n".join(fallback[start:start+8])
                try:
                    found,diag=text_identify(block)
                    qwen_diag.extend([{"block":f"fallback-{start//8+1}","type":t,"response":v} for t,v in diag])
                    for x in found:
                        pages_found=[n for n in x.get("pages",[]) if 1<=n<=len(pages)]
                        if pages_found:
                            x["pages"]=sorted(set(pages_found)); x["page"]=x["pages"][0]; allp.append(x)
                except Exception as e:
                    qwen_diag.append({"block":f"fallback-{start//8+1}","type":"exception","response":str(e)})

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

        result={"products":res,"stats":{"pages":len(pages),"characters":total_chars,"ocr_pages":ocr_pages,"ocr_available":bool(tess),"empty_text_pages":empty_pages,"detected":len(allp),"unique":len(res),"found":sum(x.get("found",False) for x in res),"qwen_blocks":len(qwen_diag),"qwen_diagnostics":qwen_diag[:40]}}
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
