from decimal import Decimal
from django.db import models
from referees.models import Referee
from matches.models import Match, MatchAssignment, CompetitionPhase


class FeeStructure(models.Model):
    """
    Fee structure for different competition phases.
    E.g., OB1 alapszakasz: 10,000 Ft, OB1 rájátszás: 12,000 Ft
    """
    phase = models.ForeignKey(
        CompetitionPhase,
        on_delete=models.CASCADE,
        related_name='fee_structures',
        verbose_name='Szakasz'
    )
    role = models.CharField(
        max_length=20,
        choices=MatchAssignment.Role.choices,
        verbose_name='Szerep'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Összeg (Ft)'
    )
    valid_from = models.DateField(verbose_name='Érvényes ettől')
    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name='Érvényes eddig'
    )

    class Meta:
        verbose_name = 'Díjazási struktúra'
        verbose_name_plural = 'Díjazási struktúrák'
        ordering = ['phase', 'role', '-valid_from']

    def __str__(self):
        return f"{self.phase} - {self.get_role_display()} - {self.amount} Ft"


class MatchFee(models.Model):
    """
    Calculated fee for a specific referee assignment.
    """
    assignment = models.OneToOneField(
        MatchAssignment,
        on_delete=models.CASCADE,
        related_name='fee',
        verbose_name='Kijelölés'
    )
    base_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Alap összeg'
    )
    # For shared officiating (if the fee is split)
    split_ratio = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal('1.00'),
        verbose_name='Megosztási arány'
    )
    final_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Végső összeg'
    )
    # Manual correction
    manual_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Manuális korrekció'
    )
    adjustment_reason = models.CharField(
        max_length=300,
        blank=True,
        verbose_name='Korrekció indoka'
    )

    class Meta:
        verbose_name = 'Mérkőzés díj'
        verbose_name_plural = 'Mérkőzés díjak'

    def __str__(self):
        return f"{self.assignment} - {self.final_amount} Ft"

    @property
    def gross_amount(self):
        """Calculate gross amount for EKHO (bruttó = nettó / 0.85)."""
        if self.final_amount:
            return round(self.final_amount / Decimal('0.85'), 0)
        return Decimal('0')

    def save(self, *args, **kwargs):
        # Calculate final amount
        self.final_amount = (self.base_amount * self.split_ratio) + self.manual_adjustment
        super().save(*args, **kwargs)


class MonthlyStatement(models.Model):
    """
    Monthly billing statement for a referee.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Piszkozat'
        PENDING = 'pending', 'Jóváhagyásra vár'
        APPROVED = 'approved', 'Jóváhagyva'
        PAID = 'paid', 'Kifizetve'

    referee = models.ForeignKey(
        Referee,
        on_delete=models.CASCADE,
        related_name='monthly_statements',
        verbose_name='Játékvezető'
    )
    year = models.PositiveIntegerField(verbose_name='Év')
    month = models.PositiveIntegerField(verbose_name='Hónap')
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Teljes összeg'
    )
    match_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Mérkőzések száma'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name='Státusz'
    )
    approved_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_statements',
        verbose_name='Jóváhagyta'
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Jóváhagyás dátuma'
    )
    notes = models.TextField(blank=True, verbose_name='Megjegyzés')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Havi elszámolás'
        verbose_name_plural = 'Havi elszámolások'
        unique_together = ['referee', 'year', 'month']
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.referee} - {self.year}/{self.month:02d} - {self.total_amount} Ft"


class StatementLine(models.Model):
    """
    Individual line item in a monthly statement.
    """
    statement = models.ForeignKey(
        MonthlyStatement,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name='Elszámolás'
    )
    match_fee = models.ForeignKey(
        MatchFee,
        on_delete=models.CASCADE,
        related_name='statement_lines',
        verbose_name='Mérkőzés díj'
    )

    class Meta:
        verbose_name = 'Elszámolás sor'
        verbose_name_plural = 'Elszámolás sorok'
        unique_together = ['statement', 'match_fee']

    def __str__(self):
        return f"{self.statement} - {self.match_fee}"


class TravelCost(models.Model):
    """
    Travel cost reimbursement for a match assignment.
    """

    class ExpenseType(models.TextChoices):
        NONE = 'none', 'Nincs'
        CAR = 'car', 'Autós kiküldetés'
        PUBLIC = 'public', 'Tömegközlekedés'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Jóváhagyásra vár'
        APPROVED = 'approved', 'Jóváhagyva'
        REJECTED = 'rejected', 'Elutasítva'
        RETURNED = 'returned', 'Visszaküldve'
        DECLINED = 'declined', 'Nem igényelt'

    assignment = models.OneToOneField(
        MatchAssignment,
        on_delete=models.CASCADE,
        related_name='travel_cost',
        verbose_name='Kijelölés'
    )
    expense_type = models.CharField(
        max_length=20,
        choices=ExpenseType.choices,
        default=ExpenseType.NONE,
        verbose_name='Költség típus'
    )
    # Car expense fields
    distance_km = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name='Távolság (km)'
    )
    car_rate_per_km = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        verbose_name='Km díj (Ft/km)'
    )
    # Public transport fields
    receipt_file = models.FileField(
        upload_to='travel_receipts/',
        null=True,
        blank=True,
        verbose_name='Számla'
    )
    receipt_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Számla összeg'
    )
    # Calculated/final amount
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Összeg (Ft)'
    )
    # Approval
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Státusz'
    )
    reviewed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_travel_costs',
        verbose_name='Elbíráló'
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Elbírálás dátuma'
    )
    comment = models.TextField(
        blank=True,
        verbose_name='Megjegyzés'
    )
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Utazási költség'
        verbose_name_plural = 'Utazási költségek'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.assignment} - {self.get_expense_type_display()} - {self.amount} Ft"

    @property
    def file_extension(self):
        """Get the file extension of the receipt."""
        if self.receipt_file:
            import os
            return os.path.splitext(self.receipt_file.name)[1].lower()
        return ''

    @property
    def is_image(self):
        """Check if the file is an image."""
        return self.file_extension in ['.png', '.jpg', '.jpeg']

    @property
    def is_pdf(self):
        """Check if the file is a PDF."""
        return self.file_extension == '.pdf'

    def save(self, *args, **kwargs):
        # Calculate amount based on type
        if self.expense_type == self.ExpenseType.CAR and self.distance_km:
            self.amount = self.distance_km * self.car_rate_per_km
        elif self.expense_type == self.ExpenseType.PUBLIC and self.receipt_amount:
            self.amount = self.receipt_amount
        super().save(*args, **kwargs)


class TaxDeclaration(models.Model):
    """
    EFO/EKHO declaration tracking for match assignments.
    Tracks when assignments are declared and if they need re-declaration after changes.
    """

    class DeclarationType(models.TextChoices):
        EFO = 'efo', 'EFO'
        EKHO = 'ekho', 'EKHO'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Bejelentésre vár'
        DECLARED = 'declared', 'Bejelentett'
        MODIFIED = 'modified', 'Módosítás történt'

    assignment = models.OneToOneField(
        MatchAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tax_declaration',
        verbose_name='Kijelölés'
    )
    # Store match and user separately so we can still display info when assignment is deleted
    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='tax_declarations',
        verbose_name='Mérkőzés'
    )
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='user_tax_declarations',
        verbose_name='Játékvezető'
    )
    declaration_type = models.CharField(
        max_length=10,
        choices=DeclarationType.choices,
        verbose_name='Bejelentés típus'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Státusz'
    )
    # Tracking what was declared (to detect changes)
    declared_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='Bejelentett dátum'
    )
    declared_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name='Bejelentett időpont'
    )
    declared_venue_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Bejelentett helyszín ID'
    )
    declared_referees = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Bejelentett játékvezetők'
    )
    # Change tracking
    changes_detected = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Észlelt változások'
    )
    # Who and when
    declared_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tax_declarations',
        verbose_name='Bejelentette'
    )
    declared_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Bejelentés időpontja'
    )
    # Hidden flag - for items that accountant wants to dismiss temporarily
    is_hidden = models.BooleanField(
        default=False,
        verbose_name='Elrejtve'
    )
    hidden_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Elrejtés időpontja'
    )
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Adóbejelentés'
        verbose_name_plural = 'Adóbejelentések'
        ordering = ['-created_at']

    def __str__(self):
        if self.assignment:
            return f"{self.assignment} - {self.get_declaration_type_display()} - {self.get_status_display()}"
        elif self.match and self.user:
            return f"{self.user} - {self.match} - {self.get_declaration_type_display()} - {self.get_status_display()}"
        return f"TaxDeclaration {self.id} - {self.get_declaration_type_display()}"

    def mark_as_declared(self, declaring_user):
        """Mark the assignment as declared, storing current state."""
        from django.utils import timezone

        match = self.assignment.match

        # Store match and user references for when assignment is deleted
        self.match = match
        self.user = self.assignment.user

        # Store current state for change detection
        self.declared_date = match.date
        self.declared_time = match.time
        self.declared_venue_id = match.venue_id if match.venue else None

        # Store current referees
        referees = list(match.assignments.filter(
            role__in=[MatchAssignment.Role.REFEREE, MatchAssignment.Role.RESERVE],
            response_status=MatchAssignment.ResponseStatus.ACCEPTED
        ).values_list('user_id', flat=True))
        self.declared_referees = referees

        self.status = self.Status.DECLARED
        self.changes_detected = []
        self.declared_by = declaring_user
        self.declared_at = timezone.now()
        self.save()

    def check_for_changes(self):
        """Check if the match has changed since declaration."""
        if self.status != self.Status.DECLARED:
            return []

        from matches.models import Venue
        from accounts.models import User

        # Check if assignment was deleted (referee removed from match)
        if not self.assignment:
            user_name = self.user.get_full_name() if self.user else 'Ismeretlen'
            changes = [{
                'field': 'assignment_deleted',
                'label': 'Játékvezető törölve',
                'type': 'removed',
                'display': f"{user_name} törölve a mérkőzésről"
            }]
            self.status = self.Status.MODIFIED
            self.changes_detected = changes
            self.save()
            # Notify accountants
            if self.match:
                self._notify_accountants_about_changes(self.match, changes)
            return changes

        # Check if referee resigned (declined the assignment)
        if self.assignment.response_status == MatchAssignment.ResponseStatus.DECLINED:
            user_name = self.user.get_full_name() if self.user else 'Ismeretlen'
            changes = [{
                'field': 'assignment_resigned',
                'label': 'Játékvezető lemondott',
                'type': 'resigned',
                'display': f"{user_name} lemondta a mérkőzést"
            }]
            self.status = self.Status.MODIFIED
            self.changes_detected = changes
            self.save()
            # Notify accountants
            if self.match:
                self._notify_accountants_about_changes(self.match, changes)
            return changes

        match = self.assignment.match
        changes = []

        # Check date
        if self.declared_date and match.date != self.declared_date:
            old_date_str = self.declared_date.strftime('%Y.%m.%d') if self.declared_date else '-'
            new_date_str = match.date.strftime('%Y.%m.%d') if match.date else '-'
            changes.append({
                'field': 'date',
                'label': 'Dátum',
                'old': old_date_str,
                'new': new_date_str,
                'display': f"Dátum: {old_date_str} → {new_date_str}"
            })

        # Check time
        if self.declared_time != match.time:
            old_time_str = self.declared_time.strftime('%H:%M') if self.declared_time else '-'
            new_time_str = match.time.strftime('%H:%M') if match.time else '-'
            changes.append({
                'field': 'time',
                'label': 'Időpont',
                'old': old_time_str,
                'new': new_time_str,
                'display': f"Időpont: {old_time_str} → {new_time_str}"
            })

        # Check venue
        current_venue_id = match.venue_id if match.venue else None
        if self.declared_venue_id != current_venue_id:
            # Get venue names
            old_venue_name = '-'
            new_venue_name = '-'
            if self.declared_venue_id:
                try:
                    old_venue = Venue.objects.get(id=self.declared_venue_id)
                    old_venue_name = old_venue.name
                except Venue.DoesNotExist:
                    pass
            if match.venue:
                new_venue_name = match.venue.name
            changes.append({
                'field': 'venue',
                'label': 'Helyszín',
                'old': old_venue_name,
                'new': new_venue_name,
                'display': f"Helyszín: {old_venue_name} → {new_venue_name}"
            })

        # Check referees
        current_referees = list(match.assignments.filter(
            role__in=[MatchAssignment.Role.REFEREE, MatchAssignment.Role.RESERVE],
            response_status=MatchAssignment.ResponseStatus.ACCEPTED
        ).values_list('user_id', flat=True))

        old_set = set(self.declared_referees or [])
        new_set = set(current_referees)

        if old_set != new_set:
            removed_ids = old_set - new_set
            added_ids = new_set - old_set

            referee_changes = []

            # Get names of removed referees
            if removed_ids:
                removed_users = User.objects.filter(id__in=removed_ids)
                for u in removed_users:
                    referee_changes.append({
                        'type': 'removed',
                        'display': f"{u.get_full_name()} törölve a mérkőzésről"
                    })

            # Get names of added referees
            if added_ids:
                added_users = User.objects.filter(id__in=added_ids)
                for u in added_users:
                    referee_changes.append({
                        'type': 'added',
                        'display': f"{u.get_full_name()} kiírva a mérkőzésre"
                    })

            changes.append({
                'field': 'referees',
                'label': 'Játékvezetők',
                'referee_changes': referee_changes,
                'display': '; '.join([rc['display'] for rc in referee_changes])
            })

        if changes:
            self.status = self.Status.MODIFIED
            self.changes_detected = changes
            self.save()

            # Notify accountants about the changes
            self._notify_accountants_about_changes(match, changes)

        return changes

    def _notify_accountants_about_changes(self, match, changes):
        """Send notification to accountants about declared match changes."""
        from documents.models import Notification
        from accounts.models import User
        from django.db.models import Q

        # Get all accountants
        accountants = User.objects.filter(
            Q(role=User.Role.ACCOUNTANT) | Q(is_accountant_flag=True),
            is_deleted=False
        )

        # Build notification message
        date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
        teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
        # Get referee name - from assignment if exists, otherwise from stored user
        if self.assignment:
            referee_name = self.assignment.user.get_full_name()
        elif self.user:
            referee_name = self.user.get_full_name()
        else:
            referee_name = 'Ismeretlen'
        declaration_type_display = 'EFO' if self.declaration_type == 'efo' else 'EKHO'

        # Build detailed changes list
        changes_lines = []
        for c in changes:
            if c.get('display'):
                changes_lines.append(c['display'])
        changes_str = '\n'.join(changes_lines)

        # Create notification for each accountant
        for accountant in accountants:
            Notification.objects.create(
                recipient=accountant,
                title=f"Bejelentett {declaration_type_display} meccs módosítva",
                message=f"{date_str}\n{teams}\n{referee_name}\n\nVáltozás:\n{changes_str}",
                notification_type=Notification.Type.WARNING,
                link=f"/billing/{self.declaration_type}/"
            )
