import typing as t
from collections import defaultdict
from decimal import Decimal
from enum import auto
from functools import partial
from random import choice, randint
from unittest.mock import Mock

from typing_extensions import Self
from zana.types.enums import IntEnum, StrEnum

from django.db import models as m
from django.utils import timezone
from zana.django.models import alias


class Rating(IntEnum):
    VERT_BAD = 1
    BAD = 2
    AVERAGE = 3
    GOOD = 4
    VERY_GOOD = 5

_T = t.TypeVar('_T', bound='BaseModel')


class BaseModel(m.Model):
    class Meta:
        abstract = True

    all_assignments: t.Final[dict[tuple[Self, type[_T]], list[_T]]] = defaultdict(list)
    all_mocks: t.Final[dict[tuple[Self, str], Mock]] = defaultdict(Mock)

    def assigned(self, cls: type[_T]) -> list[_T]:
        return self.all_assignments[self, cls]

    def mocks(self, key): 
        if not isinstance(key, str):
            key = key.__name__
        return self.all_mocks[key]


class Author(BaseModel):

    name: str = m.CharField(max_length=200)
    age: str = m.IntegerField()
    books: 'm.manager.RelatedManager[Book]'

    rating = alias[float | int](m.Avg('books__rating'), annotate=True, default=0.0, field=m.FloatField())
    
    @rating.getter
    def rating(self):
        return self.books.aggregate(avg_rating=m.Avg('rating', default=0))['avg_rating']

    publishers = alias['m.manager.RelatedManager[Book]']()
    
    @publishers
    def publishers(cls):
        return m.Subquery(Publisher.objects.filter(books__authors__pk=m.OuterRef('pk')))

    @publishers.getter
    def publishers(self):
        return self.books.order_by('publisher').distinct('publisher')


class City(StrEnum):
    CAIRO = auto()
    LONDON = auto()
    NAIROBI = auto()
    NEW_YORK = auto()
    TOKYO = auto()

    @classmethod
    def random(cls):
        return choice(list(cls))


class Publisher(BaseModel):
    name: str = m.CharField(max_length=200)
    city: City = m.CharField(max_length=64, choices=City.choices, default=City.random)

    books: 'm.manager.RelatedManager[Book]'

    rating = alias[float | int](m.Avg('books__rating'), annotate=True, default=0.0, field=m.FloatField())
    
    @rating.getter
    def rating(self) -> int | float:
        return self.books.aggregate(avg_rating=m.Avg('rating', default=0))['avg_rating']
    



def rand_date():
    now = timezone.now()
    rt = now.replace(year=randint(now.year-5, now.year), month=randint(1,12), day=randint(1,28))
    return now.replace(year=rt.year-1) if rt > now else rt

def rand_price(mn=200, mx=2000, dom=50):
    return (randint(mn, mx) // dom) * dom


class Book(BaseModel):
    title: str = m.CharField(max_length=200)
    price: Decimal = m.DecimalField(max_digits=12, null=True, decimal_places=2, default=rand_price)
    rating: int = m.SmallIntegerField(choices=Rating.choices, null=True)
    authors: 'm.manager.RelatedManager[Author]' = m.ManyToManyField('Author', related_name='books')
    publisher: Publisher = m.ForeignKey('Publisher', m.RESTRICT, related_name='books')
    num_sold: int = m.IntegerField(default=partial(randint, 0,10))
    date_published = m.DateTimeField(null=True, default=rand_date)

    # def set_published_on(self, val):
    #     self.date_published = val

    published_on = alias(date_published, annotate=True)

    published_by = alias(setter=True)[Self].publisher.name




    

