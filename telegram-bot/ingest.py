import os
import argparse
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

DB_DIR = os.getenv("CHROMA_DB_DIR", "/app/chroma_db")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

def obtener_embeddings():
    return OllamaEmbeddings(model=EMBEDDING_MODEL, base_url=OLLAMA_HOST)

def cargar_documento(ruta):
    if ruta.endswith(".pdf"):
        loader = PyPDFLoader(ruta)
    elif ruta.endswith(".txt"):
        loader = TextLoader(ruta, encoding="utf-8")
    else:
        raise ValueError("Formato no soportado. Usá .pdf o .txt")
    return loader.load()

def indexar_documento(ruta_archivo):
    print(f"1. Cargando '{ruta_archivo}'...")
    docs = cargar_documento(ruta_archivo)

    print("2. Dividiendo en fragmentos...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)
    splits = text_splitter.split_documents(docs)

    print(f"3. Guardando embeddings en '{DB_DIR}'...")
    embeddings = obtener_embeddings()
    
    vectorstore = Chroma(
        persist_directory=DB_DIR,
        embedding_function=embeddings
    )
    vectorstore.add_documents(splits)
    print("✅ Indexación completada.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=True, help="Ruta al archivo PDF/TXT")
    args = parser.parse_args()
    indexar_documento(args.file)
