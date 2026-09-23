import os
import sys
import asyncio
import psycopg2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

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
        
        # 1. Registrar o actualizar usuario
        cur.execute("""
            INSERT INTO usuarios (telegram_id, username, nombre)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_id) 
            DO UPDATE SET username = EXCLUDED.username, nombre = EXCLUDED.nombre;
        """, (user_id, username, first_name))
        
        # 2. Guardar mensaje del usuario y respuesta del bot
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
        # Trae el nombre de la tabla usuarios y las intervenciones
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
        
        # Formatear el historial con el nombre real del estudiante
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

# --- HANDLER PRINCIPAL ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or "Estudiante"
    user_message = update.message.text.strip().replace('"', '')

    # 1. Recuperar historial de los últimos 3 mensajes desde Postgres
    historial = await asyncio.to_thread(obtener_historial_usuario, user_id, 3)

    try:
        if ENABLE_RAG:
            docs_recuperados = retriever.invoke(user_message)
            contexto_formateado = format_docs(docs_recuperados)
            
            prompt_final = prompt_tutor.format(
                history=historial,
                context=contexto_formateado,
                question=user_message,
                user_name=first_name
            )
            
            reply = await asyncio.to_thread(
                rag_chain.invoke, 
                {"question": user_message, "history": historial, "user_name": first_name}
            )
        else:
            prompt_final = (
                f"Historial previo de la conversación:\n{historial}\n"
                f"Usuario: {first_name} Mensaje: {user_message}\n"
                f"Respuesta:"
            )
            reply = await asyncio.to_thread(llm.invoke, prompt_final)

        # 🔍 IMPRIMIR EL PROMPT QUE LLEGA A QWEN
        print("\n" + "="*20 + " PROMPT QUE RECIBE QWEN " + "="*20)
        print(prompt_final)
        print("="*64 + "\n")

    except Exception as e:
        reply = "Error al procesar la consulta 😢"
        print(f"❌ Error LLM: {e}")

    # 2. Guardar la nueva interacción en la BD
    await asyncio.to_thread(registrar_interaccion_db, user_id, username, first_name, user_message, reply)

    await update.message.reply_text(reply)

if __name__ == "__main__":
    print(f"✨ Bot activado | Modo RAG: {'ACTIVADO' if ENABLE_RAG else 'DESACTIVADO (Modo Rápido)'}")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()