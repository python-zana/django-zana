import typing as t
from decimal import Decimal

from typing_extensions import Self
from zana.types.enums import IntEnum

from django.db import models as m
from django.utils import timezone
from zana.django.models import alias


class Rating(IntEnum):
    VERT_BAD = 1
    BAD = 2
    AVERAGE = 3
    GOOD = 4
    VERY_GOOD = 5


class Author(m.Model):
    name: str = m.CharField(max_length=200)
    age: str = m.IntegerField()
    books: 'm.manager.RelatedManager[Book]'


    def get_avg_rating(self):
        return self.books.aggregate(avg_rating=m.Avg('rating', default=0))['avg_rating']

    rating: t.Union[float, int] = alias(lambda cls: m.Avg('books__rating'), get_avg_rating, default=0.0, field=m.FloatField()).getter(get_avg_rating)



class Book(m.Model):
    title: str = m.CharField(max_length=200)
    price: Decimal = m.DecimalField(max_digits=12, null=True, decimal_places=2)
    rating: int = m.SmallIntegerField(choices=Rating.choices, null=True)
    author: Author = m.ForeignKey('Author', m.RESTRICT, related_name='books')
    
    date_published = m.DateTimeField(null=True, default=timezone.now)

    def set_published_on(self, val):
        self.date_published = val

    published_on = alias(date_published, annotate=True).setter(set_published_on)

    authored_by = alias(setter=True)[Self].author.name
    

