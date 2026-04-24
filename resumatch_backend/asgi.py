"""ASGI config for the RESUMATCH backend."""
import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "resumatch_backend.settings")

application = get_asgi_application()
