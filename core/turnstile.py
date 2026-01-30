"""
Cloudflare Turnstile verification utility.

Használat:
    from core.turnstile import verify_turnstile

    # View-ban:
    token = request.POST.get('cf-turnstile-response', '')
    ip = get_client_ip(request)

    if not verify_turnstile(token, ip):
        return render(request, 'login.html', {'error': 'Biztonsági ellenőrzés sikertelen.'})
"""

import requests
from django.conf import settings


def verify_turnstile(token, ip_address=None, fail_open=False):
    """
    Cloudflare Turnstile token ellenőrzése.

    Args:
        token: A cf-turnstile-response mező értéke a formból
        ip_address: Opcionális - a kliens IP címe
        fail_open: Ha True, hálózati hiba esetén átengedi (alapértelmezett: False - szigorú mód)

    Returns:
        bool: True ha sikeres, False ha sikertelen
    """
    import logging
    logger = logging.getLogger(__name__)

    # Ha nincs beállítva a secret key, akkor átengedjük (dev mód)
    if not settings.TURNSTILE_SECRET_KEY:
        return True

    if not token:
        logger.warning(f"Turnstile: no token provided from IP {ip_address}")
        return False

    try:
        data = {
            'secret': settings.TURNSTILE_SECRET_KEY,
            'response': token,
        }

        if ip_address:
            data['remoteip'] = ip_address

        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data=data,
            timeout=10
        )

        result = response.json()

        if not result.get('success', False):
            error_codes = result.get('error-codes', [])
            logger.warning(f"Turnstile verification failed from IP {ip_address}: {error_codes}")

        return result.get('success', False)

    except requests.Timeout:
        logger.error(f"Turnstile verification timeout from IP {ip_address}")
        return fail_open

    except requests.RequestException as e:
        logger.error(f"Turnstile network error from IP {ip_address}: {e}")
        return fail_open

    except Exception as e:
        logger.error(f"Turnstile unexpected error from IP {ip_address}: {e}")
        return fail_open


def get_turnstile_context():
    """
    Turnstile site key a template context-hez.

    Használat view-ban:
        context.update(get_turnstile_context())

    Template-ben:
        {{ turnstile_site_key }}
    """
    return {
        'turnstile_site_key': settings.TURNSTILE_SITE_KEY,
        'turnstile_enabled': bool(settings.TURNSTILE_SITE_KEY),
    }
