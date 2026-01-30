"""
Password validation utilities and custom token generators.
"""
import re
from datetime import datetime

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int


class InitialPasswordTokenGenerator(PasswordResetTokenGenerator):
    """
    Custom token generator for initial password setup (new users).
    Valid for 24 hours instead of the default PASSWORD_RESET_TIMEOUT.
    """
    TIMEOUT_SECONDS = 86400  # 24 óra

    def check_token(self, user, token):
        """
        Check that a password reset token is correct for a given user.
        Uses custom 24-hour timeout instead of settings.PASSWORD_RESET_TIMEOUT.
        """
        if not (user and token):
            return False
        # Parse the token
        try:
            ts_b36, _ = token.split("-")
        except ValueError:
            return False

        try:
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False

        # Check that the timestamp/uid has not been tampered with
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(
                self._make_token_with_timestamp(user, ts, secret),
                token,
            ):
                break
        else:
            return False

        # Check the timestamp is within limit (24 hours)
        if (self._num_seconds(self._now()) - ts) > self.TIMEOUT_SECONDS:
            return False

        return True


# Singleton instance for initial password setup tokens
initial_password_token_generator = InitialPasswordTokenGenerator()


def validate_password_complexity(password):
    """
    Validate password meets complexity requirements:
    - At least 8 characters
    - At least 1 lowercase letter
    - At least 1 uppercase letter
    - At least 1 number
    - At least 1 special character

    Returns tuple: (is_valid, error_message)
    """
    errors = []

    if len(password) < 8:
        errors.append("legalább 8 karakter hosszú")

    if not re.search(r'[a-z]', password):
        errors.append("legalább 1 kisbetű")

    if not re.search(r'[A-Z]', password):
        errors.append("legalább 1 nagybetű")

    if not re.search(r'[0-9]', password):
        errors.append("legalább 1 szám")

    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?~`]', password):
        errors.append("legalább 1 speciális karakter")

    if errors:
        return False, f"A jelszónak tartalmaznia kell: {', '.join(errors)}."

    return True, None


PASSWORD_REQUIREMENTS_HTML = """
<ul style="margin: 8px 0 0 0; padding-left: 20px; font-size: 0.8rem; color: #6b7280;">
    <li>8 karakter</li>
    <li>legalább 1 kisbetű</li>
    <li>legalább 1 nagybetű</li>
    <li>legalább 1 szám</li>
    <li>legalább 1 speciális karakter (!@#$%^&* stb.)</li>
</ul>
"""
