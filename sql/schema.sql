-- =====================================================================
--  AMPARO · Agente de orientación jurídica básica
--  Esquema PostgreSQL + pgvector
--  Separa: (1) datos transaccionales  (2) conocimiento vectorial
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ---------------------------------------------------------------------
-- (A) Catálogos del dominio jurídico
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS areas (
    slug          TEXT PRIMARY KEY,
    nombre        TEXT NOT NULL,
    descripcion   TEXT NOT NULL,           -- se usa para clasificar por similitud
    color         TEXT NOT NULL,
    simbolo       TEXT NOT NULL,
    embedding     vector(768)
);

CREATE TABLE IF NOT EXISTS rutas (
    id         SERIAL PRIMARY KEY,
    area_slug  TEXT REFERENCES areas(slug) ON DELETE CASCADE,
    orden      INT  NOT NULL,
    titulo     TEXT NOT NULL,
    detalle    TEXT NOT NULL,
    plazo      TEXT
);

CREATE TABLE IF NOT EXISTS entidades (
    id         SERIAL PRIMARY KEY,
    nombre     TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    municipio  TEXT NOT NULL,
    contacto   TEXT,
    canal      TEXT,
    gratuito   BOOLEAN DEFAULT TRUE,
    areas      TEXT[] NOT NULL,
    nota       TEXT
);

-- ---------------------------------------------------------------------
-- (B) Conocimiento vectorial (RAG)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documentos (
    id       SERIAL PRIMARY KEY,
    slug     TEXT UNIQUE NOT NULL,
    titulo   TEXT NOT NULL,
    fuente   TEXT NOT NULL,             -- norma principal (ej. "Ley 1755 de 2015")
    area     TEXT REFERENCES areas(slug),
    url      TEXT
);

CREATE TABLE IF NOT EXISTS fragmentos (
    id            SERIAL PRIMARY KEY,
    documento_id  INT REFERENCES documentos(id) ON DELETE CASCADE,
    orden         INT NOT NULL,
    seccion       TEXT,
    contenido     TEXT NOT NULL,
    tokens        INT,
    embedding     vector(768) NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('spanish', contenido)) STORED
);

CREATE INDEX IF NOT EXISTS idx_fragmentos_hnsw
    ON fragmentos USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_fragmentos_tsv
    ON fragmentos USING gin (tsv);

-- ---------------------------------------------------------------------
-- (C) Datos transaccionales: conversaciones y trazabilidad
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversaciones (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    titulo      TEXT,
    area        TEXT REFERENCES areas(slug),
    urgencia    TEXT,
    creada      TIMESTAMPTZ DEFAULT now(),
    actualizada TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mensajes (
    id               SERIAL PRIMARY KEY,
    conversacion_id  UUID REFERENCES conversaciones(id) ON DELETE CASCADE,
    rol              TEXT CHECK (rol IN ('usuario','agente')),
    contenido        TEXT NOT NULL,
    canal            TEXT DEFAULT 'texto',         -- texto | voz
    fuentes          JSONB,
    expediente       JSONB,
    metricas         JSONB,
    creado           TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mensajes_conv ON mensajes(conversacion_id, creado);

CREATE TABLE IF NOT EXISTS documentos_generados (
    id               SERIAL PRIMARY KEY,
    conversacion_id  UUID REFERENCES conversaciones(id) ON DELETE SET NULL,
    tipo             TEXT NOT NULL,
    campos           JSONB,
    creado           TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluaciones (
    id         SERIAL PRIMARY KEY,
    ejecutada  TIMESTAMPTZ DEFAULT now(),
    resumen    JSONB NOT NULL,
    casos      JSONB NOT NULL
);
