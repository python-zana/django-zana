import copy
import re
import typing as t
from operator import attrgetter
from types import new_class

from typing_extensions import Self
from zana.common import cached_attr
from zana.proxy import Proxy

from django.db import models as m

_T_Model = t.TypeVar("_T_Model", bound=m.Model, covariant=True)
# __set__ value type
_ST = t.TypeVar("_ST")
# __get__ return type
_GT = t.TypeVar("_GT")
_T_Field = t.TypeVar("_T_Field", bound="m.Field[m.Combinable | t.Any, t.Any]")


class PseudoField(m.Field, t.Generic[_GT, _ST]):
    """A field type that does not directly correspond to a database column.

    Serves as a base class to fields such as `AliasField`
    """

    output_field: "m.Field[_ST, _GT]" = None

    def __init__(self, *args, output_field: _T_Field = None, **kwargs) -> None:
        if output_field is not None:
            self.output_field = output_field
        super().__init__(*args, **kwargs)

    @cached_attr
    def cached_col(self: Self):
        return self.make_col(self.model._meta.db_table, self)

    @cached_attr
    def concrete_field(self: Self):
        return self._adapt_real_field(self._get_real_field())

    def db_type(self, connection):
        return None

    def get_attname_column(self):
        return self.get_attname(), None

    def get_col(self, alias: str, output_field: m.Field = None):
        if alias == self.model._meta.db_table and (output_field is None or output_field == self):
            return self.cached_col
        return self.make_col(alias, output_field)

    def make_col(self, alias: str, output_field: m.Field = None):
        raise NotImplementedError(f"{self.__class__.__qualname__}")

    def contribute_to_class(self, cls: type[_T_Model], name: str, private_only: bool = None):
        super().contribute_to_class(cls, name, private_only)
        if descriptor := self.get_descriptor():
            if hasattr(descriptor, "__set_name__"):
                descriptor.__set_name__(cls, self.attname)
            setattr(cls, self.attname, descriptor)

    def deconstruct(self):
        base: tuple[str, str, list, dict] = super().deconstruct()
        cls, (name, path, args, kwargs) = self.__class__, base

        if kwargs.get("output_field", self.output_field) != cls.output_field:
            kwargs["output_field"] = self.output_field

        return name, path, args, kwargs

    def get_descriptor_class(self):
        return self.descriptor_class

    def get_descriptor(self):
        if (cls := self.get_descriptor_class()) is not None:
            return cls(self)

    def _get_real_field(self):
        return self.output_field

    def _adapt_real_field(self, field: m.Field | None):
        if field is not None:
            field = copy.deepcopy(field)
            field.choices = field.choices or self.choices
            field.set_attributes_from_name(self.name)
            field.model = Proxy(attrgetter("model"), self)
        return field

    def _real_field_method(name):
        def method(self: Self, /, *a, **kw):
            nonlocal name
            return getattr(self.concrete_field or super(), name)(*a, **kw)

        method.__name__ = name
        return method

    for m in (
        "get_prep_value",
        "get_db_prep_value",
        "get_db_prep_save",
        "to_python",
        "value_from_object",
        "value_to_string",
        "formfield",
    ):
        vars()[m] = _real_field_method(m)

    del _real_field_method
