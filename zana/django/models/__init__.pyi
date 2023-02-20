import typing as t  # type: ignore
from collections import abc  # type: ignore

from typing_extensions import Self  # type: ignore

from django.db import models as m  # type: ignore

from . import fields
from .fields import aliases
from .operator import Attr, Call, Chain, Func, Item, Meth, Signature, Slice

__all__ = [
    "AliasField",
    "PseudoField",
    "Signature",
    "Attr",
    "Item",
    "Slice",
    "Call",
    "Meth",
    "Func",
    "Chain",
]

_T_Alias = aliases._T
_T_AliasExpr = aliases._T_Expr
_T_AliasField = aliases._T_Field
_T_AliasModel = aliases._T_Model

class PseudoField(fields.PseudoField): ...
class AliasField(aliases.AliasField[_T_Alias]): ...
