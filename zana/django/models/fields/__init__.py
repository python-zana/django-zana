from functools import wraps

from django.db import models as m
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

__all__ = [
    "PseudoField",
    "AliasField",
]


class PseudoField(m.Field):
    """A field that does not map to a real database column.

    It will be included in migrations but will not create a database column.
    Examples: `AliasField`

    """

    def db_type(self, connection):
        return None

    def get_attname_column(self):
        return self.get_attname(), None


class _Patcher:
    @staticmethod
    def schema_editor(cls: type[BaseDatabaseSchemaEditor]):
        if not getattr(cls._field_should_be_altered, "_zana_checks_pseudo_fields_", None):
            orig__field_should_be_altered = cls._field_should_be_altered

            @wraps(orig__field_should_be_altered)
            def _field_should_be_altered(self: BaseDatabaseSchemaEditor, old_field, new_field):
                if not all(isinstance(f, PseudoField) for f in (old_field, new_field)):
                    return orig__field_should_be_altered(self, old_field, new_field)

            _field_should_be_altered._zana_checks_pseudo_fields_ = True
            cls._field_should_be_altered = _field_should_be_altered

    @classmethod
    def install(cls):
        cls.schema_editor(BaseDatabaseSchemaEditor)


_Patcher.install()


from .aliases import AliasField
