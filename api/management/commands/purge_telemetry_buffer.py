"""
Management command: purge_telemetry_buffer

Purges stale TelemetryRaw records from PostgreSQL to keep the database lean.
S3 is the permanent ML archive — PostgreSQL is only a write-ahead buffer.

Retention policy:
  • Successfully written (dynamo_ok=True AND s3_ok=True): 7 days
    → S3 already has the data; no value keeping it in Postgres longer.
  • Failed / pending records: 90 days
    → Kept long enough for manual recovery; warnings logged so ops can investigate.

Usage:
    python manage.py purge_telemetry_buffer              # use default retention days
    python manage.py purge_telemetry_buffer --dry-run    # show counts without deleting
    python manage.py purge_telemetry_buffer --ok-days 14 --failed-days 180
    python manage.py purge_telemetry_buffer --failed-only  # only purge unrecoverable failures

Recommended cron (daily at 02:00 UTC, after forecast_archiver runs at 01:00):
    0 2 * * * /path/to/venv/bin/python manage.py purge_telemetry_buffer >> /var/log/purge_telemetry.log 2>&1
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from api.models import TelemetryRaw

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Purge stale TelemetryRaw records to keep PostgreSQL lean'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ok-days',
            type=int,
            default=7,
            help='Delete successfully-written records older than N days (default: 7)',
        )
        parser.add_argument(
            '--failed-days',
            type=int,
            default=90,
            help='Delete failed/pending records older than N days (default: 90)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print counts without deleting anything',
        )
        parser.add_argument(
            '--failed-only',
            action='store_true',
            help='Only purge failed/pending records (skip successful ones)',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        ok_cutoff = now - timedelta(days=options['ok_days'])
        failed_cutoff = now - timedelta(days=options['failed_days'])

        # Successful records: both DynamoDB and S3 confirmed written
        ok_qs = TelemetryRaw.objects.filter(
            dynamo_ok=True,
            s3_ok=True,
            received_at__lt=ok_cutoff,
        )

        # Failed/pending records: at least one write failed, old enough to be unrecoverable
        failed_qs = TelemetryRaw.objects.filter(
            received_at__lt=failed_cutoff,
        ).exclude(
            dynamo_ok=True,
            s3_ok=True,
        )

        ok_count = ok_qs.count()
        failed_count = failed_qs.count()

        if failed_count > 0:
            # Log as warning — persistent failures mean data may be missing from S3/DynamoDB
            logger.warning(
                "purge_telemetry_buffer: %d failed/pending records older than %d days "
                "will be purged — these records may be missing from DynamoDB/S3. "
                "Run 'replay_telemetry --hours %d' before purging if recovery is still possible.",
                failed_count,
                options['failed_days'],
                options['failed_days'] * 24,
            )
            self.stderr.write(
                self.style.WARNING(
                    f"WARNING: {failed_count} failed/pending records older than "
                    f"{options['failed_days']} days will be purged. "
                    f"Run replay_telemetry first if you need to recover them."
                )
            )

        self.stdout.write(
            f"Successful records to purge (>{options['ok_days']}d): {ok_count}"
        )
        self.stdout.write(
            f"Failed/pending records to purge (>{options['failed_days']}d): {failed_count}"
        )

        if options['dry_run']:
            self.stdout.write("Dry run — no records deleted.")
            return

        total_deleted = 0

        if not options['failed_only']:
            deleted, _ = ok_qs.delete()
            total_deleted += deleted
            self.stdout.write(f"  Deleted {deleted} successful records.")

        if failed_count > 0:
            deleted, _ = failed_qs.delete()
            total_deleted += deleted
            self.stdout.write(f"  Deleted {deleted} failed/pending records.")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Total purged: {total_deleted} records."
        ))
        logger.info("purge_telemetry_buffer: purged %d records total", total_deleted)
