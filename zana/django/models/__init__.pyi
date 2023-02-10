import typing as t
from collections import abc

from typing_extensions import Self

from django.db import models as m

from . import aliases

_T_Alias = aliases._T
_T_AliasExpr = aliases._T_Expr
_T_AliasModel = aliases._T_Model

class AliasField(aliases.AliasField[_T_Alias]):
    def __new__(
        cls: type[Self],
        expression: _T_AliasExpr = None,
        getter: t.Union[abc.Callable[[_T_AliasModel], _T_Alias], bool] = None,
        setter: t.Union[abc.Callable[[_T_AliasModel, _T_Alias], t.NoReturn], bool] = None,
        deleter: abc.Callable[[_T_AliasModel], t.NoReturn] = None,
        *,
        annotate: bool = None,
        attr: str = None,
        doc: str = None,
        default=...,
        cache: bool = None,
        defer: bool = None,
        output_field: m.Field = None,
        **kwds,
    ) -> _T_Alias | Self: ...
