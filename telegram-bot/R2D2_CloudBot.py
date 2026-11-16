import os
import sys
import asyncio
import base64
import httpx
import psycopg2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction # para simular la accion de escribir 'Escribiendo...'

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

# Variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama_sandbox:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5:1.5b")
VISION_MODEL = os.getenv("VISION_MODEL", "moondream:latest")
TRANSLATOR_MODEL = os.getenv("TRANSLATOR_MODEL", "lauchacarro/qwen2.5-translator")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
DB_DIR = os.getenv("CHROMA_DB_DIR", "/app/chroma_db")
ENABLE_RAG = os.getenv("ENABLE_RAG", "true").lower() in ("true", "1", "yes")

# Configuración PostgreSQL
DB_HOST = os.getenv("DB_HOST", "postgres_db")
DB_NAME = os.getenv("POSTGRES_DB", "arturito_db")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")


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


def obtener_historial_usuario(user_id, limit=3):
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

if ENABLE_RAG:
    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_HOST)
    vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    prompt_tutor = ChatPromptTemplate.from_template(
        "Historial reciente de la conversación:\n{history}\n\n"
        "Responde a la pregunta basándote EXCLUSIVAMENTE en el siguiente contexto oficial.\n"
        "Si la respuesta no está en el contexto, indica que no la tienes y sugiere consultar en Secretaría Académica.\n\n"
        "Contexto oficial:\n{context}\n\n"
        "Estudiante ({user_name}): {question}\n"
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


# --- PIPELINE DE VISIÓN Y TRADUCCIÓN DEDICADA ---
async def consultar_moondream_con_traductor(base64_image: str, prompt_usuario: str) -> str:
    url = f"{OLLAMA_HOST}/api/generate"
    consulta = prompt_usuario.strip() if prompt_usuario and prompt_usuario.strip() else "Describe esta imagen en detalle."
    
    # 1. Análisis con Moondream en inglés
    payload_vision = {
        "model": VISION_MODEL,
        "prompt": f"Analyze the image and answer this question in detail: {consulta}",
        "images": [base64_image],
        "stream": False
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp_vision = await client.post(url, json=payload_vision)
        if resp_vision.status_code != 200:
            print(f"❌ Error Ollama API Vision ({resp_vision.status_code}): {resp_vision.text}")
            resp_vision.raise_for_status()
            
        desc_ingles = resp_vision.json().get("response", "").strip()
        if not desc_ingles:
            print("⚠️ Moondream devolvió una respuesta vacía.")
            return "No logré extraer una respuesta clara de esta imagen."
            
        print(f"👁️ Moondream (EN): {desc_ingles}")

        # 2. Traducción con modelo dedicado y Temperatura 0.0
        prompt_traduccion = (
            f"Translate the following text to Spanish considering the user request: '{consulta}'.\n"
            f"Text to translate: {desc_ingles}\n"
            f"Spanish translation:"
        )

        payload_traduccion = {
            "model": TRANSLATOR_MODEL,
            "prompt": prompt_traduccion,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "top_p": 0.1
            }
        }

        resp_trad = await client.post(url, json=payload_traduccion)
        if resp_trad.status_code == 200:
            traduccion = resp_trad.json().get("response", "").strip()
            print(f"🌐 Traducción (ES): {traduccion}")
            return traduccion
            
        return desc_ingles


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
            # La cadena hace la recuperación; no llames antes a retriever.invoke().
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

def dividir_texto(texto: str, limite: int = 3900) -> list[str]:
    """Divide texto en partes seguras para Telegram, respetando emojis."""
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

        # Si se puede, corta en un salto de línea o espacio.
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


async def detener_typing(typing_task: asyncio.Task):
    typing_task.cancel()
    try:
        await typing_task
    except asyncio.CancelledError:
        pass


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
        prompt_moondream = caption_usuario.strip()
        user_message_log = f"[FOTO CON DESCRIPCIÓN] {prompt_moondream}"
    else:
        prompt_moondream = "Describe esta imagen en detalle."
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

        reply = await consultar_moondream_con_traductor(
            base64_image,
            prompt_moondream
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

    # Registrar una sola vez.
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

    # Si la respuesta ocupa más de un mensaje, enviar las partes restantes.
    for parte in partes[1:]:
        await update.message.reply_text(parte)



if __name__ == "__main__":
    print(f"✨ Bot activado | Modo RAG: {'ACTIVADO' if ENABLE_RAG else 'DESACTIVADO (Modo Rápido)'}")
    print(f"🧠 Texto: {MODEL_NAME} | 🌐 Traductor: {TRANSLATOR_MODEL} | 👁️ Visión: {VISION_MODEL}")
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()