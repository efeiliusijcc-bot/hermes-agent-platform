CREATE ROLE hermes_reader
  LOGIN
  PASSWORD 'postgres-mcp-e2e-reader'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT;

ALTER ROLE hermes_reader SET default_transaction_read_only = on;

CREATE DATABASE business_db;
CREATE DATABASE analytics_db;
CREATE DATABASE private_db;

REVOKE CONNECT ON DATABASE private_db FROM PUBLIC;
GRANT CONNECT ON DATABASE business_db, analytics_db TO hermes_reader;

\connect business_db

CREATE SCHEMA reporting;
CREATE TABLE public.skills (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL,
  category text NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.skills (name, category, enabled) VALUES
  ('write-hb', 'reporting', true),
  ('material-reader', 'document', true),
  ('legacy-search', 'retrieval', false);

CREATE TABLE reporting.execution_summary (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_name text NOT NULL,
  status text NOT NULL,
  duration_ms integer NOT NULL,
  executed_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO reporting.execution_summary (agent_name, status, duration_ms) VALUES
  ('manager-hermes', 'succeeded', 1820),
  ('writer-pi', 'succeeded', 940),
  ('reviewer-deepseek', 'failed', 760);

CREATE VIEW reporting.successful_executions AS
SELECT id, agent_name, duration_ms, executed_at
FROM reporting.execution_summary
WHERE status = 'succeeded';

GRANT USAGE ON SCHEMA public, reporting TO hermes_reader;
GRANT SELECT ON public.skills, reporting.execution_summary, reporting.successful_executions TO hermes_reader;

\connect analytics_db

CREATE SCHEMA metrics;
CREATE TABLE metrics.daily_usage (
  usage_date date NOT NULL,
  agent_id text NOT NULL,
  invocation_count integer NOT NULL,
  error_count integer NOT NULL,
  PRIMARY KEY (usage_date, agent_id)
);
INSERT INTO metrics.daily_usage VALUES
  ('2026-08-17', 'manager-hermes', 12, 0),
  ('2026-08-18', 'manager-hermes', 18, 1),
  ('2026-08-18', 'writer-pi', 9, 0);

CREATE VIEW metrics.agent_totals AS
SELECT agent_id, sum(invocation_count) AS invocations, sum(error_count) AS errors
FROM metrics.daily_usage
GROUP BY agent_id;

GRANT USAGE ON SCHEMA metrics TO hermes_reader;
GRANT SELECT ON metrics.daily_usage, metrics.agent_totals TO hermes_reader;
