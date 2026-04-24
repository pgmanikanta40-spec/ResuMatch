"""WSGI config for the RESUMATCH backend."""
import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "resumatch_backend.settings")

application = get_wsgi_application()
