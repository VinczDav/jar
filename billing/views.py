from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.db.models import Q
from django.utils import timezone
from matches.models import Match, MatchAssignment, Competition, Season
from accounts.models import User
from audit.utils import log_action


@login_required
def match_counts(request):
    """Show match counts/list for current user or selected user (for admins)."""
    from datetime import timedelta

    user = request.user
    now = timezone.localtime(timezone.now())  # Convert to local time (Europe/Budapest)
    today = now.date()
    one_min_ago = (now - timedelta(minutes=1)).time()

    # Get current season
    current_season = Season.get_current()

    # Get filter values
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    competition_id = request.GET.get('competition', '')
    selected_user_id = request.GET.get('user', '')

    # Set default dates if not provided (past 7 days for past matches)
    if not date_from and not date_to:
        date_from = str(today - timedelta(days=7))
        date_to = str(today)

    # Determine which user's assignments to show
    target_user = user
    if user.is_jt_admin and selected_user_id:
        try:
            target_user = User.objects.get(id=selected_user_id)
        except User.DoesNotExist:
            target_user = user

    # Base query: completed matches where user was assigned and accepted
    assignments = MatchAssignment.objects.filter(
        user=target_user,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED,
        match__is_deleted=False  # Exclude soft-deleted matches
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    ).exclude(
        match__status=Match.Status.CANCELLED
    )

    # Only include matches that have started (date < today OR (date == today AND time <= one_min_ago))
    assignments = assignments.filter(
        Q(match__date__lt=today) |
        Q(match__date=today, match__time__isnull=False, match__time__lte=one_min_ago)
    )

    # Apply filters
    if date_from:
        assignments = assignments.filter(match__date__gte=date_from)
    if date_to:
        assignments = assignments.filter(match__date__lte=date_to)
    if competition_id:
        assignments = assignments.filter(match__phase__competition_id=competition_id)

    # Order by date descending
    assignments = assignments.order_by('-match__date', '-match__time')

    # Get competitions for filter dropdown
    competitions = Competition.objects.filter(season=current_season) if current_season else Competition.objects.none()

    # Get all users for admin filter (include both role-based and flag-based users)
    all_users = User.objects.filter(
        Q(role=User.Role.REFEREE) | Q(role=User.Role.JT_ADMIN) |
        Q(is_referee_flag=True) | Q(is_jt_admin_flag=True),
        is_deleted=False
    ).order_by('last_name', 'first_name') if user.is_jt_admin else []

    context = {
        'assignments': assignments,
        'competitions': competitions,
        'all_users': all_users,
        'date_from': date_from,
        'date_to': date_to,
        'selected_competition': competition_id,
        'selected_user_id': selected_user_id,
        'target_user': target_user,
        'is_admin_view': user.is_jt_admin,
    }

    return render(request, 'billing/match_counts.html', context)


@login_required
def tig(request):
    """Show TIG (Teljesítési Igazolás) for current user."""
    user = request.user
    now = timezone.localtime(timezone.now())  # Convert to local time (Europe/Budapest)
    today = now.date()

    # Get year and month from request, default to current
    year = request.GET.get('year', today.year)
    month = request.GET.get('month', today.month)
    competition_id = request.GET.get('competition', '')
    selected_user_id = request.GET.get('user', '')

    try:
        year = int(year)
        month = int(month)
    except (ValueError, TypeError):
        year = today.year
        month = today.month

    # Determine which user's assignments to show
    # JT Admin and Accountant can view other users' TIG
    target_user = user
    is_admin_view = user.is_jt_admin or user.is_accountant
    if is_admin_view and selected_user_id:
        try:
            target_user = User.objects.get(id=selected_user_id)
        except User.DoesNotExist:
            target_user = user

    # Build date range for selected month
    import calendar
    _, last_day = calendar.monthrange(year, month)
    from datetime import date, timedelta
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    # Time-based filtering: only show matches that have started (start + 1 min passed)
    one_min_ago = (now - timedelta(minutes=1)).time()

    # Get assignments for the selected month - only matches that have started
    assignments = MatchAssignment.objects.filter(
        user=target_user,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED,
        match__date__gte=month_start,
        match__date__lte=month_end,
        match__is_deleted=False  # Exclude soft-deleted matches
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    ).exclude(
        match__status=Match.Status.CANCELLED
    )

    # Only include matches that have started (date < today OR (date == today AND time <= one_min_ago))
    from django.db.models import Q
    assignments = assignments.filter(
        Q(match__date__lt=today) |
        Q(match__date=today, match__time__isnull=False, match__time__lte=one_min_ago)
    )

    # Apply competition filter
    if competition_id:
        assignments = assignments.filter(match__phase__competition_id=competition_id)

    assignments = assignments.order_by('match__date', 'match__time')

    # Calculate fees (check for custom fee first, then fall back to phase settings)
    total_fee = 0
    assignments_with_fees = []
    for assignment in assignments:
        # Check if there's a custom fee set by admin
        try:
            match_fee = assignment.fee
            fee = int(match_fee.final_amount)
            is_custom = match_fee.manual_adjustment != 0
        except:
            # Use the model method which handles tournaments correctly
            fee = assignment.match.get_payment_per_referee()
            is_custom = False

        total_fee += fee
        # Format fee with space as thousands separator (Hungarian format)
        fee_display = f"{fee:,}".replace(',', ' ') if fee else None
        assignments_with_fees.append({
            'assignment': assignment,
            'fee': fee,
            'fee_display': fee_display,
            'is_custom': is_custom,
        })

    # Available years (2026 onwards for future, plus current year)
    current_year = today.year
    available_years = list(range(2026, current_year + 2))

    # Hungarian month names
    month_names = [
        'Január', 'Február', 'Március', 'Április', 'Május', 'Június',
        'Július', 'Augusztus', 'Szeptember', 'Október', 'November', 'December'
    ]

    # Get competitions for filter dropdown
    current_season = Season.get_current()
    competitions = Competition.objects.filter(season=current_season) if current_season else Competition.objects.none()

    # Get all users for admin filter (include both role-based and flag-based users)
    # For accountants: only show referees (not themselves)
    if is_admin_view:
        all_users_query = User.objects.filter(
            Q(role=User.Role.REFEREE) | Q(role=User.Role.JT_ADMIN) |
            Q(is_referee_flag=True) | Q(is_jt_admin_flag=True),
            is_deleted=False
        )
        # If user is accountant (but not JT admin), exclude themselves from the list
        if user.is_accountant and not user.is_jt_admin:
            all_users_query = all_users_query.exclude(id=user.id)
        all_users = all_users_query.order_by('last_name', 'first_name')
    else:
        all_users = []

    # Format total fee with space as thousands separator
    total_fee_display = f"{total_fee:,}".replace(',', ' ')

    context = {
        'assignments_with_fees': assignments_with_fees,
        'total_fee': total_fee,
        'total_fee_display': total_fee_display,
        'selected_year': year,
        'selected_month': month,
        'available_years': available_years,
        'month_names': month_names,
        'competitions': competitions,
        'selected_competition': competition_id,
        'all_users': all_users,
        'selected_user_id': selected_user_id,
        'target_user': target_user,
        'is_admin_view': is_admin_view,
    }

    return render(request, 'billing/tig.html', context)


def _tig_admin_view(request, can_edit=True):
    """Common view for TIG admin/VB pages."""
    now = timezone.localtime(timezone.now())
    today = now.date()

    # Get year and month from request, default to current
    year = request.GET.get('year', today.year)
    month = request.GET.get('month', today.month)
    selected_user_id = request.GET.get('user', '')

    try:
        year = int(year)
        month = int(month)
    except (ValueError, TypeError):
        year = today.year
        month = today.month

    # Determine which user's assignments to show
    target_user = None
    if selected_user_id:
        try:
            target_user = User.objects.get(id=selected_user_id)
        except User.DoesNotExist:
            target_user = None

    assignments_with_fees = []
    total_fee = 0

    if target_user:
        # Build date range for selected month
        import calendar
        _, last_day = calendar.monthrange(year, month)
        from datetime import date, timedelta
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)

        # Time-based filtering
        one_min_ago = (now - timedelta(minutes=1)).time()

        # Get assignments for the selected month
        assignments = MatchAssignment.objects.filter(
            user=target_user,
            response_status=MatchAssignment.ResponseStatus.ACCEPTED,
            match__date__gte=month_start,
            match__date__lte=month_end,
            match__is_deleted=False
        ).select_related(
            'match', 'match__home_team', 'match__away_team',
            'match__venue', 'match__phase', 'match__phase__competition'
        ).exclude(
            match__status=Match.Status.CANCELLED
        )

        # Only include matches that have started
        assignments = assignments.filter(
            Q(match__date__lt=today) |
            Q(match__date=today, match__time__isnull=False, match__time__lte=one_min_ago)
        )

        assignments = assignments.order_by('match__date', 'match__time')

        # Calculate fees (uses match.get_payment_per_referee for tournament support)
        for assignment in assignments:
            # Check if there's a custom fee
            try:
                match_fee = assignment.fee
                fee = int(match_fee.final_amount)
                is_custom = match_fee.manual_adjustment != 0
            except:
                # Use model method which handles tournaments correctly
                fee = assignment.match.get_payment_per_referee()
                is_custom = False

            total_fee += fee
            fee_display = f"{fee:,}".replace(',', ' ') if fee else None
            assignments_with_fees.append({
                'assignment': assignment,
                'fee': fee,
                'fee_display': fee_display,
                'is_custom': is_custom,
            })

    # Available years
    current_year = today.year
    available_years = list(range(2026, current_year + 2))

    # Hungarian month names
    month_names = [
        'Január', 'Február', 'Március', 'Április', 'Május', 'Június',
        'Július', 'Augusztus', 'Szeptember', 'Október', 'November', 'December'
    ]

    # Get all users for filter (include both role-based and flag-based users)
    all_users = User.objects.filter(
        Q(role=User.Role.REFEREE) | Q(role=User.Role.JT_ADMIN) |
        Q(is_referee_flag=True) | Q(is_jt_admin_flag=True),
        is_deleted=False
    ).order_by('last_name', 'first_name')

    # Format total fee
    total_fee_display = f"{total_fee:,}".replace(',', ' ')

    context = {
        'assignments_with_fees': assignments_with_fees,
        'total_fee': total_fee,
        'total_fee_display': total_fee_display,
        'selected_year': year,
        'selected_month': month,
        'available_years': available_years,
        'month_names': month_names,
        'all_users': all_users,
        'selected_user_id': selected_user_id,
        'target_user': target_user,
        'can_edit': can_edit,
    }

    return render(request, 'billing/tig_admin.html', context)


@login_required
def tig_admin(request):
    """JT Admin: Modify TIG amounts."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')
    return _tig_admin_view(request, can_edit=True)


@login_required
def tig_vb(request):
    """VB Tag: View TIG amounts (read-only)."""
    if not request.user.is_vb:
        return HttpResponseForbidden('Nincs jogosultságod.')
    return _tig_admin_view(request, can_edit=False)


@login_required
def travel_costs(request):
    """Upload and view travel cost reimbursements."""
    from .models import TravelCost
    import calendar
    from datetime import date

    user = request.user
    today = timezone.localtime(timezone.now()).date()  # Use local time for date

    # Get year and month from request, default to current
    year = request.GET.get('year', today.year)
    month = request.GET.get('month', today.month)

    try:
        year = int(year)
        month = int(month)
    except (ValueError, TypeError):
        year = today.year
        month = today.month

    # Build date range for selected month
    _, last_day = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    # Check if user has vehicle reimbursement permission and car data registered
    has_car_data = bool(user.vehicle_license_plate)
    can_submit_car_expense = user.vehicle_reimbursement_enabled and has_car_data

    # Time-based filtering: only show matches that have started (start + 1 min passed)
    from datetime import timedelta
    from django.db.models import Q
    one_min_ago = (timezone.now() - timedelta(minutes=1)).time()

    # Get user's past accepted assignments for match selection (without existing travel cost)
    # Only include matches that have started (date < today OR (date == today AND time <= one_min_ago))
    past_assignments = MatchAssignment.objects.filter(
        user=user,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED,
        match__is_deleted=False
    ).filter(
        Q(match__date__lt=today) |
        Q(match__date=today, match__time__isnull=False, match__time__lte=one_min_ago)
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).order_by('-match__date', '-match__time')

    # Filter out assignments that already have a travel cost
    past_assignments = [a for a in past_assignments[:100] if not hasattr(a, 'travel_cost') or not a.travel_cost]

    # Get user's existing travel costs for the selected month
    user_travel_costs = TravelCost.objects.filter(
        assignment__user=user,
        assignment__match__date__gte=month_start,
        assignment__match__date__lte=month_end,
    ).select_related(
        'assignment', 'assignment__match', 'assignment__match__home_team',
        'assignment__match__away_team', 'assignment__match__venue',
        'assignment__match__phase', 'assignment__match__phase__competition'
    ).order_by('assignment__match__date', 'assignment__match__time')

    # Calculate total for approved travel costs
    total_amount = 0
    for tc in user_travel_costs:
        if tc.status == TravelCost.Status.APPROVED and tc.amount:
            total_amount += int(tc.amount)

    # Format total with space as thousands separator (Hungarian format)
    total_amount_display = f"{total_amount:,}".replace(',', ' ')

    # Hungarian month names
    month_names = [
        'Január', 'Február', 'Március', 'Április', 'Május', 'Június',
        'Július', 'Augusztus', 'Szeptember', 'Október', 'November', 'December'
    ]

    # Available years
    current_year = today.year
    available_years = list(range(2026, current_year + 2))

    context = {
        'can_submit_car_expense': can_submit_car_expense,
        'has_car_data': has_car_data,
        'vehicle_reimbursement_enabled': user.vehicle_reimbursement_enabled,
        'past_assignments': past_assignments[:50],  # Limit to 50
        'travel_costs': user_travel_costs,
        'selected_year': year,
        'selected_month': month,
        'month_names': month_names,
        'available_years': available_years,
        'total_amount': total_amount,
        'total_amount_display': total_amount_display,
    }

    return render(request, 'billing/travel_costs.html', context)


@login_required
def efo(request):
    """Accountant: EFO registration management."""
    if not request.user.is_accountant:
        return HttpResponseForbidden('Nincs jogosultságod.')
    return _tax_declaration_view(request, 'efo')


@login_required
def ekho(request):
    """Accountant: EKHO registration management."""
    if not request.user.is_accountant:
        return HttpResponseForbidden('Nincs jogosultságod.')
    return _tax_declaration_view(request, 'ekho')


def _tax_declaration_view(request, declaration_type):
    """Common view for EFO/EKHO declarations."""
    from .models import TaxDeclaration
    from matches.models import Venue
    from datetime import timedelta

    today = timezone.localtime(timezone.now()).date()
    five_days_from_now = today + timedelta(days=5)

    # For EKHO: calculate deadline for urgent status (7th of next month after match date)
    # A match is urgent if it's past the 7th of the month after the match and still pending

    # Set default date filters based on declaration type
    # EFO: today to today + 7 days
    # EKHO: first day of month to today
    if declaration_type == 'efo':
        default_date_from = today.strftime('%Y-%m-%d')
        default_date_to = (today + timedelta(days=7)).strftime('%Y-%m-%d')
    else:  # ekho
        default_date_from = today.replace(day=1).strftime('%Y-%m-%d')
        default_date_to = today.strftime('%Y-%m-%d')

    # Get filter values (use defaults if not specified)
    date_from = request.GET.get('date_from', default_date_from)
    date_to = request.GET.get('date_to', default_date_to)
    venue_id = request.GET.get('venue', '')
    user_id = request.GET.get('user', '')

    # Get users with this billing type
    users_with_type = User.objects.filter(
        billing_type=declaration_type,
        is_deleted=False
    ).order_by('last_name', 'first_name')

    user_ids = list(users_with_type.values_list('id', flat=True))

    # Filter for matches that require MFSZ declaration:
    # - mfsz_declaration_override=True explicitly
    # - OR mfsz_declaration_override is None AND phase.requires_mfsz_declaration=True
    # - OR mfsz_declaration_override is None AND phase is None (defaults to True)
    mfsz_declaration_filter = (
        Q(match__mfsz_declaration_override=True) |
        (Q(match__mfsz_declaration_override__isnull=True) & Q(match__phase__requires_mfsz_declaration=True)) |
        (Q(match__mfsz_declaration_override__isnull=True) & Q(match__phase__isnull=True))
    )

    # Get all assignments for these users - ONLY ACCEPTED status
    assignments = MatchAssignment.objects.filter(
        user_id__in=user_ids,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED,
        match__is_deleted=False,
        match__is_assignment_published=True
    ).filter(
        mfsz_declaration_filter
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition',
        'user'
    ).exclude(
        match__status=Match.Status.CANCELLED
    )

    # Apply filters
    if date_from:
        assignments = assignments.filter(match__date__gte=date_from)
    if date_to:
        assignments = assignments.filter(match__date__lte=date_to)
    if venue_id:
        assignments = assignments.filter(match__venue_id=venue_id)
    if user_id:
        assignments = assignments.filter(user_id=user_id)

    assignments = assignments.order_by('match__date', 'match__time')

    # Ensure all assignments have a TaxDeclaration
    pending_items = []
    declared_items = []
    modified_items = []
    hidden_items = []

    # Track which declarations we've processed (to avoid duplicates with orphaned)
    processed_declaration_ids = set()

    for assignment in assignments:
        # First, check if there's an orphaned declaration for the same user+match
        # (This happens when user was removed then re-added to the same match)
        orphaned = TaxDeclaration.objects.filter(
            declaration_type=declaration_type,
            assignment__isnull=True,
            user=assignment.user,
            match=assignment.match
        ).first()

        if orphaned:
            # Re-link orphaned declaration to the new assignment
            orphaned.assignment = assignment
            # Reset status if it was marked as modified due to removal
            if orphaned.status == TaxDeclaration.Status.MODIFIED and orphaned.changes_detected:
                # Check if the only change was "assignment_deleted"
                changes = orphaned.changes_detected
                if len(changes) == 1 and changes[0].get('field') == 'assignment_deleted':
                    # User was re-added, revert to declared status
                    orphaned.status = TaxDeclaration.Status.DECLARED
                    orphaned.changes_detected = []
            orphaned.save()
            declaration = orphaned
        else:
            # Get or create declaration, storing match and user for future reference
            declaration, created = TaxDeclaration.objects.get_or_create(
                assignment=assignment,
                defaults={
                    'declaration_type': declaration_type,
                    'match': assignment.match,
                    'user': assignment.user,
                }
            )
            # Update match/user if they were missing (for older declarations)
            if not declaration.match or not declaration.user:
                declaration.match = assignment.match
                declaration.user = assignment.user
                declaration.save(update_fields=['match', 'user'])

        processed_declaration_ids.add(declaration.id)

        # Check for changes if already declared
        if declaration.status == TaxDeclaration.Status.DECLARED:
            declaration.check_for_changes()

        # Check urgency based on declaration type
        match_date = assignment.match.date
        if declaration_type == 'ekho':
            # EKHO: urgent if past 7th of the month after match date and still pending
            if match_date and declaration.status != TaxDeclaration.Status.DECLARED:
                # Calculate the 7th of the next month after match
                if match_date.month == 12:
                    deadline = match_date.replace(year=match_date.year + 1, month=1, day=7)
                else:
                    deadline = match_date.replace(month=match_date.month + 1, day=7)
                is_urgent = today > deadline
            else:
                is_urgent = False
        else:
            # EFO: urgent if match is within 5 days
            is_urgent = match_date and match_date <= five_days_from_now

        # Get fee data - first check for custom fee, otherwise calculate from phase
        try:
            match_fee = assignment.fee
            fee_amount = match_fee.final_amount
        except Exception:
            # Use calculated fee from phase settings
            fee_amount = assignment.match.get_payment_per_referee()

        # Calculate gross amount for EKHO (bruttó = nettó / 0.85)
        if fee_amount:
            gross_amount = round(Decimal(str(fee_amount)) / Decimal('0.85'), 0)
        else:
            gross_amount = None

        item = {
            'assignment': assignment,
            'declaration': declaration,
            'is_urgent': is_urgent,
            'fee_amount': fee_amount,
            'gross_amount': gross_amount,
        }

        # Sort into appropriate list
        if declaration.is_hidden:
            hidden_items.append(item)
        elif declaration.status == TaxDeclaration.Status.PENDING:
            pending_items.append(item)
        elif declaration.status == TaxDeclaration.Status.MODIFIED:
            modified_items.append(item)
        else:
            declared_items.append(item)

    # Handle re-assignments with PENDING status
    # (User was removed then re-added but hasn't accepted yet)
    # We need to re-link orphaned declarations to the new PENDING assignments
    pending_assignments = MatchAssignment.objects.filter(
        user_id__in=user_ids,
        response_status=MatchAssignment.ResponseStatus.PENDING,
        match__is_deleted=False,
        match__is_assignment_published=True
    ).filter(
        mfsz_declaration_filter
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).select_related('user', 'match')

    for assignment in pending_assignments:
        # Check if there's an orphaned declaration for this user+match
        orphaned = TaxDeclaration.objects.filter(
            declaration_type=declaration_type,
            assignment__isnull=True,
            user=assignment.user,
            match=assignment.match
        ).first()

        if orphaned:
            # Re-link orphaned declaration to the new pending assignment
            orphaned.assignment = assignment
            # Reset status if it was marked as modified due to removal
            if orphaned.status == TaxDeclaration.Status.MODIFIED and orphaned.changes_detected:
                changes = orphaned.changes_detected
                if len(changes) == 1 and changes[0].get('field') == 'assignment_deleted':
                    # User was re-added, revert to declared status
                    orphaned.status = TaxDeclaration.Status.DECLARED
                    orphaned.changes_detected = []
            orphaned.save()
            processed_declaration_ids.add(orphaned.id)

    # Filter for matches that require MFSZ declaration (for orphaned declarations)
    orphaned_mfsz_filter = (
        Q(match__mfsz_declaration_override=True) |
        (Q(match__mfsz_declaration_override__isnull=True) & Q(match__phase__requires_mfsz_declaration=True)) |
        (Q(match__mfsz_declaration_override__isnull=True) & Q(match__phase__isnull=True))
    )

    # Get orphaned declarations (assignment was deleted but declaration exists)
    orphaned_declarations = TaxDeclaration.objects.filter(
        declaration_type=declaration_type,
        assignment__isnull=True,
        user_id__in=user_ids,
        match__is_deleted=False,
        match__is_assignment_published=True
    ).filter(
        orphaned_mfsz_filter
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).exclude(
        id__in=processed_declaration_ids
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition',
        'user'
    )

    # Apply filters to orphaned declarations
    if date_from:
        orphaned_declarations = orphaned_declarations.filter(match__date__gte=date_from)
    if date_to:
        orphaned_declarations = orphaned_declarations.filter(match__date__lte=date_to)
    if venue_id:
        orphaned_declarations = orphaned_declarations.filter(match__venue_id=venue_id)
    if user_id:
        orphaned_declarations = orphaned_declarations.filter(user_id=user_id)

    orphaned_declarations = orphaned_declarations.order_by('match__date', 'match__time')

    # Filter out orphaned declarations where user has been re-assigned to same match
    # This happens when user was removed then re-added - we need to check ALL assignments
    # (including PENDING ones, not just ACCEPTED that we processed above)
    reassigned_user_match_pairs = set()

    # First, get pairs from processed items (ACCEPTED assignments)
    for item in pending_items + declared_items + modified_items:
        if item['assignment']:
            reassigned_user_match_pairs.add((item['assignment'].user_id, item['assignment'].match_id))

    # Also check for PENDING assignments (not yet accepted but re-assigned)
    pending_reassignments = MatchAssignment.objects.filter(
        user_id__in=user_ids,
        response_status=MatchAssignment.ResponseStatus.PENDING,
        match__is_deleted=False,
        match__is_assignment_published=True
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).values_list('user_id', 'match_id')

    for user_id_val, match_id_val in pending_reassignments:
        reassigned_user_match_pairs.add((user_id_val, match_id_val))

    orphaned_declarations = [
        d for d in orphaned_declarations
        if (d.user_id, d.match_id) not in reassigned_user_match_pairs
    ]

    # Process orphaned declarations
    for declaration in orphaned_declarations:
        if declaration.status == TaxDeclaration.Status.DECLARED:
            declaration.check_for_changes()

        match_date = declaration.match.date if declaration.match else None
        if declaration_type == 'ekho':
            # EKHO: urgent if past 7th of the month after match date and still pending
            if match_date and declaration.status != TaxDeclaration.Status.DECLARED:
                if match_date.month == 12:
                    deadline = match_date.replace(year=match_date.year + 1, month=1, day=7)
                else:
                    deadline = match_date.replace(month=match_date.month + 1, day=7)
                is_urgent = today > deadline
            else:
                is_urgent = False
        else:
            is_urgent = match_date and match_date <= five_days_from_now

        item = {
            'assignment': None,
            'declaration': declaration,
            'is_orphaned': True,
            'is_urgent': is_urgent,
        }

        if declaration.is_hidden:
            hidden_items.append(item)
        elif declaration.status == TaxDeclaration.Status.MODIFIED:
            modified_items.append(item)
        elif declaration.status == TaxDeclaration.Status.DECLARED:
            declared_items.append(item)

    # Get resigned declarations (assignment is DECLINED but declaration exists)
    # These are referees who resigned after the match was declared
    resigned_declarations = TaxDeclaration.objects.filter(
        declaration_type=declaration_type,
        assignment__isnull=False,
        assignment__response_status=MatchAssignment.ResponseStatus.DECLINED,
        status__in=[TaxDeclaration.Status.DECLARED, TaxDeclaration.Status.MODIFIED],
        user_id__in=user_ids,
        match__is_deleted=False,
        match__is_assignment_published=True
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).exclude(
        id__in=processed_declaration_ids
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition',
        'user', 'assignment'
    )

    # Apply filters to resigned declarations
    if date_from:
        resigned_declarations = resigned_declarations.filter(match__date__gte=date_from)
    if date_to:
        resigned_declarations = resigned_declarations.filter(match__date__lte=date_to)
    if venue_id:
        resigned_declarations = resigned_declarations.filter(match__venue_id=venue_id)
    if user_id:
        resigned_declarations = resigned_declarations.filter(user_id=user_id)

    resigned_declarations = resigned_declarations.order_by('match__date', 'match__time')

    # Process resigned declarations
    for declaration in resigned_declarations:
        if declaration.status == TaxDeclaration.Status.DECLARED:
            declaration.check_for_changes()

        match_date = declaration.match.date if declaration.match else None
        if declaration_type == 'ekho':
            # EKHO: urgent if past 7th of the month after match date and still pending
            if match_date and declaration.status != TaxDeclaration.Status.DECLARED:
                if match_date.month == 12:
                    deadline = match_date.replace(year=match_date.year + 1, month=1, day=7)
                else:
                    deadline = match_date.replace(month=match_date.month + 1, day=7)
                is_urgent = today > deadline
            else:
                is_urgent = False
        else:
            is_urgent = match_date and match_date <= five_days_from_now

        item = {
            'assignment': declaration.assignment,
            'declaration': declaration,
            'is_resigned': True,
            'is_urgent': is_urgent,
        }

        if declaration.is_hidden:
            hidden_items.append(item)
        elif declaration.status == TaxDeclaration.Status.MODIFIED:
            modified_items.append(item)

    # Get venues for filter dropdown
    venues = Venue.objects.all().order_by('name')

    # Calculate total pending count (pending + modified, excluding hidden)
    pending_total_count = len(pending_items) + len(modified_items)

    context = {
        'declaration_type': declaration_type,
        'declaration_type_display': 'EFO' if declaration_type == 'efo' else 'EKHO',
        'pending_items': pending_items,
        'declared_items': declared_items,
        'modified_items': modified_items,
        'hidden_items': hidden_items,
        'pending_total_count': pending_total_count,
        'users_with_type': users_with_type,
        'venues': venues,
        'date_from': date_from,
        'date_to': date_to,
        'selected_venue': venue_id,
        'selected_user': user_id,
    }

    template = 'billing/efo.html' if declaration_type == 'efo' else 'billing/ekho.html'
    return render(request, template, context)


@login_required
def referee_data(request):
    """Accountant: View referee data."""
    if not request.user.is_accountant:
        return HttpResponseForbidden('Nincs jogosultságod.')

    # Get all referees and JT admins (include both role-based and flag-based users)
    users = User.objects.filter(
        Q(role=User.Role.REFEREE) | Q(role=User.Role.JT_ADMIN) |
        Q(is_referee_flag=True) | Q(is_jt_admin_flag=True),
        is_deleted=False
    ).order_by('last_name', 'first_name')

    context = {
        'users': users,
    }

    return render(request, 'billing/referee_data.html', context)


@login_required
def api_tig_update(request):
    """API endpoint to update TIG amounts and soft-delete assignments."""
    from django.http import JsonResponse
    from django.views.decorators.http import require_POST
    from decimal import Decimal
    from .models import MatchFee
    import json

    if not request.user.is_jt_admin:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        data = json.loads(request.body)
        changes = data.get('changes', [])
        deletions = data.get('deletions', [])

        # Process fee changes
        for change in changes:
            assignment_id = change.get('assignment_id')
            new_amount = change.get('amount', 0)

            try:
                assignment = MatchAssignment.objects.get(id=assignment_id)

                # Get or create MatchFee
                match_fee, created = MatchFee.objects.get_or_create(
                    assignment=assignment,
                    defaults={
                        'base_amount': Decimal(new_amount),
                        'final_amount': Decimal(new_amount),
                    }
                )

                if not created:
                    # Calculate adjustment from original (uses model method for tournament support)
                    original_fee = assignment.match.get_payment_per_referee()

                    match_fee.base_amount = Decimal(original_fee)
                    match_fee.manual_adjustment = Decimal(new_amount) - Decimal(original_fee)
                    match_fee.final_amount = Decimal(new_amount)
                    match_fee.save()

            except MatchAssignment.DoesNotExist:
                continue

        # Process soft deletions - set fee to 0 (or actually delete)
        for assignment_id in deletions:
            try:
                assignment = MatchAssignment.objects.get(id=assignment_id)
                # Option 1: Set fee to 0
                match_fee, created = MatchFee.objects.get_or_create(
                    assignment=assignment,
                    defaults={
                        'base_amount': Decimal(0),
                        'final_amount': Decimal(0),
                    }
                )
                if not created:
                    match_fee.base_amount = Decimal(0)
                    match_fee.final_amount = Decimal(0)
                    match_fee.manual_adjustment = Decimal(0)
                    match_fee.adjustment_reason = 'Törölve'
                    match_fee.save()
            except MatchAssignment.DoesNotExist:
                continue

        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def travel_costs_admin(request):
    """JT Admin / VB: Review and approve travel cost reimbursements."""
    from .models import TravelCost
    from matches.models import Venue
    import calendar
    from datetime import date, timedelta

    if not (request.user.is_jt_admin or request.user.is_vb):
        return HttpResponseForbidden('Nincs jogosultságod.')

    now = timezone.localtime(timezone.now())
    today = now.date()

    # Get year and month from request, default to current
    year = request.GET.get('year', today.year)
    month = request.GET.get('month', today.month)

    try:
        year = int(year)
        month = int(month)
    except (ValueError, TypeError):
        year = today.year
        month = today.month

    # Get filter values
    view_mode = request.GET.get('view', 'month')  # 'month' or 'all_pending'
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    venue_id = request.GET.get('venue', '')
    user_id = request.GET.get('user', '')
    competition_id = request.GET.get('competition', '')
    status_filter = request.GET.get('status', '')

    # Time-based filtering
    one_min_ago = (now - timedelta(minutes=1)).time()

    # Build date range for selected month
    _, last_day = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    # Different query based on view mode
    if view_mode == 'all_pending':
        # Get all pending travel costs, filtered by year/month
        travel_costs = TravelCost.objects.filter(
            status=TravelCost.Status.PENDING,
            assignment__match__is_deleted=False,
            assignment__match__date__gte=month_start,
            assignment__match__date__lte=month_end,
        ).select_related(
            'assignment', 'assignment__match', 'assignment__match__home_team',
            'assignment__match__away_team', 'assignment__match__venue',
            'assignment__match__phase', 'assignment__match__phase__competition',
            'assignment__user'
        ).exclude(
            assignment__match__status=Match.Status.CANCELLED
        )

        # Apply additional date filters (if specified, these narrow down further)
        if date_from:
            travel_costs = travel_costs.filter(assignment__match__date__gte=date_from)
        if date_to:
            travel_costs = travel_costs.filter(assignment__match__date__lte=date_to)
        if venue_id:
            travel_costs = travel_costs.filter(assignment__match__venue_id=venue_id)
        if user_id:
            travel_costs = travel_costs.filter(assignment__user_id=user_id)
        if competition_id:
            travel_costs = travel_costs.filter(assignment__match__phase__competition_id=competition_id)

        travel_costs = travel_costs.order_by('-assignment__match__date', '-assignment__match__time')

        # Build data from travel costs
        assignments_data = []
        for tc in travel_costs:
            assignments_data.append({
                'assignment': tc.assignment,
                'travel_cost': tc,
            })
    else:
        # Monthly view - only show items with travel costs
        travel_costs_query = TravelCost.objects.filter(
            assignment__match__is_deleted=False,
            assignment__match__date__gte=month_start,
            assignment__match__date__lte=month_end,
        ).select_related(
            'assignment', 'assignment__match', 'assignment__match__home_team',
            'assignment__match__away_team', 'assignment__match__venue',
            'assignment__match__phase', 'assignment__match__phase__competition',
            'assignment__user'
        ).exclude(
            assignment__match__status=Match.Status.CANCELLED
        )

        # Apply date filters within month
        if date_from:
            travel_costs_query = travel_costs_query.filter(assignment__match__date__gte=date_from)
        if date_to:
            travel_costs_query = travel_costs_query.filter(assignment__match__date__lte=date_to)
        if venue_id:
            travel_costs_query = travel_costs_query.filter(assignment__match__venue_id=venue_id)
        if user_id:
            travel_costs_query = travel_costs_query.filter(assignment__user_id=user_id)
        if competition_id:
            travel_costs_query = travel_costs_query.filter(assignment__match__phase__competition_id=competition_id)

        # Filter by status
        if status_filter:
            if status_filter == 'pending':
                travel_costs_query = travel_costs_query.filter(status=TravelCost.Status.PENDING)
            elif status_filter == 'approved':
                travel_costs_query = travel_costs_query.filter(status=TravelCost.Status.APPROVED)
            elif status_filter == 'rejected':
                travel_costs_query = travel_costs_query.filter(status=TravelCost.Status.REJECTED)
            elif status_filter == 'returned':
                travel_costs_query = travel_costs_query.filter(status=TravelCost.Status.RETURNED)
            elif status_filter == 'declined':
                travel_costs_query = travel_costs_query.filter(status=TravelCost.Status.DECLINED)

        travel_costs_query = travel_costs_query.order_by('-assignment__match__date', '-assignment__match__time')

        # Build data
        assignments_data = []
        for tc in travel_costs_query:
            assignments_data.append({
                'assignment': tc.assignment,
                'travel_cost': tc,
            })

    # Hungarian month names
    month_names = [
        'Január', 'Február', 'Március', 'Április', 'Május', 'Június',
        'Július', 'Augusztus', 'Szeptember', 'Október', 'November', 'December'
    ]

    # Get filter options
    current_season = Season.get_current()
    competitions = Competition.objects.filter(season=current_season) if current_season else Competition.objects.none()
    venues = Venue.objects.all().order_by('name')
    users = User.objects.filter(
        Q(role=User.Role.REFEREE) | Q(role=User.Role.JT_ADMIN) |
        Q(is_referee_flag=True) | Q(is_jt_admin_flag=True),
        is_deleted=False
    ).order_by('last_name', 'first_name')

    # Count all pending for badge
    all_pending_count = TravelCost.objects.filter(
        status=TravelCost.Status.PENDING,
        assignment__match__is_deleted=False
    ).exclude(
        assignment__match__status=Match.Status.CANCELLED
    ).count()

    context = {
        'assignments_data': assignments_data,
        'competitions': competitions,
        'venues': venues,
        'users': users,
        'selected_year': year,
        'selected_month': month,
        'month_names': month_names,
        'view_mode': view_mode,
        'date_from': date_from,
        'date_to': date_to,
        'selected_venue': venue_id,
        'selected_user': user_id,
        'selected_competition': competition_id,
        'selected_status': status_filter,
        'all_pending_count': all_pending_count,
        'is_admin': request.user.is_admin_user,
    }

    return render(request, 'billing/travel_costs_admin.html', context)


@login_required
def api_travel_cost_approve(request, travel_cost_id):
    """API endpoint to approve a travel cost."""
    from django.http import JsonResponse
    from .models import TravelCost
    from documents.models import Notification
    import json

    if not (request.user.is_jt_admin or request.user.is_vb):
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)
        data = json.loads(request.body) if request.body else {}

        # Update amount if provided
        amount = data.get('amount')
        if amount is not None:
            from decimal import Decimal
            travel_cost.amount = Decimal(str(amount))

        travel_cost.status = TravelCost.Status.APPROVED
        travel_cost.reviewed_by = request.user
        travel_cost.reviewed_at = timezone.now()
        travel_cost.comment = data.get('comment', '')
        travel_cost.save()

        # Audit log
        log_action(request, 'travel', 'accept', f'Útiköltség jóváhagyva - {travel_cost.assignment.user.get_full_name()}', obj=travel_cost, extra={
            'amount': str(travel_cost.amount),
            'user': travel_cost.assignment.user.get_full_name()
        })

        # Send notification to the user
        match = travel_cost.assignment.match
        date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
        teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
        amount_str = f"{int(travel_cost.amount)} Ft" if travel_cost.amount else ''

        Notification.objects.create(
            recipient=travel_cost.assignment.user,
            title="Útiköltség jóváhagyva",
            message=f"{date_str}\n{teams}\n{amount_str}",
            notification_type=Notification.Type.SUCCESS,
            link="/billing/travel-costs/"
        )

        return JsonResponse({'success': True})

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_travel_cost_reject(request, travel_cost_id):
    """API endpoint to reject a travel cost."""
    from django.http import JsonResponse
    from .models import TravelCost
    from documents.models import Notification
    import json

    if not (request.user.is_jt_admin or request.user.is_vb):
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)
        data = json.loads(request.body) if request.body else {}

        travel_cost.status = TravelCost.Status.REJECTED
        travel_cost.reviewed_by = request.user
        travel_cost.reviewed_at = timezone.now()
        travel_cost.comment = data.get('comment', '')
        travel_cost.save()

        # Audit log
        log_action(request, 'travel', 'reject', f'Útiköltség elutasítva - {travel_cost.assignment.user.get_full_name()}', obj=travel_cost, extra={
            'user': travel_cost.assignment.user.get_full_name(),
            'reason': travel_cost.comment
        })

        # Send notification to the user
        match = travel_cost.assignment.match
        date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
        teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
        reason = travel_cost.comment if travel_cost.comment else 'Nincs indoklás megadva'

        Notification.objects.create(
            recipient=travel_cost.assignment.user,
            title="Útiköltség elutasítva",
            message=f"{date_str}\n{teams}\n{reason}",
            notification_type=Notification.Type.WARNING,
            link="/billing/travel-costs/"
        )

        return JsonResponse({'success': True})

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_travel_cost_return(request, travel_cost_id):
    """API endpoint to return a travel cost for re-upload."""
    from django.http import JsonResponse
    from .models import TravelCost
    from documents.models import Notification
    import json

    if not (request.user.is_jt_admin or request.user.is_vb):
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)
        data = json.loads(request.body) if request.body else {}

        comment = data.get('comment', '')
        if not comment.strip():
            return JsonResponse({'success': False, 'error': 'A visszaküldés okának megadása kötelező.'}, status=400)

        travel_cost.status = TravelCost.Status.RETURNED
        travel_cost.reviewed_by = request.user
        travel_cost.reviewed_at = timezone.now()
        travel_cost.comment = comment
        travel_cost.save()

        # Audit log
        log_action(request, 'travel', 'update', f'Útiköltség visszaküldve javításra - {travel_cost.assignment.user.get_full_name()}', obj=travel_cost, extra={
            'user': travel_cost.assignment.user.get_full_name(),
            'reason': comment
        })

        # Send notification to the user
        match = travel_cost.assignment.match
        date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
        teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"

        Notification.objects.create(
            recipient=travel_cost.assignment.user,
            title="Útiköltség visszaküldve",
            message=f"{date_str}\n{teams}\n{comment}",
            notification_type=Notification.Type.WARNING,
            link="/billing/travel-costs/"
        )

        return JsonResponse({'success': True})

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_declaration_declare(request, declaration_id):
    """API endpoint to mark an assignment as declared."""
    from django.http import JsonResponse
    from .models import TaxDeclaration

    if not request.user.is_accountant:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        declaration = TaxDeclaration.objects.get(id=declaration_id)
        declaration.mark_as_declared(request.user)
        # Audit log
        log_action(request, 'declaration', 'send', f'{declaration.get_declaration_type_display()} bejelentés elküldve - {declaration.user.get_full_name()}', obj=declaration)
        return JsonResponse({'success': True})

    except TaxDeclaration.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_declaration_undeclare(request, declaration_id):
    """API endpoint to move an assignment back to pending."""
    from django.http import JsonResponse
    from .models import TaxDeclaration

    if not request.user.is_accountant:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        declaration = TaxDeclaration.objects.get(id=declaration_id)
        declaration.status = TaxDeclaration.Status.PENDING
        declaration.declared_at = None
        declaration.declared_by = None
        declaration.changes_detected = []
        declaration.save()
        # Audit log
        log_action(request, 'declaration', 'update', f'{declaration.get_declaration_type_display()} bejelentés visszavonva - {declaration.user.get_full_name()}', obj=declaration)
        return JsonResponse({'success': True})

    except TaxDeclaration.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_declaration_delete(request, declaration_id):
    """API endpoint to permanently delete a declaration (only from hidden tab)."""
    from django.http import JsonResponse
    from .models import TaxDeclaration

    if not request.user.is_accountant:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        declaration = TaxDeclaration.objects.get(id=declaration_id)

        # Only allow deleting hidden declarations
        if not declaration.is_hidden:
            return JsonResponse({'success': False, 'error': 'Csak elrejtett bejelentést lehet véglegesen törölni.'}, status=400)

        # Audit log before delete
        log_action(request, 'declaration', 'delete', f'{declaration.get_declaration_type_display()} bejelentés törölve - {declaration.user.get_full_name()}', extra={
            'user': declaration.user.get_full_name(),
            'declaration_id': declaration_id
        })
        declaration.delete()
        return JsonResponse({'success': True})

    except TaxDeclaration.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_declaration_hide(request, declaration_id):
    """API endpoint to hide a declaration."""
    from django.http import JsonResponse
    from .models import TaxDeclaration

    if not request.user.is_accountant:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        declaration = TaxDeclaration.objects.get(id=declaration_id)
        declaration.is_hidden = True
        declaration.hidden_at = timezone.now()
        declaration.save()
        return JsonResponse({'success': True})

    except TaxDeclaration.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_declaration_unhide(request, declaration_id):
    """API endpoint to unhide a declaration (restore from hidden)."""
    from django.http import JsonResponse
    from .models import TaxDeclaration

    if not request.user.is_accountant:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        declaration = TaxDeclaration.objects.get(id=declaration_id)
        declaration.is_hidden = False
        declaration.hidden_at = None
        declaration.save()
        return JsonResponse({'success': True})

    except TaxDeclaration.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _notify_admins_about_travel_cost(travel_cost):
    """Send notification to JT admins about new travel cost upload."""
    from documents.models import Notification

    # Get match details
    match = travel_cost.assignment.match
    date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
    teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
    user_name = travel_cost.assignment.user.get_full_name()
    expense_type_display = 'Autós' if travel_cost.expense_type == 'car' else 'Tömegközlekedés'

    # Get all JT admins
    jt_admins = User.objects.filter(
        Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True),
        is_deleted=False
    )

    # Create notification for each JT admin
    for admin in jt_admins:
        Notification.objects.create(
            recipient=admin,
            title="Új útiköltség jóváhagyásra vár",
            message=f"{user_name}\n{date_str}\n{teams}\n{expense_type_display}",
            notification_type=Notification.Type.INFO,
            link="/billing/travel-costs-admin/?view=all_pending"
        )


@login_required
def api_travel_cost_upload(request):
    """API endpoint to upload a travel cost receipt."""
    from django.http import JsonResponse
    from .models import TravelCost
    from .utils import is_file_type_allowed, validate_file_size
    from decimal import Decimal

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        user = request.user
        assignment_id = request.POST.get('assignment_id')
        expense_type = request.POST.get('type')
        amount = request.POST.get('amount', '')
        document = request.FILES.get('document')

        # Validate required fields
        if not assignment_id:
            return JsonResponse({'success': False, 'error': 'Mérkőzés kiválasztása kötelező.'}, status=400)

        if not expense_type or expense_type not in ['car', 'public_transport']:
            return JsonResponse({'success': False, 'error': 'Típus kiválasztása kötelező.'}, status=400)

        # Get assignment and verify ownership
        try:
            assignment = MatchAssignment.objects.get(id=assignment_id, user=user)
        except MatchAssignment.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'A kiválasztott mérkőzés nem található.'}, status=404)

        # Check if travel cost already exists
        if hasattr(assignment, 'travel_cost') and assignment.travel_cost:
            return JsonResponse({'success': False, 'error': 'Ehhez a mérkőzéshez már van feltöltött útiköltség.'}, status=400)

        # Handle car expense
        if expense_type == 'car':
            # Check permission
            if not user.vehicle_reimbursement_enabled:
                return JsonResponse({'success': False, 'error': 'Nincs jogosultságod autós elszámolásra.'}, status=403)

            if not user.vehicle_license_plate:
                return JsonResponse({'success': False, 'error': 'Nincs regisztrált autó.'}, status=400)

            # Document is required for car expense (kiküldetési rendelvény)
            if not document:
                return JsonResponse({'success': False, 'error': 'Kiküldetési rendelvény feltöltése kötelező.'}, status=400)

            # Validate file type
            if not is_file_type_allowed(document.name):
                return JsonResponse({'success': False, 'error': 'Nem megengedett fájltípus. Elfogadott: PDF, PNG, JPG, JPEG'}, status=400)

            # Validate file size (max 10MB)
            if not validate_file_size(document, max_size_mb=10):
                return JsonResponse({'success': False, 'error': 'A fájl mérete maximum 10MB lehet.'}, status=400)

            # Parse requested amount
            try:
                receipt_amount = Decimal(amount) if amount else Decimal('0')
            except:
                receipt_amount = Decimal('0')

            travel_cost = TravelCost.objects.create(
                assignment=assignment,
                expense_type=TravelCost.ExpenseType.CAR,
                receipt_file=document,
                receipt_amount=receipt_amount,
                status=TravelCost.Status.PENDING,
            )

            # Audit log
            log_action(request, 'travel', 'create', f'Autós útiköltség feltöltve - {assignment.match}', obj=travel_cost, extra={
                'amount': str(receipt_amount),
                'match_id': assignment.match.id
            })

            # Notify JT admins
            _notify_admins_about_travel_cost(travel_cost)

            return JsonResponse({
                'success': True,
                'travel_cost_id': travel_cost.id,
                'message': 'Autós kiküldetési rendelvény sikeresen létrehozva.'
            })

        # Handle public transport expense
        if expense_type == 'public_transport':
            if not document:
                return JsonResponse({'success': False, 'error': 'Dokumentum feltöltése kötelező.'}, status=400)

            # Validate file type
            if not is_file_type_allowed(document.name):
                return JsonResponse({'success': False, 'error': 'Nem megengedett fájltípus. Elfogadott: PDF, PNG, JPG, JPEG'}, status=400)

            # Validate file size (max 10MB)
            if not validate_file_size(document, max_size_mb=10):
                return JsonResponse({'success': False, 'error': 'A fájl mérete maximum 10MB lehet.'}, status=400)

            # Parse amount
            try:
                receipt_amount = Decimal(amount) if amount else Decimal('0')
            except:
                receipt_amount = Decimal('0')

            # Create travel cost
            travel_cost = TravelCost.objects.create(
                assignment=assignment,
                expense_type=TravelCost.ExpenseType.PUBLIC,
                receipt_file=document,
                receipt_amount=receipt_amount,
                status=TravelCost.Status.PENDING,
            )

            # Audit log
            log_action(request, 'travel', 'create', f'Tömegközlekedési útiköltség feltöltve - {assignment.match}', obj=travel_cost, extra={
                'amount': str(receipt_amount),
                'match_id': assignment.match.id
            })

            # Notify JT admins
            _notify_admins_about_travel_cost(travel_cost)

            return JsonResponse({
                'success': True,
                'travel_cost_id': travel_cost.id,
                'message': 'Számla sikeresen feltöltve.',
            })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_travel_cost_preview(request, travel_cost_id):
    """API endpoint to get file preview URL."""
    from django.http import JsonResponse
    from .models import TravelCost

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)

        # Allow owner, JT Admin, and VB to view
        if travel_cost.assignment.user != request.user and not (request.user.is_jt_admin or request.user.is_vb):
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        # Check if file exists
        if not travel_cost.receipt_file:
            return JsonResponse({'success': False, 'error': 'Nincs feltöltött fájl.'}, status=404)

        return JsonResponse({
            'success': True,
            'file_url': travel_cost.receipt_file.url,
            'is_image': travel_cost.is_image,
            'is_pdf': travel_cost.is_pdf,
        })

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_travel_cost_delete(request, travel_cost_id):
    """API endpoint to delete a travel cost (only if pending or returned and owner)."""
    from django.http import JsonResponse
    from .models import TravelCost

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)

        # Only owner can delete
        if travel_cost.assignment.user != request.user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        # Only pending or returned can be deleted
        if travel_cost.status not in [TravelCost.Status.PENDING, TravelCost.Status.RETURNED]:
            return JsonResponse({'success': False, 'error': 'Csak függőben lévő vagy visszaküldött elszámolás törölhető.'}, status=400)

        # Delete file if exists
        if travel_cost.receipt_file:
            travel_cost.receipt_file.delete(save=False)

        travel_cost.delete()

        return JsonResponse({'success': True})

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_travel_cost_reupload(request, travel_cost_id):
    """API endpoint to re-upload a returned travel cost."""
    from django.http import JsonResponse
    from .models import TravelCost
    from .utils import is_file_type_allowed, validate_file_size
    from decimal import Decimal

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)

        # Only owner can re-upload
        if travel_cost.assignment.user != request.user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        # Only returned can be re-uploaded
        if travel_cost.status != TravelCost.Status.RETURNED:
            return JsonResponse({'success': False, 'error': 'Csak visszaküldött elszámolást lehet újra feltölteni.'}, status=400)

        document = request.FILES.get('document')
        amount = request.POST.get('amount', '')

        # Validate document
        if not document:
            return JsonResponse({'success': False, 'error': 'Dokumentum feltöltése kötelező.'}, status=400)

        if not is_file_type_allowed(document.name):
            return JsonResponse({'success': False, 'error': 'Nem megengedett fájltípus. Elfogadott: PDF, PNG, JPG, JPEG'}, status=400)

        if not validate_file_size(document, max_size_mb=10):
            return JsonResponse({'success': False, 'error': 'A fájl mérete maximum 10MB lehet.'}, status=400)

        # Validate amount
        try:
            receipt_amount = Decimal(amount) if amount else Decimal('0')
        except:
            receipt_amount = Decimal('0')

        # Delete old file
        if travel_cost.receipt_file:
            travel_cost.receipt_file.delete(save=False)

        # Update travel cost
        travel_cost.receipt_file = document
        travel_cost.receipt_amount = receipt_amount
        travel_cost.status = TravelCost.Status.PENDING
        travel_cost.reviewed_by = None
        travel_cost.reviewed_at = None
        travel_cost.comment = ''
        travel_cost.save()

        # Notify JT admins
        _notify_admins_about_travel_cost(travel_cost)

        return JsonResponse({
            'success': True,
            'message': 'Dokumentum sikeresen újrafeltöltve.'
        })

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_travel_cost_decline(request, travel_cost_id):
    """API endpoint to decline a returned travel cost (user doesn't want reimbursement)."""
    from django.http import JsonResponse
    from .models import TravelCost

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)

        # Only owner can decline
        if travel_cost.assignment.user != request.user:
            return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

        # Only returned can be declined
        if travel_cost.status != TravelCost.Status.RETURNED:
            return JsonResponse({'success': False, 'error': 'Csak visszaküldött elszámolást lehet lemondani.'}, status=400)

        # Delete file if exists
        if travel_cost.receipt_file:
            travel_cost.receipt_file.delete(save=False)

        # Update status to declined
        travel_cost.status = TravelCost.Status.DECLINED
        travel_cost.amount = 0
        travel_cost.receipt_file = None
        travel_cost.receipt_amount = None
        travel_cost.save()

        return JsonResponse({
            'success': True,
            'message': 'Útiköltség igénylés lemondva.'
        })

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_travel_cost_edit(request, travel_cost_id):
    """API endpoint to edit a travel cost (Admin only)."""
    from django.http import JsonResponse
    from .models import TravelCost
    from decimal import Decimal
    import json

    # Only admin can edit
    if not request.user.is_admin_user:
        return JsonResponse({'success': False, 'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Csak POST kérés engedélyezett.'}, status=405)

    try:
        travel_cost = TravelCost.objects.get(id=travel_cost_id)
        data = json.loads(request.body) if request.body else {}

        status = data.get('status')
        amount = data.get('amount')
        comment = data.get('comment', '')

        # Validate status
        valid_statuses = ['pending', 'approved', 'rejected', 'returned', 'declined']
        if status not in valid_statuses:
            return JsonResponse({'success': False, 'error': 'Érvénytelen státusz.'}, status=400)

        # Validate amount
        if amount is None or float(amount) < 0:
            return JsonResponse({'success': False, 'error': 'Érvénytelen összeg.'}, status=400)

        # Use direct update to bypass model's save() method which overwrites amount
        update_fields = {
            'status': status,
            'amount': Decimal(str(amount)),
            'reviewed_by': request.user,
            'reviewed_at': timezone.now(),
        }
        if comment:
            update_fields['comment'] = comment

        TravelCost.objects.filter(id=travel_cost_id).update(**update_fields)

        return JsonResponse({'success': True})

    except TravelCost.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Nem található.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
