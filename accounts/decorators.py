from functools import wraps

from django.http import HttpResponseForbidden


def coordinator_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role != "coordinator":
            return HttpResponseForbidden("Coordinator access required.")
        return view_func(request, *args, **kwargs)

    return wrapper


def facilitator_or_coordinator_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role not in (
            "coordinator",
            "facilitator",
        ):
            return HttpResponseForbidden("Staff access required.")
        return view_func(request, *args, **kwargs)

    return wrapper
