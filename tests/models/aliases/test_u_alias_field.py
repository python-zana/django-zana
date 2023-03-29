from collections import abc
from unittest.mock import MagicMock, Mock, patch

import pytest

from django.core import checks
from django.db import models as m
from example.aliases.models import BaseModel
from zana.django.models import AliasField
from zana.django.models.fields.aliases import ImplementsAliases

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
                AliasField, "_check_access_mutators", return_value=[]
            ) as mk_check_access_mutators,
            patch.object(
                AliasField, "_check_alias_expression", return_value=[]
            ) as mk_check_alias_expression,
        ):
            kwargs = {"abc": Mock(), "xyz": Mock()}
            field = AliasField[m.IntegerField]()
            field.check(**kwargs)
            mk_super_check.assert_called_once_with(**kwargs)
            mk_check_access_mutators.assert_called_once_with()
            mk_check_alias_expression.assert_called_once_with()

    @pytest.mark.parametrize(
        "at, err, val",
        [
            ("getter", None, None),
            ("getter", None, Mock(bool)),
            ("getter", None, Mock(abc.Callable)),
            ("getter", "E002", object()),
            ("setter", None, None),
            ("setter", None, Mock(abc.Callable)),
            ("setter", "E003", object()),
            ("deleter", None, None),
            ("deleter", None, Mock(abc.Callable)),
            ("deleter", "E004", object()),
        ],
    )
    def test__check_access_mutators(self, at, err, val):
        aka = AliasField(m.F("field"), **{at: val})
        errors = aka._check_access_mutators()
        if err:
            assert any(e.id in (None, f"AliasField.{err}") for e in errors)
        else:
            assert not errors

    def test__check_alias_expression(self):
        zoo = AliasField[m.IntegerField](m.F("field"), cast=True)
        foo = AliasField(m.F("field"), cast=True)

        assert not zoo._check_alias_expression()

        foo_error, *_ = foo._check_alias_expression()
        assert isinstance(foo_error, checks.Error)
        assert foo_error.id == "AliasField.E001"
