from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    """Teljes körű eseménynapló a rendszer minden műveletéhez."""

    class Category(models.TextChoices):
        AUTH = 'auth', 'Hitelesítés'
        MATCH = 'match', 'Mérkőzés'
        ASSIGNMENT = 'assignment', 'Kiírás'
        DECLARATION = 'declaration', 'Bejelentés'
        DOCUMENT = 'document', 'Dokumentum'
        USER = 'user', 'Felhasználó'
        TRAVEL = 'travel', 'Útiköltség'
        REPORT = 'report', 'Jelentés'
        SYSTEM = 'system', 'Rendszer'
        EMAIL = 'email', 'Email'

    class Action(models.TextChoices):
        CREATE = 'create', 'Létrehozás'
        UPDATE = 'update', 'Módosítás'
        DELETE = 'delete', 'Törlés'
        LOGIN = 'login', 'Bejelentkezés'
        LOGOUT = 'logout', 'Kijelentkezés'
        LOGIN_FAILED = 'login_failed', 'Sikertelen bejelentkezés'
        VIEW = 'view', 'Megtekintés'
        SEND = 'send', 'Küldés'
        ACCEPT = 'accept', 'Elfogadás'
        REJECT = 'reject', 'Elutasítás'
        CANCEL = 'cancel', 'Lemondás'
        EXPORT = 'export', 'Exportálás'
        UPLOAD = 'upload', 'Feltöltés'
        DOWNLOAD = 'download', 'Letöltés'
        PUBLISH = 'publish', 'Közzététel'
        DRAFT = 'draft', 'Piszkozat mentés'
        PASSWORD_RESET = 'password_reset', 'Jelszó visszaállítás'
        PASSWORD_CHANGE = 'password_change', 'Jelszó változtatás'

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='Időpont')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='Felhasználó'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP cím')
    user_agent = models.CharField(max_length=500, blank=True, verbose_name='Böngésző')

    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        db_index=True,
        verbose_name='Kategória'
    )
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        db_index=True,
        verbose_name='Művelet'
    )

    object_type = models.CharField(max_length=100, blank=True, verbose_name='Objektum típus')
    object_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='Objektum ID')
    object_repr = models.CharField(max_length=200, blank=True, verbose_name='Objektum neve')

    description = models.TextField(verbose_name='Leírás')
    changes = models.JSONField(null=True, blank=True, verbose_name='Változások')
    extra_data = models.JSONField(null=True, blank=True, verbose_name='Extra adatok')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Napló bejegyzés'
        verbose_name_plural = 'Napló bejegyzések'
        indexes = [
            models.Index(fields=['category', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['object_type', 'object_id']),
        ]

    def __str__(self):
        user_str = self.user.get_full_name() if self.user else 'Ismeretlen'
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {user_str} - {self.get_action_display()}"

    @property
    def action_icon(self):
        """Material Icons ikon a művelethez."""
        icons = {
            'create': 'add_circle',
            'update': 'edit',
            'delete': 'delete',
            'login': 'login',
            'logout': 'logout',
            'login_failed': 'error',
            'view': 'visibility',
            'send': 'send',
            'accept': 'check_circle',
            'reject': 'cancel',
            'cancel': 'block',
            'export': 'download',
            'upload': 'upload',
            'download': 'download',
            'publish': 'publish',
            'draft': 'save',
            'password_reset': 'lock_reset',
            'password_change': 'key',
        }
        return icons.get(self.action, 'info')

    @property
    def action_color(self):
        """CSS szín a művelethez."""
        colors = {
            'create': 'var(--success-color)',
            'update': 'var(--accent-color)',
            'delete': 'var(--danger-color)',
            'login': 'var(--success-color)',
            'logout': 'var(--text-secondary)',
            'login_failed': 'var(--danger-color)',
            'view': 'var(--text-secondary)',
            'send': 'var(--accent-color)',
            'accept': 'var(--success-color)',
            'reject': 'var(--danger-color)',
            'cancel': 'var(--warning-color)',
            'export': 'var(--accent-color)',
            'upload': 'var(--accent-color)',
            'download': 'var(--text-secondary)',
            'publish': 'var(--success-color)',
            'draft': 'var(--warning-color)',
            'password_reset': 'var(--warning-color)',
            'password_change': 'var(--accent-color)',
        }
        return colors.get(self.action, 'var(--text-secondary)')
