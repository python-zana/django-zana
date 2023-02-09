import typing as t
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from enum import auto
from random import choice, randint, random, shuffle
from unittest.mock import Mock

from typing_extensions import Self
from zana.types.enums import IntEnum, StrEnum

from django.db import models as m
from django.utils import timezone
from zana.django.models import AliasField, alias

ZERO_DEC = Decimal("0.00")


class Rating(IntEnum):
    VERY_BAD = 1
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
    version: datetime = AliasField("updated_at", default=None)

    def assigned(self, cls: type[_T]) -> list[_T]:
        return self.all_assignments[self, cls]

    def mocks(self, key):
        if not isinstance(key, str):
            key = key.__name__
        return self.all_mocks[key]

    __repr_attr__ = ("id",)

    def __repr_args__(self) -> str:
        fields = {f.name: f for f in self._meta.get_fields()}
        return [
            (at, getattr(self, f"get_{f.name}_display", lambda: getattr(self, f.name, None))())
            for at in self.__repr_attr__
            for f in [fields.get(at, m.Field(name=at))]
        ]

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({dict(self.__repr_args__())})"


class Author(BaseModel):
    __repr_attr__ = ("id", "name")
    name: str = m.CharField(max_length=200)
    age: str = m.IntegerField()
    books: "m.manager.RelatedManager[Book]"

    rating: Decimal = AliasField[float](
        m.Avg("books__rating"),
        annotate=True,
        default=ZERO_DEC,
        output_field=m.DecimalField(max_digits=20, decimal_places=2),
    )

    num_books: Decimal = AliasField[float](m.Count("books__pk"))

    publishers: "m.manager.RelatedManager[Book]" = AliasField()

    @publishers.annotation
    def get_publishers_annotation(cls):
        return m.Subquery(Publisher.objects.filter(books__authors__pk=m.OuterRef("pk")))

    @publishers.getter
    def get_publishers(self) -> "m.manager.RelatedManager[Book]":
        return self.books.order_by("publisher").distinct("publisher")

    income: Decimal = AliasField()

    @income.annotation
    def get_income(cls):
        return m.Subquery(
            Book.objects.filter(authors__pk=m.OuterRef("pk"))
            .values("authors__pk")
            .annotate(net_income__sum=m.Sum("net_income", default=ZERO_DEC))
            .values("net_income__sum")
        )

    @classmethod
    def create_samples(cls, count=4):
        stop, age = count + 1, lambda: randint(16, 85)
        return [cls.objects.create(name=f"Author {x}", age=age()) for x in range(1, stop)]

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"


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
    __repr_attr__ = ("id", "name", "commission", "rating")

    name: str = m.CharField(max_length=200)
    city: City = m.CharField(max_length=64, choices=City.choices, default=City.random)
    commission: Decimal = m.DecimalField(max_digits=4, decimal_places=2, default=rand_commission)
    books: "m.manager.RelatedManager[Book]"
    num_books: Decimal = AliasField[float](m.Count("books__pk"))

    rating = alias[float | int](
        m.Avg("books__rating", output_field=m.DecimalField(max_digits=20, decimal_places=2)),
        annotate=True,
        default=ZERO_DEC,
        output_field=m.DecimalField(max_digits=20, decimal_places=2),
    )

    income = alias[Decimal]()

    @income
    def income(cls):
        return m.Subquery(
            Book.objects.filter(publisher=m.OuterRef("pk"))
            .values("publisher")
            .annotate(commission_income__sum=m.Sum("commission_income", default=ZERO_DEC))
            .values("commission_income__sum")
        )

    @classmethod
    def create_samples(cls, count=2):
        return [cls.objects.create(name=f"Publisher {x}") for x in range(count)]

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"


class Book(BaseModel):
    __repr_attr__ = ("id", "title", "price", "num_sold", "rating")

    title: str = m.CharField(max_length=200)
    price: Decimal = m.DecimalField(max_digits=12, decimal_places=2, default=rand_price)
    rating: int = m.SmallIntegerField(choices=Rating.choices, null=True)
    authors: "m.manager.RelatedManager[Author]" = m.ManyToManyField(Author, related_name="books")
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

    def __str__(self) -> str:
        return f"{self.title} ({self.pk})"

    @classmethod
    def create_samples(
        cls,
        c_publishers: Counter[Publisher, int] | int = 2,
        c_authors: Counter[Author, int] = None,
    ):
        if isinstance(c_publishers, int):
            c_publishers = Counter(
                {p: randint(1, 3) for p in Publisher.create_samples(c_publishers)}
            )

        if c_authors is None:
            c_authors = len(c_publishers) * 2

        if isinstance(c_authors, int):
            c_authors = Counter(
                {
                    a: randint(1, c_publishers.total() // 2)
                    for a in Author.create_samples(c_authors)
                }
            )

        publishers, max_rating = list(c_publishers.elements()), max(Rating)
        shuffle(publishers)
        books: list[Book] = []
        n_authors = c_authors.total() // c_publishers.total()
        n_rem = c_authors.total() % c_publishers.total()
        for x, publisher in enumerate(publishers):
            (*authors,) = c_authors
            shuffle(authors)
            authors = authors[: n_authors + 1 if x < n_rem else n_authors]
            book = publisher.books.create(
                title=f"Book {x}",
                rating=Rating(x % max_rating + 1),
            )

            authors and book.authors.add(*authors)
            for obj in [publisher, *authors]:
                obj.assigned(Book).append(book)
                book.assigned(obj.__class__).append(obj)

            c_authors = +(c_authors - Counter(authors))
            books.append(book)
        return books


class Novel(Book):
    class Meta:
        proxy = True

    date_released = AliasField("published_on__date", attr=False)
