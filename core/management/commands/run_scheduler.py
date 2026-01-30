"""
Unified scheduler that runs all scheduled tasks.

This single command handles all periodic tasks:
- Publishing scheduled news and knowledge posts (every 5 minutes)
- Sending medical certificate reminders (daily at 9:00)
- Sending pending match reminders (daily at 9:00)

Usage:
    python manage.py run_scheduler

Just run this command and leave it running in the background.
On Windows, you can run it in a separate terminal or as a service.
"""
import time
import signal
import sys
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Run all scheduled tasks in a single background process'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True
        self.last_daily_run = None

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run all tasks once and exit (useful for testing)',
        )

    def handle(self, *args, **options):
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if options['once']:
            self.stdout.write('Running all tasks once...')
            self._run_frequent_tasks()
            self._run_daily_tasks()
            self.stdout.write(self.style.SUCCESS('All tasks completed.'))
            return

        self.stdout.write(self.style.SUCCESS('Scheduler started. Press Ctrl+C to stop.'))
        self.stdout.write('Running tasks:')
        self.stdout.write('  - Scheduled news/knowledge posts: every 5 minutes')
        self.stdout.write('  - Medical reminders: daily at 9:00')
        self.stdout.write('  - Match reminders: daily at 9:00')
        self.stdout.write('')

        while self.running:
            try:
                now = timezone.localtime(timezone.now())

                # Run frequent tasks (every 5 minutes)
                if now.minute % 5 == 0:
                    self._run_frequent_tasks()

                # Run daily tasks at 9:00
                today = now.date()
                if now.hour == 9 and now.minute == 0:
                    if self.last_daily_run != today:
                        self._run_daily_tasks()
                        self.last_daily_run = today

                # Sleep for 60 seconds before checking again
                time.sleep(60)

            except Exception as e:
                self.stderr.write(self.style.ERROR(f'Error in scheduler: {e}'))
                time.sleep(60)  # Wait before retrying

        self.stdout.write(self.style.SUCCESS('Scheduler stopped.'))

    def _signal_handler(self, signum, frame):
        self.stdout.write('\nShutdown signal received...')
        self.running = False

    def _run_frequent_tasks(self):
        """Tasks that run every 5 minutes."""
        self._publish_scheduled_content()

    def _run_daily_tasks(self):
        """Tasks that run once daily at 9:00."""
        self.stdout.write(f'[{timezone.localtime(timezone.now())}] Running daily tasks...')
        self._send_medical_reminders()
        self._send_match_reminders()

    def _publish_scheduled_content(self):
        """Publish scheduled news and knowledge posts."""
        from education.models import News, KnowledgePost
        from documents.models import Notification
        from accounts.models import User
        import re

        now = timezone.now()
        published_count = 0

        # Publish scheduled news
        scheduled_news = News.objects.filter(
            scheduled_at__isnull=False,
            scheduled_at__lte=now,
            is_published=False,
            is_hidden=False
        )

        for news in scheduled_news:
            news.is_published = True
            news.published_at = now
            news.save()

            # Send notifications
            users = User.objects.filter(is_deleted=False)
            preview = news.content[:100] + '...' if len(news.content) > 100 else news.content
            preview = re.sub('<[^<]+?>', '', preview)

            for user in users:
                Notification.objects.create(
                    recipient=user,
                    title="Új hír jelent meg",
                    message=f"{news.title}\n\n{preview}",
                    notification_type=Notification.Type.INFO,
                    link="/"
                )

            published_count += 1
            self.stdout.write(self.style.SUCCESS(f'Published news: {news.title}'))

        # Publish scheduled knowledge posts
        scheduled_knowledge = KnowledgePost.objects.filter(
            scheduled_at__isnull=False,
            scheduled_at__lte=now,
            is_draft=False,
            is_hidden=False,
            is_active=True
        )

        for post in scheduled_knowledge:
            post.scheduled_at = None
            post.save()

            # Send notifications
            users = User.objects.filter(is_deleted=False)
            preview = post.content[:100] + '...' if len(post.content) > 100 else post.content
            preview = re.sub('<[^<]+?>', '', preview)

            for user in users:
                Notification.objects.create(
                    recipient=user,
                    title="Új tudástár bejegyzés",
                    message=f"{post.title}\n\n{preview}",
                    notification_type=Notification.Type.INFO,
                    link="/education/knowledge/"
                )

            published_count += 1
            self.stdout.write(self.style.SUCCESS(f'Published knowledge post: {post.title}'))

        if published_count > 0:
            self.stdout.write(f'[{timezone.localtime(now)}] Published {published_count} items')

    def _send_medical_reminders(self):
        """Send reminders for expiring medical certificates."""
        from accounts.models import User
        from documents.models import Notification

        today = timezone.localtime(timezone.now()).date()
        reminder_days = [30, 7]
        sent_count = 0

        for days in reminder_days:
            target_date = today + timedelta(days=days)

            users = User.objects.filter(
                medical_valid_until=target_date,
                is_deleted=False
            )

            for user in users:
                # Check if already sent today
                existing = Notification.objects.filter(
                    recipient=user,
                    title__startswith="Sportorvosi lejár",
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
                    sent_count += 1

        if sent_count > 0:
            self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} medical reminders'))

    def _send_match_reminders(self):
        """Send reminders for pending match assignments."""
        from matches.models import Match, MatchAssignment
        from documents.models import Notification
        from accounts.models import User
        from django.db.models import Q

        today = timezone.localtime(timezone.now()).date()
        reminder_days = [5, 3, 2, 1]
        sent_count = 0

        for days in reminder_days:
            target_date = today + timedelta(days=days)

            # Find matches on target date with pending assignments
            matches = Match.objects.filter(
                date=target_date,
                status__in=[Match.Status.SCHEDULED, Match.Status.CONFIRMED],
                is_assignment_published=True
            ).select_related('home_team', 'away_team', 'venue')

            for match in matches:
                pending_assignments = MatchAssignment.objects.filter(
                    match=match,
                    user__isnull=True
                ).select_related('role')

                if pending_assignments.exists():
                    # Notify coordinators
                    coordinators = User.objects.filter(
                        Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True),
                        is_deleted=False
                    )

                    date_str = match.date.strftime('%Y.%m.%d (%A)')
                    time_str = match.time.strftime('%H:%M') if match.time else ''
                    teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
                    venue = match.venue.name if match.venue else 'Nincs helyszín'

                    pending_roles = ', '.join([a.role.name for a in pending_assignments if a.role])
                    message = f"{date_str} {time_str}\n{teams}\n{venue}\n\nBetöltetlen pozíciók: {pending_roles}"

                    if days == 1:
                        title = "SÜRGŐS: Holnapi mérkőzésen betöltetlen pozíció!"
                        notification_type = Notification.Type.ERROR
                    elif days <= 3:
                        title = f"Mérkőzés {days} nap múlva - betöltetlen pozíció"
                        notification_type = Notification.Type.WARNING
                    else:
                        title = f"Mérkőzés {days} nap múlva - betöltetlen pozíció"
                        notification_type = Notification.Type.INFO

                    for coordinator in coordinators:
                        # Check if already notified today for this match
                        existing = Notification.objects.filter(
                            recipient=coordinator,
                            link=f"/matches/{match.id}/edit/",
                            created_at__date=today
                        ).exists()

                        if not existing:
                            Notification.objects.create(
                                recipient=coordinator,
                                title=title,
                                message=message,
                                notification_type=notification_type,
                                link=f"/matches/{match.id}/edit/"
                            )
                            sent_count += 1

        if sent_count > 0:
            self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} match reminders'))
