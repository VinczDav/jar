"""
Email utility functions for JAR system.

Usage:
    from core.email_utils import send_templated_email, send_email

    # Send templated email
    send_templated_email(
        to_email='user@example.com',
        subject='Mérkőzés emlékeztető',
        template_name='match_reminder',
        context={
            'user_name': 'Kiss János',
            'match': match_obj,
        }
    )

    # Send simple email
    send_email(
        to_email='user@example.com',
        subject='Test',
        html_content='<p>Hello</p>',
        text_content='Hello'
    )
"""

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
from django.utils import timezone
from django.db import models
import logging

logger = logging.getLogger(__name__)


def is_email_enabled():
    """
    Check if email sending is enabled in site settings.
    """
    try:
        from accounts.models import SiteSettings
        settings_obj = SiteSettings.get_settings()
        return settings_obj.email_enabled
    except Exception:
        # If we can't check, assume enabled
        return True


def send_email(to_email, subject, html_content, text_content=None, from_email=None):
    """
    Send a simple email with HTML and optional text content.
    """
    # Check if email is enabled
    if not is_email_enabled():
        logger.info(f"[EMAIL] Email sending is disabled in settings, skipping: {subject}")
        return False

    if isinstance(to_email, str):
        to_email = [to_email]

    # Filter out empty emails
    to_email = [e for e in to_email if e]
    if not to_email:
        return False

    if text_content is None:
        text_content = strip_tags(html_content)

    from_email = from_email or settings.DEFAULT_FROM_EMAIL

    # Log to console in TEST_EMAIL mode (for debugging)
    test_email_mode = getattr(settings, 'TEST_EMAIL', False)
    if test_email_mode and settings.DEBUG:
        print("\n" + "=" * 60)
        print("📧 EMAIL KÜLDÉS (TEST MODE)")
        print("=" * 60)
        print(f"Címzett: {', '.join(to_email)}")
        print(f"Feladó: {from_email}")
        print(f"Tárgy: {subject}")
        print("-" * 60)
        print(html_content[:500] + "..." if len(html_content) > 500 else html_content)
        print("=" * 60 + "\n")

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=to_email
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        if test_email_mode and settings.DEBUG:
            print(f"✅ Email sikeresen elküldve: {', '.join(to_email)}\n")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        if test_email_mode and settings.DEBUG:
            print(f"❌ Email küldés sikertelen: {e}\n")
        return False


def send_templated_email(to_email, subject, template_name, context=None, from_email=None):
    """
    Send an email using Django templates.
    """
    logger.info(f"[TEMPLATED EMAIL] Starting: to={to_email}, template={template_name}")
    context = context or {}

    # Add common context
    context.setdefault('site_name', 'JAR')
    context.setdefault('site_url', getattr(settings, 'SITE_URL', 'https://jar.hu'))
    context.setdefault('current_year', timezone.now().year)

    # Render HTML template
    html_template = f'emails/{template_name}.html'
    try:
        html_content = render_to_string(html_template, context)
        logger.info(f"[TEMPLATED EMAIL] HTML template rendered successfully, length={len(html_content)}")
    except Exception as e:
        logger.error(f"[TEMPLATED EMAIL] HTML template render FAILED: {e}", exc_info=True)
        raise

    # Try to render text template, fallback to stripping HTML
    try:
        txt_template = f'emails/{template_name}.txt'
        text_content = render_to_string(txt_template, context)
        logger.info(f"[TEMPLATED EMAIL] Text template rendered")
    except Exception:
        text_content = strip_tags(html_content)
        logger.info(f"[TEMPLATED EMAIL] Using stripped HTML for text content")

    return send_email(to_email, subject, html_content, text_content, from_email)


# =============================================================================
# ROLE-BASED EMAIL HELPERS
# =============================================================================

def get_users_with_role(role_name):
    """
    Get all users who have a specific role (primary or secondary).
    """
    from accounts.models import User

    role_map = {
        'jt_admin': (User.Role.JT_ADMIN, 'is_jt_admin_flag'),
        'vb': (User.Role.VB, 'is_vb_flag'),
        'accountant': (User.Role.ACCOUNTANT, 'is_accountant_flag'),
        'inspector': (User.Role.INSPECTOR, 'is_inspector_flag'),
        'admin': (User.Role.ADMIN, 'is_admin_flag'),
        'referee': (User.Role.REFEREE, 'is_referee_flag'),
    }

    if role_name not in role_map:
        return User.objects.none()

    role_value, flag_field = role_map[role_name]

    return User.objects.filter(
        is_active=True,
        is_deleted=False
    ).filter(
        models.Q(role=role_value) | models.Q(**{flag_field: True})
    ).distinct()


def send_to_role(role_name, subject, template_name, context=None):
    """
    Send email to all users with a specific role.
    """
    users = get_users_with_role(role_name)
    emails = list(users.exclude(email='').values_list('email', flat=True))

    if not emails:
        return False

    return send_templated_email(
        to_email=emails,
        subject=subject,
        template_name=template_name,
        context=context
    )


# =============================================================================
# SECURITY ALERTS
# =============================================================================

def send_security_alert(user, alert_type, details=None, request=None):
    """
    Send a security alert email to admins.
    """
    from accounts.models import User

    # Get all admin users
    admins = User.objects.filter(
        is_admin_flag=True,
        is_active=True,
        is_deleted=False
    ).exclude(email='')

    if not admins.exists():
        return False

    admin_emails = list(admins.values_list('email', flat=True))

    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')

    context = {
        'user': user,
        'alert_type': alert_type,
        'details': details or {},
        'ip_address': ip_address,
    }

    subject_map = {
        'failed_logins': f'Biztonsági figyelmeztetés: 10 sikertelen bejelentkezés - {user.username}',
        'suspicious_activity': f'Gyanús tevékenység - {user.username}',
    }

    subject = subject_map.get(alert_type, f'Biztonsági figyelmeztetés - {user.username}')

    return send_templated_email(
        to_email=admin_emails,
        subject=subject,
        template_name='security_alert',
        context=context
    )


# =============================================================================
# USER ACCOUNT EMAILS
# =============================================================================

def send_welcome_email(user, generated_password=None):
    """
    Send welcome email with password setup link to new user.
    The link is valid for 24 hours.
    """
    if not user.email:
        return False

    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes
    from core.validators import initial_password_token_generator

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = initial_password_token_generator.make_token(user)
    setup_url = f"{settings.SITE_URL}/password-setup/{uid}/{token}/"

    context = {
        'user': user,
        'email': user.email,
        'setup_url': setup_url,
    }

    return send_templated_email(
        to_email=user.email,
        subject='Új fiókot regisztráltak neked a JAR rendszerben!',
        template_name='welcome_password_setup',
        context=context
    )


def send_password_reset_email(user, new_password):
    """
    Send password reset email when admin resets user's password.
    """
    if not user.email:
        return False

    context = {
        'user': user,
        'password': new_password,
    }

    return send_templated_email(
        to_email=user.email,
        subject='Jelszó visszaállítás',
        template_name='password_reset',
        context=context
    )


# =============================================================================
# MATCH ASSIGNMENT EMAILS
# =============================================================================

def send_match_assignment_notification(assignment, notify_type='new', changes=None, new_user_ids=None):
    """
    Send match assignment notification to referee.

    Args:
        assignment: MatchAssignment object
        notify_type: 'new', 'modified', 'removed'
        changes: dict of changes for modified notifications
        new_user_ids: set of user IDs who are newly added (to highlight in email)
    """
    logger.info(f"[ASSIGNMENT EMAIL] Starting send_match_assignment_notification: notify_type={notify_type}, new_user_ids={new_user_ids}")

    user = assignment.user
    if not user or not user.email:
        logger.warning(f"[ASSIGNMENT EMAIL] No user or email: user={user}, email={user.email if user else None}")
        return False

    match = assignment.match
    logger.info(f"[ASSIGNMENT EMAIL] Match: {match}, user: {user.email}")

    # Build detailed subject line
    date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
    day_names = {
        0: 'hétfő', 1: 'kedd', 2: 'szerda', 3: 'csütörtök',
        4: 'péntek', 5: 'szombat', 6: 'vasárnap'
    }
    day_str = day_names.get(match.date.weekday(), '') if match.date else ''
    time_str = match.time.strftime('%H:%M') if match.time else ''
    venue_str = match.venue.name if match.venue else ''

    # Safely get competition name
    comp_str = ''
    try:
        if match.phase and match.phase.competition:
            comp_str = match.phase.competition.name
    except Exception as e:
        logger.warning(f"[ASSIGNMENT EMAIL] Could not get competition: {e}")

    if notify_type == 'new':
        subject = f"Új mérkőzésre lettél kiírva! {date_str} ({day_str}), {time_str}, {venue_str}"
        if comp_str:
            subject += f", ({comp_str})"
    elif notify_type == 'modified':
        subject = f"Megváltozott kiírás: {date_str} ({day_str}) {time_str}, {venue_str}"
        if comp_str:
            subject += f", ({comp_str})"
    elif notify_type == 'removed':
        subject = f"Adminisztrátorod törölt a kiírásból! {date_str} ({day_str}) {time_str}, {venue_str}"
        if comp_str:
            subject += f", ({comp_str})"
    else:
        subject = 'Kiírás változás - JAR'

    logger.info(f"[ASSIGNMENT EMAIL] Subject: {subject}")

    # Get all assignments for this match to show in the email
    # Order by: referee -> reserve -> inspector -> tournament_director
    from matches.models import MatchAssignment
    role_order = {
        MatchAssignment.Role.REFEREE: 0,
        MatchAssignment.Role.RESERVE: 1,
        MatchAssignment.Role.INSPECTOR: 2,
        MatchAssignment.Role.TOURNAMENT_DIRECTOR: 3,
    }
    all_assignments_qs = match.assignments.select_related('user')
    all_assignments = sorted(all_assignments_qs, key=lambda a: (role_order.get(a.role, 99), a.id))
    logger.info(f"[ASSIGNMENT EMAIL] All assignments count: {len(all_assignments)}")

    context = {
        'assignment': assignment,
        'user': user,
        'match': match,
        'notify_type': notify_type,
        'changes': changes,
        'all_assignments': all_assignments,
        'new_user_ids': new_user_ids or set(),
    }

    try:
        result = send_templated_email(
            to_email=user.email,
            subject=subject,
            template_name='match_assignment',
            context=context
        )
        logger.info(f"[ASSIGNMENT EMAIL] send_templated_email result: {result}")
        return result
    except Exception as e:
        logger.error(f"[ASSIGNMENT EMAIL] send_templated_email FAILED: {e}", exc_info=True)
        raise


def send_match_reminder(assignment, days_until=1):
    """
    Send match reminder to referee.
    """
    user = assignment.user
    if not user or not user.email:
        return False

    context = {
        'assignment': assignment,
        'user': user,
        'match': assignment.match,
        'days_until': days_until,
    }

    return send_templated_email(
        to_email=user.email,
        subject='Mérkőzés emlékeztető - JAR',
        template_name='match_reminder',
        context=context
    )


def send_unaccepted_match_reminder(assignment, days_until):
    """
    Send reminder for unaccepted match assignment.
    """
    user = assignment.user
    if not user or not user.email:
        return False

    context = {
        'assignment': assignment,
        'user': user,
        'match': assignment.match,
        'days_until': days_until,
    }

    return send_templated_email(
        to_email=user.email,
        subject=f'El nem fogadott mérkőzésed van {days_until} nap múlva! Fogadd el még ma!',
        template_name='unaccepted_match_reminder',
        context=context
    )


# =============================================================================
# JT ADMIN NOTIFICATIONS
# =============================================================================

def send_assignment_declined_notification(assignment, declining_user):
    """
    Notify JT Admins when someone declines an assignment.
    """
    jt_admins = get_users_with_role('jt_admin').exclude(email='')
    admin_users = get_users_with_role('admin').exclude(email='')

    emails = list(set(
        list(jt_admins.values_list('email', flat=True)) +
        list(admin_users.values_list('email', flat=True))
    ))

    if not emails:
        return False

    match = assignment.match

    # Build subject line
    day_names = {
        0: 'hétfő', 1: 'kedd', 2: 'szerda', 3: 'csütörtök',
        4: 'péntek', 5: 'szombat', 6: 'vasárnap'
    }
    date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
    day_str = day_names.get(match.date.weekday(), '') if match.date else ''
    time_str = match.time.strftime('%H:%M') if match.time else ''
    venue_str = match.venue.name if match.venue else ''
    comp_str = match.phase.competition.name if match.phase and match.phase.competition else ''

    subject = f"{declining_user.get_full_name()} lemondta a mérkőzést: {date_str} ({day_str}), {time_str}, {venue_str}"
    if comp_str:
        subject += f", ({comp_str})"

    # Get all assignments for this match
    # Order by: referee -> reserve -> inspector -> tournament_director
    from matches.models import MatchAssignment
    role_order = {
        MatchAssignment.Role.REFEREE: 0,
        MatchAssignment.Role.RESERVE: 1,
        MatchAssignment.Role.INSPECTOR: 2,
        MatchAssignment.Role.TOURNAMENT_DIRECTOR: 3,
    }
    all_assignments_qs = match.assignments.select_related('user')
    all_assignments = sorted(all_assignments_qs, key=lambda a: (role_order.get(a.role, 99), a.id))

    context = {
        'assignment': assignment,
        'declining_user': declining_user,
        'match': match,
        'all_assignments': all_assignments,
    }

    return send_templated_email(
        to_email=emails,
        subject=subject,
        template_name='assignment_declined',
        context=context
    )


def send_match_data_incomplete_notification(match, days_until):
    """
    Notify JT Admins about incomplete match data.
    """
    jt_admins = get_users_with_role('jt_admin').exclude(email='')
    admin_users = get_users_with_role('admin').exclude(email='')

    emails = list(set(
        list(jt_admins.values_list('email', flat=True)) +
        list(admin_users.values_list('email', flat=True))
    ))

    if not emails:
        return False

    context = {
        'match': match,
        'days_until': days_until,
    }

    return send_templated_email(
        to_email=emails,
        subject=f'Mérkőzés adatai hiányosak ({days_until} nap múlva) - JAR',
        template_name='match_incomplete',
        context=context
    )


# =============================================================================
# TRAVEL COST NOTIFICATIONS
# =============================================================================

def send_travel_cost_status_notification(travel_cost, status_type):
    """
    Send notification about travel cost status change.
    """
    user = travel_cost.user
    if not user or not user.email:
        return False

    match = travel_cost.assignment.match

    # Build subject with match details
    status_labels = {
        'approved': 'Elfogadták',
        'rejected': 'Elutasították',
        'returned': 'Visszaküldték',
    }
    status_label = status_labels.get(status_type, 'Módosult')

    # Build match details for subject
    date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
    day_names = {
        0: 'hétfő', 1: 'kedd', 2: 'szerda', 3: 'csütörtök',
        4: 'péntek', 5: 'szombat', 6: 'vasárnap'
    }
    day_str = day_names.get(match.date.weekday(), '') if match.date else ''
    time_str = match.time.strftime('%H:%M') if match.time else ''
    venue_str = match.venue.name if match.venue else ''
    competition_str = ''
    if hasattr(match, 'phase') and match.phase and match.phase.competition:
        competition_str = match.phase.competition.name
    elif hasattr(match, 'competition') and match.competition:
        competition_str = match.competition.name

    subject = f'{status_label} az útiköltség elszámolásod - {date_str} ({day_str}) {time_str}, {venue_str}'
    if competition_str:
        subject += f', ({competition_str})'

    context = {
        'travel_cost': travel_cost,
        'match': match,
        'user': user,
        'status_type': status_type,
    }

    return send_templated_email(
        to_email=user.email,
        subject=subject,
        template_name='travel_cost_status',
        context=context
    )


def send_new_travel_cost_notification(travel_cost):
    """
    Notify VB/JT Admins about new travel cost submission.
    """
    vb_users = get_users_with_role('vb').exclude(email='')
    jt_admins = get_users_with_role('jt_admin').exclude(email='')

    emails = list(set(
        list(vb_users.values_list('email', flat=True)) +
        list(jt_admins.values_list('email', flat=True))
    ))

    if not emails:
        return False

    context = {
        'travel_cost': travel_cost,
        'user': travel_cost.user,
    }

    return send_templated_email(
        to_email=emails,
        subject='Új útiköltséget rögzítettek',
        template_name='new_travel_cost',
        context=context
    )


# =============================================================================
# MEDICAL CERTIFICATE NOTIFICATIONS
# =============================================================================

def send_medical_certificate_expiring(user, days_until):
    """
    Notify user about expiring medical certificate.
    """
    if not user.email:
        return False

    context = {
        'user': user,
        'days_until': days_until,
        'expiry_date': user.medical_certificate_expiry,
    }

    return send_templated_email(
        to_email=user.email,
        subject=f'A sportorvosi engedélyed {days_until} nap múlva lejár!',
        template_name='medical_certificate_expiring',
        context=context
    )


# =============================================================================
# FEEDBACK NOTIFICATIONS
# =============================================================================

def send_new_feedback_notification(feedback):
    """
    Notify referee about new feedback received.
    """
    referee = feedback.referee
    if not referee or not referee.email:
        return False

    context = {
        'feedback': feedback,
        'referee': referee,
    }

    return send_templated_email(
        to_email=referee.email,
        subject='Új visszajelzést kaptál! - JAR',
        template_name='new_feedback',
        context=context
    )


# =============================================================================
# NEWS AND KNOWLEDGE BASE
# =============================================================================

def send_news_notification(news_item, recipients=None):
    """
    Send notification about new news item.
    """
    if recipients is None:
        # Send to all active referees
        recipients = get_users_with_role('referee')

    emails = [u.email for u in recipients if u.email]
    if not emails:
        return False

    context = {
        'news': news_item,
    }

    return send_templated_email(
        to_email=emails,
        subject=f'Új hír: {news_item.title} - JAR',
        template_name='news_notification',
        context=context
    )


def send_knowledge_base_notification(article, recipients=None):
    """
    Send notification about new knowledge base article.
    """
    if recipients is None:
        # Send to all active referees
        recipients = get_users_with_role('referee')

    emails = [u.email for u in recipients if u.email]
    if not emails:
        return False

    context = {
        'article': article,
    }

    return send_templated_email(
        to_email=emails,
        subject=f'Új bejegyzés a tudástárban: {article.title} - JAR',
        template_name='knowledge_base_notification',
        context=context
    )


# =============================================================================
# ACCOUNTANT (KÖNYVELŐ) NOTIFICATIONS
# =============================================================================

def send_efo_notification(assignments, notification_type='pending', changes=None):
    """
    Send EFO notification to accountants.

    Args:
        assignments: list of MatchAssignment objects
        notification_type: 'pending', 'modified', 'deleted'
        changes: dict of changes for modified notifications
    """
    accountants = get_users_with_role('accountant').exclude(email='')

    if not accountants.exists():
        return False

    # Send to each accountant individually (with their name)
    results = []
    for accountant in accountants:
        subject_map = {
            'pending': 'Várakozó EFO bejelentés',
            'modified': 'Módosult EFO bejelentés',
            'deleted': 'Törölt EFO bejelentés',
        }

        # Prepare assignments with changes info
        assignment_data = []
        for assignment in assignments:
            item = assignment
            if changes:
                item.changes = changes
            else:
                item.changes = {}
            assignment_data.append(item)

        context = {
            'assignments': assignment_data,
            'notification_type': notification_type,
            'accountant_name': accountant.get_full_name(),
        }

        result = send_templated_email(
            to_email=accountant.email,
            subject=subject_map.get(notification_type, 'EFO bejelentés'),
            template_name='efo_notification',
            context=context
        )
        results.append(result)

    return all(results)


def send_ekho_notification(summary):
    """
    Send EKHO notification to accountants (end of month).

    Args:
        summary: list of dicts with 'name', 'match_count', 'total_gross'
    """
    accountants = get_users_with_role('accountant').exclude(email='')

    if not accountants.exists():
        return False

    # Send to each accountant individually
    results = []
    for accountant in accountants:
        context = {
            'summary': summary,
            'accountant_name': accountant.get_full_name(),
        }

        result = send_templated_email(
            to_email=accountant.email,
            subject='Várakozó EKHO bejelentés',
            template_name='ekho_notification',
            context=context
        )
        results.append(result)

    return all(results)
