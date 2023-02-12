import typing as t
from collections import abc

from typing_extensions import Self

from django.db import models as m

from . import aliases

_T_Alias = aliases._T
_T_AliasExpr = aliases._T_Expr
_T_AliasField = aliases._T_Field
_T_AliasModel = aliases._T_Model

class AliasField(aliases.AliasField[_T_Alias]):
    def __new__(
        cls: type[Self],
        expression: _T_AliasExpr = None,
        getter: t.Union[abc.Callable[[_T_AliasModel], _T_Alias], bool] = None,
        setter: t.Union[abc.Callable[[_T_AliasModel, _T_Alias], t.NoReturn], bool] = None,
        deleter: abc.Callable[[_T_AliasModel], t.NoReturn] = None,
        *,
        select: bool = None,
        path: str = None,
        doc: str = None,
        cache: bool = None,
        defer: bool = None,
        cast: bool = None,
        internal: _T_AliasField = None,
        **kwds,
    ) -> _T_Alias | Self: ...
