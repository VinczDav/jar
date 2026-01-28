from django.contrib.auth.models import AbstractUser
from django.db import models


class Coordinator(models.Model):
    """
    Model for storing coordinator contact information.
    Links to a User with JT Admin role.
    Each user can only be a coordinator once.
    """
    user = models.OneToOneField(
        'User',
        on_delete=models.CASCADE,
        verbose_name='Felhasználó',
        related_name='coordinator_entry'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Aktív',
        db_index=True  # Index for filtering active coordinators
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name='Sorrend'
    )

    class Meta:
        verbose_name = 'Koordinátor'
        verbose_name_plural = 'Koordinátorok'
        ordering = ['order', 'user__last_name', 'user__first_name']

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.user.phone})"

    @property
    def name(self):
        return self.user.get_full_name()

    @property
    def phone(self):
        return self.user.phone


class SiteSettings(models.Model):
    """
    Singleton model for site-wide settings.
    Only one instance should exist.
    """
    # Cancellation settings
    min_cancellation_hours = models.PositiveIntegerField(
        default=96,
        verbose_name='Minimum lemondási idő (óra)',
        help_text='Ha a mérkőzés ennyi órán belül van, a játékvezető nem mondhatja le önállóan.'
    )

    class Meta:
        verbose_name = 'Rendszer beállítások'
        verbose_name_plural = 'Rendszer beállítások'

    def __str__(self):
        return 'Rendszer beállítások'

    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def get_cancellation_days(self):
        """Return the cancellation time in days for display."""
        return self.min_cancellation_hours / 24


class User(AbstractUser):
    """
    Custom User model for JAR system.
    Extends Django's AbstractUser with role-based permissions.
    """

    class Role(models.TextChoices):
        REFEREE = 'referee', 'Játékvezető'
        JT_ADMIN = 'jt_admin', 'JT Admin'
        VB = 'vb', 'VB tag'
        INSPECTOR = 'inspector', 'Ellenőr'
        ACCOUNTANT = 'accountant', 'Könyvelő'
        ADMIN = 'admin', 'Adminisztrátor'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.REFEREE,
        verbose_name='Szerepkör'
    )

    # Profile picture
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True,
        verbose_name='Profilkép'
    )

    # Contact info (visible to colleagues)
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Telefonszám'
    )

    # === Address fields ===
    country = models.CharField(
        max_length=100,
        default='Magyarország',
        blank=True,
        verbose_name='Ország'
    )
    postal_code = models.CharField(
        max_length=10,
        blank=True,
        verbose_name='Irányítószám'
    )
    city = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Város'
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Cím'
    )

    # === Birth info fields ===
    mother_maiden_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Anyja leánykori neve'
    )
    birth_date = models.DateField(
        blank=True,
        null=True,
        verbose_name='Születési idő'
    )
    birth_place = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Születési hely'
    )

    # === Medical fields ===
    medical_valid_until = models.DateField(
        blank=True,
        null=True,
        verbose_name='Sportorvosi érvényessége'
    )

    # === Vehicle fields ===
    vehicle_owner = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Gépjármű tulajdonos neve'
    )
    vehicle_authorization = models.BooleanField(
        default=False,
        verbose_name='Van meghatalmazás'
    )
    vehicle_make = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Gépjármű gyártó'
    )
    vehicle_model = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Gépjármű modell'
    )
    vehicle_year = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name='Gyártás éve'
    )
    vehicle_engine_cc = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name='Motor (cm³)'
    )
    vehicle_license_plate = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Rendszám'
    )

    class EngineType(models.TextChoices):
        BENZIN = 'benzin', 'Benzin'
        DIESEL = 'diesel', 'Dízel'
        ELEKTROMOS = 'elektromos', 'Elektromos'
        HIBRID = 'hibrid', 'Hibrid'
        LPG = 'lpg', 'LPG'

    vehicle_engine_type = models.CharField(
        max_length=20,
        choices=EngineType.choices,
        blank=True,
        verbose_name='Motor típusa'
    )

    vehicle_reimbursement_enabled = models.BooleanField(
        default=False,
        verbose_name='Gépjármű elszámolás engedélyezve',
        help_text='Ha be van kapcsolva, a felhasználó feltölthet autós útiköltséget'
    )

    # === Contract fields ===
    taj_number = models.CharField(
        max_length=12,
        blank=True,
        verbose_name='TAJ szám'
    )

    # === Billing fields ===
    class BillingType(models.TextChoices):
        NINCS = 'nincs', 'Nincs'
        EFO = 'efo', 'EFO'
        EKHO = 'ekho', 'EKHO'

    billing_type = models.CharField(
        max_length=10,
        choices=BillingType.choices,
        default=BillingType.NINCS,
        verbose_name='Elszámolás típusa'
    )
    tax_id = models.CharField(
        max_length=15,
        blank=True,
        verbose_name='Adóazonosító jel'
    )
    bank_account = models.CharField(
        max_length=30,
        blank=True,
        verbose_name='Bankszámlaszám'
    )

    # === Role flags (for multiple roles) ===
    is_referee_flag = models.BooleanField(
        default=False,
        verbose_name='Játékvezető (megjelenik a kollégák között)'
    )
    is_jt_admin_flag = models.BooleanField(
        default=False,
        verbose_name='JT Admin jogosultság'
    )
    is_vb_flag = models.BooleanField(
        default=False,
        verbose_name='VB tag jogosultság'
    )
    is_inspector_flag = models.BooleanField(
        default=False,
        verbose_name='Ellenőr jogosultság'
    )
    is_accountant_flag = models.BooleanField(
        default=False,
        verbose_name='Könyvelő jogosultság'
    )
    is_admin_flag = models.BooleanField(
        default=False,
        verbose_name='Admin jogosultság'
    )

    # === Other admin flags ===
    has_content_module = models.BooleanField(
        default=False,
        verbose_name='Tartalomgyártó modul'
    )
    is_hidden_from_colleagues = models.BooleanField(
        default=False,
        verbose_name='Rejtett a kollégák között'
    )
    is_login_disabled = models.BooleanField(
        default=False,
        verbose_name='Bejelentkezés letiltva'
    )

    # === Soft delete fields ===
    is_deleted = models.BooleanField(
        default=False,
        verbose_name='Törölve'
    )
    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Törlés időpontja'
    )

    # === Security fields ===
    failed_login_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Sikertelen bejelentkezések'
    )
    last_failed_login = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Utolsó sikertelen bejelentkezés'
    )

    class Meta:
        verbose_name = 'Felhasználó'
        verbose_name_plural = 'Felhasználók'

    def __str__(self):
        return f"{self.get_full_name() or self.username}"

    def get_full_name(self):
        """Return last_name + first_name (Hungarian name order)."""
        full_name = f"{self.last_name} {self.first_name}".strip()
        return full_name or self.username

    # Role checks - check both primary role AND role flags
    @property
    def is_referee(self):
        """Játékvezető - can see matches, statistics, colleagues"""
        return self.role == self.Role.REFEREE or self.is_referee_flag or self.is_admin_user

    @property
    def is_jt_admin(self):
        """JT Admin / Koordinátor - can manage assignments, profiles, TIG"""
        return self.role == self.Role.JT_ADMIN or self.is_jt_admin_flag or self.is_admin_user

    @property
    def is_vb(self):
        """VB tag - can approve travel costs"""
        return self.role == self.Role.VB or self.is_vb_flag or self.is_admin_user

    @property
    def is_inspector(self):
        """Ellenőr - can create reports"""
        return self.role == self.Role.INSPECTOR or self.is_inspector_flag or self.is_admin_user

    @property
    def is_accountant(self):
        """Könyvelő - can manage EFO/EKHO"""
        return self.role == self.Role.ACCOUNTANT or self.is_accountant_flag or self.is_admin_user

    @property
    def is_admin_user(self):
        """Full admin access"""
        return self.role == self.Role.ADMIN or self.is_admin_flag

    @property
    def is_visible_to_colleagues(self):
        """Should this user be visible in the colleagues list?"""
        if self.is_hidden_from_colleagues or self.is_deleted:
            return False
        # Visible if primary role is referee/jt_admin OR has referee flag
        return self.role in [self.Role.REFEREE, self.Role.JT_ADMIN] or self.is_referee_flag

    @property
    def medical_days_until_expiry(self):
        """Calculate days until medical certificate expires. Returns None if not set."""
        if not self.medical_valid_until:
            return None
        from django.utils import timezone
        today = timezone.localtime(timezone.now()).date()
        delta = self.medical_valid_until - today
        return delta.days

    def get_available_roles_for_view(self):
        """Get list of roles this user can 'view as' (admin only)"""
        if self.is_admin_user:
            return [
                (self.Role.REFEREE, 'Játékvezető nézet'),
                (self.Role.JT_ADMIN, 'JT Admin nézet'),
                (self.Role.VB, 'VB nézet'),
                (self.Role.INSPECTOR, 'Ellenőr nézet'),
                (self.Role.ACCOUNTANT, 'Könyvelő nézet'),
                (self.Role.ADMIN, 'Admin nézet'),
            ]
        return []
