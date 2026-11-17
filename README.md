# 🤖 R2D2 CloudBot (Arturito) — Agente IA Local en Docker

Asistente conversacional y **agente autónomo multi-modelo** dockerizado para Telegram, ejecutándose 100% en entorno local sin dependencias de APIs externas en la nube. Integra **Ollama** (`qwen2.5:3b`, `qwen2.5-coder:1.5b`, `moondream:1.8b` y `lauchacarro/qwen2.5-translator`), recuperación aumentada por generación (**RAG**) con **ChromaDB** (`nomic-embed-text`), y persistencia relacional de usuarios e historial en **PostgreSQL**.

---

## 🧠 Capacidades del Agente

A diferencia de un chatbot lineal, **Arturito** utiliza una arquitectura híbrida que combina *Tool Calling* (`ChatOllama` + `bind_tools` en LangChain) con enrutamiento determinista para tareas de programación, invocando dinámicamente 5 herramientas locales:

1. **💻 Delegación de Programación (`resolver_programacion_codigo`):** Deriva tareas de escritura de código, scripts (Python, SQL, Bash, Java, HTML, etc.), depuración o explicación técnica al modelo especialista **`qwen2.5-coder:1.5b`**.
2. **📚 Consulta de Documentos (`buscar_en_documentos_rag`):** Busca información semántica en los archivos `.pdf` y `.txt` indexados en **ChromaDB** (`nomic-embed-text`).
3. **🗄️ Bitácora Histórica (`buscar_historial_postgresql`):** Consulta conversaciones previas en **PostgreSQL** (filtrando por palabra clave o recuperando los últimos mensajes recientes) aisladas por el `telegram_id` del usuario activo.
4. **📤 Exportación de Historial (`exportar_historial_postgresql`):** Descarga el historial completo de conversaciones del usuario desde **PostgreSQL** directamente a un archivo `.csv` o `.txt` adjunto en Telegram.
5. **📝 Generación de Reportes (`generar_reporte_archivo`):** Crea archivos descargables (`.txt` o `.csv`) en `telegram-bot/reports/` con resúmenes o datos extraídos y los envía automáticamente en el chat.
6. **🖼️ Pipeline Multimodal de Imágenes:** Analiza fotografías enviadas al chat con **`moondream:1.8b`** y traduce la respuesta al español mediante **`lauchacarro/qwen2.5-translator`** (`temperature=0.0`).
7. **📥 Ingesta Dinámica por Chat:** Permite enviar archivos `.pdf` o `.txt` directamente como documento al bot de Telegram para fragmentarlos (`RecursiveCharacterTextSplitter`) e indexarlos al instante en ChromaDB.

---

## 🏗️ Arquitectura del Sistema

El entorno está orquestado con **Docker Compose** e integra tres servicios aislados en red interna (`ai_sandbox_net`):

* **`telegram_bot` (`telegram_bot_sandbox`):** Aplicación en Python (`PYTHONUNBUFFERED=1`) que gestiona los handlers de Telegram, el bucle del agente LangChain, la ingesta de archivos, la exportación de reportes (persistidos en `./telegram-bot/reports`) y las conexiones con PostgreSQL y ChromaDB.
* **`ollama-isolated` (`ollama_sandbox`):** Servidor local de Ollama endurecido (sin puertos expuestos al host, usuario no-root `10001:10001`, `cap_drop: ALL`, `no-new-privileges` y `OLLAMA_MAX_LOADED_MODELS=2`) que aloja los 5 modelos locales (`qwen2.5:3b`, `qwen2.5-coder:1.5b`, `moondream:1.8b`, `lauchacarro/qwen2.5-translator` y `nomic-embed-text`).
* **`postgres_db` (`postgres_db_sandbox`):** Base de datos PostgreSQL 15 para el registro y persistencia relacional de usuarios y mensajes.

*(Para ver el árbol de directorios completo, consultá [`architecture.md`](./architecture.md)).*

---

## 🚀 Requisitos Previos

* **Ubuntu / Linux** con [Docker Engine](https://docs.docker.com/engine/install/) y [Docker Compose](https://docs.docker.com/compose/install/) instalados.
* **Token de Telegram Bot** proporcionado por [@BotFather](https://t.me/botfather).

---

## ⚙️ Configuración del Entorno

El proyecto divide las variables de entorno en dos archivos `.env` (ambos ignorados en Git; se incluyen las plantillas `env` como referencia):

### 1. Variables de Modelos e Inferencia (`.env` en la raíz)
Crear `.env` en la raíz del proyecto para configurar Ollama y los modelos utilizados por los contenedores:

```env
# Configuración de modelos Ollama
MODEL_NAME=qwen2.5:3b
EMBEDDING_MODEL=nomic-embed-text
OLLAMA_HOST=http://ollama_sandbox:11434
VISION_MODEL=moondream:1.8b
TRANSLATOR_MODEL=lauchacarro/qwen2.5-translator
CODER_MODEL=qwen2.5-coder:1.5b
```

### 2. Variables del Bot (`telegram-bot/.env`)
1. Ingresar a la carpeta del bot:
   ```bash
   cd telegram-bot
   ```
2. Crear o editar el archivo `.env`:
   ```bash
   nano .env
   ```
3. Contenido recomendado:
   ```env
   # Credenciales de Telegram
   TELEGRAM_BOT_TOKEN=tu_token_de_telegram_aqui

   # Configuración PostgreSQL
   DB_HOST=postgres_db
   POSTGRES_DB=telegram_bot_db
   POSTGRES_USER=bot_user
   POSTGRES_PASSWORD=bot_password_segura

   # Configuración RAG
   ENABLE_RAG=true
   ```

---

## 🛠️ Despliegue e Inicio de Servicios

Desde la raíz del proyecto (donde reside `docker-compose.yml`), ejecutar:

```bash
# Construir y levantar la arquitectura en segundo plano
docker compose up -d --build
```

> **Nota:** La descarga inicial de los modelos ocurre automáticamente durante la compilación del servicio `ollama-isolated` utilizando las variables definidas en la raíz.

### Verificación Manual de Modelos en Ollama (Opcional)

Si necesitás descargar o verificar algún modelo manualmente dentro del contenedor:
```bash
docker exec -it ollama_sandbox ollama pull qwen2.5:3b
docker exec -it ollama_sandbox ollama pull qwen2.5-coder:1.5b
docker exec -it ollama_sandbox ollama pull nomic-embed-text
docker exec -it ollama_sandbox ollama pull moondream:1.8b
docker exec -it ollama_sandbox ollama pull lauchacarro/qwen2.5-translator
```

---

## 📄 Ingesta de Documentos (Modo RAG)

Existen dos formas de cargar documentos `.pdf` o `.txt` en la base vectorial ChromaDB:

* **Directamente desde Telegram (Recomendado):** Adjuntá y enviá cualquier archivo `.pdf` o `.txt` al chat del bot. Arturito lo guardará en `telegram-bot/docs/`, lo fragmentará e indexará automáticamente en ChromaDB.
* **Por línea de comandos (Consola):**
  1. Copiar el archivo dentro de `telegram-bot/docs/`.
  2. Ejecutar el script auxiliar dentro del contenedor:
     ```bash
     docker exec -it telegram_bot_sandbox python ingest.py --file /app/docs/TuDocumento.pdf
     ```

---

## 📊 Mantenimiento y Monitoreo

* **Seguir logs del bot en tiempo real:**
  ```bash
  docker logs -f telegram_bot_sandbox
  ```
* **Consultar historial de mensajes en PostgreSQL:**
  ```bash
  docker exec -it postgres_db_sandbox psql -U bot_user -d telegram_bot_db -c "
  SELECT 
      u.nombre AS estudiante,
      u.username,
      m.mensaje_usuario,
      m.respuesta_bot
  FROM mensajes m
  JOIN usuarios u ON m.telegram_id = u.telegram_id
  ORDER BY m.fecha DESC;"
  ```
* **Limpiar el historial de chat guardado:**
  ```bash
  docker exec -it postgres_db_sandbox psql -U bot_user -d telegram_bot_db -c "TRUNCATE TABLE mensajes;"
  ```
* **Interactuar con el contenedor de Ollama:**
  ```bash
  docker exec -it ollama_sandbox /bin/sh
  ```
* **Cambiar el modelo principal de IA:**
  1. Modificar `MODEL_NAME=` en el archivo `.env` de la raíz por alguno descargado previamente en `ollama_sandbox`.
  2. Recrear el contenedor del bot para tomar la nueva variable:
     ```bash
     docker compose up -d telegram_bot
     ```
* **Detener todos los servicios:**
  ```bash
  docker compose down
  ```