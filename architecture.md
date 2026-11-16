# Arquitectura del Proyecto — Arturito (`R2D2_CloudBot`)

Asistente conversacional y agente autónomo desplegado localmente mediante **Docker Compose**, integrado con **Telegram**, **Ollama**, **ChromaDB** y **PostgreSQL**.

## Estructura de Directorios

```text
.
├── docker-compose.yml       # Orquestación de servicios (Ollama, PostgreSQL y Bot de Telegram)
├── Dockerfile               # Imagen base del entorno Ollama
├── .env                     # Variables de entorno globales (ignoradas en Git)
├── env                      # Plantilla de configuración de entorno
├── architecture.md          # Documentación de la arquitectura del sistema
├── README.md                # Guía de instalación y uso
└── telegram-bot/
    ├── Dockerfile.telegram  # Imagen del contenedor del bot Python
    ├── R2D2_CloudBot.py     # Lógica principal: Agente LangChain, RAG, Visión y Handlers de Telegram
    ├── init.sql             # Esquema inicial de tablas en PostgreSQL (usuarios y mensajes)
    ├── ingest.py            # Script auxiliar de ingesta por consola
    ├── .env                 # Configuración específica del bot (tokens y modelos)
    ├── env                  # Plantilla de variables del bot
    ├── docs/                # Almacenamiento local de PDFs y TXTs cargados para RAG (ignorado en Git)
    ├── chroma_db/           # Base de datos vectorial persistente de ChromaDB (ignorada en Git)
    └── reports/             # Reportes .txt y .csv generados dinámicamente por el agente (ignorado en Git)