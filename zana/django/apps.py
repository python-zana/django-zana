import os

from django.apps import AppConfig


class ZanaConfig(AppConfig):
    name = f'{__package__}'
    verbose_name = 'Zana'
    label = 'zana'
    path = os.path.dirname(__file__)

