import typing as t
from enum import IntFlag
from functools import reduce
from operator import or_

from django.db.models.enums import (Choices, ChoicesMeta, IntegerChoices,
                                    TextChoices)
from typing_extensions import Self

_T_Enum = t.TypeVar('_T_Enum', bound='IntFlagChoicesMeta')


class IntFlagChoicesMeta(ChoicesMeta):
   
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._member_map_:
            self._all_ = None
    
    @property
    def all(self) -> Self:
        if self._all_ is None:
            if union := reduce(or_, map(int, self._member_map_.values()), 0):
                self._all_ = self(union)
        return self._all_



class IntFlagChoices(IntFlag, Choices, metaclass=IntFlagChoicesMeta):
    
    all: Self
    _all_: Self

    def __iter__(self):
        return (m for m in self.__class__ if m & self)

    def __contains__(self: Self, other: Self) -> bool:
        return not not (self & other)

    def __len__(self) -> int:
        return f'{self:b}'.count('1')

