"""
URL configuration for JAR project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404, JsonResponse
from django.urls import path, include
from django.db import connection


# Customize default admin site
admin.site.site_header = 'JAR Adatbázis'
admin.site.site_title = 'JAR Admin'
admin.site.index_title = 'Adatbázis kezelés'

# Store original has_permission
_original_has_permission = admin.AdminSite.has_permission

def custom_has_permission(self, request):
    """Allow access only if user is super admin (or Django superuser)."""
    if not request.user.is_active:
        return False
    if request.user.is_superuser:
        return True
    # Only super admins can access Django admin, not regular admins
    if hasattr(request.user, 'is_super_admin') and request.user.is_super_admin:
        return True
    return False

admin.site.has_permission = lambda request: custom_has_permission(admin.site, request)


def admin_guard(request):
    """Block direct admin access in production."""
    raise Http404("Not found")


def health_check(request):
    """Health check endpoint for monitoring and load balancers."""
    try:
        # Check database connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({
            'status': 'healthy',
            'database': 'connected'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e)
        }, status=503)


urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('', include('accounts.urls', namespace='accounts')),
    path('matches/', include('matches.urls', namespace='matches')),
    path('billing/', include('billing.urls', namespace='billing')),
    path('referees/', include('referees.urls', namespace='referees')),
    path('education/', include('education.urls', namespace='education')),
    path('documents/', include('documents.urls', namespace='documents')),
    path('audit/', include('audit.urls', namespace='audit')),
]

# Admin URL configuration
if settings.ADMIN_ENABLED:
    # Use the secret admin path
    urlpatterns.append(
        path(settings.ADMIN_URL_PATH, admin.site.urls),
    )

    # In development, also allow /admin/ for convenience
    if settings.DEBUG:
        urlpatterns.append(
            path('admin/', admin.site.urls),
        )
    else:
        # Block the standard /admin/ path in production
        urlpatterns.append(
            path('admin/', admin_guard),
        )

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
