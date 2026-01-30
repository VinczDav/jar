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
    require_cancellation_reason = models.BooleanField(
        default=True,
        verbose_name='Lemondási indok kötelező',
        help_text='Ha be van kapcsolva, a játékvezetőnek indokot kell megadnia lemondáskor.'
    )

    # Security settings
    max_failed_login_attempts = models.PositiveIntegerField(
        default=10,
        verbose_name='Max. hibás bejelentkezés',
        help_text='Ennyi sikertelen bejelentkezés után értesítést kapnak az adminok.'
    )
    session_timeout_hours = models.PositiveIntegerField(
        default=8,
        verbose_name='Session időtartam (óra)',
        help_text='Ennyi óra inaktivitás után automatikusan kijelentkezteti a felhasználót.'
    )

    # Match application settings
    application_referees_enabled = models.BooleanField(
        default=False,
        verbose_name='Játékvezető jelentkezés',
        help_text='Játékvezetők jelentkezhetnek meccsekre'
    )
    application_inspectors_enabled = models.BooleanField(
        default=False,
        verbose_name='Ellenőr jelentkezés',
        help_text='Ellenőrök jelentkezhetnek meccsekre'
    )
    application_tournament_directors_enabled = models.BooleanField(
        default=False,
        verbose_name='Tornaigazgató jelentkezés',
        help_text='Tornaigazgatók jelentkezhetnek meccsekre'
    )

    # === Super Admin only settings ===
    # Email settings
    email_enabled = models.BooleanField(
        default=True,
        verbose_name='E-mail küldés engedélyezve',
        help_text='Ha kikapcsolod, a rendszer nem küld e-maileket senkinek.'
    )
    admin_notification_emails = models.TextField(
        blank=True,
        verbose_name='Admin értesítési e-mail címek',
        help_text='Vesszővel elválasztott e-mail címek, akik kritikus értesítéseket kapnak.'
    )

    # Security alert settings
    notify_server_issues = models.BooleanField(
        default=True,
        verbose_name='Szerver problémák értesítés',
        help_text='Kritikus szerver állapot értesítések (RAM, CPU, tárhely)'
    )
    notify_security_alerts = models.BooleanField(
        default=True,
        verbose_name='Biztonsági figyelmeztetések',
        help_text='Bot támadások, szokatlan bejelentkezések értesítése'
    )
    notify_unusual_login_countries = models.BooleanField(
        default=True,
        verbose_name='Szokatlan országból bejelentkezés',
        help_text='Értesítés ha valaki szokatlan helyről jelentkezik be'
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


class NotificationSettings(models.Model):
    """
    Singleton model for notification settings.
    Controls which notifications are enabled/disabled.
    """
    # Match related notifications
    notify_match_assignment = models.BooleanField(
        default=True,
        verbose_name='Új kiírás értesítés',
        help_text='Értesítés új mérkőzés kiíráskor'
    )
    notify_match_reminder = models.BooleanField(
        default=True,
        verbose_name='Mérkőzés emlékeztető (elfogadott)',
        help_text='Emlékeztető email az elfogadott mérkőzésekről'
    )
    notify_match_reminder_pending = models.BooleanField(
        default=True,
        verbose_name='Mérkőzés emlékeztető (nem elfogadott)',
        help_text='Emlékeztető email a még nem elfogadott mérkőzésekről'
    )
    match_reminder_hours = models.PositiveIntegerField(
        default=24,
        verbose_name='Emlékeztető órával előtte',
        help_text='Hány órával a mérkőzés előtt küldjön emlékeztetőt (alapértelmezett: 24 óra = 1 nap)'
    )
    # Deprecated - kept for backwards compatibility
    match_reminder_days = models.PositiveIntegerField(
        default=2,
        verbose_name='Emlékeztető nappal előtte (régi)',
        help_text='DEPRECATED - használd a match_reminder_hours mezőt'
    )
    notify_match_cancellation = models.BooleanField(
        default=True,
        verbose_name='Lemondás értesítés',
        help_text='Értesítés mérkőzés lemondáskor (adminoknak)'
    )
    notify_match_modification = models.BooleanField(
        default=True,
        verbose_name='Mérkőzés módosítás értesítés',
        help_text='Értesítés mérkőzés adatainak módosításakor'
    )

    # EFO/Declaration notifications
    notify_efo = models.BooleanField(
        default=True,
        verbose_name='EFO értesítés',
        help_text='EFO bejelentés értesítések'
    )

    # Travel expense notifications
    notify_travel_expense = models.BooleanField(
        default=True,
        verbose_name='Útiköltség értesítés',
        help_text='Útiköltség jóváhagyás/visszaküldés értesítések'
    )

    # News/Education notifications
    notify_news = models.BooleanField(
        default=True,
        verbose_name='Hírek értesítés',
        help_text='Új hír megjelenésekor értesítés'
    )
    notify_mandatory_news = models.BooleanField(
        default=True,
        verbose_name='Kötelező hírek értesítés',
        help_text='Kötelező elolvasandó hírek értesítése'
    )

    # Document notifications
    notify_report = models.BooleanField(
        default=True,
        verbose_name='Jelentés értesítés',
        help_text='Ellenőri jelentés beérkezésekor értesítés'
    )

    # Medical/Certificate notifications
    notify_medical_expiry = models.BooleanField(
        default=True,
        verbose_name='Orvosi lejárat értesítés',
        help_text='Orvosi alkalmassági lejárat előtti emlékeztető'
    )
    medical_expiry_reminder_days = models.PositiveIntegerField(
        default=30,
        verbose_name='Orvosi lejárat emlékeztető (nap)',
        help_text='Hány nappal a lejárat előtt küldjön emlékeztetőt'
    )

    # Security notifications (admin only)
    notify_failed_logins = models.BooleanField(
        default=True,
        verbose_name='Sikertelen bejelentkezés értesítés',
        help_text='Értesítés többszöri sikertelen bejelentkezéskor (adminoknak)'
    )

    class Meta:
        verbose_name = 'Értesítés beállítások'
        verbose_name_plural = 'Értesítés beállítások'

    def __str__(self):
        return 'Értesítés beállítások'

    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class User(AbstractUser):
    """
    Custom User model for JAR system.
    Extends Django's AbstractUser with role-based permissions.
    """

    class Role(models.TextChoices):
        REFEREE = 'referee', 'Játékvezető'
        TOURNAMENT_DIRECTOR = 'tournament_director', 'Tornaigazgató'
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
    facebook_link = models.URLField(
        max_length=255,
        blank=True,
        verbose_name='Facebook/Messenger link',
        help_text='Facebook profil vagy Messenger link a gyors kapcsolatfelvételhez'
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
    is_tournament_director_flag = models.BooleanField(
        default=False,
        verbose_name='Tornaigazgató jogosultság'
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

    # === Super Admin (csak Django adminból állítható) ===
    is_super_admin = models.BooleanField(
        default=False,
        verbose_name='Szuper Admin',
        help_text='Védett admin: nem kitiltható, végleges törlés, teljes napló. Csak Django adminból állítható!'
    )

    # === Archive fields (Kizárt felhasználó) ===
    is_archived = models.BooleanField(
        default=False,
        verbose_name='Kizárt',
        help_text='Ha be van jelölve, a felhasználó nem tud bejelentkezni'
    )
    archived_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Kizárás időpontja'
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
    must_change_password = models.BooleanField(
        default=True,
        verbose_name='Jelszó változtatás szükséges',
        help_text='Első belépéskor kötelező jelszót változtatni'
    )
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
    # Note: Admin users do NOT automatically get all permissions,
    # they must explicitly have the role or flag for each permission
    @property
    def is_referee(self):
        """Játékvezető - can see matches, statistics, colleagues"""
        return self.role == self.Role.REFEREE or self.is_referee_flag

    @property
    def is_jt_admin(self):
        """JT Admin / Koordinátor - can manage assignments, profiles, TIG"""
        return self.role == self.Role.JT_ADMIN or self.is_jt_admin_flag

    @property
    def is_vb(self):
        """VB tag - can approve travel costs"""
        return self.role == self.Role.VB or self.is_vb_flag

    @property
    def is_inspector(self):
        """Ellenőr - can create reports"""
        return self.role == self.Role.INSPECTOR or self.is_inspector_flag

    @property
    def is_tournament_director(self):
        """Tornaigazgató - can be assigned as TIG"""
        return self.role == self.Role.TOURNAMENT_DIRECTOR or self.is_tournament_director_flag

    @property
    def is_accountant(self):
        """Könyvelő - can manage EFO/EKHO"""
        return self.role == self.Role.ACCOUNTANT or self.is_accountant_flag

    @property
    def is_admin_user(self):
        """Full admin access - for Django admin and admin-only features"""
        return self.role == self.Role.ADMIN or self.is_admin_flag or self.is_super_admin

    @property
    def can_hard_delete(self):
        """Only super admins can permanently delete items"""
        return self.is_super_admin

    @property
    def can_grant_admin(self):
        """Only super admins can grant admin privileges to others"""
        return self.is_super_admin

    @property
    def can_view_full_audit_log(self):
        """Super admins see full audit log, regular admins see limited view"""
        return self.is_super_admin

    @property
    def is_visible_to_colleagues(self):
        """Should this user be visible in the colleagues list?"""
        # Hidden if login disabled, hidden flag, archived, or deleted
        if self.is_login_disabled or self.is_hidden_from_colleagues or self.is_archived or self.is_deleted:
            return False
        # Visible if primary role is referee/jt_admin/tournament_director OR has referee flag
        return self.role in [self.Role.REFEREE, self.Role.JT_ADMIN, self.Role.TOURNAMENT_DIRECTOR] or self.is_referee_flag

    def save(self, *args, **kwargs):
        """Override save to sync primary role with flags."""
        # Map roles to their corresponding flag fields
        role_flag_map = {
            self.Role.REFEREE: 'is_referee_flag',
            self.Role.TOURNAMENT_DIRECTOR: 'is_tournament_director_flag',
            self.Role.JT_ADMIN: 'is_jt_admin_flag',
            self.Role.VB: 'is_vb_flag',
            self.Role.INSPECTOR: 'is_inspector_flag',
            self.Role.ACCOUNTANT: 'is_accountant_flag',
            self.Role.ADMIN: 'is_admin_flag',
        }

        # Set the flag for the primary role to True
        if self.role in role_flag_map:
            setattr(self, role_flag_map[self.role], True)

        # Super admin protection: cannot be disabled, archived, or deleted
        if self.is_super_admin:
            self.is_login_disabled = False
            self.is_archived = False
            self.archived_at = None
            self.is_deleted = False
            self.deleted_at = None
            self.is_admin_flag = True  # Ensure admin flag is always set

        # If login is disabled, also hide from colleagues
        if self.is_login_disabled:
            self.is_hidden_from_colleagues = True

        super().save(*args, **kwargs)

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

    def hide_user(self):
        """Hide this user from lists (can still login)."""
        self.is_active = False
        self.is_hidden_from_colleagues = True
        self.save(update_fields=['is_active', 'is_hidden_from_colleagues'])

    def exclude_user(self):
        """Exclude/ban this user (cannot login, sees 'Fiókod le lett tiltva')."""
        from django.utils import timezone
        if self.is_super_admin:
            return  # Super admin cannot be excluded
        self.is_archived = True
        self.archived_at = timezone.now()
        self.is_hidden_from_colleagues = True
        self.save(update_fields=['is_archived', 'archived_at', 'is_hidden_from_colleagues'])

    def soft_delete(self):
        """Soft delete this user (appears as if doesn't exist on login)."""
        from django.utils import timezone
        if self.is_super_admin:
            return  # Super admin cannot be deleted
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.is_hidden_from_colleagues = True
        # Convert user's assignments to "Hiányzik" placeholder
        from matches.models import MatchAssignment
        for assignment in self.match_assignments.all():
            assignment.user = None
            assignment.placeholder_type = 'hianyzik'
            assignment.save(update_fields=['user', 'placeholder_type'])
        self.save(update_fields=['is_deleted', 'deleted_at', 'is_hidden_from_colleagues'])

    def restore(self):
        """Restore this user from archive or trash."""
        self.is_archived = False
        self.archived_at = None
        self.is_deleted = False
        self.deleted_at = None
        self.is_active = True
        self.is_hidden_from_colleagues = False
        self.save(update_fields=['is_archived', 'archived_at', 'is_deleted', 'deleted_at', 'is_active', 'is_hidden_from_colleagues'])
