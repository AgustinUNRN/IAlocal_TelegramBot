# 🤖 R2D2 CloudBot (Arturito) — Agente IA Local en Docker

Asistente conversacional y **agente autónomo multi-modelo** dockerizado para Telegram, ejecutándose 100% en entorno local sin dependencias de APIs externas en la nube. Integra **Ollama** (`qwen2.5:3b`, `qwen2.5-coder:1.5b`, `moondream:1.8b` y `lauchacarro/qwen2.5-translator`), recuperación aumentada por generación (**RAG**) con **ChromaDB** (`nomic-embed-text`), y persistencia relacional de usuarios e historial en **PostgreSQL**[cite: 6, 7, 8].

---

## 🧠 Capacidades del Agente

A diferencia de un chatbot lineal, **Arturito** utiliza *Tool Calling* (`ChatOllama` + `bind_tools` en LangChain) para razonar sobre cada mensaje y decidir autónomamente qué herramienta o modelo especialista invocar:

1. **💻 Delegación de Programación (`resolver_programacion_codigo`):** Deriva tareas de escritura de código, scripts (Python, SQL, Bash, Java, HTML, etc.), depuración o explicación técnica al modelo especialista **`qwen2.5-coder:1.5b`**[cite: 6].
2. **📚 Consulta de Documentos (`buscar_en_documentos_rag`):** Busca información semántica en los archivos `.pdf` y `.txt` indexados en **ChromaDB** (`nomic-embed-text`).
3. **🗄️ Bitácora Histórica (`buscar_historial_postgresql`):** Consulta conversaciones previas en **PostgreSQL** filtrando estrictamente por el `telegram_id` del usuario activo.
4. **📝 Generación de Reportes (`generar_reporte_archivo`):** Crea archivos descargables (`.txt` o `.csv`) en `/app/reports` y los envía automáticamente como documento adjunto en Telegram[cite: 6, 7].
5. **🖼️ Pipeline Multimodal de Imágenes:** Analiza fotografías enviadas al chat con **`moondream:1.8b`** y traduce la respuesta al español mediante **`lauchacarro/qwen2.5-translator`** (`temperature=0.0`)[cite: 6].
6. **📥 Ingesta Dinámica por Chat:** Permite enviar archivos `.pdf` o `.txt` directamente como documento al bot de Telegram para fragmentarlos (`RecursiveCharacterTextSplitter`) e indexarlos al instante en ChromaDB[cite: 6, 7].

---

## 🏗️ Arquitectura del Sistema

El entorno está orquestado con **Docker Compose** e integra tres servicios aislados en red local (`ai_sandbox_net`):

* **`telegram_bot` (`telegram_bot_sandbox`):** Aplicación en Python (`R2D2_CloudBot.py`) que gestiona los handlers de Telegram, el bucle del agente LangChain, la ingesta de archivos, la generación de reportes y las conexiones con PostgreSQL y ChromaDB[cite: 6, 7].
* **`ollama-isolated` (`ollama_sandbox`):** Servidor local de Ollama que aloja los 5 modelos locales (`qwen2.5:3b`, `qwen2.5-coder:1.5b`, `moondream:1.8b`, `lauchacarro/qwen2.5-translator` y `nomic-embed-text`)[cite: 6, 7, 8].
* **`postgres_db` (`postgres_db_sandbox`):** Base de datos PostgreSQL para el registro y persistencia relacional de usuarios y mensajes[cite: 6, 7].

*(Para ver el árbol de directorios completo, consultá [`architecture.md`](./architecture.md)).*

---

## 🚀 Requisitos Previos

* **Ubuntu / Linux** con [Docker Engine](https://docs.docker.com/engine/install/) y [Docker Compose](https://docs.docker.com/compose/install/) instalados.
* **Token de Telegram Bot** proporcionado por [@BotFather](https://t.me/botfather).

---

## ⚙️ Configuración del Entorno

El proyecto divide las variables de entorno en dos archivos `.env` (ambos ignorados en Git; se incluyen las plantillas `env` como referencia):

### 1. Variables de Modelos e Inferencia (`.env` en la raíz)
Crear `.env` en la raíz del proyecto para configurar Ollama y los modelos utilizados por los contenedores[cite: 7, 8]:

```env
# Configuración de modelos Ollama
MODEL_NAME=qwen2.5:3b
EMBEDDING_MODEL=nomic-embed-text
OLLAMA_HOST=http://ollama_sandbox:11434
VISION_MODEL=moondream:1.8b
TRANSLATOR_MODEL=lauchacarro/qwen2.5-translator
CODER_MODEL=qwen2.5-coder:1.5b
```
### 2 Variables del Bot (telegram-bot/)
1. Ubicarse en el directorio principal e ingresar a la carpeta del bot:
   ```bash
   cd telegram-bot
   ```

2. Crear o editar el archivo .env con las credenciales y configuraciones del entorno:
    ```Bash
    nano .env
    ```
3.  Contenido recomendado del .env:
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

## 🛠️ Despliegue e Inicio de Servicios

Desde la raíz del proyecto (donde reside docker-compose.yml), ejecutar:
    
```Bash
# Construir y levantar la arquitectura en segundo plano
docker compose up -d --build
# Levantar los contenedores en segundo plano
docker compose up -d
```
Nota: La descarga de los modelos ocurre de forma automática durante la etapa de compilación del servicio ollama-isolated utilizando las variables pasadas desde la raíz.

### Verificación de Modelos en Ollama (Primera vez)

Si los modelos no están descargados internamente, ejecutá:
```Bash
docker exec -it ollama_sandbox ollama pull qwen2.5:3b
docker exec -it ollama_sandbox ollama pull qwen2.5-coder:1.5b
docker exec -it ollama_sandbox ollama pull nomic-embed-text
docker exec -it ollama_sandbox ollama pull moondream:1.8b
docker exec -it ollama_sandbox ollama pull lauchacarro/qwen2.5-translator
```

## 📄 Ingesta de Documentos (Modo RAG)

Existen dos formas de cargar documentos .pdf o .txt en la base vectorial ChromaDB

- Directamente desde Telegram (Recomendado): Adjuntá y enviá cualquier archivo .pdf o .txt al chat del bot. Arturito lo guardará en telegram-bot/docs/, lo fragmentará e indexará automáticamente en ChromaDB.

- Por línea de comandos (Consola):

1.  Copiar el archivo dentro de telegram-bot/docs/.

2.  Ejecutar el script auxiliar dentro del contenedor:
    ```Bash
    docker exec -it telegram_bot_sandbox python ingest.py --file /app/docs/TuDocumento.pdf
    ```

## 📊 Mantenimiento y Monitoreo

   * Seguir logs del bot en tiempo real:
        ```Bash
        docker logs -f telegram_bot_sandbox
        ```
    * Consultar historial de mensajes en PostgreSQL:
        ```Bash
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

    * Limpiar el historial de chat guardado:
       ```Bash
       docker exec -it postgres_db_sandbox psql -U bot_user -d telegram_bot_db -c "TRUNCATE TABLE mensajes;"
      ```
    
    * Interactuar con el contenedor de ollama
        ```Bash
        docker exec -it ollama_sandbox /bin/bash
        ```
        
   * Detener los servicios:
       ```Bash
     docker compose down
       ```
   * Cambio de modelo de IA
 
   1. Modificar el archivo `.env` `MODEL_NAME=` por alguno descargado previamente

   2. Aplicar los cambios
        ```Bash
        docker compose up -d telegram_bot
        ```
   3. Detener todos los servicios:
         ```Bash
        docker compose down
        ```

