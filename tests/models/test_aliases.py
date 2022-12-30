import typing as t
from collections import Counter
from lib2to3 import pytree
from random import randint, shuffle
from statistics import mean
from unittest.mock import Mock

import pytest

from example.aliases.models import Author, BaseModel, Book, Publisher, Rating
from zana.django.models import alias

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
        return [Publisher.objects.create(name=f'Publisher {x}') for x in range(count)]

    def create_authors(self, count=4):
        stop, age = count +1, lambda: randint(16,85)
        return [Author.objects.create(name=f"Author {x}", age=age()) for x in range(1, stop)]

    def create_books(self, c_publishers: Counter[Publisher, Author], c_authors: Counter[Author, int]):
        c_authors, publishers, max_rating = +c_authors, list(c_publishers.elements()), max(Rating)
        shuffle(publishers)
        books: list[Book] = []
        n_authors = c_authors.total() // c_publishers.total() 
        n_rem = c_authors.total() % c_publishers.total() 
        for x, publisher in enumerate(publishers):
            *authors, = c_authors
            shuffle(authors)
            authors = authors[:n_authors + 1 if x < n_rem else n_authors]
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
            
    def test_basic(self):
        publishers = self.create_publishers(3)
        authors = self.create_authors(6)
        c_publishers = Counter({o: c for o,c in zip(publishers, (6,4,2)) })
        c_authors = Counter({o: c for o,c in zip(authors, (8,6,4,3,2,1)) })
        
        books = self.create_books(c_publishers, c_authors)

        for publisher in publishers:
            e_books = publisher.assigned(Book)
            assert len(e_books) == publisher.books.count()

            e_rating = mean(b.rating for b in e_books)
            assert e_rating == publisher.rating == publisher.__dict__['rating']
            del publisher.rating
            assert not 'rating' in publisher.__dict__
            result = Publisher.objects.get(pk=publisher.pk, rating=e_rating)
            assert publisher == result
            assert e_rating == result.__dict__['rating']

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

