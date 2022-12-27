import typing as t
from lib2to3 import pytree
from random import randint
from statistics import mean

import pytest

pytestmark = [
    pytest.mark.django_db,

]

from example.models import Author, Book, Rating


class test_alias:

    max_rating = max(Rating)

    def create_authors(self, count=2):
        stop, age = count +1, lambda: randint(16,85)
        return [Author.objects.create(name=f"Author {x}", age=age()) for x in range(1, stop)]

    def create_books(self, author: Author, count=max_rating):
        price = lambda: (randint(200, 5000) // 50) * 50
        return Book.objects.bulk_create(Book(title=f"Book {x} ({author.name})", author=author, price=price(), rating=Rating(x % self.max_rating + 1)) for x in range(count))

    def test_basic(self):
        author_0, author_1 = self.create_authors()
        author_0._b_count, author_1._b_count = 5, 3
        

        for author in (author_0, author_1):
            self.create_books(author, author._b_count)

        for author in (author_0, author_1):
            rating = mean(range(1, 1+author._b_count))
            assert author.books.count() == author._b_count
            assert author.rating == rating
            assert author == Author.objects.get(rating=rating)
            assert author.name == author.books.first().authored_by
            
            assert {*author.books.all()} == {*Book.objects.filter(authored_by=author.name).all()}


