import math
from collections import Counter
from statistics import mean
from unittest.mock import Mock

import pytest

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
            assert {*e_books} == {*Book.objects.filter(published_by=publisher.name).all()}
            book.published_by = mk_name = Mock(str)
            assert mk_name is book.published_by is publisher.name

        # assert 0

    def test_queryset(self):
        books = Book.create_samples()
        authors: list[Author] = list(Author.objects.alias("rating").all())

        for author in authors:
            e_books = list(author.books.all())
            e_rating = mean(b.rating for b in e_books)
            assert pytest.approx(e_rating, rel=1e-2) == float(author.__dict__["rating"])
            author.refresh_from_db(None, ["rating"])
            a_rating = author.rating
            assert pytest.approx(e_rating, rel=1e-2) == float(a_rating)

            e_income = sum(b.num_sold * (b.price - b.commission) for b in e_books)
            a_income = author.income
            assert e_income == a_income

            assert e_books[0].version is e_books[0].updated_at
        # assert 0

    def test_books(self):
        book: Book
        publishers = Publisher.create_samples(3)
        authors = Author.create_samples(6)
        c_publishers = Counter({o: c for o, c in zip(publishers, (8, 6, 3))})
        c_authors = Counter({o: c for o, c in zip(authors, (9, 6, 5, 3, 2, 2))})
        qs = Book.objects.all()
        books = Book.create_samples(c_publishers, c_authors)
        tagmax = max(b.data["tags"][0] for b in books)
        with_tagmax = [b for b in books if b.data["tags"][0] == tagmax]
        for i, book in enumerate(qs.filter(tag=tagmax, tags__0=tagmax).all(), 1):
            assert book.tag == book.tags[0] == tagmax == book.data["tags"][0]
            assert book.tags == book.data["tags"][:2]
            assert book in with_tagmax
            assert book.num_pages == book.data["content"]["pages"]

        assert i == len(with_tagmax)

        e_published_by, mk_published_by = book.publisher.name, Mock(str)
        assert e_published_by == book.published_by == book.publisher.name
        book.published_by = mk_published_by
        assert book.published_by is mk_published_by is book.publisher.name
        del book.published_by
        assert e_published_by == book.published_by == book.publisher.name

        num_pages = book.num_pages
        mk_pages = Mock(int)
        book.num_pages = mk_pages
        assert book.data["content"]["pages"] is mk_pages is book.num_pages
        del book.num_pages
        assert "pages" not in book.data["content"]
        book.num_pages = num_pages
        assert book.data["content"]["pages"] == num_pages == book.num_pages

        tag_1 = book.data["tags"][1]
        del book.tag
        book.save()
        assert (
            book.tag
            == tag_1
            == qs.filter(pk=book.pk).annotate("tag").values_list("tag", flat=True).get()
        )
        assert qs.filter(pk=book.pk).exclude(tag=tagmax).get(pk=book.pk, tag=tag_1)

        assert book.date == book.published_on.date()
        # assert 0
