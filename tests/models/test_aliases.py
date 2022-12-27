import typing as t
from lib2to3 import pytree

import pytest

pytestmark = [
    pytest.mark.django_db,

]

from example.models import Author


class test_alias:

    def test_basic(self):
        obj = Author(name='John Doe', age=25)
        obj.save()
        