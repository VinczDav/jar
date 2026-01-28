from django.conf import settings
from django.db import models


class Referee(models.Model):
    """
    Referee profile with all personal and professional data.
    Linked to User model via OneToOne relationship.
    """

    class LicenseLevel(models.TextChoices):
        C = 'C', 'C'
        C_PLUS = 'C+', 'C+'
        B = 'B', 'B'
        B_PLUS = 'B+', 'B+'
        A = 'A', 'A'
        A_PLUS = 'A+', 'A+'

    class InternationalLevel(models.TextChoices):
        NONE = '', 'Nincs'
        C = 'C', 'C'
        B = 'B', 'B'
        A = 'A', 'A'

    class BillingType(models.TextChoices):
        FULL_EKHO = 'full_ekho', 'Teljes EKHO'
        PARTIAL_EKHO = 'partial_ekho', 'Részben EKHO'
        STUDENT = 'student', 'Diák'
        EFO = 'efo', 'EFO'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Aktív'
        INACTIVE = 'inactive', 'Inaktív'

    # Link to User
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referee_profile',
        verbose_name='Felhasználó'
    )

    # Personal data
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Telefonszám'
    )

    # Address
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
    street = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Közterület'
    )
    street_type = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Közterület típusa'
    )
    house_number = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Házszám'
    )
    floor_door = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Emelet/ajtó'
    )

    # Car data (for travel reimbursement)
    has_travel_reimbursement = models.BooleanField(
        default=False,
        verbose_name='Van útiköltség-térítés'
    )
    drivers_license_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Vezetői engedély szám'
    )
    car_brand = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Autó márkája'
    )
    car_model = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Autó típusa'
    )
    car_plate = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Rendszám'
    )

    # Medical
    medical_valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name='Sportorvosi érvényessége'
    )

    # License levels
    license_level = models.CharField(
        max_length=5,
        choices=LicenseLevel.choices,
        default=LicenseLevel.C,
        verbose_name='Licenc szint'
    )
    international_level = models.CharField(
        max_length=5,
        choices=InternationalLevel.choices,
        default=InternationalLevel.NONE,
        blank=True,
        verbose_name='Nemzetközi szint'
    )

    # Billing
    billing_type = models.CharField(
        max_length=20,
        choices=BillingType.choices,
        default=BillingType.EFO,
        verbose_name='Elszámolás típus'
    )

    # Status
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name='Státusz'
    )

    # JB notes
    jb_notes = models.TextField(
        blank=True,
        verbose_name='JB megjegyzések'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Játékvezető'
        verbose_name_plural = 'Játékvezetők'
        ordering = ['user__last_name', 'user__first_name']

    def __str__(self):
        return str(self.user)

    @property
    def full_address(self):
        parts = [
            self.postal_code,
            self.city,
            f"{self.street} {self.street_type}",
            self.house_number,
            self.floor_door
        ]
        return ', '.join(filter(None, parts))


class Unavailability(models.Model):
    """
    Referee unavailability periods (when they can't officiate).
    """
    referee = models.ForeignKey(
        Referee,
        on_delete=models.CASCADE,
        related_name='unavailabilities',
        verbose_name='Játékvezető'
    )
    start_date = models.DateField(verbose_name='Kezdete')
    end_date = models.DateField(verbose_name='Vége')
    reason = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Indok'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Szabadság'
        verbose_name_plural = 'Szabadságok'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.referee} - {self.start_date} - {self.end_date}"


class InspectorReport(models.Model):
    """Inspector report for a match."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Piszkozat'
        SUBMITTED = 'submitted', 'Beküldve'

    match = models.ForeignKey(
        'matches.Match',
        on_delete=models.CASCADE,
        related_name='inspector_reports',
        verbose_name='Mérkőzés'
    )
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='inspector_reports',
        verbose_name='Ellenőr'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name='Státusz'
    )
    general_notes = models.TextField(
        blank=True,
        verbose_name='Általános megjegyzések'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ellenőri jelentés'
        verbose_name_plural = 'Ellenőri jelentések'
        ordering = ['-created_at']
        # One report per match per inspector
        unique_together = ['match', 'inspector']

    def __str__(self):
        return f"Jelentés: {self.match} - {self.inspector}"

    @property
    def is_submitted(self):
        return self.status == self.Status.SUBMITTED


class RefereeEvaluation(models.Model):
    """Individual referee evaluation within an inspector report."""

    report = models.ForeignKey(
        InspectorReport,
        on_delete=models.CASCADE,
        related_name='evaluations',
        verbose_name='Jelentés'
    )
    referee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_evaluations',
        verbose_name='Játékvezető'
    )
    # Rating fields (1-5 stars)
    rules_knowledge = models.PositiveSmallIntegerField(
        default=3,
        verbose_name='Szabályismeret',
        help_text='1-5 értékelés'
    )
    positioning = models.PositiveSmallIntegerField(
        default=3,
        verbose_name='Mozgás, elhelyezkedés',
        help_text='1-5 értékelés'
    )
    communication = models.PositiveSmallIntegerField(
        default=3,
        verbose_name='Kommunikáció',
        help_text='1-5 értékelés'
    )
    fitness = models.PositiveSmallIntegerField(
        default=3,
        verbose_name='Fizikai felkészültség',
        help_text='1-5 értékelés'
    )
    # Overall rating (auto-calculated or manual)
    overall_rating = models.PositiveSmallIntegerField(
        default=3,
        verbose_name='Összértékelés',
        help_text='1-5 értékelés'
    )
    notes = models.TextField(
        blank=True,
        verbose_name='Megjegyzések'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Játékvezető értékelés'
        verbose_name_plural = 'Játékvezető értékelések'
        ordering = ['report', 'referee__last_name']
        # One evaluation per referee per report
        unique_together = ['report', 'referee']

    def __str__(self):
        return f"{self.referee} - {self.overall_rating}/5"

    @property
    def average_rating(self):
        """Calculate average of all rating fields."""
        ratings = [self.rules_knowledge, self.positioning, self.communication, self.fitness]
        return sum(ratings) / len(ratings)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
