import typing as t

from zana.types.enums import IntEnum

from django.db import models as m
from zana.django.models import alias


class Rating(IntEnum):
    VERT_BAD = 1
    BAD = 2
    AVERAGE = 3
    GOOD = 4
    VERY_GOOD = 5


class Author(m.Model):
    name = m.CharField(max_length=200)
    age = m.IntegerField()
    books: 'm.manager.RelatedManager[Book]'


    def get_avg_rating(self):
        return self.books.aggregate(avg_rating=m.Avg('books__rating', default=0))['avg_rating']

    avg_rating = alias(m.Avg('books__rating', default=0), get_avg_rating)




class Book(m.Model):
    title = m.CharField(max_length=200)
    price = m.DecimalField(max_digits=12, null=True, decimal_places=2)
    rating = m.SmallIntegerField(choices=Rating.choices, null=True)
    author = m.ForeignKey('Author', m.RESTRICT, 'books')
    
    date_published = m.DateTimeField(null=True)

    author_name = alias('author__name')

