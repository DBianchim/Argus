-- setup_db.sql — Provisão do banco do Argus (rodar UMA vez, como superusuário)
--
--   psql -U postgres -h localhost -f scripts/setup_db.sql
--
-- Troque a senha antes de executar. Depois, ajuste DATABASE_URL no .env:
--   postgresql+asyncpg://argus:<senha>@localhost:5432/argus
--
-- Observação: se o role/banco já existirem, estes comandos falham (esperado —
-- é um setup único). Para recriar, faça DROP antes.

CREATE ROLE argus WITH LOGIN PASSWORD 'troque-esta-senha';
CREATE DATABASE argus OWNER argus;
