import os

from .settings import BASE_DIR

DEBUG = True
DATABASES_BY_VENDOR = {
    "sqlite": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
    "pgsql": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "zana",
        "USER": "postgres",
        "PASSWORD": "qwertea21",
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "TEST": {
            "NAME": "zana_django_test",
        },
    },
    "mysql": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "zana_django",
        "USER": "dbuser",
        "PASSWORD": "~1q2w3e4R5T6Y&.",
        "HOST": "127.0.0.1",
        "TEST": {
            "NAME": "zana_django_test",
        },
    },
}
