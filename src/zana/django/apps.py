from django.apps import AppConfig
from django.db.models.signals import class_prepared


@class_prepared.connect
def __on_class_prepared(sender, **kwds):
    from zana.django.models.aliases import ImplementsAliases, _patch_model
    issubclass(sender, ImplementsAliases) and _patch_model(sender)
    


class ZanaAppConfig(AppConfig):
    name = f'{__package__}'
    verbose_name = 'Zana'

