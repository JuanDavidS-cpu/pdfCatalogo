# ZUASH Local AI Engine

Motor local para analizar **PDFs arbitrarios de proveedores** y convertir las páginas en productos individuales.

## Motores

- **PyMuPDF**: apertura/render de PDF, texto con coordenadas y recursos de imagen.
- **Docling Parse**: segunda lectura estructural del PDF cuando está instalado.
- **PaddleOCR-VL 1.6**: parser visual de documentos y reconocimiento espacial.
- **Qwen3-VL vía Ollama**: segunda opinión visual independiente para detectar productos y asociar nombre + caja.
- **OpenCV**: validación geométrica, solapes y descarte de cajas imposibles.
- **DDGS**: búsqueda de imágenes sin API key obligatoria.
- **Fragrantica**: enriquecimiento opcional del nombre mediante el endpoint existente de ZUASH.

PaddleOCR-VL 1.6 es un modelo de 0.9B orientado a comprensión de documentos y actualmente usa PP-DocLayoutV3 para layout; su documentación oficial expone la clase Python `PaddleOCRVL` con pipeline v1.6. Qwen3-VL ofrece grounding espacial y modelos locales en Ollama. Docling Parse entrega texto e imágenes con coordenadas. cite... 

## Instalación recomendada en Windows

Para el primer intento usa **WSL2 + Ubuntu**, especialmente para el stack de IA. PaddleOCR documenta instalaciones y despliegues optimizados principalmente sobre Linux para ciertos backends acelerados.

### 1. Crear entorno

```bash
cd local_engine
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Instalar Ollama

Instala Ollama para Windows/WSL desde su sitio oficial y comprueba:

```bash
ollama --version
```

Después:

```bash
ollama pull qwen3-vl:8b
```

El modelo `qwen3-vl:8b` se publica con entrada de texto+imagen y aproximadamente 6.1 GB de tamaño en Ollama. También existen variantes 2B, 4B, 30B y 32B. 

### 3. Arrancar el motor

Desde `local_engine`:

```bash
source .venv/bin/activate
python app.py
```

Después abre:

```
http://127.0.0.1:8765
```

## Arquitectura

```
PDF
 |
 +--> PyMuPDF -----------+
 |                        |
 +--> Docling Parse ------+--> evidencias estructurales
 |                        |
 +--> PaddleOCR-VL -------+--> regiones/document layout
 |                        |
 +--> Qwen3-VL -----------+--> regiones/nombres independientes
                          |
                          v
                     OpenCV validator
                          |
                          v
                   consenso multi-modelo
                          |
                 +--------+--------+
                 |                 |
              nombre            imagen limpia
                 |                 |
             Fragrantica           DDGS
                 |                 |
                 +--------+--------+
                          |
                          v
                    Catalogo ZUASH
```

### Regla anti-recorte

El motor **no** crea un producto sólo porque haya una botella o un nombre.

Una tarjeta se crea cuando existe evidencia suficiente de una región individual. Las regiones se fusionan sólo si los modelos están de acuerdo espacialmente o si un motor fuerte aporta una detección clara.

Si no hay evidencia suficiente, la página queda marcada para revisión y no se convierte en una tarjeta falsa.

## Modelos

Por defecto:

- PaddleOCR-VL 1.6: `pipeline_version="v1.6"`
- Qwen3-VL: `qwen3-vl:8b`

Se pueden cambiar mediante variables:

```bash
export QWEN_MODEL=qwen3-vl:4b
export ZUASH_PADDLE_DEVICE=cpu
```

## Imagen

DDGS busca imágenes sin necesitar Serper/SerpApi. La aplicación guarda la URL y utiliza la primera imagen que responde con un tipo de contenido de imagen válido; si no encuentra una imagen externa, conserva el recorte de la fuente como respaldo para revisión.

## Importante

Este motor está diseñado para **cualquier layout**, no para un único proveedor. Aun así, ningún modelo puede garantizar 100% de acierto en todos los documentos del mundo. Por eso la arquitectura exige consenso y muestra las regiones dudosas para revisión en lugar de inventarlas.
