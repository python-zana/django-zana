import typing as t
from lib2to3 import pytree

import pytest

pytestmark = [
    pytest.mark.django_db,

]

from example.models import Author, Book


class test_alias:

    def test_basic(self):
        author = Author.objects.create(name='John Doe', age=25)
        book: Book = author.books.create(title='My Book', price=20, rating=4)

        assert book in {*author.books.all()}
        
        