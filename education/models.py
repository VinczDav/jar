from django.conf import settings
from django.db import models
from referees.models import Referee


class KnowledgePost(models.Model):
    """Knowledge base post for educational content."""

    title = models.CharField(max_length=200, verbose_name='Cím')
    content = models.TextField(blank=True, verbose_name='Tartalom')
    thumbnail = models.ImageField(
        upload_to='knowledge/thumbnails/',
        blank=True,
        null=True,
        verbose_name='Borítókép'
    )
    video_url = models.URLField(
        blank=True,
        verbose_name='YouTube videó URL',
        help_text='YouTube videó link (pl. https://youtube.com/watch?v=...)'
    )
    is_draft = models.BooleanField(
        default=False,
        verbose_name='Piszkozat',
        help_text='Piszkozatként mentett bejegyzéseket csak adminok látják'
    )
    scheduled_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Időzített közzététel',
        help_text='Ha beállítod, a bejegyzés automatikusan megjelenik a megadott időpontban'
    )
    is_hidden = models.BooleanField(
        default=False,
        verbose_name='Elrejtett',
        help_text='Elrejtett bejegyzéseket csak adminok látják'
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')
    is_active = models.BooleanField(default=True, verbose_name='Aktív')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='knowledge_posts',
        verbose_name='Létrehozta'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tudástár bejegyzés'
        verbose_name_plural = 'Tudástár bejegyzések'
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.title

    @property
    def youtube_embed_url(self):
        """Convert YouTube URL to embed URL."""
        if not self.video_url:
            return None
        url = self.video_url
        # Handle various YouTube URL formats
        if 'youtube.com/watch?v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
            return f'https://www.youtube.com/embed/{video_id}'
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
            return f'https://www.youtube.com/embed/{video_id}'
        elif 'youtube.com/embed/' in url:
            return url
        return None

    @property
    def youtube_thumbnail_url(self):
        """Get YouTube video thumbnail URL."""
        if not self.video_url:
            return None
        url = self.video_url
        video_id = None
        if 'youtube.com/watch?v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
        elif 'youtube.com/embed/' in url:
            video_id = url.split('embed/')[1].split('?')[0]
        if video_id:
            return f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg'
        return None


class KnowledgeAttachment(models.Model):
    """File attachment for a knowledge post."""
    post = models.ForeignKey(
        KnowledgePost,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='Bejegyzés'
    )
    file = models.FileField(
        upload_to='knowledge/attachments/',
        verbose_name='Fájl'
    )
    original_filename = models.CharField(
        max_length=255,
        verbose_name='Eredeti fájlnév'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Csatolmány'
        verbose_name_plural = 'Csatolmányok'
        ordering = ['uploaded_at']

    def __str__(self):
        return self.original_filename


class News(models.Model):
    """News/announcement post."""
    title = models.CharField(max_length=200, verbose_name='Cím')
    content = models.TextField(verbose_name='Tartalom')
    image = models.ImageField(
        upload_to='news/',
        blank=True,
        null=True,
        verbose_name='Kép'
    )
    is_published = models.BooleanField(default=False, verbose_name='Közzétéve')
    is_pinned = models.BooleanField(default=False, verbose_name='Kitűzött')
    is_hidden = models.BooleanField(
        default=False,
        verbose_name='Elrejtett',
        help_text='Elrejtett híreket csak tartalomkészítők látják'
    )
    is_system_news = models.BooleanField(
        default=False,
        verbose_name='Rendszerhír',
        help_text='Rendszerhír esetén a szerző "JAR Rendszer"-ként jelenik meg'
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Időzített közzététel',
        help_text='Ha be van állítva, a hír automatikusan közzé lesz téve ezen időpontban'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='news_posts',
        verbose_name='Létrehozta'
    )
    published_at = models.DateTimeField(null=True, blank=True, verbose_name='Közzététel ideje')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Hír'
        verbose_name_plural = 'Hírek'
        ordering = ['-is_pinned', 'order', '-published_at', '-created_at']

    def __str__(self):
        return self.title

    @property
    def is_scheduled(self):
        """Check if news is scheduled for future publication."""
        from django.utils import timezone
        return self.scheduled_at and self.scheduled_at > timezone.now() and not self.is_published

    @property
    def is_visible(self):
        """Check if news should be visible to regular users."""
        from django.utils import timezone
        if self.is_published:
            return True
        if self.scheduled_at and self.scheduled_at <= timezone.now():
            return True
        return False


class Course(models.Model):
    """Educational course/training material."""
    title = models.CharField(max_length=200, verbose_name='Cím')
    description = models.TextField(blank=True, verbose_name='Leírás')
    is_active = models.BooleanField(default=True, verbose_name='Aktív')
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Kurzus'
        verbose_name_plural = 'Kurzusok'
        ordering = ['order', 'title']

    def __str__(self):
        return self.title


class Lesson(models.Model):
    """Individual lesson within a course."""
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='lessons',
        verbose_name='Kurzus'
    )
    title = models.CharField(max_length=200, verbose_name='Cím')
    content = models.TextField(verbose_name='Tartalom')
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Lecke'
        verbose_name_plural = 'Leckék'
        ordering = ['course', 'order']

    def __str__(self):
        return f"{self.course.title} - {self.title}"


class LessonAttachment(models.Model):
    """File attachment for a lesson."""
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='Lecke'
    )
    title = models.CharField(max_length=200, verbose_name='Cím')
    file = models.FileField(
        upload_to='education/attachments/',
        verbose_name='Fájl'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Csatolmány'
        verbose_name_plural = 'Csatolmányok'

    def __str__(self):
        return self.title


class Exam(models.Model):
    """Exam/test associated with a course."""
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='exams',
        verbose_name='Kurzus'
    )
    title = models.CharField(max_length=200, verbose_name='Cím')
    description = models.TextField(blank=True, verbose_name='Leírás')
    passing_score = models.PositiveIntegerField(
        default=60,
        verbose_name='Minimum pontszám (%)'
    )
    time_limit_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Időkorlát (perc)'
    )
    is_active = models.BooleanField(default=True, verbose_name='Aktív')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Vizsga'
        verbose_name_plural = 'Vizsgák'

    def __str__(self):
        return f"{self.course.title} - {self.title}"


class Question(models.Model):
    """Multiple choice question for an exam."""
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='questions',
        verbose_name='Vizsga'
    )
    text = models.TextField(verbose_name='Kérdés')
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')
    points = models.PositiveIntegerField(default=1, verbose_name='Pontszám')

    class Meta:
        verbose_name = 'Kérdés'
        verbose_name_plural = 'Kérdések'
        ordering = ['exam', 'order']

    def __str__(self):
        return f"{self.exam.title} - Q{self.order}"


class Answer(models.Model):
    """Answer option for a question."""
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='answers',
        verbose_name='Kérdés'
    )
    text = models.CharField(max_length=500, verbose_name='Válasz')
    is_correct = models.BooleanField(default=False, verbose_name='Helyes')
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')

    class Meta:
        verbose_name = 'Válasz'
        verbose_name_plural = 'Válaszok'
        ordering = ['question', 'order']

    def __str__(self):
        return f"{self.question} - {self.text[:50]}"


class ExamAttempt(models.Model):
    """Record of a referee's exam attempt."""

    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'Folyamatban'
        COMPLETED = 'completed', 'Befejezett'
        PASSED = 'passed', 'Sikeres'
        FAILED = 'failed', 'Sikertelen'

    referee = models.ForeignKey(
        Referee,
        on_delete=models.CASCADE,
        related_name='exam_attempts',
        verbose_name='Játékvezető'
    )
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='attempts',
        verbose_name='Vizsga'
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Pontszám'
    )
    max_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Max pontszám'
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Százalék'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
        verbose_name='Státusz'
    )

    class Meta:
        verbose_name = 'Vizsgakísérlet'
        verbose_name_plural = 'Vizsgakísérletek'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.referee} - {self.exam} - {self.status}"


class AttemptAnswer(models.Model):
    """Record of answer given during an exam attempt."""
    attempt = models.ForeignKey(
        ExamAttempt,
        on_delete=models.CASCADE,
        related_name='given_answers',
        verbose_name='Kísérlet'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        verbose_name='Kérdés'
    )
    selected_answer = models.ForeignKey(
        Answer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name='Választott válasz'
    )
    is_correct = models.BooleanField(default=False, verbose_name='Helyes')

    class Meta:
        verbose_name = 'Adott válasz'
        verbose_name_plural = 'Adott válaszok'
        unique_together = ['attempt', 'question']

    def __str__(self):
        return f"{self.attempt} - {self.question}"


class DocumentCategory(models.Model):
    """Category/folder for organizing documents."""
    name = models.CharField(max_length=100, verbose_name='Név')
    description = models.TextField(blank=True, verbose_name='Leírás')
    icon = models.CharField(
        max_length=50,
        default='folder',
        verbose_name='Ikon',
        help_text='Material Icons név (pl. folder, school, sports)'
    )
    color = models.CharField(
        max_length=20,
        default='#3b82f6',
        verbose_name='Szín',
        help_text='Hex színkód (pl. #3b82f6)'
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')
    is_active = models.BooleanField(default=True, verbose_name='Aktív')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='document_categories',
        verbose_name='Létrehozta'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dokumentum kategória'
        verbose_name_plural = 'Dokumentum kategóriák'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Document(models.Model):
    """Document item that can be a file, link, or YouTube video."""

    class DocumentType(models.TextChoices):
        FILE = 'file', 'Fájl'
        LINK = 'link', 'Link'
        YOUTUBE = 'youtube', 'YouTube'

    category = models.ForeignKey(
        DocumentCategory,
        on_delete=models.CASCADE,
        related_name='documents',
        verbose_name='Kategória'
    )
    title = models.CharField(max_length=200, verbose_name='Cím')
    description = models.TextField(blank=True, verbose_name='Leírás')
    document_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.FILE,
        verbose_name='Típus'
    )
    # For file uploads
    file = models.FileField(
        upload_to='documents/',
        blank=True,
        null=True,
        verbose_name='Fájl'
    )
    original_filename = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Eredeti fájlnév'
    )
    # For links and YouTube
    url = models.URLField(blank=True, verbose_name='URL')
    order = models.PositiveIntegerField(default=0, verbose_name='Sorrend')
    is_active = models.BooleanField(default=True, verbose_name='Aktív')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='documents',
        verbose_name='Létrehozta'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dokumentum'
        verbose_name_plural = 'Dokumentumok'
        ordering = ['category', 'order', 'title']

    def __str__(self):
        return self.title

    @property
    def file_extension(self):
        """Get file extension for icon display."""
        if self.document_type == self.DocumentType.FILE and self.original_filename:
            ext = self.original_filename.lower().split('.')[-1] if '.' in self.original_filename else ''
            return ext
        return ''

    @property
    def file_icon(self):
        """Get Material Icons name based on file type."""
        if self.document_type == self.DocumentType.YOUTUBE:
            return 'smart_display'
        if self.document_type == self.DocumentType.LINK:
            return 'link'
        ext = self.file_extension
        if ext == 'pdf':
            return 'picture_as_pdf'
        if ext in ['doc', 'docx']:
            return 'description'
        if ext in ['xls', 'xlsx']:
            return 'table_chart'
        if ext in ['ppt', 'pptx']:
            return 'slideshow'
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            return 'image'
        if ext in ['mp4', 'avi', 'mov', 'webm']:
            return 'movie'
        if ext in ['mp3', 'wav', 'ogg']:
            return 'audio_file'
        if ext in ['zip', 'rar', '7z']:
            return 'folder_zip'
        return 'insert_drive_file'

    @property
    def file_color(self):
        """Get color based on file type."""
        if self.document_type == self.DocumentType.YOUTUBE:
            return '#ff0000'
        if self.document_type == self.DocumentType.LINK:
            return '#3b82f6'
        ext = self.file_extension
        if ext == 'pdf':
            return '#ef4444'
        if ext in ['doc', 'docx']:
            return '#2563eb'
        if ext in ['xls', 'xlsx']:
            return '#16a34a'
        if ext in ['ppt', 'pptx']:
            return '#ea580c'
        return '#6b7280'

    @property
    def youtube_embed_url(self):
        """Convert YouTube URL to embed URL."""
        if self.document_type != self.DocumentType.YOUTUBE or not self.url:
            return None
        url = self.url
        if 'youtube.com/watch?v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
            return f'https://www.youtube.com/embed/{video_id}'
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
            return f'https://www.youtube.com/embed/{video_id}'
        elif 'youtube.com/embed/' in url:
            return url
        return None

    @property
    def youtube_thumbnail_url(self):
        """Get YouTube video thumbnail URL."""
        if self.document_type != self.DocumentType.YOUTUBE or not self.url:
            return None
        url = self.url
        video_id = None
        if 'youtube.com/watch?v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
        elif 'youtube.com/embed/' in url:
            video_id = url.split('embed/')[1].split('?')[0]
        if video_id:
            return f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg'
        return None
