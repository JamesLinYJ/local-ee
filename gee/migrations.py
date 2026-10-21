"""Ordered, transactional, additive migrations; run separately from API/worker."""
import hashlib
from . import db

ADMIN_SCHEMA = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'researcher'
 CHECK (role IN ('admin','dataset_manager','researcher','viewer'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS enabled boolean NOT NULL DEFAULT true;
ALTER TABLE collections ADD COLUMN IF NOT EXISTS enabled boolean NOT NULL DEFAULT true;
ALTER TABLE collections ADD COLUMN IF NOT EXISTS managed_metadata jsonb NOT NULL DEFAULT '{}';
ALTER TABLE collections ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS audit_events (
 id bigserial PRIMARY KEY, created timestamptz NOT NULL DEFAULT now(),
 actor text NOT NULL, action text NOT NULL, object_type text NOT NULL,
 object_id text NOT NULL, changes jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_events_created ON audit_events(created DESC,id DESC);
"""


def migrations():
    # The historical schema is migration 1. Never edit its text after rollout.
    return [(1, 'historical_baseline', db.SCHEMA), (2, 'administration', ADMIN_SCHEMA), (3, 'dataset_files', FILE_SCHEMA)]


FILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset_files (
 id uuid PRIMARY KEY, collection_id text NOT NULL REFERENCES collections(id),
 user_id text NOT NULL REFERENCES users(id), filename text NOT NULL,
 size bigint NOT NULL CHECK(size>0), received bigint NOT NULL DEFAULT 0,
 sha256 text NOT NULL, status text NOT NULL DEFAULT 'uploading'
 CHECK(status IN ('uploading','stored','queued','processing','ready','error','canceled')),
 created timestamptz NOT NULL DEFAULT now(), updated timestamptz NOT NULL DEFAULT now(),
 job_id uuid, item_id text, error text, options jsonb NOT NULL DEFAULT '{}',
 UNIQUE(collection_id,sha256,size)
);
CREATE INDEX IF NOT EXISTS dataset_files_collection ON dataset_files(collection_id,created DESC);
"""


def migrate():
    with db.connect() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(1879645011)')
        connection.execute('''CREATE TABLE IF NOT EXISTS schema_migrations (
            version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,
            applied timestamptz NOT NULL DEFAULT now())''')
        applied = {r['version']: r for r in connection.execute('SELECT * FROM schema_migrations')}
        known = {version for version, _, _ in migrations()}
        if set(applied) - known:
            raise RuntimeError('Database is newer than this application; do not downgrade')
        for version, name, sql in migrations():
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if version in applied:
                if applied[version]['checksum'] != checksum:
                    raise RuntimeError(f'Migration {version} checksum changed')
                continue
            connection.execute(sql)
            connection.execute('INSERT INTO schema_migrations(version,name,checksum) VALUES(%s,%s,%s)',
                               (version, name, checksum))


if __name__ == '__main__':
    migrate()
    print('Database migrations applied.')
