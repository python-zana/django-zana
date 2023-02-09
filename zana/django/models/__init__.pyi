import typing as t
from collections import abc

from typing_extensions import Self

from django.db import models as m

from . import aliases, fields

_T = fields._T
_T_Expr = fields._T_Expr
_T_Model = fields._T_Model

class AliasField(fields.AliasField[_T]):
    def __new__(
        cls: type[Self],
        expression: _T_Expr = None,
        getter: t.Union[abc.Callable[[_T_Model], _T], bool] = None,
        setter: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool] = None,
        deleter: abc.Callable[[_T_Model], t.NoReturn] = None,
        *,
        annotate: bool = None,
        attr: str = None,
        doc: str = None,
        output_field: m.Field = None,
        default=...,
        cache: bool = None,
        defer: bool = None,
        **kwds,
    ) -> _T | Self: ...

_T = aliases._T
_T_Model = aliases._T_Model

class alias(aliases.alias[_T], property[_T]):
    def __get__(self, __obj: t.Any, __type: type = None) -> _T: ...
