# Monitor de noticias sobre violencia policial (Argentina)

Herramienta que lee los feeds RSS de medios argentinos, detecta notas que mencionan
violencia policial o institucional y las guarda en una base de datos local para que
puedas consultarlas.
> **Es una herramienta de apoyo, no de verificación.** Una coincidencia de palabras
> clave no prueba nada: siempre leé la nota original y contrastá la información.

## Qué hace

1. Descarga los feeds RSS configurados en `feeds.py`.
2. Descarta las notas ya vistas (no se repiten entre corridas).
3. Descarga cada nota nueva y busca palabras clave (ignora mayúsculas y tildes).
4. Guarda título, bajada, autor, fecha, URL y un **extracto corto** en `articles.db`.

## Instalación

Requiere Python 3.10 o superior.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
python main.py --check-feeds   # 1) verifica qué feeds funcionan
python main.py                 # 2) busca notas nuevas y las guarda
python main.py --db otra.db    # usar otro archivo de base de datos
```

**Antes de usarlo por primera vez:**

- Corré `--check-feeds` y eliminá de `feeds.py` los feeds que fallen. Las URLs incluidas
  son candidatas **sin verificar**; los medios cambian o cierran sus RSS.
- Cambiá el contacto del User-Agent en `settings.py` (o con la variable de entorno
  `SCRAPER_USER_AGENT`) por un mail real. Así los medios saben quién consulta sus sitios.

### Consultar los resultados

La base es SQLite. Podés abrirla con [DB Browser for SQLite](https://sqlitebrowser.org/)
o desde la terminal:

```bash
sqlite3 articles.db "SELECT first_seen, source, title, url FROM articles WHERE relevant = 1 ORDER BY first_seen DESC;"
```

Para exportar a CSV:

```bash
sqlite3 -header -csv articles.db "SELECT * FROM articles WHERE relevant = 1;" > notas.csv
```

## Personalizar

Todo se ajusta en `settings.py`:

| Opción | Para qué sirve |
|---|---|
| `keywords` | Términos a buscar. Frases (“gatillo fácil”) dan menos falsos positivos que palabras sueltas. |
| `max_articles_per_run` | Máximo de notas nuevas por corrida (también por variable `MAX_ARTICLES_PER_RUN`). |
| `domain_delay` | Segundos de espera entre pedidos al mismo sitio. No lo bajes mucho. |
| `respect_robots` | Respetar `robots.txt` (recomendado: `True`). |
| `store_body` | Si es `False` (por defecto) solo se guarda un extracto. |
| `allowed_hosts` | Si lo completás, solo se consultan esos dominios. |

Para agregar un medio, sumá una línea en `feeds.py`: `"nombre": "https://sitio/feed"`.

## Cómo está organizado el código

| Archivo                   | Responsabilidad                                                                         |
|---------------------------|-----------------------------------------------------------------------------------------|
| `main.py`                 | Punto de entrada por línea de comandos.                                                 |
| `scraper.py`              | Coordina todo el proceso.                                                               |
| `http_client.py`          | Descargas “educadas”: espera entre pedidos, reintentos, `robots.txt`, límite de tamaño. |
| `feed_parser.py`          | Lee RSS/Atom de forma segura.                                                           |
| `body_extractor.py`       | Extrae el texto de la nota.                                                             |
| `keywords.py`             | Búsqueda de palabras clave.                                                             |
| `privacy.py`              | Oculta emails, DNI y teléfonos.                                                         |
| `url_utils.py`            | Normaliza URLs y bloquea direcciones internas (SSRF).                                   |
| `sqlite_repository.py`    | Guarda los datos.                                                                       |
| `settings.py`, `feeds.py` | Configuración y lista de feeds.                                                         |
| `tests/`                  | Pruebas automáticas (`pytest --asyncio-mode=auto`).                                     |

Cada pieza es reemplazable: por ejemplo, podés cambiar SQLite por otra base
implementando `ArticleRepository` (`models.py`).

## Privacidad y ética

Las notas tratan sobre personas, a veces menores o víctimas.

- **Minimización:** por defecto no se guarda el texto completo, solo un extracto de
  500 caracteres con emails, DNI y teléfonos ocultos. Esta redacción es **parcial**:
  no reemplaza la revisión humana (no detecta nombres, direcciones, etc.).
- **Derechos de autor:** guardá el enlace y citá la fuente; no republiques notas completas.
- **Protegé la base:** `articles.db` puede contener datos sensibles. No la subas a
  repositorios públicos ni la compartas sin cuidado. Agregala a `.gitignore`.
- **Fuentes y menores:** aplicá tus criterios editoriales y la Ley de Protección de Datos
  Personales (25.326) al publicar cualquier análisis.
- **Uso responsable de los sitios:** la herramienta espera entre pedidos y respeta
  `robots.txt`. No la uses para sobrecargar servidores ni para saltear paywalls.

## Límites conocidos

- Hay medios sin RSS o con RSS parcial; estas notas no se detectan.
- Notas con paywall: solo se obtiene lo visible (puede quedar el cuerpo vacío).
- Las palabras clave generan falsos positivos y negativos: revisá los resultados.
- El extractor de texto es básico; en algunos sitios puede traer menús o publicidad.
- No hay interfaz gráfica ni geolocalización/clasificación automática de casos.

## Problemas frecuentes

- **`Channel.getaddrinfo() takes 3 positional arguments...`**: incompatibilidad
  `aiodns`/`pycares`. El código ya usa otro resolver; si persiste, `pip install -U aiodns`.
- **`robots.txt prohíbe ...`**: el sitio no permite ese acceso; se respeta.
- **Un feed “falla”**: puede estar caído, bloqueado o haber cambiado de URL.