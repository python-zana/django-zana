import typing as t
from collections import abc

from typing_extensions import Self

from django.db import models as m

from . import aliases, fields

_T_Alias = aliases._T
_T_AliasExpr = aliases._T_Expr
_T_AliasField = aliases._T_Field
_T_AliasModel = aliases._T_Model

class PseudoField(fields.PseudoField): ...
class AliasField(aliases.AliasField[_T_Alias]): ...
