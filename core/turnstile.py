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


def verify_turnstile(token, ip_address=None):
    """
    Cloudflare Turnstile token ellenőrzése.

    Args:
        token: A cf-turnstile-response mező értéke a formból
        ip_address: Opcionális - a kliens IP címe

    Returns:
        bool: True ha sikeres, False ha sikertelen
    """
    # Ha nincs beállítva a secret key, akkor átengedjük (dev mód)
    if not settings.TURNSTILE_SECRET_KEY:
        return True

    if not token:
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
        return result.get('success', False)

    except requests.RequestException:
        # Hálózati hiba esetén engedjük át (fail-open)
        # Producition-ben lehet fail-close is, de az rossz UX
        return True
    except Exception:
        return True


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
