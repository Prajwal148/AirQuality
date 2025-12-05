# aqi/decorators.py
from functools import wraps
from django.core.exceptions import PermissionDenied

def app_admin_required(view_func=None, *, allow_superusers: bool = True):
    """
    Guard a view so only app admins (Profile.is_app_admin) — and optionally
    Django superusers/staff — may access it.

    Usage:
        @app_admin_required
        def my_view(...): ...

        @app_admin_required(allow_superusers=False)
        def stricter_view(...): ...
    """
    def decorator(fn):
        @wraps(fn)
        def _wrapped(request, *args, **kwargs):
            user = getattr(request, "user", None)
            ok = False
            if user and user.is_authenticated:
                prof = getattr(getattr(user, "profile", None), "is_app_admin", False)
                ok = bool(prof)
                if allow_superusers and not ok:
                    ok = user.is_superuser or user.is_staff
            if not ok:
                raise PermissionDenied("Admin privileges required.")
            return fn(request, *args, **kwargs)
        return _wrapped

    # Support both @app_admin_required and @app_admin_required(...)
    if view_func is not None:
        return decorator(view_func)
    return decorator
