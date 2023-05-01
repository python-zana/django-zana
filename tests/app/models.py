import typing as t
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from django.db import models as m

_FT = t.TypeVar("_FT", bound=m.Field)
_T = t.TypeVar("_T")


DJANGO_FIELDS: dict[type[_FT], tuple[_T, type[_T]] | tuple[_T, type[_T], dict]] = {
    m.BooleanField: (True, bool),
    m.CharField: ("Foo Bar Baz", str, dict(max_length=250)),
    m.EmailField: ("name@example.com", str),
    m.SlugField: ("foo-bar-baz", str),
    m.TextField: ("Foo\nBar\nBaz", str),
    m.BinaryField: (b"Foo Bar Baz", bytes),
    m.URLField: ("http://example.com", str),
    m.GenericIPAddressField: ("2001:db8:3333:4444:5555:6666:7777:8888", str),
    # Date & Time Fields
    m.DateField: (date(2010, 10, 10), date),
    m.DateTimeField: (
        datetime(2010, 10, 10, 10, 10, 10, 10, tzinfo=timezone.utc),
        datetime,
    ),
    m.DurationField: (timedelta(days=10, seconds=36610), timedelta),
    m.TimeField: (time(10, 10, 10, 10), time),
    m.FilePathField: ("/foo/bar/baz", str),
    # Number fields
    m.DecimalField: (
        Decimal("12.0025"),
        Decimal,
        dict(decimal_places=4, max_digits=16),
    ),
    m.FloatField: (0.125, float),
    m.IntegerField: (125, int),
    m.BigIntegerField: (int(5e12), int),
    m.PositiveBigIntegerField: (int(5e12), int),
    # m.BigAutoField: (125, int),
    m.SmallIntegerField: (25, int),
    m.PositiveSmallIntegerField: (25, int),
    # m.SmallAutoField: (25, int),
    m.PositiveIntegerField: (25, int),
    # m.AutoField: (25, int),
    m.UUIDField: (UUID("6562d5ee-083c-4131-b878-9f0ec7dcbf5d"), UUID),
    m.JSONField: ({"abc": [123, 456], "foo": {"bar": "baz"}, "xyz": True}, t.Any),
    m.FileField: ("abc/xyz/foo.bar", str),
    # m.ImageField: ("abc/xyz/foo.png", str),
    # m.ForeignKey: (None, None),
    # m.OneToOneField: (None, None),
    # m.ManyToManyField: (None, None),
}

_TJsonable = None | bool | str | int | float | dict | tuple | list
j = {}


def get_field_py_type(cls: type[_FT]):
    return DJANGO_FIELDS[cls][1]


def get_field_kwargs(cls: str | type[_FT]):
    return dict((DJANGO_FIELDS[get_field_type(cls)] + ((),))[-1])


def get_field_type(name: str | type[_FT]):
    if isinstance(name, str):
        name = TestModel._meta.get_field(name.lower()).__class__
    return name


class AbcTestModel(m.Model):
    class Meta:
        abstract = True


class TestModel(AbcTestModel):
    class Meta:
        verbose_name = "Field Implementation"

    alias: t.Any

    foreignkey = m.ForeignKey(
        "self", m.SET_NULL, null=True, related_name="foreignkey_reverse"
    )
    onetoonefield = m.OneToOneField(
        "self", m.SET_NULL, null=True, related_name="onetoonefield_reverse"
    )
    manytomanyfield = m.ManyToManyField("self", related_name="manytomanyfield_reverse")

    _json_default = {
        cls.__name__.lower(): str(DJANGO_FIELDS[cls][0])
        for cls in (
            m.DateField,
            m.DateTimeField,
            m.TimeField,
            m.DurationField,
            m.DecimalField,
            m.UUIDField,
        )
    }

    for cls, (v, t, *kw) in DJANGO_FIELDS.items():
        n = cls.__name__.lower()
        if n not in vars():
            vars()[n] = cls(default=v, **(kw[0] if kw else {}))
            isinstance(v, _TJsonable) and _json_default.setdefault(n, v)

    del cls, v, t, kw, n

    json = m.JSONField(default=_json_default)
