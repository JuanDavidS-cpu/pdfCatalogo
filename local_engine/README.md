# ZUASH PDF Catalog Engine v3

Motor de catalogos basado en texto + IA, sin analizar las imagenes del PDF.

Flujo:
1. PyMuPDF extrae el texto pagina por pagina.
2. Qwen3 8B, ejecutado con Ollama, identifica solo perfumes.
3. Se limpian precios, SKU, proveedor, Instagram, telefonos y publicidad.
4. Se busca cada perfume en Internet.
5. Fragrantica es la fuente prioritaria de la ficha y se obtiene su URL e imagen.
6. La interfaz muestra progreso real, perfumes encontrados y enlaces.

## Instalacion
Python 3.12 + Ollama.
Instala dependencias con pip install -r requirements.txt.
Instala el modelo con ollama pull qwen3:8b.

## Ejecutar
uvicorn app:app --host 127.0.0.1 --port 8765

Abre http://127.0.0.1:8765

## Uso como pagina web
La interfaz es una pagina web. Puede publicarse en un hosting como Vercel, pero Qwen3/Ollama debe ejecutarse en un backend o servidor que tenga Ollama. No se intenta ejecutar Ollama dentro de Vercel.
