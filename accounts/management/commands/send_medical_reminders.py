"""
Management command to send reminders for expiring medical certificates.

Sends notifications to referees whose medical certificates are expiring
in 30 or 7 days.

Usage:
    python manage.py send_medical_reminders

Should be run daily via cron job, e.g.:
    0 9 * * * cd /path/to/project && python manage.py send_medical_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from accounts.models import User
from documents.models import Notification


class Command(BaseCommand):
    help = 'Send reminders for expiring medical certificates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without actually sending',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.localtime(timezone.now()).date()

        # Reminder days: 30 and 7 days before expiry
        reminder_days = [30, 7]

        total_sent = 0

        for days in reminder_days:
            target_date = today + timedelta(days=days)

            # Find users with medical certificates expiring on this date
            users = User.objects.filter(
                medical_valid_until=target_date,
                is_deleted=False
            )

            for user in users:
                if dry_run:
                    self.stdout.write(
                        f"Would send to {user.email}: Medical expires in {days} days ({target_date})"
                    )
                else:
                    # Check if we already sent a reminder today
                    existing = Notification.objects.filter(
                        recipient=user,
                        title="Sportorvosi lejár",
                        created_at__date=today
                    ).exists()

                    if not existing:
                        if days == 7:
                            title = "Sportorvosi lejár 7 nap múlva!"
                            notification_type = Notification.Type.WARNING
                        else:
                            title = "Sportorvosi lejár 30 nap múlva"
                            notification_type = Notification.Type.INFO

                        Notification.objects.create(
                            recipient=user,
                            title=title,
                            message=f"A sportorvosi igazolásod {target_date.strftime('%Y.%m.%d')}-én lejár.\n\nKérlek gondoskodj időben az új igazolásról!",
                            notification_type=notification_type,
                            link="/accounts/profile/"
                        )
                        total_sent += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Sent reminder to {user.email}: Medical expires in {days} days"
                            )
                        )

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run - no notifications sent'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Successfully sent {total_sent} reminders'))
