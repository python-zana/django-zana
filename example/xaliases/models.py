import typing as t
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from enum import auto
from random import choice, randint, random
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


_T = t.TypeVar("_T", bound="BaseModel")


def rand_date():
    now = timezone.now()
    rt = now.replace(
        year=randint(now.year - 5, now.year), month=randint(1, 12), day=randint(1, 28)
    )
    return now.replace(year=rt.year - 1) if rt > now else rt


def rand_price(mn=200, mx=2000, dom=50):
    return randint(mn, mx) // dom * dom


def rand_commission(dom=4e-2):
    return random() // dom * dom


def rand_num_sold(mn=0, mx=200, dom=10):
    return randint(mn, mx) // dom * dom


class BaseModel(m.Model):
    class Meta:
        abstract = True

    all_assignments: t.Final[dict[tuple[Self, type[_T]], list[_T]]] = defaultdict(list)
    all_mocks: t.Final[dict[tuple[Self, str], Mock]] = defaultdict(Mock)
    created_at: datetime = m.DateTimeField(auto_now_add=True)
    updated_at: datetime = m.DateTimeField(auto_now=True)
    version: datetime = alias("updated_at")

    def assigned(self, cls: type[_T]) -> list[_T]:
        return self.all_assignments[self, cls]

    def mocks(self, key):
        if not isinstance(key, str):
            key = key.__name__
        return self.all_mocks[key]


class Author(BaseModel):
    name: str = m.CharField(max_length=200)
    age: str = m.IntegerField()
    books: "m.manager.RelatedManager[Book]"

    rating: float = alias[float](
        m.Avg("books__rating"),
        annotate=True,
        defer=True,
        default=0.0,
        output_field=m.FloatField(),
    )

    publishers: "m.manager.RelatedManager[Book]" = alias()
    if not t.TYPE_CHECKING:

        @publishers
        def publishers(cls):
            return m.Subquery(Publisher.objects.filter(books__authors__pk=m.OuterRef("pk")))

        @publishers.getter
        def publishers(self) -> "m.manager.RelatedManager[Book]":
            return self.books.order_by("publisher").distinct("publisher")

    income = alias[Decimal](defer=True)

    @income
    def income(cls):
        return m.Subquery(
            Book.objects.filter(authors__pk=m.OuterRef("pk"))
            .values("authors__pk")
            .annotate(net_income__sum=m.Sum("net_income", default=_ZERO_DEC))
            .values("net_income__sum")
        )

    def __repr__(self) -> str:
        return f"<{self.name} [{self.books.count()}]>"


class City(StrEnum):
    CAIRO = auto()
    LONDON = auto()
    NAIROBI = auto()
    NEW_YORK = auto()
    TOKYO = auto()

    @classmethod
    def random(cls):
        return choice(list(cls))


_ZERO_DEC = Decimal("0.00")


class Publisher(BaseModel):
    name: str = m.CharField(max_length=200)
    city: City = m.CharField(max_length=64, choices=City.choices, default=City.random)
    commission: Decimal = m.DecimalField(max_digits=4, decimal_places=2, default=rand_commission)
    books: "m.manager.RelatedManager[Book]"

    rating = alias[float | int](
        m.Avg("books__rating"), annotate=True, default=0.0, output_field=m.FloatField()
    )

    @rating.getter
    def rating(self) -> int | float:
        return self.books.aggregate(avg_rating=m.Avg("rating", default=0))["avg_rating"]

    income = alias[Decimal]()

    @income
    def income(cls):
        return m.Subquery(
            Book.objects.filter(publisher=m.OuterRef("pk"))
            .values("publisher")
            .annotate(commission_income__sum=m.Sum("commission_income", default=_ZERO_DEC))
            .values("commission_income__sum")
        )

    def __repr__(self) -> str:
        return f"<{self.name}: [{self.books.count()}] {self.commission}>"


class Book(BaseModel):
    title: str = m.CharField(max_length=200)
    price: Decimal = m.DecimalField(max_digits=12, decimal_places=2, default=rand_price)
    rating: int = m.SmallIntegerField(choices=Rating.choices, null=True)
    authors: "m.manager.RelatedManager[Author]" = m.ManyToManyField("Author", related_name="books")
    publisher: Publisher = m.ForeignKey("Publisher", m.RESTRICT, related_name="books")
    num_sold: int = m.IntegerField(default=rand_num_sold)
    date_published = m.DateTimeField(null=True, default=rand_date)

    commission = alias[Decimal](m.F("price") * m.F("publisher__commission"), cache=False)

    @commission.getter
    def commission(self):
        return self.publisher.commission * self.price

    net_price = alias[Decimal](m.F("price") - m.F("commission"), cache=False)

    @net_price.getter
    def net_price(self):
        return self.price * self.commission

    net_income = alias[Decimal](m.F("net_price") * m.F("num_sold"), cache=False)

    @net_income.getter
    def net_income(self):
        return self.num_sold * self.net_price

    commission_income = alias[Decimal](m.F("commission") * m.F("num_sold"), cache=False)

    @commission_income.getter
    def commission_income(self):
        return self.num_sold * self.commission

    gross_income = alias[Decimal](m.F("price") * m.F("num_sold"), cache=False)

    @gross_income.getter
    def gross_income(self):
        return self.num_sold * self.price

    published_on = alias("date_published", annotate=True)

    published_by = alias(setter=True)[Self].publisher.name

    def __repr__(self) -> str:
        return f"<{self.title}: ${self.price} x {self.num_sold} = ${self.gross_income}>"
