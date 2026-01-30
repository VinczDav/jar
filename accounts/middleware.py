"""
Middleware for user status checks.
"""
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.contrib import messages


class UserStatusMiddleware:
    """
    Middleware that checks if a logged-in user is still active.
    Kicks out users who have been archived, deleted, or login disabled.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only check authenticated users
        if request.user.is_authenticated:
            # Refresh user from database to get latest status
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(pk=request.user.pk)

                # Check if user should be kicked out
                should_logout = False

                if user.is_deleted:
                    should_logout = True
                elif user.is_archived:
                    should_logout = True
                elif user.is_login_disabled:
                    should_logout = True

                if should_logout:
                    # Log the user out
                    logout(request)
                    # Redirect to login page
                    return redirect('accounts:login')

            except User.DoesNotExist:
                # User no longer exists, log them out
                logout(request)
                return redirect('accounts:login')

        response = self.get_response(request)
        return response
