# Monitor de rebajas Gollo (>=50% descuento)

Revisa TODO el catálogo de https://www.gollo.com/c cada 15 minutos y te manda
un correo a **martinez96jason@gmail.com** cuando aparece un producto NUEVO con
50% de descuento o más. No repite alertas del mismo producto mientras siga en
oferta; si el producto sale de oferta y luego vuelve a bajar de precio, te
avisa de nuevo.

No usa Chrome/Selenium: el catálogo de Gollo ya trae los precios en el HTML,
así que basta con `requests` + `BeautifulSoup` (más rápido y liviano).

## 1. Crear el repositorio en GitHub

1. Crea un repositorio nuevo en GitHub (puede ser público o privado).
2. Sube estos archivos tal cual están (mantené la carpeta `.github/workflows/`).

```bash
cd gollo-monitor
git init
git add .
git commit -m "Monitor de rebajas Gollo"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/TU-REPO.git
git push -u origin main
```

## 2. Crear una "Contraseña de aplicación" de Gmail

Gmail no deja usar tu contraseña normal para enviar correos por script. Hay
que generar una contraseña de aplicación:

1. Activa la verificación en 2 pasos en tu cuenta de Google (si no la tenés):
   https://myaccount.google.com/security
2. Andá a: https://myaccount.google.com/apppasswords
3. Generá una contraseña de aplicación (elegí "Otra" y ponele un nombre,
   ej. "gollo-bot"). Te va a dar un código de 16 caracteres.

**Importante:** este bot debe enviar el correo desde una cuenta de Gmail
(la tuya u otra que crees solo para esto). El destinatario
(martinez96jason@gmail.com) puede ser cualquier correo, no tiene que ser Gmail.

## 3. Configurar los "Secrets" en GitHub

En tu repositorio: **Settings → Secrets and variables → Actions → New repository secret**

Agregá estos dos:

| Nombre                | Valor                                              |
|------------------------|-----------------------------------------------------|
| `GMAIL_USER`           | La cuenta de Gmail desde la que se envía (ej: tuBot@gmail.com) |
| `GMAIL_APP_PASSWORD`   | La contraseña de aplicación de 16 caracteres del paso 2 |

Si en algún momento querés cambiar el correo destino, editá la línea
`ALERT_EMAIL` en `.github/workflows/monitor.yml`.

## 4. Probarlo manualmente

En GitHub: pestaña **Actions → Monitor de rebajas Gollo → Run workflow**.
Así lo corrés una vez sin esperar los 15 minutos, y revisás en los logs que
todo funcione (cuántas páginas escaneó, cuántas ofertas encontró, etc.)

Después de esa primera corrida, quedará activo automáticamente cada 15
minutos.

## Notas importantes

- **Primera corrida:** la primera vez probablemente te va a mandar de golpe
  TODAS las ofertas de +50% que ya existen ahora mismo en la página (pueden
  ser bastantes). De ahí en adelante solo te avisa de las nuevas.
- **GitHub Actions gratis:** en repos públicos los minutos son ilimitados. En
  privados tenés 2,000 minutos/mes gratis, y esto consume pocos minutos por
  corrida, así que sobra de sobra.
- **Catálogo completo = ~65-70 páginas por corrida.** El script espera ~1.2
  segundos entre cada una para no sobrecargar el sitio, así que cada corrida
  tarda unos 2-3 minutos.
- Si Gollo cambia el diseño de su web más adelante y el bot deja de detectar
  productos, avisame y lo ajustamos.
