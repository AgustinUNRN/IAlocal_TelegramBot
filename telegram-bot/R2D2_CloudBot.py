import os
import sys
import csv
import asyncio
import base64
import httpx
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# Variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama_sandbox:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5:3b")
VISION_MODEL = os.getenv("VISION_MODEL", "moondream:1.8b")
TRANSLATOR_MODEL = os.getenv("TRANSLATOR_MODEL", "lauchacarro/qwen2.5-translator")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
DB_DIR = os.getenv("CHROMA_DB_DIR", "/app/chroma_db")
DOCS_DIR = os.getenv("DOCS_DIR", "/app/docs")
REPORTS_DIR = os.getenv("REPORTS_DIR", "/app/reports")
ENABLE_RAG = os.getenv("ENABLE_RAG", "true").lower() in ("true", "1", "yes")
CODER_MODEL = os.getenv("CODER_MODEL", "qwen2.5-coder:1.5b")

# Configuración PostgreSQL
DB_HOST = os.getenv("DB_HOST", "postgres_db")
DB_NAME = os.getenv("POSTGRES_DB", "arturito_db")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")

os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


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


# --- CONFIGURACIÓN DE EMBEDDINGS Y CHROMADB ---
embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_HOST)
vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
retriever = vectorstore.as_retriever(search_kwargs={"k": 4})


def indexar_documento_sync(ruta_archivo: str) -> int:
    print(f"1. Cargando '{ruta_archivo}'...")
    if ruta_archivo.lower().endswith(".pdf"):
        loader = PyPDFLoader(ruta_archivo)
    elif ruta_archivo.lower().endswith(".txt"):
        loader = TextLoader(ruta_archivo, encoding="utf-8")
    else:
        raise ValueError("Formato no soportado. Usá .pdf o .txt")

    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    splits = text_splitter.split_documents(docs)

    if not splits:
        raise ValueError("El documento no contiene texto extraíble.")

    vectorstore.add_documents(splits)
    print(f"✅ Indexados {len(splits)} fragmentos.")
    return len(splits)


# --- DEFINICIÓN DE HERRAMIENTAS DEL AGENTE (@tool) ---
def construir_herramientas_usuario(user_id: int, archivos_generados: list[str]):
    """Crea las herramientas vinculadas al contexto del usuario actual."""

    @tool
    def resolver_programacion_codigo(tarea_codigo: str) -> str:
        """Delega tareas de programación, generación de scripts (Python, SQL, Bash, Java, HTML, etc.), depuración de errores o explicación técnica de código a un modelo especializado en programación."""
        prompt_coder = (
            "Eres un ingeniero de software experto. Resuelve la siguiente solicitud de programación "
            "en español de forma clara, directa y con código bien estructurado:\n\n"
            f"{tarea_codigo}"
        )
        respuesta = llm_coder.invoke(prompt_coder)
        return str(respuesta.content).strip()

    @tool
    def buscar_en_documentos_rag(consulta: str) -> str:
        """Busca información técnica, normativa o académica dentro de los documentos PDF y TXT cargados en la base de conocimiento."""
        if not ENABLE_RAG:
            return "El módulo de documentos RAG está desactivado actualmente."
        docs = retriever.invoke(consulta)
        if not docs:
            return "No se encontraron fragmentos relevantes en los documentos cargados."
        return "\n\n---\n\n".join(
            f"[Fuente: {os.path.basename(d.metadata.get('source', 'doc'))}]\n{d.page_content}"
            for d in docs
        )

    @tool
    def buscar_historial_postgresql(palabra_clave: str = "") -> str:
        """Busca en el historial de conversaciones pasadas del usuario en PostgreSQL. Si se indica palabra_clave filtra por ella; si se deja vacía devuelve los últimos mensajes recientes."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            clave = (palabra_clave or "").strip()
            if clave:
                cur.execute("""
                    SELECT fecha, mensaje_usuario, respuesta_bot
                    FROM mensajes
                    WHERE telegram_id = %s
                      AND (mensaje_usuario ILIKE %s OR respuesta_bot ILIKE %s)
                    ORDER BY fecha DESC
                    LIMIT 6;
                """, (user_id, f"%{clave}%", f"%{clave}%"))
            else:
                cur.execute("""
                    SELECT fecha, mensaje_usuario, respuesta_bot
                    FROM mensajes
                    WHERE telegram_id = %s
                    ORDER BY fecha DESC
                    LIMIT 8;
                """, (user_id,))
            filas = cur.fetchall()
            cur.close()
            conn.close()

            if not filas:
                return (
                    f"No se encontraron registros previos con '{clave}'."
                    if clave
                    else "Aún no hay mensajes previos registrados en el historial."
                )

            resultado = []
            for fecha, msg_u, resp_b in filas:
                fecha_str = fecha.strftime("%d/%m/%Y %H:%M")
                resultado.append(f"[{fecha_str}] Usuario: {msg_u} | Arturito: {resp_b[:250]}...")
            return "\n".join(resultado)
        except Exception as e:
            return f"Error al consultar PostgreSQL: {e}"
    @tool
    def exportar_historial_postgresql(formato: str = "csv") -> str:
        """Exporta el historial completo de conversaciones del usuario desde PostgreSQL directamente a un archivo descargable .csv o .txt."""
        ext = "csv" if formato.lower().strip(".") == "csv" else "txt"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_archivo = os.path.join(REPORTS_DIR, f"historial_chat_{timestamp}.{ext}")

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT fecha, mensaje_usuario, respuesta_bot
                FROM mensajes
                WHERE telegram_id = %s
                ORDER BY fecha ASC;
            """, (user_id,))
            filas = cur.fetchall()
            cur.close()
            conn.close()

            if not filas:
                return "No hay mensajes registrados en PostgreSQL para exportar."

            if ext == "csv":
                with open(ruta_archivo, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["fecha", "mensaje_usuario", "respuesta_bot"])
                    for fecha, msg_u, resp_b in filas:
                        writer.writerow([
                            fecha.strftime("%Y-%m-%d %H:%M:%S"),
                            msg_u,
                            resp_b
                        ])
            else:
                with open(ruta_archivo, "w", encoding="utf-8") as f:
                    f.write("=== HISTORIAL COMPLETO DE CONVERSACIONES ===\n\n")
                    for fecha, msg_u, resp_b in filas:
                        f.write(f"[{fecha.strftime('%d/%m/%Y %H:%M:%S')}]\n")
                        f.write(f"Usuario: {msg_u}\n")
                        f.write(f"Arturito: {resp_b}\n")
                        f.write("-" * 50 + "\n")

            archivos_generados.append(ruta_archivo)
            return f"Historial exportado con {len(filas)} registros en '{os.path.basename(ruta_archivo)}'. Se adjuntará automáticamente."
        except Exception as e:
            return f"Error al exportar el historial: {e}"

    @tool
    def generar_reporte_archivo(titulo: str, contenido: str, formato: str = "txt") -> str:
        """Genera un archivo descargable (.txt o .csv) con un resumen, informe o tabla solicitada por el usuario para enviarlo por Telegram."""
        ext = "csv" if formato.lower().strip(".") == "csv" else "txt"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_limpio = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in titulo)[:30]
        ruta_archivo = os.path.join(REPORTS_DIR, f"{nombre_limpio}_{timestamp}.{ext}")

        try:
            if ext == "csv":
                with open(ruta_archivo, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for linea in contenido.strip().splitlines():
                        writer.writerow([col.strip() for col in linea.split(",")])
            else:
                with open(ruta_archivo, "w", encoding="utf-8") as f:
                    f.write(f"=== {titulo.upper()} ===\n")
                    f.write(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n")
                    f.write(contenido.strip() + "\n")

            archivos_generados.append(ruta_archivo)
            return f"Archivo '{os.path.basename(ruta_archivo)}' generado con éxito. Se adjuntará automáticamente en el chat."
        except Exception as e:
            return f"No se pudo crear el archivo: {e}"

    return [
        resolver_programacion_codigo,
        buscar_en_documentos_rag,
        buscar_historial_postgresql,
        exportar_historial_postgresql,
        generar_reporte_archivo
    ]


# --- BUCLE DE EJECUCIÓN DEL AGENTE ---
llm_chat = ChatOllama(model=MODEL_NAME, base_url=OLLAMA_HOST, temperature=0.2)
llm_coder = ChatOllama(model=CODER_MODEL, base_url=OLLAMA_HOST, temperature=0.1)


async def ejecutar_agente(
    update: Update,
    user_id: int,
    first_name: str,
    user_message: str
) -> tuple[str, list[str]]:
    archivos_generados: list[str] = []
    herramientas = construir_herramientas_usuario(user_id, archivos_generados)
    mapa_herramientas = {t.name: t for t in herramientas}
    llm_con_tools = llm_chat.bind_tools(herramientas)

    palabras_codigo = (
        "python", "sql", "bash", "java", "javascript", "html", "css", "c++",
        "código", "codigo", "script", "función", "funcion", "algoritmo",
        "programá", "programa", "programar", "debug", "depurar", "query", "consulta sql"
    )
    msg_lower = user_message.lower()
    if any(p in msg_lower for p in palabras_codigo) and not any(x in msg_lower for x in ("historial", "conversaciones", "bitácora", "archivo", ".txt", ".csv")):
        aviso = f"💻 Delegando tarea de código a {CODER_MODEL}..."
        print(f"🤖 Agente invoca -> resolver_programacion_codigo({{'tarea_codigo': {user_message!r}}})")
        await update.message.reply_text(aviso)
        resultado_coder = await asyncio.to_thread(
            mapa_herramientas["resolver_programacion_codigo"].invoke,
            {"tarea_codigo": user_message}
        )
        return str(resultado_coder).strip(), archivos_generados

    archivos_cargados = [f for f in os.listdir(DOCS_DIR) if f.lower().endswith((".pdf", ".txt"))]
    lista_docs = ", ".join(archivos_cargados) if archivos_cargados else "ninguno"

    system_prompt = SystemMessage(content=(
        f"Eres Arturito, un agente orquestador en español para {first_name}.\n"
        f"Archivos cargados en la base de conocimiento: [{lista_docs}].\n"
        "REGLAS ESTRICTAS DE DELEGACIÓN:\n"
        "- NO tienes permitido escribir código fuente por tu cuenta. Ante cualquier pedido de programación, scripts, funciones o SQL, DEBES invocar la herramienta de programación.\n"
        "- NO tienes permitido responder sobre el contenido de los documentos por memoria propia. Ante cualquier pregunta sobre los archivos cargados, DEBES invocar la herramienta de búsqueda en documentos.\n"
        "- Si te piden exportar o crear un archivo .txt o .csv, DEBES invocar la herramienta de generación de reportes.\n"
        "- Si te piden exportar o descargar el historial de conversaciones, DEBES invocar la herramienta exportar_historial_postgresql.\n"
        "- Si te piden recordar conversaciones anteriores, DEBES invocar la herramienta de historial.\n"
        "- Solo responde directamente sin herramientas si te saludan o preguntan qué archivos hay cargados.\n"
        "- Nunca menciones nombres de herramientas ni pidas al usuario que las ejecute."
    ))

    mensajes = [system_prompt, HumanMessage(content=user_message)]

    for _ in range(3):
        respuesta_ai = await asyncio.to_thread(llm_con_tools.invoke, mensajes)
        mensajes.append(respuesta_ai)

        if not respuesta_ai.tool_calls:
            return str(respuesta_ai.content).strip(), archivos_generados

        for tool_call in respuesta_ai.tool_calls:
            nombre_tool = tool_call["name"]
            args_tool = tool_call["args"]
            call_id = tool_call["id"]

            etiquetas = {
                "resolver_programacion_codigo": f"💻 Delegando tarea de código a {CODER_MODEL}...",
                "buscar_en_documentos_rag": "📚 Buscando en documentos RAG...",
                "buscar_historial_postgresql": "🗄️ Consultando bitácora en PostgreSQL...",
                "exportar_historial_postgresql": "🗄️ Exportando historial de PostgreSQL...",
                "generar_reporte_archivo": "📝 Generando archivo de reporte..."
            }
            aviso = etiquetas.get(nombre_tool, f"⚙️ Ejecutando {nombre_tool}...")
            print(f"🤖 Agente invoca -> {nombre_tool}({args_tool})")
            await update.message.reply_text(aviso)

            if nombre_tool in mapa_herramientas:
                resultado_tool = await asyncio.to_thread(
                    mapa_herramientas[nombre_tool].invoke,
                    args_tool
                )
            else:
                resultado_tool = f"Herramienta desconocida: {nombre_tool}"

            mensajes.append(ToolMessage(content=str(resultado_tool), tool_call_id=call_id))

    respuesta_final = await asyncio.to_thread(llm_chat.invoke, mensajes)
    return str(respuesta_final.content).strip(), archivos_generados


# --- UTILIDADES DE TELEGRAM ---
async def mantener_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    while True:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
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
        corte_espacio = max(texto.rfind("\n", 0, corte), texto.rfind(" ", 0, corte))
        if corte_espacio > corte // 2:
            corte = corte_espacio
        partes.append(texto[:corte].strip())
        texto = texto[corte:].lstrip()
    return partes or [" "]


async def enviar_respuesta_larga(update: Update, texto: str):
    for parte in dividir_texto(texto):
        await update.message.reply_text(parte)


# --- PIPELINE DE VISIÓN ---
async def consultar_modelo_vision(base64_image: str, prompt_usuario: str) -> str:
    url = f"{OLLAMA_HOST}/api/generate"
    consulta = prompt_usuario.strip() if prompt_usuario and prompt_usuario.strip() else "Describe esta imagen en detalle."
    es_moondream = "moondream" in VISION_MODEL.lower()

    prompt_vision = (
        f"Analyze the image and answer this question in detail: {consulta}"
        if es_moondream
        else f"Responde a la siguiente consulta sobre la imagen en español: {consulta}"
    )

    payload_vision = {
        "model": VISION_MODEL,
        "prompt": prompt_vision,
        "images": [base64_image],
        "stream": False
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        resp_vision = await client.post(url, json=payload_vision)
        resp_vision.raise_for_status()
        respuesta_raw = resp_vision.json().get("response", "").strip()
        if not respuesta_raw:
            return "No logré extraer una respuesta clara de esta imagen."

        if not es_moondream:
            return respuesta_raw

        prompt_traduccion = (
            f"Translate the following text to Spanish considering the user request: '{consulta}'.\n"
            f"Text to translate: {respuesta_raw}\n"
            f"Spanish translation:"
        )
        resp_trad = await client.post(url, json={
            "model": TRANSLATOR_MODEL,
            "prompt": prompt_traduccion,
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 0.1}
        })
        if resp_trad.status_code == 200:
            return resp_trad.json().get("response", "").strip()
        return respuesta_raw


# --- HANDLERS ---
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return

    doc = update.message.document
    nombre_archivo = doc.file_name or "documento.pdf"
    if not nombre_archivo.lower().endswith((".pdf", ".txt")):
        return

    user = update.message.from_user
    mensaje_estado = await update.message.reply_text(
        f"📥 Recibido {nombre_archivo}. Indexando en la base de conocimiento RAG... ⏳"
    )
    typing_task = asyncio.create_task(mantener_typing(context, update.effective_chat.id))
    ruta_destino = os.path.join(DOCS_DIR, nombre_archivo)

    try:
        telegram_file = await doc.get_file()
        await telegram_file.download_to_drive(ruta_destino)
        cantidad_chunks = await asyncio.to_thread(indexar_documento_sync, ruta_destino)
        reply = (
            f"✅ Documento {nombre_archivo} indexado correctamente en el RAG.\n"
            f"• Fragmentos generados: {cantidad_chunks}\n"
            f"• Ya podés pedirme consultas o reportes sobre su contenido."
        )
    except Exception as e:
        reply = f"❌ Error al indexar {nombre_archivo}: {e}"
    finally:
        await detener_typing(typing_task)

    await asyncio.to_thread(
        registrar_interaccion_db,
        user.id,
        user.username or "",
        user.first_name or "Estudiante",
        f"[INGESTA RAG] {nombre_archivo}",
        reply
    )
    await mensaje_estado.edit_text(reply)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or "Estudiante"
    user_message = update.message.text.strip()

    typing_task = asyncio.create_task(mantener_typing(context, update.effective_chat.id))
    archivos_adjuntos: list[str] = []

    try:
        reply, archivos_adjuntos = await ejecutar_agente(update, user_id, first_name, user_message)
    except Exception as e:
        reply = "Ocurrió un error al ejecutar el agente 😢"
        print(f"❌ Error Agente: {e}")
    finally:
        await detener_typing(typing_task)

    reply = reply or "No pude generar una respuesta."

    await asyncio.to_thread(
        registrar_interaccion_db, user_id, username, first_name, user_message, reply
    )

    await enviar_respuesta_larga(update, reply)

    for ruta_archivo in archivos_adjuntos:
        if os.path.exists(ruta_archivo):
            with open(ruta_archivo, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=os.path.basename(ruta_archivo),
                    caption="📎 Reporte generado por el agente."
                )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    es_imagen = update.message.photo or (
        update.message.document
        and update.message.document.mime_type
        and update.message.document.mime_type.startswith("image/")
    )
    if not es_imagen:
        return

    user = update.message.from_user
    caption_usuario = update.message.caption
    prompt_vision = caption_usuario.strip() if caption_usuario and caption_usuario.strip() else "Describe esta imagen en detalle."
    user_message_log = f"[FOTO] {prompt_vision}"

    mensaje_estado = await update.message.reply_text("🔎 Analizando la imagen…")
    typing_task = asyncio.create_task(mantener_typing(context, update.effective_chat.id))

    try:
        photo_file = await (update.message.photo[-1].get_file() if update.message.photo else update.message.document.get_file())
        photo_bytes = await photo_file.download_as_bytearray()
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")
        reply = await consultar_modelo_vision(base64_image, prompt_vision)
    except Exception as e:
        reply = "Ocurrió un error al procesar la imagen 🖼️"
        print(f"❌ Error en handle_photo: {e}")
    finally:
        await detener_typing(typing_task)

    await asyncio.to_thread(
        registrar_interaccion_db,
        user.id,
        user.username or "",
        user.first_name or "Estudiante",
        user_message_log,
        reply
    )

    partes = dividir_texto(reply)
    await mensaje_estado.edit_text(partes[0])
    for parte in partes[1:]:
        await update.message.reply_text(parte)


if __name__ == "__main__":
    print(f"✨ Bot Agente activado | Modelo: {MODEL_NAME} | Coder: {CODER_MODEL} | RAG: {ENABLE_RAG} | Visión: {VISION_MODEL}")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.Document.PDF | filters.Document.TXT, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()