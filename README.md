# ZUASH PDF Catalog Studio

Aplicación web para convertir catálogos PDF de perfumes en un catálogo PDF premium de ZUASH.

## Flujo
1. Carga un PDF.
2. Extrae el texto para proponer nombres reales.
3. Intenta extraer imágenes individuales embebidas en el PDF.
4. Si no encuentra imágenes individuales, usa el render de la página como respaldo.
5. Puedes corregir nombres y abrir una búsqueda exacta en Google Imágenes para sustituir fotos faltantes.
6. Genera un PDF A4 negro/dorado con 6 productos por página.

## Privacidad
El PDF se procesa en el navegador. No se sube a un servidor de la aplicación.

## Nota sobre imágenes de Google
La app no descarga automáticamente imágenes desde Google porque Google Imágenes no ofrece una API pública gratuita para este flujo. El botón de búsqueda abre la consulta del perfume para que puedas elegir una imagen. La extracción directa desde el PDF es la opción automática principal.

## Ejecutar
Abrir `index.html` directamente o publicarlo como sitio estático en GitHub Pages, Vercel o Netlify.
