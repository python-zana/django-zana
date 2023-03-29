import math
from collections import Counter
from statistics import mean
from unittest.mock import Mock

import pytest

from django.db import models as m  # type: ignore
from example.aliases.models import Author, BaseModel, Book, Publisher, Rating

pytestmark = [
    pytest.mark.django_db,
]


class test_AliasField:
    max_rating = max(Rating)

    def setup_method(self):
        BaseModel.all_assignments.clear()

    def teardown_method(self):
        BaseModel.all_assignments.clear()

    def test_attribute_access(self):
        publishers = Publisher.create_samples(3)
        authors = Author.create_samples(6)
        c_publishers = Counter({o: c for o, c in zip(publishers, (6, 4, 2))})
        c_authors = Counter({o: c for o, c in zip(authors, (8, 6, 4, 3, 2, 1))})

        books = Book.create_samples(c_publishers, c_authors)

        for publisher in publishers:
            e_books = publisher.assigned(Book)
            assert len(e_books) == publisher.books.count()
            assert {*e_books} == {*publisher.books.all()}

            e_rating = mean(b.rating for b in e_books)
            e_rating_min, e_rating_max = math.floor(e_rating), math.ceil(e_rating)
            rating = publisher.rating
            assert e_rating_min <= rating <= e_rating_max
            assert rating == publisher.__dict__["rating"]
            del publisher.rating
            assert not "rating" in publisher.__dict__
            result = Publisher.objects.get(
                pk=publisher.pk, rating__gte=e_rating_min, rating__lte=e_rating_max
            )
            assert publisher == result
            assert rating == result.__dict__["rating"]
            e_income = sum(b.num_sold * (b.price * result.commission) for b in e_books)

            assert result.income == e_income

            result.rating = mk_ratting = Mock(float)
            assert mk_ratting is result.rating
            result.refresh_from_db()
            assert rating == result.rating
            book = e_books[0]
            assert publisher.name == book.published_by
            assert {*e_books} == {
                *Book.objects.filter(published_by=publisher.name).all()
            }
            book.published_by = mk_name = Mock(str)
            assert mk_name is book.published_by is publisher.name

        # assert 0

    def test_queryset(self):
        books = Book.create_samples()
        authors: list[Author] = list(Author.objects.alias("rating").all())

        for author in authors:
            e_books = list(author.books.all())
            e_rating = math.ceil(mean(b.rating for b in e_books))
            assert e_rating == author.__dict__["rating"]
            author.refresh_from_db(None, ["rating"])
            a_rating = author.rating
            assert e_rating == a_rating

            e_income = sum(b.num_sold * (b.price - b.commission) for b in e_books)
            a_income = author.income
            assert e_income == a_income

            assert e_books[0].version == e_books[0].updated_at
        # assert 0

    @pytest.mark.using_db("sqlite", "postgresql", "mysql")
    def test_books(self, db_backends):
        book: Book
        publishers = Publisher.create_samples(3)
        authors = Author.create_samples(6)
        c_publishers = Counter({o: c for o, c in zip(publishers, (8, 6, 3))})
        c_authors = Counter({o: c for o, c in zip(authors, (9, 6, 5, 3, 2, 2))})
        qs = Book.objects.all()
        books = Book.create_samples(c_publishers, c_authors)
        tagmax = max(b.data["tags"][0] for b in books)
        with_tagmax = [b for b in books if b.data["tags"][0] == tagmax]
        i, book = 0, qs.last()

        for i, book in enumerate(
            qs.annotate("num_pages", "tag", "tags")
            .filter(tag=tagmax, tags__0=tagmax)
            .all(),
            1,
        ):
            assert book.tag == book.tags[0] == tagmax == book.data["tags"][0]
            assert book.tags[:2] == book.data["tags"][:2]
            assert book in with_tagmax
            assert book.num_pages == book.data["content"]["pages"]

        print(f"\n{qs.filter(tag=tagmax, tags__0=tagmax).explain() = !r}\n")

        assert i == len(with_tagmax)

        e_published_by, mk_published_by = book.publisher.name, Mock(str)
        assert e_published_by == book.published_by == book.publisher.name
        book.published_by = mk_published_by
        assert book.published_by is mk_published_by is book.publisher.name
        del book.published_by
        assert e_published_by == book.published_by == book.publisher.name

        assert book.date == book.published_on.date()
        assert book == qs.alias("date").get(pk=book.pk, date=book.date)

        num_pages = book.num_pages
        mk_pages = Mock(int)
        book.num_pages = mk_pages
        assert book.data["content"]["pages"] is mk_pages is book.num_pages
        del book.num_pages
        assert "pages" not in book.data["content"]
        book.num_pages = num_pages
        assert book.data["content"]["pages"] == num_pages == book.num_pages
        assert book == qs.get(pk=book.pk, num_pages=num_pages)

        tag_1 = book.data["tags"][1]
        del book.tag
        book.save()
        assert (
            book.tag
            == tag_1
            == qs.filter(pk=book.pk).annotate("tag").values_list("tag", flat=True).get()
        )
        r_book = (
            qs.filter(pk=book.pk)
            .exclude(tag=tagmax)
            .get(pk=book.pk, num_pages=num_pages, tag=tag_1)
        )
        assert r_book == book
        assert book.date == book.published_on.date()

        # e_desc = book.data["description"]
        # print(
        #     f"\n{qs.filter(desc_c=e_desc, desc_r=e_desc, desc_s=e_desc).explain() = }\n"
        # )
        # assert e_desc == book.desc_c == book.desc_r == book.desc_s
        # assert (
        #     qs.filter(desc_c=e_desc, desc_r=e_desc, desc_s=e_desc).get(pk=book.pk)
        #     == book
        # )

        short_books = [b for b in books if b.data["content"]["pages"] <= 500]
        not_short_books = [b for b in books if b.data["content"]["pages"] > 500]
        i = 0
        print(f"\n{qs.filter(is_short=True).all().explain() = }\n")
        for i, book in enumerate(qs.filter(is_short=True).all(), 1):
            assert book.is_short is True is (book.data["content"]["pages"] <= 500)
            assert book in short_books
        assert i == len(short_books)
        assert not ({*short_books} & {*not_short_books})
        assert {*not_short_books} == {*qs.filter(is_short=False).all()}

        best_seller_books = [b for b in books if b.data["is_best_seller"]]
        not_best_seller_books = [b for b in books if not b.data["is_best_seller"]]
        i = 0
        print(f"\n{qs.filter(is_best_seller=True).all().explain() = }\n")
        for i, book in enumerate(qs.filter(is_best_seller=True).all(), 1):
            assert book.is_best_seller is True is book.data["is_best_seller"]
            assert book in best_seller_books
        assert i == len(best_seller_books)
        assert not ({*best_seller_books} & {*not_best_seller_books})
        assert {*not_best_seller_books} == {*qs.filter(is_best_seller=False).all()}

        # assert 0
