from django.conf import settings
from django.urls import path
from django.views.static import serve

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("index.html", views.home, name="home-html"),
    path("practice/", views.practice, name="practice"),
    path("practice.html", views.practice, name="practice-html"),
    path("api/analyze/", views.analyze_resume, name="analyze-resume"),
    path("app.js", serve, {"document_root": settings.BASE_DIR, "path": "app.js"}),
    path("styles.css", serve, {"document_root": settings.BASE_DIR, "path": "styles.css"}),
]
