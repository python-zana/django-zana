from django.apps import AppConfig
from django.db.models.signals import class_prepared
from zana.django.apps import ZanaAppConfig as BaseAppConfig

\


class ZanaAppConfig(BaseAppConfig):
    # name = f'{__package__}'
    verbose_name = 'Zana'

