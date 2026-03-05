# Migration: Convert api_telemetryraw to time-partitioned table (PARTITION BY RANGE (timestamp))
# Enables partition pruning and efficient purge by time range for scale beyond pilot.

from django.db import migrations


def apply_partitioning(apps, schema_editor):
    """Convert api_telemetryraw to a time-partitioned table. Idempotent if already partitioned."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        # Check if already partitioned (avoid re-run)
        cursor.execute("""
            SELECT c.relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'api_telemetryraw';
        """)
        r = cursor.fetchone()
        if not r:
            return
        if r[0] == 'p':
            return  # already partitioned

        # Create partitioned table (same columns); PK must include partition key in PG11+
        cursor.execute("""
            CREATE TABLE api_telemetryraw_new (
                id BIGSERIAL,
                device_id INTEGER NOT NULL REFERENCES api_device(id) ON DELETE CASCADE,
                site_id VARCHAR(64) NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                payload JSONB NOT NULL,
                dynamo_ok BOOLEAN NOT NULL DEFAULT FALSE,
                s3_ok BOOLEAN NOT NULL DEFAULT FALSE,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id, timestamp)
            ) PARTITION BY RANGE (timestamp);
        """)
        # Yearly partitions + default (covers pilot and replay)
        for year in [2024, 2025, 2026, 2027]:
            cursor.execute(f"""
                CREATE TABLE api_telemetryraw_new_{year}
                PARTITION OF api_telemetryraw_new
                FOR VALUES FROM (%s) TO (%s);
            """, [f"{year}-01-01 00:00:00+00", f"{year + 1}-01-01 00:00:00+00"])
        cursor.execute("""
            CREATE TABLE api_telemetryraw_new_default PARTITION OF api_telemetryraw_new DEFAULT;
        """)
        # Copy data
        cursor.execute("""
            INSERT INTO api_telemetryraw_new (id, device_id, site_id, timestamp, payload, dynamo_ok, s3_ok, received_at)
            SELECT id, device_id, site_id, timestamp, payload, dynamo_ok, s3_ok, received_at
            FROM api_telemetryraw;
        """)
        # Swap
        cursor.execute("DROP TABLE api_telemetryraw;")
        cursor.execute("ALTER TABLE api_telemetryraw_new RENAME TO api_telemetryraw;")
        # So Django's ORM uses the correct sequence for new rows
        cursor.execute("ALTER SEQUENCE api_telemetryraw_new_id_seq RENAME TO api_telemetryraw_id_seq;")
        # Indexes (applied to all partitions in PG11+)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_telemetryraw_site_timestamp ON api_telemetryraw (site_id, timestamp DESC);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_telemetryraw_dynamo_s3_received ON api_telemetryraw (dynamo_ok, s3_ok, received_at);
        """)


def reverse_partitioning(apps, schema_editor):
    """Revert to non-partitioned table (recreate regular table and copy data back)."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT c.relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'api_telemetryraw';
        """)
        r = cursor.fetchone()
        if not r or r[0] != 'p':
            return
        cursor.execute("""
            CREATE TABLE api_telemetryraw_old (
                id BIGSERIAL PRIMARY KEY,
                device_id INTEGER NOT NULL REFERENCES api_device(id) ON DELETE CASCADE,
                site_id VARCHAR(64) NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                payload JSONB NOT NULL,
                dynamo_ok BOOLEAN NOT NULL DEFAULT FALSE,
                s3_ok BOOLEAN NOT NULL DEFAULT FALSE,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );
        """)
        cursor.execute("""
            INSERT INTO api_telemetryraw_old (id, device_id, site_id, timestamp, payload, dynamo_ok, s3_ok, received_at)
            SELECT id, device_id, site_id, timestamp, payload, dynamo_ok, s3_ok, received_at FROM api_telemetryraw;
        """)
        cursor.execute("DROP TABLE api_telemetryraw;")
        cursor.execute("ALTER TABLE api_telemetryraw_old RENAME TO api_telemetryraw;")
        cursor.execute("CREATE INDEX idx_telemetryraw_site_timestamp ON api_telemetryraw (site_id, timestamp DESC);")
        cursor.execute("CREATE INDEX idx_telemetryraw_dynamo_s3_received ON api_telemetryraw (dynamo_ok, s3_ok, received_at);")


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0022_telemetrymessageid"),
    ]

    operations = [
        migrations.RunPython(apply_partitioning, reverse_partitioning, elidable=False),
    ]
