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

-- =====================================================================
-- (D) Gestión de casos del consultorio (v2)
-- =====================================================================
CREATE TABLE IF NOT EXISTS consultantes (
    id             SERIAL PRIMARY KEY,
    nombre         TEXT NOT NULL,
    documento      TEXT,
    telefono       TEXT,
    correo         TEXT,
    municipio      TEXT DEFAULT 'Mocoa',
    zona           TEXT CHECK (zona IN ('urbana','rural')),
    consentimiento BOOLEAN NOT NULL DEFAULT FALSE,   -- Ley 1581 de 2012
    creado         TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS consultantes_documento_uq ON consultantes(documento) WHERE documento IS NOT NULL;

-- Cada conversación es un CASO: tipo de consulta (área), estado y consultante
ALTER TABLE conversaciones ADD COLUMN IF NOT EXISTS consultante_id INT REFERENCES consultantes(id) ON DELETE SET NULL;
ALTER TABLE conversaciones ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'abierto';
ALTER TABLE conversaciones ADD COLUMN IF NOT EXISTS notas TEXT;
DO $$ BEGIN
    ALTER TABLE conversaciones ADD CONSTRAINT conversaciones_estado_ck
        CHECK (estado IN ('abierto','orientado','remitido','en_tramite','cerrado'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS historial_estados (
    id               SERIAL PRIMARY KEY,
    conversacion_id  UUID REFERENCES conversaciones(id) ON DELETE CASCADE,
    estado           TEXT NOT NULL,
    nota             TEXT,
    creado           TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE entidades ADD COLUMN IF NOT EXISTS atiende_citas BOOLEAN DEFAULT FALSE;
ALTER TABLE entidades ADD COLUMN IF NOT EXISTS horario TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS entidades_nombre_uq ON entidades(nombre);

CREATE TABLE IF NOT EXISTS citas_consultorio (
    id               SERIAL PRIMARY KEY,
    conversacion_id  UUID REFERENCES conversaciones(id) ON DELETE SET NULL,
    consultante_id   INT REFERENCES consultantes(id) ON DELETE CASCADE,
    entidad_id       INT REFERENCES entidades(id),
    fecha            DATE NOT NULL,
    hora             TIME NOT NULL,
    modalidad        TEXT NOT NULL DEFAULT 'presencial' CHECK (modalidad IN ('presencial','virtual','telefonica')),
    motivo           TEXT,
    estado           TEXT NOT NULL DEFAULT 'solicitada' CHECK (estado IN ('solicitada','confirmada','atendida','cancelada')),
    creado           TIMESTAMPTZ DEFAULT now()
);
-- Un mismo horario no puede asignarse dos veces en la misma entidad
CREATE UNIQUE INDEX IF NOT EXISTS citas_horario_uq ON citas_consultorio(entidad_id, fecha, hora) WHERE estado <> 'cancelada';

ALTER TABLE documentos_generados ADD COLUMN IF NOT EXISTS consultante_id INT REFERENCES consultantes(id) ON DELETE SET NULL;
ALTER TABLE documentos_generados ADD COLUMN IF NOT EXISTS origen TEXT DEFAULT 'impresion';

-- Vista de casos para consultas e informes
CREATE OR REPLACE VIEW casos AS
SELECT c.id, c.titulo, c.area AS tipo_consulta, c.urgencia, c.estado, c.creada, c.actualizada,
       p.nombre AS consultante, p.municipio,
       (SELECT count(*) FROM mensajes m WHERE m.conversacion_id = c.id) AS mensajes,
       (SELECT count(*) FROM documentos_generados d WHERE d.conversacion_id = c.id) AS documentos,
       (SELECT count(*) FROM citas_consultorio ci WHERE ci.conversacion_id = c.id AND ci.estado <> 'cancelada') AS citas
FROM conversaciones c LEFT JOIN consultantes p ON p.id = c.consultante_id;
