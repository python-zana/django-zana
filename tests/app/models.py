from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
import typing as t
from uuid import UUID, uuid4
from django.db import models as m


DJANGO_FIELDS = {
    m.BooleanField: ([True, False], bool),
    m.CharField: (["xyz"], str),
    # m.EmailField: ([_V_], _T_),
    # m.SlugField: ([_V_], _T_),
    # m.URLField: ([_V_], _T_),
    # Date & Time Fields
    m.DateField: ([date.today()], date),
    m.DateTimeField: ([datetime.now()], datetime),
    m.DurationField: ([timedelta(days=10, seconds=36610)], timedelta),
    m.TimeField: ([datetime.now().time()], time),
    m.FilePathField: (["/foo/bar/baz", Path("/foo/bar/baz")], str),
    m.DecimalField: ([Decimal("12.25")], Decimal),
    m.FloatField: ([0.125], float),
    m.IntegerField: ([125], int),
    m.BigIntegerField: ([125], int),
    m.PositiveBigIntegerField: ([125], int),
    m.BigAutoField: ([125], int),
    m.SmallIntegerField: ([25], int),
    m.PositiveSmallIntegerField: ([25], int),
    m.SmallAutoField: ([25], int),
    m.PositiveIntegerField: ([25], int),
    m.AutoField: ([25], int),
    m.IPAddressField: (["192.168.100.0"], str),
    m.GenericIPAddressField: (["2001:0db8:85a3:0000:0000:8a2e:0370:7334"], str),
    m.TextField: (["abc xyz"], str),
    m.BinaryField: ([b""], memoryview),
    m.UUIDField: ([uuid4()], UUID),
    m.JSONField: ([{"abc": [123, 456], "foo": {"bar": "baz"}, "xyz": True}], t.Any),
    m.FileField: (["abc/xyz/foo.bar"], str),
    m.ImageField: (["abc/xyz/foo.png"], str),
    # m.ForeignObject: ([_V_], _T_),
    # m.ForeignKey: ([_V_], _T_),
    # m.OneToOneField: ([_V_], _T_),
    # m.ManyToManyField: ([_V_], _T_),
}


class AbcTestModel(m.Model):
    class Meta:
        abstract = True


# class FieldImpl(AbcTestModel):
#     class Meta:
#         verbose_name = "Field Implementation"
