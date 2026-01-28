from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Max
from .models import KnowledgePost, KnowledgeAttachment, News, DocumentCategory, Document


def _notify_users_about_news(news):
    """Send notification to all active users about a new published news."""
    from documents.models import Notification
    from accounts.models import User

    # Get all active users (not deleted)
    users = User.objects.filter(is_deleted=False)

    # Truncate content for preview (first 100 chars)
    preview = news.content[:100] + '...' if len(news.content) > 100 else news.content
    # Remove HTML tags for preview
    import re
    preview = re.sub('<[^<]+?>', '', preview)

    for user in users:
        Notification.objects.create(
            recipient=user,
            title="Új hír jelent meg",
            message=f"{news.title}\n\n{preview}",
            notification_type=Notification.Type.INFO,
            link="/"  # Dashboard where news is shown
        )


def _notify_users_about_knowledge_post(post):
    """Send notification to all active users about a new knowledge post."""
    from documents.models import Notification
    from accounts.models import User
    import re

    # Get all active users (not deleted)
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


@login_required
def knowledge_base(request):
    """Show knowledge base posts and videos."""
    from django.db.models import Q

    now = timezone.now()
    posts = KnowledgePost.objects.filter(is_active=True)

    # Admins see all, others only see published (non-draft, not hidden, AND either no schedule or past schedule)
    if not request.user.is_jt_admin:
        posts = posts.filter(
            is_draft=False,
            is_hidden=False
        ).filter(
            Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=now)
        )

    # Search
    search = request.GET.get('search', '')
    if search:
        posts = posts.filter(title__icontains=search)

    context = {
        'posts': posts,
        'search': search,
        'can_edit': request.user.is_jt_admin,
        'now': now,
    }
    return render(request, 'education/knowledge_base.html', context)


@login_required
def knowledge_post_create(request):
    """JT Admin: Create a new knowledge base post."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()
        video_url = request.POST.get('video_url', '').strip()
        is_draft = request.POST.get('is_draft') == 'on'
        send_notification = request.POST.get('send_notification') == 'on'
        scheduled_date = request.POST.get('scheduled_date', '').strip()
        scheduled_time = request.POST.get('scheduled_time', '').strip()

        if not title:
            return render(request, 'education/knowledge_post_form.html', {
                'error': 'A cím megadása kötelező.',
            })

        # Get the next order value (highest + 1)
        max_order = KnowledgePost.objects.filter(is_active=True).aggregate(Max('order'))['order__max'] or 0

        post = KnowledgePost(
            title=title,
            content=content,
            video_url=video_url,
            is_draft=is_draft,
            order=max_order + 1,
            created_by=request.user,
        )

        is_scheduled_future = False
        # Handle scheduling
        if scheduled_date and scheduled_time and not is_draft:
            from datetime import datetime
            try:
                scheduled_datetime = datetime.strptime(
                    f"{scheduled_date} {scheduled_time}",
                    "%Y-%m-%d %H:%M"
                )
                post.scheduled_at = timezone.make_aware(scheduled_datetime)
                is_scheduled_future = post.scheduled_at > timezone.now()
            except ValueError:
                pass

        # Handle thumbnail
        if 'thumbnail' in request.FILES:
            post.thumbnail = request.FILES['thumbnail']

        post.save()

        # Handle multiple file attachments
        for file in request.FILES.getlist('attachments'):
            KnowledgeAttachment.objects.create(
                post=post,
                file=file,
                original_filename=file.name
            )

        # Send notification if publishing immediately (not draft, not scheduled for future)
        if send_notification and not is_draft and not is_scheduled_future:
            _notify_users_about_knowledge_post(post)

        return redirect('education:knowledge_base')

    return render(request, 'education/knowledge_post_form.html')


@login_required
def knowledge_post_edit(request, post_id):
    """JT Admin: Edit a knowledge base post."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    post = get_object_or_404(KnowledgePost, id=post_id)

    if request.method == 'POST':
        # Track if post was previously draft or scheduled
        was_draft = post.is_draft
        was_scheduled = post.scheduled_at and post.scheduled_at > timezone.now()

        post.title = request.POST.get('title', '').strip()
        post.content = request.POST.get('content', '').strip()
        post.video_url = request.POST.get('video_url', '').strip()
        post.is_draft = request.POST.get('is_draft') == 'on'
        send_notification = request.POST.get('send_notification') == 'on'
        scheduled_date = request.POST.get('scheduled_date', '').strip()
        scheduled_time = request.POST.get('scheduled_time', '').strip()

        if not post.title:
            return render(request, 'education/knowledge_post_form.html', {
                'error': 'A cím megadása kötelező.',
                'post': post,
            })

        is_scheduled_future = False
        # Handle scheduling
        if scheduled_date and scheduled_time and not post.is_draft:
            from datetime import datetime
            try:
                scheduled_datetime = datetime.strptime(
                    f"{scheduled_date} {scheduled_time}",
                    "%Y-%m-%d %H:%M"
                )
                post.scheduled_at = timezone.make_aware(scheduled_datetime)
                is_scheduled_future = post.scheduled_at > timezone.now()
            except ValueError:
                pass
        else:
            post.scheduled_at = None

        # Handle thumbnail
        if 'thumbnail' in request.FILES:
            post.thumbnail = request.FILES['thumbnail']

        # Handle remove thumbnail
        if request.POST.get('remove_thumbnail') == 'on' and post.thumbnail:
            post.thumbnail.delete(save=False)
            post.thumbnail = None

        post.save()

        # Handle new file attachments
        for file in request.FILES.getlist('attachments'):
            KnowledgeAttachment.objects.create(
                post=post,
                file=file,
                original_filename=file.name
            )

        # Handle attachment deletions
        delete_attachments = request.POST.getlist('delete_attachment')
        if delete_attachments:
            for att_id in delete_attachments:
                try:
                    att = KnowledgeAttachment.objects.get(id=att_id, post=post)
                    att.file.delete(save=False)
                    att.delete()
                except KnowledgeAttachment.DoesNotExist:
                    pass

        # Send notification if just published (was draft/scheduled, now public)
        just_published = (was_draft or was_scheduled) and not post.is_draft and not is_scheduled_future
        if send_notification and just_published:
            _notify_users_about_knowledge_post(post)

        return redirect('education:knowledge_base')

    return render(request, 'education/knowledge_post_form.html', {'post': post})


@login_required
def api_knowledge_post_delete(request, post_id):
    """JT Admin: Delete a knowledge base post."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        post = KnowledgePost.objects.get(id=post_id)
        post.is_active = False
        post.save()
        return JsonResponse({'success': True})
    except KnowledgePost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_knowledge_post_move(request, post_id, direction):
    """JT Admin: Move a knowledge base post up or down."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        post = KnowledgePost.objects.get(id=post_id, is_active=True)

        if direction == 'up':
            # Find the post with the next lower order value
            prev_post = KnowledgePost.objects.filter(
                is_active=True,
                order__lt=post.order
            ).order_by('-order').first()

            if prev_post:
                # Swap order values
                post.order, prev_post.order = prev_post.order, post.order
                post.save()
                prev_post.save()
        elif direction == 'down':
            # Find the post with the next higher order value
            next_post = KnowledgePost.objects.filter(
                is_active=True,
                order__gt=post.order
            ).order_by('order').first()

            if next_post:
                # Swap order values
                post.order, next_post.order = next_post.order, post.order
                post.save()
                next_post.save()

        return JsonResponse({'success': True})
    except KnowledgePost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_knowledge_post_toggle_visibility(request, post_id):
    """JT Admin: Toggle visibility of a knowledge base post."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        post = KnowledgePost.objects.get(id=post_id, is_active=True)
        post.is_hidden = not post.is_hidden
        post.save()
        return JsonResponse({'success': True, 'is_hidden': post.is_hidden})
    except KnowledgePost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


# News views
@login_required
def news_create(request):
    """Content creator: Create a new news post."""
    if not request.user.has_content_module:
        return HttpResponseForbidden('Nincs jogosultságod.')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()
        is_published = request.POST.get('is_published') == 'on'
        is_pinned = request.POST.get('is_pinned') == 'on'
        scheduled_date = request.POST.get('scheduled_date', '').strip()
        scheduled_time = request.POST.get('scheduled_time', '').strip()

        if not title or not content:
            return render(request, 'education/news_form.html', {
                'error': 'A cím és tartalom megadása kötelező.',
            })

        news = News(
            title=title,
            content=content,
            is_published=is_published,
            is_pinned=is_pinned,
            created_by=request.user,
        )

        # Admin-only: system news flag
        if request.user.is_admin_user:
            news.is_system_news = request.POST.get('is_system_news') == 'on'

        # Handle scheduling
        if scheduled_date and scheduled_time:
            from datetime import datetime
            try:
                scheduled_datetime = datetime.strptime(
                    f"{scheduled_date} {scheduled_time}",
                    "%Y-%m-%d %H:%M"
                )
                news.scheduled_at = timezone.make_aware(scheduled_datetime)
            except ValueError:
                pass

        if is_published:
            news.scheduled_at = None  # Clear scheduling if publishing now

            # Admin-only: custom published date (can be in the past)
            published_date = request.POST.get('published_date', '').strip()
            published_time = request.POST.get('published_time', '').strip()
            if request.user.is_admin_user and published_date and published_time:
                from datetime import datetime
                try:
                    published_datetime = datetime.strptime(
                        f"{published_date} {published_time}",
                        "%Y-%m-%d %H:%M"
                    )
                    news.published_at = timezone.make_aware(published_datetime)
                except ValueError:
                    news.published_at = timezone.now()
            else:
                news.published_at = timezone.now()

        # Handle image
        if 'image' in request.FILES:
            news.image = request.FILES['image']

        news.save()

        # Send notification if publishing immediately
        if is_published:
            _notify_users_about_news(news)

        return redirect('accounts:dashboard')

    return render(request, 'education/news_form.html')


@login_required
def news_edit(request, news_id):
    """Content creator: Edit a news post."""
    if not request.user.has_content_module:
        return HttpResponseForbidden('Nincs jogosultságod.')

    news = get_object_or_404(News, id=news_id)

    # Only creator or admin can edit
    if news.created_by != request.user and not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    if request.method == 'POST':
        news.title = request.POST.get('title', '').strip()
        news.content = request.POST.get('content', '').strip()
        was_published = news.is_published
        news.is_published = request.POST.get('is_published') == 'on'
        news.is_pinned = request.POST.get('is_pinned') == 'on'
        scheduled_date = request.POST.get('scheduled_date', '').strip()
        scheduled_time = request.POST.get('scheduled_time', '').strip()

        # Admin-only: system news flag
        if request.user.is_admin_user:
            news.is_system_news = request.POST.get('is_system_news') == 'on'

        if not news.title or not news.content:
            return render(request, 'education/news_form.html', {
                'error': 'A cím és tartalom megadása kötelező.',
                'news': news,
            })

        # Handle scheduling
        if scheduled_date and scheduled_time:
            from datetime import datetime
            try:
                scheduled_datetime = datetime.strptime(
                    f"{scheduled_date} {scheduled_time}",
                    "%Y-%m-%d %H:%M"
                )
                news.scheduled_at = timezone.make_aware(scheduled_datetime)
            except ValueError:
                pass
        else:
            news.scheduled_at = None

        # Admin-only: custom published date (can be in the past)
        published_date = request.POST.get('published_date', '').strip()
        published_time = request.POST.get('published_time', '').strip()
        if request.user.is_admin_user and published_date and published_time:
            from datetime import datetime
            try:
                published_datetime = datetime.strptime(
                    f"{published_date} {published_time}",
                    "%Y-%m-%d %H:%M"
                )
                news.published_at = timezone.make_aware(published_datetime)
            except ValueError:
                pass

        # Set published_at if just published (and no custom date was set by admin)
        if news.is_published and not was_published and not news.published_at:
            news.published_at = timezone.now()
            news.scheduled_at = None  # Clear scheduling if publishing now

        # Handle image
        if 'image' in request.FILES:
            news.image = request.FILES['image']

        news.save()

        # Send notification if just published
        if news.is_published and not was_published:
            _notify_users_about_news(news)

        return redirect('accounts:dashboard')

    return render(request, 'education/news_form.html', {'news': news})


@login_required
def api_news_delete(request, news_id):
    """Content creator: Delete a news post."""
    if not request.user.has_content_module:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        news = News.objects.get(id=news_id)

        # Only creator or admin can delete
        if news.created_by != request.user and not request.user.is_admin_user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        news.delete()
        return JsonResponse({'success': True})
    except News.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_news_publish(request, news_id):
    """Content creator: Publish/unpublish a news post."""
    if not request.user.has_content_module:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        news = News.objects.get(id=news_id)

        # Only creator or admin can publish
        if news.created_by != request.user and not request.user.is_admin_user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        was_published = news.is_published
        news.is_published = not news.is_published
        if news.is_published and not news.published_at:
            news.published_at = timezone.now()
        news.save()

        # Send notification if just published
        if news.is_published and not was_published:
            _notify_users_about_news(news)

        return JsonResponse({'success': True, 'is_published': news.is_published})
    except News.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_news_toggle_visibility(request, news_id):
    """Content creator: Toggle visibility of a news post."""
    if not request.user.has_content_module:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        news = News.objects.get(id=news_id)

        # Only creator or admin can toggle visibility
        if news.created_by != request.user and not request.user.is_admin_user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        news.is_hidden = not news.is_hidden
        news.save()
        return JsonResponse({'success': True, 'is_hidden': news.is_hidden})
    except News.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_news_move(request, news_id, direction):
    """Content creator: Move a news post up or down."""
    if not request.user.has_content_module:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        news = News.objects.get(id=news_id)

        # Only creator or admin can move
        if news.created_by != request.user and not request.user.is_admin_user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        if direction == 'up':
            # Find the news with the next lower order value
            prev_news = News.objects.filter(
                order__lt=news.order
            ).order_by('-order').first()

            if prev_news:
                news.order, prev_news.order = prev_news.order, news.order
                news.save()
                prev_news.save()
        elif direction == 'down':
            # Find the news with the next higher order value
            next_news = News.objects.filter(
                order__gt=news.order
            ).order_by('order').first()

            if next_news:
                news.order, next_news.order = next_news.order, news.order
                news.save()
                next_news.save()

        return JsonResponse({'success': True})
    except News.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_news_toggle_pin(request, news_id):
    """Content creator: Toggle pin status of a news post."""
    if not request.user.has_content_module:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        news = News.objects.get(id=news_id)

        # Only creator or admin can toggle pin
        if news.created_by != request.user and not request.user.is_admin_user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        news.is_pinned = not news.is_pinned
        news.save()
        return JsonResponse({'success': True, 'is_pinned': news.is_pinned})
    except News.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


# Document Library views
@login_required
def document_library(request):
    """Show document library with categories."""
    categories = DocumentCategory.objects.filter(is_active=True).prefetch_related('documents')

    # Filter documents to only active ones
    for category in categories:
        category.active_documents = category.documents.filter(is_active=True)

    can_edit = request.user.is_jt_admin

    context = {
        'categories': categories,
        'can_edit': can_edit,
    }
    return render(request, 'education/document_library.html', context)


CATEGORY_ICONS = ['folder', 'folder_special', 'school', 'sports', 'sports_basketball', 'description', 'picture_as_pdf', 'video_library', 'link', 'rule', 'gavel', 'medical_services', 'fitness_center', 'emoji_events', 'groups', 'calendar_month']
CATEGORY_COLORS = ['#3b82f6', '#8b5cf6', '#ec4899', '#ef4444', '#f97316', '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#6366f1', '#6b7280', '#1e293b']


@login_required
def document_category_create(request):
    """JT Admin: Create a new document category."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        icon = request.POST.get('icon', 'folder').strip()
        color = request.POST.get('color', '#3b82f6').strip()

        if not name:
            return render(request, 'education/document_category_form.html', {
                'error': 'A név megadása kötelező.',
                'icons': CATEGORY_ICONS,
                'colors': CATEGORY_COLORS,
            })

        max_order = DocumentCategory.objects.filter(is_active=True).aggregate(Max('order'))['order__max'] or 0

        category = DocumentCategory.objects.create(
            name=name,
            description=description,
            icon=icon,
            color=color,
            order=max_order + 1,
            created_by=request.user,
        )

        return redirect('education:document_library')

    return render(request, 'education/document_category_form.html', {
        'icons': CATEGORY_ICONS,
        'colors': CATEGORY_COLORS,
    })


@login_required
def document_category_edit(request, category_id):
    """JT Admin: Edit a document category."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    category = get_object_or_404(DocumentCategory, id=category_id)

    if request.method == 'POST':
        category.name = request.POST.get('name', '').strip()
        category.description = request.POST.get('description', '').strip()
        category.icon = request.POST.get('icon', 'folder').strip()
        category.color = request.POST.get('color', '#3b82f6').strip()

        if not category.name:
            return render(request, 'education/document_category_form.html', {
                'error': 'A név megadása kötelező.',
                'category': category,
                'icons': CATEGORY_ICONS,
                'colors': CATEGORY_COLORS,
            })

        category.save()
        return redirect('education:document_library')

    return render(request, 'education/document_category_form.html', {
        'category': category,
        'icons': CATEGORY_ICONS,
        'colors': CATEGORY_COLORS,
    })


@login_required
def api_document_category_delete(request, category_id):
    """JT Admin: Delete a document category."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        category = DocumentCategory.objects.get(id=category_id)
        category.is_active = False
        category.save()
        # Also deactivate all documents in the category
        Document.objects.filter(category=category).update(is_active=False)
        return JsonResponse({'success': True})
    except DocumentCategory.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_document_category_move(request, category_id, direction):
    """JT Admin: Move a category up or down."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        category = DocumentCategory.objects.get(id=category_id, is_active=True)

        if direction == 'up':
            prev_category = DocumentCategory.objects.filter(
                is_active=True,
                order__lt=category.order
            ).order_by('-order').first()

            if prev_category:
                category.order, prev_category.order = prev_category.order, category.order
                category.save()
                prev_category.save()
        elif direction == 'down':
            next_category = DocumentCategory.objects.filter(
                is_active=True,
                order__gt=category.order
            ).order_by('order').first()

            if next_category:
                category.order, next_category.order = next_category.order, category.order
                category.save()
                next_category.save()

        return JsonResponse({'success': True})
    except DocumentCategory.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def document_create(request):
    """JT Admin: Create a new document."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    categories = DocumentCategory.objects.filter(is_active=True)

    if request.method == 'POST':
        category_id = request.POST.get('category')
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        document_type = request.POST.get('document_type', 'file')
        url = request.POST.get('url', '').strip()

        if not category_id or not title:
            return render(request, 'education/document_form.html', {
                'error': 'A kategória és cím megadása kötelező.',
                'categories': categories,
            })

        try:
            category = DocumentCategory.objects.get(id=category_id)
        except DocumentCategory.DoesNotExist:
            return render(request, 'education/document_form.html', {
                'error': 'A kiválasztott kategória nem található.',
                'categories': categories,
            })

        max_order = Document.objects.filter(category=category, is_active=True).aggregate(Max('order'))['order__max'] or 0

        document = Document(
            category=category,
            title=title,
            description=description,
            document_type=document_type,
            order=max_order + 1,
            created_by=request.user,
        )

        if document_type == 'file':
            if 'file' not in request.FILES:
                return render(request, 'education/document_form.html', {
                    'error': 'A fájl feltöltése kötelező.',
                    'categories': categories,
                })
            document.file = request.FILES['file']
            document.original_filename = request.FILES['file'].name
        else:
            if not url:
                return render(request, 'education/document_form.html', {
                    'error': 'Az URL megadása kötelező.',
                    'categories': categories,
                })
            document.url = url

        document.save()
        return redirect('education:document_library')

    return render(request, 'education/document_form.html', {'categories': categories})


@login_required
def document_edit(request, document_id):
    """JT Admin: Edit a document."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    document = get_object_or_404(Document, id=document_id)
    categories = DocumentCategory.objects.filter(is_active=True)

    if request.method == 'POST':
        category_id = request.POST.get('category')
        document.title = request.POST.get('title', '').strip()
        document.description = request.POST.get('description', '').strip()
        url = request.POST.get('url', '').strip()

        if not category_id or not document.title:
            return render(request, 'education/document_form.html', {
                'error': 'A kategória és cím megadása kötelező.',
                'document': document,
                'categories': categories,
            })

        try:
            document.category = DocumentCategory.objects.get(id=category_id)
        except DocumentCategory.DoesNotExist:
            return render(request, 'education/document_form.html', {
                'error': 'A kiválasztott kategória nem található.',
                'document': document,
                'categories': categories,
            })

        if document.document_type == 'file':
            if 'file' in request.FILES:
                # Delete old file
                if document.file:
                    document.file.delete(save=False)
                document.file = request.FILES['file']
                document.original_filename = request.FILES['file'].name
        else:
            if not url:
                return render(request, 'education/document_form.html', {
                    'error': 'Az URL megadása kötelező.',
                    'document': document,
                    'categories': categories,
                })
            document.url = url

        document.save()
        return redirect('education:document_library')

    return render(request, 'education/document_form.html', {
        'document': document,
        'categories': categories,
    })


@login_required
def api_document_delete(request, document_id):
    """JT Admin: Delete a document."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        document = Document.objects.get(id=document_id)
        document.is_active = False
        document.save()
        return JsonResponse({'success': True})
    except Document.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)


@login_required
def api_document_move(request, document_id, direction):
    """JT Admin: Move a document up or down within its category."""
    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        document = Document.objects.get(id=document_id, is_active=True)

        if direction == 'up':
            prev_doc = Document.objects.filter(
                category=document.category,
                is_active=True,
                order__lt=document.order
            ).order_by('-order').first()

            if prev_doc:
                document.order, prev_doc.order = prev_doc.order, document.order
                document.save()
                prev_doc.save()
        elif direction == 'down':
            next_doc = Document.objects.filter(
                category=document.category,
                is_active=True,
                order__gt=document.order
            ).order_by('order').first()

            if next_doc:
                document.order, next_doc.order = next_doc.order, document.order
                document.save()
                next_doc.save()

        return JsonResponse({'success': True})
    except Document.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
