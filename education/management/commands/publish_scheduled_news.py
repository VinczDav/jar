"""
Management command to publish scheduled news and knowledge posts.

Publishes news posts and knowledge posts that have a scheduled_at
datetime in the past and are not yet published.

Usage:
    python manage.py publish_scheduled_news

Should be run frequently via cron job (e.g., every 5 minutes):
    */5 * * * * cd /path/to/project && python manage.py publish_scheduled_news
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from education.models import News, KnowledgePost
from documents.models import Notification
from accounts.models import User
import re


class Command(BaseCommand):
    help = 'Publish scheduled news and knowledge posts, send notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be published without actually publishing',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()

        total_published = 0

        # === Handle News ===
        scheduled_news = News.objects.filter(
            scheduled_at__isnull=False,
            scheduled_at__lte=now,
            is_published=False,
            is_hidden=False
        )

        for news in scheduled_news:
            if dry_run:
                self.stdout.write(f"Would publish news: {news.title}")
            else:
                # Publish the news
                news.is_published = True
                news.published_at = now
                news.save()

                # Send notifications to all users
                self._notify_users_about_news(news)

                total_published += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Published news: {news.title}")
                )

        # === Handle Knowledge Posts ===
        # Knowledge posts with scheduled_at in the past that are still marked as draft or have future schedule
        scheduled_knowledge = KnowledgePost.objects.filter(
            scheduled_at__isnull=False,
            scheduled_at__lte=now,
            is_draft=False,  # Not a draft (scheduled for publication)
            is_hidden=False,
            is_active=True
        )

        for post in scheduled_knowledge:
            if dry_run:
                self.stdout.write(f"Would publish knowledge post: {post.title}")
            else:
                # Clear scheduled_at (it's now published)
                post.scheduled_at = None
                post.save()

                # Send notifications to all users
                self._notify_users_about_knowledge_post(post)

                total_published += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Published knowledge post: {post.title}")
                )

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run - nothing published'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Successfully published {total_published} items'))

    def _notify_users_about_news(self, news):
        """Send notification to all active users about a new published news."""
        users = User.objects.filter(is_deleted=False)

        # Truncate content for preview (first 100 chars)
        preview = news.content[:100] + '...' if len(news.content) > 100 else news.content
        # Remove HTML tags for preview
        preview = re.sub('<[^<]+?>', '', preview)

        for user in users:
            Notification.objects.create(
                recipient=user,
                title="Új hír jelent meg",
                message=f"{news.title}\n\n{preview}",
                notification_type=Notification.Type.INFO,
                link="/"
            )

    def _notify_users_about_knowledge_post(self, post):
        """Send notification to all active users about a new knowledge post."""
        users = User.objects.filter(is_deleted=False)

        # Truncate content for preview (first 100 chars)
        preview = post.content[:100] + '...' if len(post.content) > 100 else post.content
        # Remove HTML tags for preview
        preview = re.sub('<[^<]+?>', '', preview)

        for user in users:
            Notification.objects.create(
                recipient=user,
                title="Új tudástár bejegyzés",
                message=f"{post.title}\n\n{preview}",
                notification_type=Notification.Type.INFO,
                link="/education/knowledge/"
            )
