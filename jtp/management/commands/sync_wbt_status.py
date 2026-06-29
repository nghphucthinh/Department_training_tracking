"""
Management command: sync WBT course completions from inf_data.

Usage:
    python manage.py sync_wbt_status
    python manage.py sync_wbt_status --wwid 12345678
"""
from django.core.management.base import BaseCommand

from jtp.services import sync_wbt_completions_for_employee, sync_wbt_completions_for_all


class Command(BaseCommand):
    help = 'Sync WBT course completion status from the inf_data table'

    def add_arguments(self, parser):
        parser.add_argument(
            '--wwid',
            type=str,
            default=None,
            help='Sync only for a specific employee WWID (omit to sync all)',
        )

    def handle(self, *args, **options):
        wwid = options.get('wwid')
        if wwid:
            self.stdout.write(f'Syncing WBT completions for WWID: {wwid} …')
            count = sync_wbt_completions_for_employee(wwid)
        else:
            self.stdout.write('Syncing WBT completions for ALL employees …')
            count = sync_wbt_completions_for_all()

        self.stdout.write(self.style.SUCCESS(f'Done — {count} course record(s) updated.'))
