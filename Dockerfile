FROM ollama/ollama:latest

RUN useradd -m -u 10001 aiuser && \
    mkdir -p /home/aiuser/.ollama && \
    chown -R 10001:10001 /home/aiuser

ENV OLLAMA_MODELS=/home/aiuser/.ollama
ENV OLLAMA_HOST=0.0.0.0

COPY --chown=10001:10001 entrypoint.sh /home/aiuser/entrypoint.sh
RUN chmod +x /home/aiuser/entrypoint.sh

USER 10001
WORKDIR /home/aiuser
EXPOSE 11434

ENTRYPOINT ["/home/aiuser/entrypoint.sh"]
