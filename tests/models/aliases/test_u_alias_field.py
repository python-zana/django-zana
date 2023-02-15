from unittest.mock import Mock, patch

import pytest

from django.core import checks
from django.db import models as m
from example.aliases.models import BaseModel
from zana.django.models import AliasField
from zana.django.models.aliases import ImplementsAliases

pytestmark = [
    pytest.mark.django_db,
]


class test_AliasField:
    def setup_method(self):
        BaseModel.all_assignments.clear()

    def teardown_method(self):
        BaseModel.all_assignments.clear()

    def test_check(self):
        with (
            patch.object(m.IntegerField, "check", return_value=[]) as mk_super_check,
            patch.object(
                AliasField, "_check_alias_setter", return_value=[]
            ) as mk_check_alias_setter,
            patch.object(
                AliasField, "_check_alias_expression", return_value=[]
            ) as mk_check_alias_expression,
        ):
            kwargs = {"abc": Mock(), "xyz": Mock()}
            field = AliasField[m.IntegerField]()
            field.check(**kwargs)
            mk_super_check.assert_called_once_with(**kwargs)
            mk_check_alias_setter.assert_called_once_with()
            mk_check_alias_expression.assert_called_once_with()

    def test__check_alias_setter(self):
        @ImplementsAliases.register
        class Test(BaseModel):
            class Meta:
                app_label = "aliases"

            zoo = AliasField(m.F("field"), source="field", setter=True)

            foo = AliasField(m.F("field"), setter=True)
            bar = AliasField(m.F("field"), source="field", cache=True, setter=True)
            baz = AliasField(m.F("field"), source="field", select=True, setter=True)

        aka = Test._alias_fields_

        assert not aka["zoo"]._check_alias_setter()

        foo_error, *_ = aka["foo"]._check_alias_setter()
        assert isinstance(foo_error, checks.Error)
        foo_error.id = "AliasField.E005"

        bar_error, *_ = aka["bar"]._check_alias_setter()
        assert isinstance(bar_error, checks.Error)
        bar_error.id = "AliasField.E004"

        baz_error, *_ = aka["baz"]._check_alias_setter()
        assert isinstance(baz_error, checks.Error)
        baz_error.id = "AliasField.E003"

    def test__check_alias_expression(self):
        @ImplementsAliases.register
        class Test(BaseModel):
            class Meta:
                app_label = "aliases"

            zoo = AliasField[m.IntegerField](m.F("field"), cast=True)

            foo = AliasField(m.F("field"), cast=True)

        aka = Test._alias_fields_

        assert not aka["zoo"]._check_alias_expression()

        foo_error, *_ = aka["foo"]._check_alias_expression()
        assert isinstance(foo_error, checks.Error)
        foo_error.id = "AliasField.E002"
