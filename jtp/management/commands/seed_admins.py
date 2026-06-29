"""
Management command: seed the hard-coded admin users into jtp_admin_users.

Usage:
    python manage.py seed_admins
"""
from django.core.management.base import BaseCommand

from jtp.models import JTPAdminUser


ADMIN_SEED = [
    {'isid': 'hoangp5',  'email': 'hoang.phuc.thinh.nguyen@intel.com'},
    {'isid': 'ngocanhm', 'email': 'ngoc.anh.minh.huynh@intel.com'},
]


class Command(BaseCommand):
    help = 'Seed the default admin users (hoangp5, ngocanhm) into jtp_admin_users'

    def handle(self, *args, **options):
        for data in ADMIN_SEED:
            obj, created = JTPAdminUser.objects.update_or_create(
                isid=data['isid'],
                defaults={'email': data['email']},
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(f'  {action}: {data["isid"]} ({data["email"]})')

        self.stdout.write(self.style.SUCCESS('Admin users seeded successfully.'))
