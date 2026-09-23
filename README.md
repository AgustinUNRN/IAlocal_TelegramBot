

# 🤖 R2D2 CloudBot (Arturito) - IA Local En Docker

Asistente conversacional dockerizado para Telegram. Implementa arquitectura local de LLM con **Ollama** (`qwen2.5:1.5b`), recuperación aumentada por generación (**RAG**) sobre documentos mediante **ChromaDB**, y persistencia relacional de usuarios e historial de chat en **PostgreSQL**.

---

## 🏗️ Arquitectura del Sistema

El entorno está orquestado con **Docker Compose** e integra tres servicios aislados en red local (`ai_sandbox_net`):

* **`telegram_bot`**: Aplicación en Python que ejecuta el handler de Telegram, orquesta las cadenas de LangChain y gestiona las conexiones con PostgreSQL y ChromaDB.
* **`ollama-isolated`**: Servidor local de Ollama que expone el modelo LLM (`qwen2.5:1.5b`) y los embeddings (`nomic-embed-text`).
* **`postgres_db`**: Base de datos PostgreSQL para el registro y persistencia relacional de estudiantes y mensajes.

---

## 🚀 Requisitos Previos

* **Ubuntu / Linux** con [Docker Engine](https://docs.docker.com/engine/install/) y [Docker Compose](https://docs.docker.com/compose/install/) instalados.
* **Token de Telegram Bot** proporcionado por [@BotFather](https://t.me/botfather).

---

## ⚙️ Configuración del Entorno

El proyecto utiliza una estructura de variables de entorno dividida entre la raíz y la subcarpeta del bot.

### 1. Variables Globales (Raíz)
Crear el archivo `.env` en la raíz del proyecto para definir infraestructura y modelos:

```env
# Modelos de Ollama
MODEL_NAME=qwen2.5:1.5b
EMBEDDING_MODEL=nomic-embed-text

# Configuración PostgreSQL
POSTGRES_DB=telegram_bot_db
POSTGRES_USER=bot_user
POSTGRES_PASSWORD=bot_password_segura
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

    # Persistencia PostgreSQL
    DB_HOST=postgres_db_sandbox
    POSTGRES_DB=telegram_bot_db
    POSTGRES_USER=bot_user
    POSTGRES_PASSWORD=bot_password_segura

    # Configuración de Modo
    ENABLE_RAG=false
    CHROMA_DB_DIR=/app/chroma_db
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
docker exec -it ollama_sandbox ollama pull qwen2.5:1.5b
docker exec -it ollama_sandbox ollama pull nomic-embed-text
```

## 📄 Ingesta de Documentos (Modo RAG)

Para alimentar la base vectorial con reglamentos o archivos PDF/TXT institucionales:

1.  Colocar los archivos PDF dentro de telegram-bot/docs/.

2.  Ejecutar el script de ingesta dentro del contenedor:
    ```Bash
    docker exec -it telegram_bot_sandbox python ingest.py --file /app/docs/TuDocumento.pdf
    ```

3.  Activar RAG cambiando ENABLE_RAG=true en el .env y reiniciando el servicio:
    ```Bash
    docker compose up -d telegram_bot
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

