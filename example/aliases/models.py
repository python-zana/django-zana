import typing as t
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from enum import auto
from random import choice, randint, random, shuffle
from unittest.mock import Mock

from polymorphic.models import PolymorphicModel
from typing_extensions import Self
from zana.canvas import magic, ops
from zana.types.enums import IntEnum, StrEnum

from django.db import models as m
from django.utils import timezone
from zana.django.models import AliasField


ZERO_DEC = Decimal("0.00")


class City(StrEnum):
    CAIRO = auto()
    LONDON = auto()
    NAIROBI = auto()
    NEW_YORK = auto()
    TOKYO = auto()

    @classmethod
    def random(cls):
        return choice(list(cls))


class Rating(IntEnum):
    NONE = 0
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
            (
                at,
                getattr(
                    self, f"get_{f.name}_display", lambda: getattr(self, f.name, None)
                )(),
            )
            for at in self.__repr_attr__
            for f in [fields.get(at, m.Field(name=at))]
        ]

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({dict(self.__repr_args__())})"


class Publisher(BaseModel):
    __repr_attr__ = ("id", "name", "commission", "rating")

    name: str = m.CharField(max_length=200)
    city: City = m.CharField(max_length=64, choices=City.choices, default=City.random)
    commission: Decimal = m.DecimalField(
        max_digits=4, decimal_places=2, default=rand_commission
    )
    books: "m.manager.RelatedManager[Book]"
    num_books: Decimal = AliasField[m.IntegerField](m.Count("books__pk"))

    rating: Decimal = AliasField[m.DecimalField](
        m.Avg("books__rating"),
        select=True,
        default=ZERO_DEC,
        cast=True,
        max_digits=20,
        decimal_places=2,
    )

    income: Decimal = AliasField()

    @income.annotation
    def get_income():
        return m.Subquery(
            Book.objects.filter(publisher=m.OuterRef("pk"))
            .values("publisher")
            .annotate(
                commission_income__sum=m.Sum("commission_income", default=ZERO_DEC)
            )
            .values("commission_income__sum")
        )

    @classmethod
    def create_samples(cls, count=2, using=None):
        return [
            cls.objects.using(using).create(name=f"Publisher {x}") for x in range(count)
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"


class Author(BaseModel, PolymorphicModel):
    __repr_attr__ = ("id", "name")
    name: str = m.CharField(max_length=200)
    age: str = m.IntegerField()
    books: "m.manager.RelatedManager[Book]"

    rating: Decimal = AliasField[m.IntegerField](
        m.functions.Ceil(m.Avg("books__rating")),
        choices=Rating.choices,
        select=True,
        default=Rating.NONE,
    )

    num_books: int = AliasField[m.IntegerField](m.Count("books__pk"))

    publishers: "m.manager.RelatedManager[Book]" = AliasField()

    @publishers.annotation
    def get_publishers_annotation():
        return m.Subquery(Publisher.objects.filter(books__authors__pk=m.OuterRef("pk")))

    @publishers.getter
    def get_publishers(self) -> "m.manager.RelatedManager[Book]":
        return self.books.order_by("publisher").distinct("publisher")

    income: Decimal = AliasField[m.DecimalField](max_digits=20, decimal_places=2)

    @income.annotation
    def get_income():
        return m.Subquery(
            Book.objects.filter(authors__pk=m.OuterRef("pk"))
            .values("authors__pk")
            .annotate(net_income__sum=m.Sum("net_income", default=ZERO_DEC))
            .values("net_income__sum")
        )

    @classmethod
    def create_samples(cls, count=4, using=None):
        stop, age = count + 1, lambda: randint(16, 85)
        return [
            cls.objects.using(using).create(name=f"Author {x}", age=age())
            for x in range(1, stop)
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"


class Writer(Author):
    house: str = m.CharField(max_length=200)


class Book(BaseModel, PolymorphicModel):
    __repr_attr__ = ("id", "title", "rating", "num_pages", "tag")

    title: str = m.CharField(max_length=200)
    price: Decimal = m.DecimalField(max_digits=12, decimal_places=2, default=rand_price)
    rating: int = m.SmallIntegerField(choices=Rating.choices, null=True)
    authors: "m.manager.RelatedManager[Author]" = m.ManyToManyField(
        Author, related_name="books"
    )
    publisher: Publisher = m.ForeignKey("Publisher", m.RESTRICT, related_name="books")
    num_sold: int = m.IntegerField(default=rand_num_sold)
    published_on: datetime = m.DateTimeField(null=True, default=rand_date)

    def default_data():
        return {
            "tags": [f"tag {i}" for i in range(randint(2, 6), 0, -1)],
            "description": f"desc {randint(0,1000)}",
            "is_best_seller": randint(0, 2) > 1,
            "content": {
                "pages": randint(100, 1000) // 50 * 50,
                "chapters": [
                    {
                        "title": "Chapter 1",
                        "topics": {"title": "Topic A", "page": 1},
                    },
                ],
            },
        }

    data = m.JSONField(default=default_data)
    this: Self = magic[Self]()

    year = AliasField[m.IntegerField](
        m.F("published_on__year"), getter=this.published_on.year(...)
    )
    date = AliasField(
        "published_on__date", defer=True, getter=this.published_on.date()(...)
    )

    published_by = AliasField(
        "publisher__name",
        setter=this.publisher(...) | ops.setattr("name"),
        deleter=this.publisher(...) | ops.delattr("name"),
        getter=this.publisher.name(...),
    )

    def get_tags(self):
        raise RuntimeError("I Was Called")
        return self.data["tags"][:2]

    tags = AliasField("data__tags", getter=get_tags)
    tag = AliasField[m.TextField](
        "data__tags__0",
        json=True,
        getter=this.data["tags"][0](...),
        setter=this.data["tags"](...) | ops.setitem(0),
        deleter=this.data["tags"](...) | ops.delitem(0),
    )
    num_pages = AliasField[m.IntegerField](
        "data__content__pages",
        getter=this.data["content"]["pages"](...),
        setter=this.data["content"](...) | ops.setitem("pages"),
        deleter=this.data["content"](...) | ops.delitem("pages"),
    )
    is_short = AliasField[m.BooleanField](
        m.Case(
            m.When(num_pages__lte=m.Value(500, m.JSONField()), then=m.Value(True)),
            default=m.Value(False),
        ),
    )
    is_best_seller: bool = AliasField[m.BooleanField](
        "data__is_best_seller", getter=this.data["is_best_seller"](...)
    )
    # desc_r = AliasField[m.CharField](
    #     "data__description", setter=True, default="", getter=this.data["description"]
    # )
    # desc_s = AliasField[m.CharField](setter=True, getter=this.data["description"])
    # desc_c = AliasField[m.CharField](setter=True, getter=this.data["description"])
    chapters = AliasField("data__content__chapters")
    topics = AliasField("data__content__chapters__0__topics")

    commission: Decimal = AliasField[m.DecimalField](
        m.F("price") * m.F("publisher__commission"),
        max_digits=20,
        decimal_places=2,
        cache=False,
    )

    @commission.getter
    def get_commission(self):
        return self.publisher.commission * self.price

    net_price: Decimal = AliasField[m.DecimalField](
        m.F("price") - m.F("commission"), max_digits=20, decimal_places=2, cache=False
    )

    @net_price.getter
    def get_net_price(self):
        return self.price * self.commission

    net_income: Decimal = AliasField[m.DecimalField](
        m.F("net_price") * m.F("num_sold"), max_digits=20, decimal_places=2, cache=False
    )

    @net_income.getter
    def get_net_income(self):
        return self.num_sold * self.net_price

    commission_income: Decimal = AliasField[m.DecimalField](
        m.F("commission") * m.F("num_sold"),
        max_digits=20,
        decimal_places=2,
        cache=False,
    )

    @commission_income.getter
    def get_commission_income(self):
        return self.num_sold * self.commission

    gross_income: Decimal = AliasField[m.DecimalField](
        m.F("price") * m.F("num_sold"), max_digits=20, decimal_places=2, cache=False
    )

    @gross_income.getter
    def get_gross_income(self):
        return self.num_sold * self.price

    def __str__(self) -> str:
        return f"{self.title} ({self.pk})"

    @classmethod
    def create_samples(
        cls,
        c_publishers: Counter[Publisher, int] | int = 2,
        c_authors: Counter[Author, int] = None,
        using=None,
    ):
        if isinstance(c_publishers, int):
            c_publishers = Counter(
                {
                    p: randint(1, 3)
                    for p in Publisher.create_samples(c_publishers, using=using)
                }
            )

        if c_authors is None:
            c_authors = len(c_publishers) * 2

        if isinstance(c_authors, int):
            c_authors = Counter(
                {
                    a: randint(1, c_publishers.total() // 2)
                    for a in Author.create_samples(c_authors, using=using)
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

    del this


class Publication(Book):
    class Meta:
        proxy = True

    period = AliasField("published_on__date", defer=True)


class Magazine(Publication):
    class Meta:
        proxy = True

    issue = AliasField[m.CharField](m.F("period"))


class Paper(Publication):
    class Meta:
        proxy = True

    issue = AliasField[m.CharField](m.F("published_on__time"))
