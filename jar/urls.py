"""
URL configuration for JAR project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
from django.urls import path, include


# Custom admin site that doesn't require re-authentication
class JARAdminSite(admin.AdminSite):
    site_header = 'JAR Adatbázis'
    site_title = 'JAR Admin'
    index_title = 'Adatbázis kezelés'

    def has_permission(self, request):
        """
        Allow access if user is authenticated and is admin.
        No separate admin login required.
        """
        return (
            request.user.is_active and
            (request.user.is_superuser or request.user.is_admin_user)
        )


# Replace default admin site
admin.site = JARAdminSite(name='jar_admin')
admin.autodiscover()


def admin_guard(request):
    """Block direct admin access in production."""
    raise Http404("Not found")


urlpatterns = [
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
