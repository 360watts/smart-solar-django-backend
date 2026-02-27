"""
Management command: replay_telemetry

Replays TelemetryRaw records where DynamoDB or S3 writes previously failed.
Run this after recovering from an AWS outage to backfill missing data.

Usage:
    python manage.py replay_telemetry              # replay all pending
    python manage.py replay_telemetry --limit 100  # replay at most 100 records
    python manage.py replay_telemetry --dry-run    # show counts without writing
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from api.models import TelemetryRaw
from api.views import _build_dynamo_item, _write_dynamo, _write_s3_csv


class Command(BaseCommand):
    help = 'Replay TelemetryRaw records that failed DynamoDB or S3 writes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of records to replay (default: all pending)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print counts without performing any writes',
        )
        parser.add_argument(
            '--hours',
            type=int,
            default=None,
            help='Only replay records received within the last N hours',
        )

    def handle(self, *args, **options):
        from django.db.models import Q

        qs = TelemetryRaw.objects.filter(
            Q(dynamo_ok=False) | Q(s3_ok=False)
        ).select_related('device').order_by('received_at')

        if options['hours']:
            cutoff = timezone.now() - timedelta(hours=options['hours'])
            qs = qs.filter(received_at__gte=cutoff)

        total = qs.count()
        self.stdout.write(f"Pending records: {total}")

        if options['dry_run']:
            dynamo_pending = qs.filter(dynamo_ok=False).count()
            s3_pending = qs.filter(s3_ok=False).count()
            self.stdout.write(f"  DynamoDB pending: {dynamo_pending}")
            self.stdout.write(f"  S3 pending:       {s3_pending}")
            return

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to replay."))
            return

        if options['limit']:
            qs = qs[:options['limit']]

        replayed = 0
        dynamo_fixed = 0
        s3_fixed = 0
        errors = 0

        for raw in qs:
            payload = raw.payload
            timestamp_iso = raw.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
            received_at = raw.received_at.strftime('%Y-%m-%dT%H:%M:%SZ')
            ttl = int((raw.received_at + timedelta(hours=24)).timestamp())
            db_item = _build_dynamo_item(raw.site_id, payload, timestamp_iso, received_at, ttl)

            new_dynamo_ok = raw.dynamo_ok
            new_s3_ok = raw.s3_ok

            if not raw.dynamo_ok:
                try:
                    _write_dynamo(db_item)
                    new_dynamo_ok = True
                    dynamo_fixed += 1
                except Exception as exc:
                    self.stderr.write(
                        f"  [raw_id={raw.pk}] DynamoDB replay failed: {exc}"
                    )
                    errors += 1

            if not raw.s3_ok:
                try:
                    _write_s3_csv(raw.site_id, timestamp_iso, db_item, received_at)
                    new_s3_ok = True
                    s3_fixed += 1
                except Exception as exc:
                    self.stderr.write(
                        f"  [raw_id={raw.pk}] S3 replay failed: {exc}"
                    )
                    errors += 1

            if new_dynamo_ok != raw.dynamo_ok or new_s3_ok != raw.s3_ok:
                TelemetryRaw.objects.filter(pk=raw.pk).update(
                    dynamo_ok=new_dynamo_ok, s3_ok=new_s3_ok
                )

            replayed += 1
            if replayed % 50 == 0:
                self.stdout.write(f"  ... processed {replayed}/{total}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Processed={replayed} | DynamoDB fixed={dynamo_fixed} | "
            f"S3 fixed={s3_fixed} | Errors={errors}"
        ))
