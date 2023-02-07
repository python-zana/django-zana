import typing as t

from typing_extensions import Self

from . import aliases, fields

_T = fields._T
_T_Model = fields._T_Model

class AliasField(fields.AliasField[_T]): ...

_T = aliases._T
_T_Model = aliases._T_Model

class alias(aliases.alias[_T], property[_T]):
    def __get__(self, __obj: t.Any, __type: type = None) -> _T: ...
