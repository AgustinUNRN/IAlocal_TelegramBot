import os
import sys
import asyncio
import base64
import httpx
import psycopg2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# Variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama_sandbox:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5:1.5b")
VISION_MODEL = os.getenv("VISION_MODEL", "moondream:latest")
TRANSLATOR_MODEL = os.getenv("TRANSLATOR_MODEL", "lauchacarro/qwen2.5-translator")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
DB_DIR = os.getenv("CHROMA_DB_DIR", "/app/chroma_db")
DOCS_DIR = os.getenv("DOCS_DIR", "/app/docs")
ENABLE_RAG = os.getenv("ENABLE_RAG", "true").lower() in ("true", "1", "yes")

# Configuración PostgreSQL
DB_HOST = os.getenv("DB_HOST", "postgres_db")
DB_NAME = os.getenv("POSTGRES_DB", "arturito_db")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")

# Asegurar que exista el directorio de documentos
os.makedirs(DOCS_DIR, exist_ok=True)


# --- CONEXIÓN Y PERSISTENCIA EN POSTGRES ---
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

def registrar_interaccion_db(user_id, username, first_name, user_message, bot_response):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO usuarios (telegram_id, username, nombre)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_id) 
            DO UPDATE SET username = EXCLUDED.username, nombre = EXCLUDED.nombre;
        """, (user_id, username, first_name))
        
        cur.execute("""
            INSERT INTO mensajes (telegram_id, mensaje_usuario, respuesta_bot)
            VALUES (%s, %s, %s);
        """, (user_id, user_message, bot_response))
        
        conn.commit()
        cur.close()
        conn.close()
        print(f"💾 Interacción de {first_name} ({user_id}) guardada en PostgreSQL.")
    except Exception as e:
        print(f"⚠️ Error al guardar en PostgreSQL: {e}")


def obtener_historial_usuario(user_id, limit=2):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.nombre, m.mensaje_usuario, m.respuesta_bot 
            FROM mensajes m
            JOIN usuarios u ON m.telegram_id = u.telegram_id
            WHERE m.telegram_id = %s 
            ORDER BY m.fecha DESC LIMIT %s;
        """, (user_id, limit))
        filas = cur.fetchall()
        cur.close()
        conn.close()
        
        historial = ""
        for nombre, msg_user, resp_bot in reversed(filas):
            historial += f"{nombre}: {msg_user}\nArturito: {resp_bot}\n"
        return historial
    except Exception as e:
        print(f"⚠️ Error al obtener historial de PostgreSQL: {e}")
        return ""


# --- CONFIGURACIÓN DE MODELOS Y RAG ---
llm = OllamaLLM(model=MODEL_NAME, base_url=OLLAMA_HOST)
embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_HOST)
vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)

if ENABLE_RAG:
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    prompt_tutor = ChatPromptTemplate.from_template(
    "Eres un asistente académico. Responde a la pregunta actual del estudiante basándote EXCLUSIVAMENTE en el 'Contexto oficial' proporcionado abajo.\n"
    "REGLAS:\n"
    "1. Ignora el 'Historial reciente' si trata sobre un tema distinto a la pregunta actual.\n"
    "2. Sintetiza toda la información relevante que encuentres en el 'Contexto oficial'.\n"
    "3. Solo si el 'Contexto oficial' no contiene absolutamente nada relacionado, indica que no figura en el documento.\n\n"
    "Contexto oficial:\n{context}\n\n"
    "Historial reciente (solo referencia):\n{history}\n\n"
    "Pregunta actual de {user_name}: {question}\n"
    "Respuesta:"
)

    rag_chain = (
        {
            "context": (lambda x: x["question"]) | retriever | format_docs,
            "history": lambda x: x["history"],
            "question": lambda x: x["question"],
            "user_name": lambda x: x["user_name"]
        }
        | prompt_tutor
        | llm
        | StrOutputParser()
    )


# --- LÓGICA DE INGESTA RAG (DESDE ingest.py) ---
def indexar_documento_sync(ruta_archivo: str) -> int:
    """Carga, fragmenta e indexa un PDF o TXT en ChromaDB. Devuelve la cantidad de fragmentos."""
    print(f"1. Cargando '{ruta_archivo}'...")
    if ruta_archivo.lower().endswith(".pdf"):
        loader = PyPDFLoader(ruta_archivo)
    elif ruta_archivo.lower().endswith(".txt"):
        loader = TextLoader(ruta_archivo, encoding="utf-8")
    else:
        raise ValueError("Formato no soportado. Usá .pdf o .txt")

    docs = loader.load()

    print("2. Dividiendo en fragmentos...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    splits = text_splitter.split_documents(docs)

    if not splits:
        raise ValueError("El documento no contiene texto extraíble.")

    print(f"3. Guardando {len(splits)} embeddings en '{DB_DIR}'...")
    vectorstore.add_documents(splits)
    print("✅ Indexación completada.")
    return len(splits)


# --- UTILIDADES DE TELEGRAM ---
async def mantener_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    while True:
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING
            )
        except Exception as e:
            print(f"⚠️ No se pudo actualizar el indicador typing: {e}")

        await asyncio.sleep(4)


async def detener_typing(typing_task: asyncio.Task):
    typing_task.cancel()
    try:
        await typing_task
    except asyncio.CancelledError:
        pass


def dividir_texto(texto: str, limite: int = 3900) -> list[str]:
    texto = texto.strip()
    partes = []

    while texto:
        unidades = 0
        corte = 0

        for i, caracter in enumerate(texto):
            peso = 2 if ord(caracter) > 0xFFFF else 1
            if unidades + peso > limite:
                break
            unidades += peso
            corte = i + 1

        if corte == len(texto):
            partes.append(texto)
            break

        corte_espacio = max(
            texto.rfind("\n", 0, corte),
            texto.rfind(" ", 0, corte)
        )
        if corte_espacio > corte // 2:
            corte = corte_espacio

        partes.append(texto[:corte].strip())
        texto = texto[corte:].lstrip()

    return partes or [" "]


async def enviar_respuesta_larga(update: Update, texto: str):
    for parte in dividir_texto(texto):
        await update.message.reply_text(parte)


# --- PIPELINE DE VISIÓN CON TRADUCCIÓN CONDICIONAL ---
async def consultar_modelo_vision(base64_image: str, prompt_usuario: str) -> str:
    url = f"{OLLAMA_HOST}/api/generate"
    consulta = prompt_usuario.strip() if prompt_usuario and prompt_usuario.strip() else "Describe esta imagen en detalle."
    es_moondream = "moondream" in VISION_MODEL.lower()

    if es_moondream:
        prompt_vision = f"Analyze the image and answer this question in detail: {consulta}"
    else:
        prompt_vision = f"Responde a la siguiente consulta sobre la imagen en español: {consulta}"

    payload_vision = {
        "model": VISION_MODEL,
        "prompt": prompt_vision,
        "images": [base64_image],
        "stream": False
    }

    timeout_config = httpx.Timeout(300.0, connect=30.0)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        resp_vision = await client.post(url, json=payload_vision)
        if resp_vision.status_code != 200:
            print(f"❌ Error Ollama API Vision ({resp_vision.status_code}): {resp_vision.text}")
            resp_vision.raise_for_status()

        respuesta_raw = resp_vision.json().get("response", "").strip()
        if not respuesta_raw:
            return "No logré extraer una respuesta clara de esta imagen."

        if not es_moondream:
            print(f"👁️ Visión Directa ({VISION_MODEL}): {respuesta_raw}")
            return respuesta_raw

        print(f"👁️ Moondream (EN): {respuesta_raw}")
        prompt_traduccion = (
            f"Translate the following text to Spanish considering the user request: '{consulta}'.\n"
            f"Text to translate: {respuesta_raw}\n"
            f"Spanish translation:"
        )

        payload_traduccion = {
            "model": TRANSLATOR_MODEL,
            "prompt": prompt_traduccion,
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 0.1}
        }

        resp_trad = await client.post(url, json=payload_traduccion)
        if resp_trad.status_code == 200:
            traduccion = resp_trad.json().get("response", "").strip()
            print(f"🌐 Traducción (ES): {traduccion}")
            return traduccion

        return respuesta_raw


# --- HANDLER PARA DOCUMENTOS PDF / TXT (INGESTA RAG) ---
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return

    doc = update.message.document
    nombre_archivo = doc.file_name or "documento.pdf"

    if not nombre_archivo.lower().endswith((".pdf", ".txt")):
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or "Estudiante"

    mensaje_estado = await update.message.reply_text(
        f"📥 Recibido `{nombre_archivo}`. Descargando e indexando en la base de conocimiento RAG... ⏳",
        parse_mode="Markdown"
    )

    typing_task = asyncio.create_task(
        mantener_typing(context, update.effective_chat.id)
    )

    ruta_destino = os.path.join(DOCS_DIR, nombre_archivo)

    try:
        # 1. Descargar archivo desde Telegram a /app/docs/
        telegram_file = await doc.get_file()
        await telegram_file.download_to_drive(ruta_destino)

        # 2. Ejecutar la ingesta en un hilo separado para no bloquear el bot
        cantidad_chunks = await asyncio.to_thread(indexar_documento_sync, ruta_destino)

        reply = (
            f"✅ Documento *{nombre_archivo}* indexado correctamente en el RAG.\n"
            f"• Fragmentos generados: `{cantidad_chunks}`\n"
            f"• Ya podés hacerme preguntas sobre su contenido."
        )

    except Exception as e:
        reply = f"❌ Error al indexar `{nombre_archivo}`: {e}"
        print(f"❌ Error en handle_document: {e}")

    finally:
        await detener_typing(typing_task)

    # Registrar acción en PostgreSQL
    await asyncio.to_thread(
        registrar_interaccion_db,
        user_id,
        username,
        first_name,
        f"[INGESTA RAG] {nombre_archivo}",
        reply
    )

    try:
        await mensaje_estado.edit_text(reply, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(reply)


# --- HANDLER PARA TEXTO (QWEN 2.5) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or "Estudiante"
    user_message = update.message.text.strip().replace('"', "")

    typing_task = asyncio.create_task(
        mantener_typing(context, update.effective_chat.id)
    )

    try:
        historial = await asyncio.to_thread(
            obtener_historial_usuario, user_id, 3
        )

        if ENABLE_RAG:
            reply = await asyncio.to_thread(
                rag_chain.invoke,
                {
                    "question": user_message,
                    "history": historial,
                    "user_name": first_name
                }
            )
        else:
            prompt_final = (
                f"Historial previo de la conversación:\n{historial}\n"
                f"Usuario: {first_name} Mensaje: {user_message}\n"
                "Respuesta:"
            )
            reply = await asyncio.to_thread(llm.invoke, prompt_final)

    except Exception as e:
        reply = "Error al procesar la consulta 😢"
        print(f"❌ Error LLM: {e}")

    finally:
        await detener_typing(typing_task)

    reply = str(reply).strip() or "No pude generar una respuesta."

    await asyncio.to_thread(
        registrar_interaccion_db,
        user_id,
        username,
        first_name,
        user_message,
        reply
    )

    await enviar_respuesta_larga(update, reply)


# --- HANDLER PARA FOTOS ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    es_imagen = (
        update.message.photo
        or (
            update.message.document
            and update.message.document.mime_type
            and update.message.document.mime_type.startswith("image/")
        )
    )
    if not es_imagen:
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or "Estudiante"

    caption_usuario = update.message.caption
    if caption_usuario and caption_usuario.strip():
        prompt_vision = caption_usuario.strip()
        user_message_log = f"[FOTO CON DESCRIPCIÓN] {prompt_vision}"
    else:
        prompt_vision = "Describe esta imagen en detalle."
        user_message_log = "[FOTO SIN DESCRIPCIÓN]"

    mensaje_estado = await update.message.reply_text(
        "🔎 Analizando la imagen… Puede tardar hasta 2 minutos."
    )

    typing_task = asyncio.create_task(
        mantener_typing(context, update.effective_chat.id)
    )

    try:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        else:
            photo_file = await update.message.document.get_file()

        photo_bytes = await photo_file.download_as_bytearray()
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        reply = await consultar_modelo_vision(
            base64_image,
            prompt_vision
        )

    except Exception as e:
        reply = "Ocurrió un error al procesar la imagen 🖼️"
        print(f"❌ Error en handle_photo: {e}")

    finally:
        await detener_typing(typing_task)

    reply_final = (
        str(reply).strip()
        if reply and str(reply).strip()
        else "No pude procesar el contenido de la imagen."
    )

    await asyncio.to_thread(
        registrar_interaccion_db,
        user_id,
        username,
        first_name,
        user_message_log,
        reply_final
    )

    partes = dividir_texto(reply_final)

    try:
        await mensaje_estado.edit_text(partes[0])
    except Exception as e:
        print(f"⚠️ No se pudo editar el mensaje de estado: {e}")
        await update.message.reply_text(partes[0])

    for parte in partes[1:]:
        await update.message.reply_text(parte)


if __name__ == "__main__":
    print(f"✨ Bot activado | Modo RAG: {'ACTIVADO' if ENABLE_RAG else 'DESACTIVADO (Modo Rápido)'}")
    print(f"🧠 Texto: {MODEL_NAME} | 🌐 Traductor: {TRANSLATOR_MODEL} | 👁️ Visión: {VISION_MODEL}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # 1. Documentos PDF / TXT para ingesta RAG
    app.add_handler(MessageHandler(filters.Document.PDF | filters.Document.TXT, handle_document))
    # 2. Imágenes comprimidas o archivos de imagen
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    # 3. Mensajes de texto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()