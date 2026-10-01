# ZUASH PDF Catalog Studio

Motor híbrido para convertir **cualquier PDF de proveedor** en productos individuales para el catálogo ZUASH.

## Arquitectura

- **PDF.js** carga y renderiza cada página.
- **Gemini Vision** es el detector visual general. Devuelve productos individuales, nombres y bounding boxes mediante salida JSON estructurada.
- **Google Cloud Vision Product Search** es un segundo detector/identificador opcional para productos que tengan imágenes de referencia.
- **Fragrantica** normaliza el nombre del perfume y sirve como fuente alternativa.
- **Google Images** se consulta mediante Serper o SerpApi para conseguir la imagen limpia final.
- La página completa **nunca** se convierte automáticamente en una tarjeta de producto.

Gemini puede detectar objetos y devolver bounding boxes en escala normalizada, además de generar JSON estructurado. Vision Product Search admite detección múltiple de productos y devuelve una caja y coincidencias para cada producto detectado.

## Variables de entorno

### Detección visual general

Obligatoria para el motor principal:

`GEMINI_API_KEY`

Opcional:

`GEMINI_MODEL`

Por defecto:

`gemini-2.5-flash`

### Product Search

`GOOGLE_PRODUCT_SET`

Autenticación mediante una de estas variables:

`GOOGLE_ACCESS_TOKEN`

o

`GOOGLE_SERVICE_ACCOUNT_JSON`

El Product Set debe contener productos e imágenes de referencia. Es recomendable añadir varias imágenes por fragancia.

### Búsqueda de imágenes

Configura una de estas:

`SERPER_API_KEY`

o

`SERPAPI_KEY`

## Flujo de procesamiento

Cada página se renderiza y se manda al detector visual. La respuesta se valida antes de crear una tarjeta:

`PDF → página → detección individual → nombre → identificación → imagen limpia → tarjeta ZUASH`

Si Product Search está disponible, sus resultados se fusionan con Gemini. Una coincidencia visual no sustituye silenciosamente un resultado de mayor confianza.

## Regla contra falsos recortes

No existe un fallback que diga simplemente “no encontré nada, así que recorto la página”.

Si ningún detector visual confirma un producto, la página se omite y se informa en la interfaz.

Esto es intencional: es mejor no crear una tarjeta que insertar una página completa, Instagram, un logo o un recorte arbitrario como si fuera un perfume.

## Reconocimiento de perfumes arbitrarios

Product Search requiere referencias previas del producto. Para perfumes que no estén en ese catálogo, Gemini Vision puede intentar identificarlos a partir del texto visible y de la botella/caja. Después se consulta Fragrantica y el buscador de imágenes.

## Desarrollo

La interfaz es estática y puede publicarse en Vercel. Las funciones bajo `/api` se ejecutan en servidor y mantienen las claves de los proveedores fuera del navegador.
