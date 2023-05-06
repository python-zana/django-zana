import datetime
import json
import sys
import typing as t
from base64 import b64encode
from collections import abc, defaultdict
from decimal import Decimal
from enum import auto
from functools import partial
from operator import methodcaller
from pickle import NONE
from types import GenericAlias, SimpleNamespace
from uuid import UUID, uuid4

from typing_extensions import Self

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models as m
from django.db.models.fields.related import RelatedField
from tests.faker import ufake
from zana.django.models import AliasField
from zana.django.utils import JsonPrimitive

_FT = t.TypeVar("_FT", bound=m.Field)
_T = t.TypeVar("_T")
_DT = t.TypeVar("_DT")

_notset = object()


T_Func = abc.Callable[..., _T]
TFactoryDict = dict[type[m.Field], T_Func]

FIELD_FACTORIES = {
    m.BooleanField: ufake.pybool,
    m.CharField: ufake.pystr,
    m.EmailField: ufake.email,
    m.SlugField: ufake.slug,
    m.TextField: ufake.text,
    m.URLField: ufake.url,
    m.BinaryField: ufake.memoryview,
    m.GenericIPAddressField: ufake.ipv6,
    m.DateField: ufake.date_object,
    m.DateTimeField: ufake.date_time,
    m.DurationField: ufake.rand_timedelta,
    m.TimeField: ufake.time_object,
    m.FilePathField: ufake.file_path,
    m.DecimalField: ufake.fixed_decimal,
    m.FloatField: ufake.pyfloat,
    m.IntegerField: ufake.pyint,
    m.BigIntegerField: partial(ufake.pyint, int(3e9), int(sys.maxsize * 0.7)),
    m.PositiveBigIntegerField: partial(ufake.pyint, int(3e9), int(sys.maxsize * 0.7)),
    m.SmallIntegerField: partial(ufake.pyint, 0, 9999),
    m.PositiveSmallIntegerField: partial(ufake.pyint, 0, 9999),
    m.PositiveIntegerField: ufake.pyint,
    m.UUIDField: partial(ufake.uuid4, cast_to=None),
    m.JSONField: ufake.json_dict,
    m.FileField: ufake.file_path,
    # m.ImageField: lambda:None,
    m.ForeignKey: lambda: None,
    m.OneToOneField: lambda: None,
    m.ManyToManyField: lambda: None,
}


FIELD_DATA_TYPES = {
    # bool
    m.BooleanField: bool,
    # str
    m.TextField: str,
    m.CharField: str,
    m.EmailField: str,
    m.SlugField: str,
    m.URLField: str,
    m.FileField: str,
    m.FilePathField: str,
    m.GenericIPAddressField: str,
    # m.ImageField: str,
    # bytes
    m.BinaryField: memoryview,
    # date types
    m.DateField: datetime.date,
    m.DateTimeField: datetime.datetime,
    m.DurationField: datetime.timedelta,
    m.TimeField: datetime.time,
    # number types
    m.DecimalField: Decimal,
    m.FloatField: float,
    m.BigIntegerField: int,
    m.IntegerField: int,
    m.PositiveBigIntegerField: int,
    m.SmallIntegerField: int,
    m.PositiveSmallIntegerField: int,
    m.PositiveIntegerField: int,
    # UUID
    m.UUIDField: UUID,
    # JSON
    m.JSONField: JsonPrimitive,
    # relation types
    m.ForeignKey: m.Model,
    m.OneToOneField: m.Model,
    m.ManyToManyField: m.QuerySet,
}

FIELD_TO_JSON_DEFAULTS = defaultdict(
    str,
    {
        m.BinaryField: m.BinaryField().value_to_string,
    },
)


def get_field_py_type(cls: type[_FT] | str) -> type[_T]:
    return FIELD_DATA_TYPES.get(TestModel.get_field(cls).__class__)


def to_field_name(field: str | type[_FT]) -> type[_FT]:
    return (field.__name__ if isinstance(field, type) else field).lower()


_type_2_id_field_map = {}
_id_2_type_field_map = {}


def field_type_id(field: str | type[_FT]) -> str:
    if isinstance(field, str):
        return _type_2_id_field_map[_id_2_type_field_map[field]]
    elif field in _type_2_id_field_map:
        return _type_2_id_field_map[field]

    if app := apps.get_containing_app_config(field.__module__):
        id = f"{app.label}_{field.__name__.lower()}"
    else:
        id = f"{field.__name__.lower()}"

    if field is not _id_2_type_field_map.setdefault(id, field):
        raise TypeError(f"duplicate id {id=}")
    if id is not _type_2_id_field_map.setdefault(field, id):
        raise TypeError(f"multiple ids assigned {field=}")
    return id


class ExprSource(m.TextChoices):
    NONE = "N/A"
    FIELD = auto()
    EVAL = auto()
    JSON = auto()

    def _missing_(cls, val):
        return cls.NONE if val in (None, "") else val


class JSONEncoder(DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, (memoryview, bytes)):
            return b64encode(o).decode("ascii")
        return super().default(o)


class AbcTestModel(m.Model):
    class Meta:
        abstract = True


class TestModel(AbcTestModel):
    __class_getitem__ = classmethod(GenericAlias)

    class Meta:
        verbose_name = "Field Implementation"

    NONE = ExprSource.NONE
    FIELD = ExprSource.FIELD
    EVAL = ExprSource.EVAL
    JSON = ExprSource.JSON

    test: _T
    proxy: _T
    field_name: t.ClassVar[str]
    source: t.ClassVar[ExprSource]
    field_type: t.ClassVar[type[m.Field]]

    implemented: t.Final[dict[type[m.Field], set]] = defaultdict(set)

    charfield = m.CharField(max_length=255, null=True)
    decimalfield = m.DecimalField(decimal_places=6, max_digits=60, null=True)

    foreignkey = m.ForeignKey(
        "self", m.SET_NULL, null=True, related_name="foreignkey_reverse"
    )
    onetoonefield = m.OneToOneField(
        to="self", on_delete=m.SET_NULL, null=True, related_name="onetoonefield_reverse"
    )
    manytomanyfield = m.ManyToManyField("self")

    foreignkey_reverse: "m.manager.RelatedManager[Self]"
    onetoonefield_reverse: Self | None
    # manytomanyfield_reverse: "m.manager.RelatedManager[Self]"

    for cls, fn in FIELD_FACTORIES.items():
        n = field_type_id(cls)
        implemented[cls].update(tuple(ExprSource))
        if n not in vars():
            vars()[n] = cls(null=True)
    del cls, fn, n

    json = m.JSONField(default=dict, encoder=JSONEncoder, null=True)

    def __init_subclass__(cls, **kw):
        super.__init_subclass__(**kw)
        dct = cls.__dict__
        cls.field_type = tt = dct.get("field_type") or None
        cls.field_name = dct.get("field_name") or (tt and tt.__name__.lower())
        cls.source = dct.get("source")

    @classmethod
    def get_field(cls, name: str | type, default: _DT = _notset) -> m.Field | _DT:
        name = to_field_name(name)
        try:
            return cls._meta.get_field(name)
        except FieldDoesNotExist:
            if default is _notset:
                raise
            return default

    @classmethod
    def get_coverage(cls, name: str | type, default: _DT = _notset) -> m.Field | _DT:
        name = to_field_name(name)
        try:
            return cls._meta.get_field(name)
        except FieldDoesNotExist:
            if default is _notset:
                raise
            return default

    @classmethod
    def get_field_name(cls, name: str | type[_FT], default: _DT = _notset) -> type[_FT]:
        if default is not _notset:
            default = SimpleNamespace(attname=default)
        return cls.get_field(name, default).name

    @property
    def field_value(self) -> _T:
        return getattr(self, self.field_name)

    @field_value.setter
    def field_value(self, val: _T):
        setattr(self, self.field_name, val)

    @property
    def json_value(self) -> _T:
        if self.source is self.JSON:
            val = self.json[self.field_name]
            typ = get_field_py_type(self.field_type)

            if not isinstance(val, typ) and not issubclass(typ, JsonPrimitive):
                val = self._meta.get_field(self.field_name).to_python(val)
            return val

    @json_value.setter
    def json_value(self, val):
        if self.source is self.JSON:
            self.json[self.field_name] = val

    @property
    def value(self) -> _T:
        return self.json_value if self.source is self.JSON else self.field_value

    @value.setter
    def value(self, val: _T):
        self.field_value = self.json_value = val

    @t.overload
    @classmethod
    def define(
        cls,
        /,
        test: type[AliasField] = None,
        *,
        name: str = None,
        field_type: type[m.Field] = None,
        source: ExprSource = None,
        **dct,
    ) -> type[Self]:
        ...

    @classmethod
    def define(cls, /, *, name=None, **dct) -> type[Self]:
        if "Meta" not in dct:
            dct["Meta"] = type("Meta", (ProxyMeta,), {})
        elif isinstance(dct["Meta"], abc.Mapping):
            dct["Meta"] = type("Meta", (ProxyMeta,), dict(dct["Meta"]))

        if name is None:
            name = f"TestCase_{dct.get('field_type', m.Field).__name__}_{ufake.random_int(1000, 9999)}"

        dct = {
            "__module__": __name__,
            "__name__": name,
            "proxy": AliasField("test")
            if isinstance(dct.get("test"), m.Field)
            else None,
            **dct,
            "source": ExprSource(dct.get("source")),
        }
        return type(name, (cls,), dct)

    def __str__(self) -> str:
        target = self.field_type and self.field_type.__name__.lower() or ""
        return f"{target} - {str(getattr(self, 'test', ''))[:60]}({self.pk})".strip(
            " -"
        )


class ProxyMeta:
    def __init_subclass__(cls) -> None:
        cls.proxy = cls.__dict__.get("proxy", True)
        cls.app_label = cls.__dict__.get("app_label", "app")
