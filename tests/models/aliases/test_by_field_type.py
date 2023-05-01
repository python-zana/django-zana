import typing as t
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from operator import attrgetter
from random import randbytes, randint, random
from secrets import token_hex
from uuid import UUID, uuid4

import pytest as pyt

from django.db import models as m
from tests.app.models import TestModel, get_field_type
from zana.django.models import AliasField

pytestmark = [
    pyt.mark.django_db,
]


class test_DjangoFields:
    @pyt.mark.parametrize(
        "fname, expected",
        [
            ("booleanfield", False),
            ("charfield", token_hex(16)),
            ("textfield", f"{token_hex(64)}\n{token_hex(64)}"),
            ("binaryfield", randbytes(64)),
            ("genericipaddressfield", "2001:db8:3333:4444:cccc:dddd:eeee:ffff"),
            ("datefield", date.today()),
            ("datetimefield", datetime.now().astimezone(timezone.utc)),
            ("durationfield", timedelta(days=1, seconds=36610)),
            ("timefield", datetime.now().astimezone(timezone.utc).time()),
            ("decimalfield", Decimal("2500.0055")),
            ("floatfield", random()),
            ("integerfield", randint(0, int(9e8))),
            ("uuidfield", uuid4()),
            ("jsonfield", {"abc": [10], "foo": {"bar": True}, "xyz": 25}),
        ],
    )
    def test_basic(self, fname: str, expected):
        ftype, get_field = get_field_type(fname), attrgetter(fname)
        alias_name, alias_name_t = f"{fname}_alias", f"{fname}_alias_t"
        alias_field, alias_field_t = AliasField(fname), AliasField[ftype](
            m.Case(m.When(m.Value(True), then=m.F(alias_name)), default=m.Value(None))
        )

        alias_field.contribute_to_class(TestModel, alias_name)
        alias_field_t.contribute_to_class(TestModel, alias_name_t)
        get_alias, get_alias_t = attrgetter(alias_name), attrgetter(alias_name_t)
        qs = TestModel.objects.all()
        default, obj = TestModel(), TestModel()
        setattr(obj, fname, expected)
        default.save(), obj.save()
        default.refresh_from_db(), obj.refresh_from_db()

        assert get_alias(default) == get_alias_t(default) == get_field(default)
        assert get_alias(obj) == get_alias_t(obj) == get_field(obj)
        # assert isinstance(get_alias(obj), type(expected))
        assert ((get_field(obj),) * 2) == qs.annotate(
            alias_name, alias_name_t
        ).values_list(alias_name, alias_name_t).get(
            **{alias_name: expected, alias_name_t: m.F(alias_name)}
        )
