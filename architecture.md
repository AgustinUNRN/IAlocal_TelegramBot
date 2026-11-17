# Arquitectura del Proyecto — Arturito (`R2D2_CloudBot`)

Asistente conversacional y agente autónomo desplegado localmente mediante **Docker Compose**, integrado con **Telegram**, **Ollama**, **ChromaDB** y **PostgreSQL**.

## Estructura de Directorios

```text
.
├── architecture.md              # Documentación de la arquitectura del sistema
├── docker-compose.yml           # Orquestación principal (Ollama, PostgreSQL y Bot de Telegram)
├── Dockerfile                   # Imagen base del entorno Ollama (usuario no-root aiuser)
├── entrypoint.sh                # Script de inicio de Ollama y descarga automática de modelos
├── env                          # Plantilla de variables de entorno globales (.env ignorado en Git)
├── README.md                    # Guía de instalación y uso del proyecto
├── ollama_minimalista/          # Entorno aislado minimalista de prueba para Ollama
│   ├── docker-compose.yml
│   └── Dockerfile
└── telegram-bot/
    ├── Dockerfile.telegram      # Imagen del contenedor del bot en Python
    ├── R2D2_CloudBot.py         # Agente LangChain, RAG, pipeline de visión y handlers de Telegram
    ├── init.sql                 # Esquema inicial de tablas en PostgreSQL (usuarios y mensajes)
    ├── ingest.py                # Script auxiliar de ingesta de documentos por consola
    ├── env                      # Plantilla de variables del bot (.env ignorado en Git)
    ├── README.md                # Documentación específica del servicio de Telegram
    ├── docs/                    # [Local / Ignorado en Git] Documentos PDF y TXT indexados en el RAG
    ├── chroma_db/               # [Local / Ignorado en Git] Base de datos vectorial de ChromaDB
    └── reports/                 # [Local / Ignorado en Git] Reportes .txt y .csv generados por el agente
```