-- Run this against PostgreSQL AFTER 001 (initial schema).
-- Requires pgvector extension: apt install postgresql-16-pgvector

-- 1. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Add proper VECTOR column to rag_chunks
--    (SQLAlchemy creates it as TEXT for SQLite compat; this upgrades it for Postgres)
ALTER TABLE rag_chunks
    ADD COLUMN IF NOT EXISTS embedding_vec VECTOR(1536);

-- Migrate existing JSON-string embeddings if any
UPDATE rag_chunks
SET    embedding_vec = embedding::vector
WHERE  embedding_vec IS NULL
  AND  embedding IS NOT NULL
  AND  embedding != '';

-- 3. HNSW index for fast ANN search (cosine distance)
--    Typical build time: seconds for thousands of chunks.
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
    ON rag_chunks
    USING hnsw (embedding_vec vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 4. After verifying data, you can drop the old TEXT column:
-- ALTER TABLE rag_chunks DROP COLUMN embedding;
-- ALTER TABLE rag_chunks RENAME COLUMN embedding_vec TO embedding;

-- ProcessedDocument cache table (created by SQLAlchemy on startup,
-- but run this if you need it before first app start)
CREATE TABLE IF NOT EXISTS processed_documents (
    id                SERIAL PRIMARY KEY,
    rag_document_id   INTEGER REFERENCES rag_documents(id) ON DELETE CASCADE,
    filename          VARCHAR(512) NOT NULL,
    format            VARCHAR(32)  NOT NULL,
    content_json      TEXT         NOT NULL,
    token_count       INTEGER      NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_processed_documents_rag_doc
    ON processed_documents (rag_document_id);
CREATE INDEX IF NOT EXISTS ix_processed_documents_filename
    ON processed_documents (filename);
