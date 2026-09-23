-- init.sql

CREATE TABLE IF NOT EXISTS usuarios (
    telegram_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    nombre VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS mensajes (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT REFERENCES usuarios(telegram_id),
    mensaje_usuario TEXT,
    respuesta_bot TEXT,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
