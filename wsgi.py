"""WSGI entrypoint untuk gunicorn"""
from dashboard_app import app as application

# gunicorn akan cari variable `app` atau `application`
app = application
