from django.conf import settings
from django.db import models


class DocumentCategory(models.Model):
    """Category for organizing documents."""
    name = models.CharField(max_length=100, verbose_name='Név')
    description = models.TextField(blank=True, verbose_name='Leírás')
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')

    class Meta:
        verbose_name = 'Dokumentum kategória'
        verbose_name_plural = 'Dokumentum kategóriák'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Document(models.Model):
    """
    Official JB document with version control.
    """
    category = models.ForeignKey(
        DocumentCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='documents',
        verbose_name='Kategória'
    )
    title = models.CharField(max_length=200, verbose_name='Cím')
    description = models.TextField(blank=True, verbose_name='Leírás')
    is_active = models.BooleanField(default=True, verbose_name='Aktív')

    # Access control
    is_public = models.BooleanField(
        default=False,
        verbose_name='Publikus',
        help_text='Mindenki láthatja, nem csak bejelentkezett felhasználók'
    )
    requires_jb_access = models.BooleanField(
        default=False,
        verbose_name='JB hozzáférés szükséges',
        help_text='Csak JB tagok láthatják'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dokumentum'
        verbose_name_plural = 'Dokumentumok'
        ordering = ['category', 'title']

    def __str__(self):
        return self.title

    @property
    def current_version(self):
        return self.versions.first()


class DocumentVersion(models.Model):
    """
    Version of a document (for version control).
    """
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='versions',
        verbose_name='Dokumentum'
    )
    version_number = models.CharField(
        max_length=20,
        verbose_name='Verziószám'
    )
    file = models.FileField(
        upload_to='documents/',
        verbose_name='Fájl'
    )
    changelog = models.TextField(
        blank=True,
        verbose_name='Változások'
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_documents',
        verbose_name='Feltöltötte'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Dokumentum verzió'
        verbose_name_plural = 'Dokumentum verziók'
        ordering = ['-uploaded_at']
        unique_together = ['document', 'version_number']

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"


class Notification(models.Model):
    """
    System notification/message for users.
    """

    class Type(models.TextChoices):
        INFO = 'info', 'Információ'
        WARNING = 'warning', 'Figyelmeztetés'
        SUCCESS = 'success', 'Sikeres'
        ERROR = 'error', 'Hiba'
        MATCH = 'match', 'Mérkőzés'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Címzett'
    )
    title = models.CharField(max_length=200, verbose_name='Cím')
    message = models.TextField(verbose_name='Üzenet')
    notification_type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.INFO,
        verbose_name='Típus'
    )
    is_read = models.BooleanField(default=False, verbose_name='Olvasott')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='Olvasva')

    # Optional link to related object
    link = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Link'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Értesítés'
        verbose_name_plural = 'Értesítések'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient} - {self.title}"
