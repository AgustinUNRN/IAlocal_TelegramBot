# `R2D2_CloudBot.py`

Este README describe específicamente el funcionamiento interno de `telegram-bot/R2D2_CloudBot.py`.

El bot utiliza Telegram como interfaz, Ollama para inferencia local, LangChain para herramientas y ChromaDB/PostgreSQL para memoria y almacenamiento.

---

## Contenido

- [Resumen](#resumen)
- [Dependencias](#dependencias)
- [Configuración](#configuración)
- [Inicialización](#inicialización)
- [Persistencia PostgreSQL](#persistencia-postgresql)
- [ChromaDB y RAG](#chromadb-y-rag)
- [Herramientas del agente](#herramientas-del-agente)
- [Ejecución del agente](#ejecución-del-agente)
- [Pipeline de visión](#pipeline-de-visión)
- [Handlers de Telegram](#handlers-de-telegram)
- [Utilidades](#utilidades)
- [Flujo general](#flujo-general)
- [Variables y rutas](#variables-y-rutas)

---

## Resumen

El archivo implementa un agente llamado **Arturito**, capaz de:

- Conversar mediante Telegram.
- Delegar tareas de programación.
- Consultar documentos PDF y TXT.
- Consultar el historial de un usuario.
- Exportar conversaciones.
- Crear reportes descargables.
- Analizar imágenes.
- Registrar todas las interacciones en PostgreSQL.

---

## Dependencias

Importaciones principales:

```python
import os
import sys
import csv
import asyncio
import base64
import httpx
import psycopg2
```

Telegram:

```python
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.constants import ChatAction
```

LangChain y Ollama:

```python
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    ToolMessage
)
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader
)
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter
)
```

---

## Configuración

Las variables se cargan desde el entorno:

```python
load_dotenv()
```

### Variables generales

| Variable | Predeterminado | Uso |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Token del bot |
| `OLLAMA_HOST` | `http://ollama_sandbox:11434` | API Ollama |
| `MODEL_NAME` | `qwen2.5:3b` | Modelo conversacional |
| `VISION_MODEL` | `moondream:1.8b` | Modelo de imágenes |
| `TRANSLATOR_MODEL` | `lauchacarro/qwen2.5-translator` | Traducción de visión |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embeddings |
| `CODER_MODEL` | `qwen2.5-coder:1.5b` | Modelo especializado en código |
| `CHROMA_DB_DIR` | `/app/chroma_db` | Base vectorial |
| `DOCS_DIR` | `/app/docs` | Archivos PDF/TXT |
| `REPORTS_DIR` | `/app/reports` | Archivos generados |
| `ENABLE_RAG` | `true` | Habilita RAG |

### Variables PostgreSQL

| Variable | Predeterminado |
|---|---|
| `DB_HOST` | `postgres_db` |
| `POSTGRES_DB` | `arturito_db` |
| `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | `postgres` |

Los directorios necesarios se crean al iniciar:

```python
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
```

---

## Inicialización

Al ejecutarse como programa principal:

```python
if __name__ == "__main__":
```

el bot:

1. Muestra los modelos configurados.
2. Construye la aplicación de Telegram.
3. Registra los handlers.
4. Inicia el polling.

```python
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.run_polling()
```

Los manejadores registrados son:

```python
app.add_handler(
    MessageHandler(
        filters.Document.PDF | filters.Document.TXT,
        handle_document
    )
)

app.add_handler(
    MessageHandler(
        filters.PHOTO | filters.Document.IMAGE,
        handle_photo
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)
```

---

## Persistencia PostgreSQL

### Conexión

```python
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )
```

### Registro de interacciones

```python
def registrar_interaccion_db(
    user_id,
    username,
    first_name,
    user_message,
    bot_response
):
```

Primero registra o actualiza al usuario:

```sql
INSERT INTO usuarios (telegram_id, username, nombre)
VALUES (%s, %s, %s)
ON CONFLICT (telegram_id)
DO UPDATE SET
    username = EXCLUDED.username,
    nombre = EXCLUDED.nombre;
```

Después registra el mensaje:

```sql
INSERT INTO mensajes (
    telegram_id,
    mensaje_usuario,
    respuesta_bot
)
VALUES (%s, %s, %s);
```

Los errores se muestran en consola y no detienen el bot:

```python
print(f"⚠️ Error al guardar en PostgreSQL: {e}")
```

---

## ChromaDB y RAG

### Embeddings

```python
embeddings = OllamaEmbeddings(
    model=EMBEDDING_MODEL,
    base_url=OLLAMA_HOST
)
```

### Vector store

```python
vectorstore = Chroma(
    persist_directory=DB_DIR,
    embedding_function=embeddings
)
```

### Recuperador

```python
retriever = vectorstore.as_retriever(
    search_kwargs={"k": 4}
)
```

Se recuperan hasta cuatro fragmentos relevantes.

---

## Indexación de documentos

La función `indexar_documento_sync()` admite PDF y TXT:

```python
if ruta_archivo.lower().endswith(".pdf"):
    loader = PyPDFLoader(ruta_archivo)
elif ruta_archivo.lower().endswith(".txt"):
    loader = TextLoader(ruta_archivo, encoding="utf-8")
else:
    raise ValueError("Formato no soportado. Usá .pdf o .txt")
```

### Fragmentación

```python
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=120
)
```

- Cada fragmento tiene hasta 800 caracteres.
- Existe una superposición de 120 caracteres.
- Los documentos vacíos generan una excepción.
- Los fragmentos se agregan a ChromaDB.

---

## Herramientas del agente

Las herramientas se crean con:

```python
construir_herramientas_usuario(
    user_id,
    archivos_generados
)
```

Esto permite vincular cada herramienta a:

- El usuario actual.
- La lista de archivos generados durante la conversación.

### Delegación de código

```python
resolver_programacion_codigo(tarea_codigo)
```

Usa:

```python
llm_coder = ChatOllama(
    model=CODER_MODEL,
    base_url=OLLAMA_HOST,
    temperature=0.1
)
```

Resuelve:

- Código.
- Scripts.
- SQL.
- Depuración.
- Explicaciones técnicas.

Si el mensaje contiene palabras relacionadas con programación, el bot puede delegarlo directamente sin usar el bucle de herramientas general.

### Búsqueda RAG

```python
buscar_en_documentos_rag(consulta)
```

1. Comprueba `ENABLE_RAG`.
2. Ejecuta `retriever.invoke(consulta)`.
3. Devuelve fragmentos relevantes.
4. Incluye el nombre del archivo de origen.

### Consulta del historial

```python
buscar_historial_postgresql(palabra_clave="")
```

Sin palabra clave:

- Devuelve las últimas ocho conversaciones.

Con palabra clave:

- Busca coincidencias en mensajes del usuario.
- Busca en el mensaje y en la respuesta.
- Devuelve hasta seis registros.

La consulta utiliza:

```sql
mensaje_usuario ILIKE %s
respuesta_bot ILIKE %s
```

### Exportación del historial

```python
exportar_historial_postgresql(formato="csv")
```

Formatos admitidos:

- `csv`.
- `txt`.

Los demás valores se convierten a TXT.

El CSV contiene:

- Fecha.
- Mensaje del usuario.
- Respuesta del bot.

El TXT contiene:

- Fecha.
- Usuario.
- Arturito.
- Separadores entre registros.

La ruta generada se agrega a `archivos_generados`.

### Generación de reportes

```python
generar_reporte_archivo(
    titulo,
    contenido,
    formato="txt"
)
```

TXT:

- Agrega encabezado.
- Agrega fecha.
- Guarda el contenido recibido.

CSV:

- Divide el contenido por líneas.
- Separa cada línea por comas.
- Guarda las columnas generadas.

---

## Ejecución del agente

### Modelos

Modelo principal:

```python
llm_chat = ChatOllama(
    model=MODEL_NAME,
    base_url=OLLAMA_HOST,
    temperature=0.2
)
```

Modelo de código:

```python
llm_coder = ChatOllama(
    model=CODER_MODEL,
    base_url=OLLAMA_HOST,
    temperature=0.1
)
```

### Derivación automática de código

Antes del bucle general se analizan palabras clave como:

```text
python
sql
bash
java
javascript
html
css
c++
código
script
función
algoritmo
debug
depurar
```

Si hay coincidencia y no se trata de historial o archivos, llama directamente a:

```python
resolver_programacion_codigo
```

### Prompt del agente

El prompt define las reglas de delegación:

- No escribir código directamente.
- Usar RAG para consultas sobre documentos.
- Usar herramientas para historial.
- Exportar mediante herramientas específicas.
- Responder directamente solo para saludos o consultas básicas.

### Bucle de herramientas

```python
for _ in range(3):
```

Permite hasta tres iteraciones:

1. Invoca el modelo con herramientas.
2. Agrega la respuesta al contexto.
3. Detecta llamadas `tool_calls`.
4. Ejecuta cada herramienta.
5. Agrega el resultado como `ToolMessage`.
6. Vuelve a invocar el modelo.
7. Devuelve la respuesta final.

Si no quedan llamadas:

```python
return str(respuesta_ai.content).strip(), archivos_generados
```

Si se alcanzan los tres ciclos:

```python
respuesta_final = llm_chat.invoke(mensajes)
```

---

## Pipeline de visión

`consultar_modelo_vision()` usa Ollama directamente mediante HTTP:

```text
POST OLLAMA_HOST/api/generate
```

Payload:

```json
{
  "model": "modelo",
  "prompt": "consulta",
  "images": ["base64"],
  "stream": false
}
```

Timeout configurado:

```python
httpx.Timeout(
    300.0,
    connect=30.0
)
```

Si el modelo es Moondream:

1. Consulta el modelo de visión.
2. Envía la respuesta al traductor.
3. Usa temperatura cero.
4. Devuelve texto en español.
5. Si falla la traducción, devuelve el texto original.

---

## Handlers de Telegram

### Indicador de escritura

```python
async def mantener_typing(context, chat_id):
```

Envía `ChatAction.TYPING` cada cuatro segundos.

Se detiene con:

```python
await detener_typing(typing_task)
```

### `handle_message`

Procesa texto.

Funciones:

- Extrae el Telegram ID.
- Extrae username y nombre.
- Elimina espacios externos.
- Ejecuta `ejecutar_agente()`.
- Guarda la interacción.
- Divide respuestas largas.
- Envía archivos generados.

### `handle_document`

Procesa PDF y TXT.

Validaciones:

- Documento presente.
- Extensión PDF/TXT.
- Nombre válido.
- Archivo disponible.

La interacción se registra como:

```text
[INGESTA RAG] nombre-del-documento
```

### `handle_photo`

Procesa:

- Fotos.
- Documentos con MIME `image/*`.

Pasos:

1. Extrae el pie de foto.
2. Descarga la imagen.
3. Convierte a Base64.
4. Ejecuta el análisis.
5. Divide la respuesta si es larga.
6. Guarda la interacción.

---

## Utilidades

### División de texto

```python
dividir_texto(texto, limite=3900)
```

Característica:

- Limita respuestas largas.
- Cuenta caracteres Unicode según su peso.
- Prioriza saltos de línea.
- Busca espacios cercanos.
- Evita cortar palabras cuando es posible.

### Envío largo

```python
enviar_respuesta_larga(update, texto)
```

Envía una parte por mensaje.

### Archivos adjuntos

```python
with open(ruta_archivo, "rb") as f:
    await update.message.reply_document(
        document=f,
        filename=os.path.basename(ruta_archivo),
        caption="📎 Reporte generado por el agente."
    )
```

---

## Flujo general

```text
Mensaje o archivo recibido
        │
        ▼
Handler correspondiente
        │
        ├── Texto ─────────── ejecutar_agente()
        ├── PDF/TXT ───────── indexar_documento_sync()
        └── Imagen ────────── consultar_modelo_vision()
        │
        ▼
Respuesta generada
        │
        ▼
Registro en PostgreSQL
        │
        ▼
Respuesta o archivo enviado por Telegram
```

---

## Variables y rutas

### Directorios internos

| Ruta | Uso |
|---|---|
| `/app/docs` | PDF y TXT recibidos |
| `/app/chroma_db` | Índices persistentes |
| `/app/reports` | Exportaciones y reportes |

### Configuración recomendada

```env
TELEGRAM_BOT_TOKEN=tu_token
OLLAMA_HOST=http://ollama_sandbox:11434
MODEL_NAME=qwen2.5:3b
CODER_MODEL=qwen2.5-coder:1.5b
VISION_MODEL=moondream:1.8b
TRANSLATOR_MODEL=lauchacarro/qwen2.5-translator
EMBEDDING_MODEL=nomic-embed-text
ENABLE_RAG=true
DB_HOST=postgres_db
POSTGRES_DB=telegram_bot_db
POSTGRES_USER=bot_user
POSTGRES_PASSWORD=bot_password_segura
CHROMA_DB_DIR=/app/chroma_db
DOCS_DIR=/app/docs
REPORTS_DIR=/app/reports
```

---

## Ejecución directa

Dentro del contenedor:

```bash
python R2D2_CloudBot.py
```

El archivo iniciará Telegram mediante polling y registrará:

- Documentos PDF/TXT.
- Fotografías o imágenes.
- Mensajes de texto.