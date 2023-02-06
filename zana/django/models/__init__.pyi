import typing as t

from typing_extensions import Self

from . import _aliases

_T = _aliases._T
_T_Model = _aliases._T_Model

class alias(_aliases.alias[_T], property[_T]):
    def __get__(self, __obj: t.Any, __type: type = None) -> _T: ...
