import os
import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id text PRIMARY KEY, password text NOT NULL, created timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tokens (
 digest text PRIMARY KEY, user_id text NOT NULL REFERENCES users(id),
 expires timestamptz NOT NULL, scope text NOT NULL DEFAULT 'user'
);
CREATE TABLE IF NOT EXISTS auth_attempts (
 bucket text PRIMARY KEY, window_started timestamptz NOT NULL DEFAULT now(), attempts integer NOT NULL
);
CREATE TABLE IF NOT EXISTS scripts (
 id uuid PRIMARY KEY, user_id text NOT NULL REFERENCES users(id), title text NOT NULL,
 code text NOT NULL, shared boolean NOT NULL DEFAULT false, updated timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobs (
 id uuid PRIMARY KEY, user_id text NOT NULL REFERENCES users(id), kind text NOT NULL,
 title text NOT NULL, status text NOT NULL CHECK(status IN ('created','queued','running','finished','error','canceled')),
 process jsonb NOT NULL DEFAULT '{}', code text, created timestamptz NOT NULL DEFAULT now(),
 updated timestamptz NOT NULL DEFAULT now(), started timestamptz, finished timestamptz,
 error text, logs text NOT NULL DEFAULT '', assets jsonb NOT NULL DEFAULT '{}',
 snapshot jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(kind,status,created);
CREATE TABLE IF NOT EXISTS collections (id text PRIMARY KEY, metadata jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS items (
 id text PRIMARY KEY, collection_id text NOT NULL REFERENCES collections(id),
 metadata jsonb NOT NULL, checksum text NOT NULL, created timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sync_runs (
 id uuid PRIMARY KEY, source text NOT NULL, started timestamptz DEFAULT now(),
 finished timestamptz, status text NOT NULL, message text
);
ALTER TABLE items ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
CREATE INDEX IF NOT EXISTS items_active ON items(collection_id,active);
ALTER TABLE scripts ADD COLUMN IF NOT EXISTS language text NOT NULL DEFAULT 'python';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS language text NOT NULL DEFAULT 'python';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS context jsonb NOT NULL DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS events jsonb NOT NULL DEFAULT '[]';
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS job_id uuid;
"""

def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,options='-c timezone=UTC')

def init():
    from .migrations import migrations
    import hashlib
    with connect() as c:
        rows=c.execute('SELECT version,checksum FROM schema_migrations ORDER BY version').fetchall()
    expected=[{'version':v,'checksum':hashlib.sha256(sql.encode()).hexdigest()} for v,_,sql in migrations()]
    if rows != expected:
        raise RuntimeError('Schema mismatch: run python -m gee.migrations before starting services')

def query(sql, args=(), one=False):
    with connect() as c:
        cur = c.execute(sql, args)
        if cur.description:
            return cur.fetchone() if one else cur.fetchall()

def job(job_id, user_id):
    from openeo_driver.errors import JobNotFoundException
    # Cast the parameter to text: malformed ids return 404 instead of a SQL error.
    row = query("SELECT * FROM jobs WHERE id::text=%s AND user_id=%s", (job_id, user_id), one=True)
    if not row:
        raise JobNotFoundException(job_id)
    return row
