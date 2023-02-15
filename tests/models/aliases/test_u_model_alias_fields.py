import re

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.db import models as m
from zana.django.models import AliasField
from zana.django.models.aliases import ModelAliasFields, get_alias_fields

pytestmark = [
    pytest.mark.django_db,
]


class test_ModelAliasField:
    def test(self):
        class Test123(m.Model):
            class Meta:
                app_label = "aliases"

            foo = AliasField(m.F("field"), setter=True)
            bar = AliasField(m.F("field"), source="field", cache=True, setter=True)
            baz = AliasField(m.F("field"), source="field", select=True, setter=True)

        aka = get_alias_fields(Test123)

        print(repr(aka))

        assert isinstance(aka, ModelAliasFields)
        assert aka.model is Test123

        assert {ModelAliasFields(Test123)} == {aka}
        assert not ModelAliasFields(Test123) != aka

        assert "foo" in aka
        assert len(aka) == 3
        assert ["foo", "bar", "baz"] == [*aka]

        assert aka["foo"] is Test123._meta.get_field("foo")

        assert aka.keys() == aka.fields.keys()
        assert [*aka.items()] == [*aka.fields.items()]
        assert [*aka.values()] == [*aka.fields.values()]

    def test_prepare(self):
        class Test123(m.Model):
            class Meta:
                app_label = "aliases"

            zoo = AliasField(m.F("field"), source="field")

        class TestBase(Test123):
            class Meta:
                app_label = "aliases"
                proxy = True

            foo = AliasField(m.F("field"))

        class TestChild_1(TestBase):
            class Meta:
                app_label = "aliases"
                proxy = True

            bar = AliasField(m.F("field"), source="field")

        assert get_alias_fields(TestChild_1)["foo"] == TestBase._meta.get_field("foo")

        with pytest.raises(
            ImproperlyConfigured,
            match=re.compile(r"(?:.*(?:foo)?.*AliasField.*)|(?:.*AliasField.*(?:foo)?.*)"),
        ):

            class TestChild_2(TestBase):
                class Meta:
                    app_label = "aliases"
                    proxy = True

                foo = AliasField(m.F("field"), setter=True)
