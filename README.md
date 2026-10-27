# Laboratorio RSS para Power Automate

Servidor pequeño e independiente para comprobar el disparador **RSS — Cuando se publica un elemento de fuente**. No usa Django, no necesita paquetes de terceros y no contiene datos personales.

## Qué incluye

- `GET /feed.xml`: fuente RSS 2.0.
- `POST /events`: agrega un evento ficticio por JSON o formulario.
- `GET /`: formulario sencillo para crear eventos manualmente.
- `GET /events/{id}`: página del evento ficticio enlazada desde el RSS.
- `GET /health`: comprobación de salud.
- SQLite persistente. Cada `pubDate` es, como mínimo, un segundo mayor que el anterior, incluso después de reiniciar.

## Ejecutar localmente

Requiere Python 3.10 o posterior. Desde esta carpeta:

```powershell
python rss_server.py
```

Abre <http://localhost:8000>. La base se crea en `data/events.db`.

Para crear un evento desde PowerShell:

```powershell
$body = @{ title = "Prueba 1"; description = "Evento ficticio" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/events -ContentType application/json -Body $body
```

En macOS/Linux con curl:

```bash
curl -X POST http://localhost:8000/events \
  -H 'Content-Type: application/json' \
  -d '{"title":"Prueba 1","description":"Evento ficticio"}'
```

## Ejecutar con Docker

```bash
docker compose up --build
```

El volumen `rss_data` conserva SQLite al recrear el contenedor. Para detener:

```bash
docker compose down
```

No agregues `-v` si deseas conservar los eventos.

## Hacerlo accesible a Power Automate

`localhost` solo es visible en tu equipo; el servicio de Power Automate necesita una URL pública alcanzable, preferiblemente HTTPS. Puedes publicar temporalmente el puerto 8000 con el túnel aprobado por tu organización o desplegar el contenedor en un entorno de prueba.

Una vez tengas, por ejemplo, `https://rss-lab.example.test`, configura:

```powershell
$env:PUBLIC_BASE_URL = "https://rss-lab.example.test"
python rss_server.py
```

Con Docker Compose, descomenta `PUBLIC_BASE_URL` en `compose.yaml` y coloca la URL real. Comprueba desde una red externa que `https://.../feed.xml` abre sin autenticación y devuelve XML.

> El servidor es un laboratorio: no incorpora autenticación ni endurecimiento para producción. Publícalo de forma temporal o protégelo a nivel de infraestructura, sin impedir que el conector RSS lea `/feed.xml`.

## Prueba en Power Automate

1. Antes de crear el flujo, abre la URL pública `/feed.xml` y valida que responde.
2. En Power Automate, crea un **flujo de nube automatizado**.
3. Selecciona el disparador **RSS — Cuando se publica un elemento de fuente**.
4. En **Dirección URL de fuente RSS**, pega la URL pública completa, por ejemplo `https://rss-lab.example.test/feed.xml`.
5. Si aparece la opción de propiedad para determinar novedades, usa la fecha de publicación (`PublishDate` / `pubDate`), no `UpdatedOn`.
6. Agrega una acción inocua para la prueba, por ejemplo **Componer**, con título, fecha de publicación, vínculo y resumen del elemento.
7. Guarda y activa el flujo. Espera a que termine la lectura inicial.
8. Crea un evento nuevo desde `/`, PowerShell o curl. No reutilices información real.
9. Revisa el historial de ejecuciones. El disparador es por sondeo: Microsoft documenta un intervalo mínimo de 1.800 segundos, por lo que puede tardar alrededor de 30 minutos o más.
10. Para una segunda prueba, crea otro evento. Su `pubDate` será estrictamente posterior, aunque lo agregues inmediatamente.

Evita precargar eventos justo antes de crear el flujo: la primera lectura puede fijar la línea base sin dispararlos. Primero guarda el flujo y luego agrega un evento nuevo.

## Ejecutar las pruebas automáticas

```powershell
python -m unittest discover -s tests -v
```

Las pruebas verifican persistencia y crecimiento estricto de timestamps, estructura RSS y el ciclo HTTP de creación/lectura.

## Referencias oficiales

- [Conector RSS de Microsoft Power Automate](https://learn.microsoft.com/es-es/connectors/rss/): documenta el disparador, el uso de `pubDate` para detectar novedades y el intervalo mínimo de sondeo de 1.800 segundos.
- [Trabajo con desencadenadores y acciones](https://learn.microsoft.com/es-es/power-automate/work-with-triggers-actions): guía general del diseñador de flujos.

## Reiniciar los datos

Local: detén el servidor y elimina `data/events.db` (y, si existen, sus archivos `-wal` y `-shm`). Docker: `docker compose down -v` elimina el volumen y todos los eventos de laboratorio.
