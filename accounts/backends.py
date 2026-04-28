from django.contrib.auth.backends import ModelBackend


class MagicLinkBackend(ModelBackend):
    """Auth backend for magic-link login. Password authentication is disabled.

    authenticate() always returns None — login is performed directly by
    the magic_login view after token validation. This backend exists so
    Django's request.user resolution (get_user) works on subsequent requests.
    """

    def authenticate(self, request, **credentials):
        return None
