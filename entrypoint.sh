#!/bin/sh
set -e

ollama serve &
SERVER_PID=$!

echo "⏳ Esperando a que el servidor Ollama inicie..."
until ollama list >/dev/null 2>&1; do
    sleep 2
done

MODELOS="
${MODEL_NAME:-qwen2.5:3b}
${CODER_MODEL:-qwen2.5-coder:1.5b}
${EMBEDDING_MODEL:-nomic-embed-text}
${VISION_MODEL:-moondream:1.8b}
${TRANSLATOR_MODEL:-lauchacarro/qwen2.5-translator}
"

for m in $MODELOS; do
    if [ -n "$m" ]; then
        echo "📥 Verificando / descargando modelo: $m..."
        ollama pull "$m"
    fi
done

echo "✅ Todos los modelos locales están listos."
wait $SERVER_PID
