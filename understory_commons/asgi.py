import os

from django.core.asgi import get_asgi_application

django_env = os.environ.get("DJANGO_ENV", "dev")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"understory_commons.settings.{django_env}")

application = get_asgi_application()
