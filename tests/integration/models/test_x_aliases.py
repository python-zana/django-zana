import math
import typing as t
from collections import Counter
from lib2to3 import pytree
from random import randint, shuffle
from statistics import mean
from unittest.mock import Mock

import pytest

from example.xaliases.models import Author, BaseModel, Book, Publisher, Rating

pytestmark = [
    pytest.mark.django_db,
]


class test_alias:
    max_rating = max(Rating)

    def setup_method(self):
        BaseModel.all_assignments.clear()

    def teardown_method(self):
        BaseModel.all_assignments.clear()

    def create_publishers(self, count=2):
        return [Publisher.objects.create(name=f"Publisher {x}") for x in range(count)]

    def create_authors(self, count=4):
        stop, age = count + 1, lambda: randint(16, 85)
        return [Author.objects.create(name=f"Author {x}", age=age()) for x in range(1, stop)]

    def create_books(
        self,
        c_publishers: Counter[Publisher, int] | int = 2,
        c_authors: Counter[Author, int] = None,
    ):
        if isinstance(c_publishers, int):
            c_publishers = Counter(
                {p: randint(1, 3) for p in self.create_publishers(c_publishers)}
            )

        if c_authors is None:
            c_authors = len(c_publishers) * 2

        if isinstance(c_authors, int):
            c_authors = Counter(
                {a: randint(1, c_publishers.total() // 2) for a in self.create_authors(c_authors)}
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

    def test_attribute_access(self):
        publishers = self.create_publishers(3)
        authors = self.create_authors(6)
        c_publishers = Counter({o: c for o, c in zip(publishers, (6, 4, 2))})
        c_authors = Counter({o: c for o, c in zip(authors, (8, 6, 4, 3, 2, 1))})

        books = self.create_books(c_publishers, c_authors)

        for publisher in publishers:
            e_books = publisher.assigned(Book)
            assert len(e_books) == publisher.books.count()
            assert {*e_books} == {*publisher.books.all()}

            e_rating = mean(b.rating for b in e_books)
            e_rating_min, e_rating_max = math.floor(e_rating), math.ceil(e_rating)
            assert e_rating == publisher.rating == publisher.__dict__["rating"]
            del publisher.rating
            assert not "rating" in publisher.__dict__
            result = Publisher.objects.get(
                pk=publisher.pk, rating__gte=e_rating_min, rating__lte=e_rating_max
            )
            assert publisher == result
            assert e_rating == result.__dict__["rating"]

            e_income = sum(b.num_sold * (b.price * result.commission) for b in e_books)

            assert result.income == e_income

            result.rating = mk_ratting = Mock(float)
            assert mk_ratting is result.rating
            result.refresh_from_db()
            assert e_rating == result.rating

            book = e_books[0]
            assert publisher.name == book.published_by
            assert {*e_books} == {*Book.objects.filter(published_by=publisher.name).all()}
            book.published_by = mk_name = Mock(str)
            assert mk_name is book.published_by is publisher.name

        # assert 0

    def test_queryset(self):
        books = self.create_books()
        authors = list(Author.objects.alias("rating").all())

        for author in authors:
            e_books = list(author.books.all())
            e_rating = mean(b.rating for b in e_books)
            assert e_rating == author.__dict__["rating"]
            author.refresh_from_db(None, ["rating"])
            assert e_rating == author.rating

            e_income = sum(b.num_sold * (b.price - b.commission) for b in e_books)
            assert e_income == author.income
