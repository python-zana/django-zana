from collections import Counter

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        return

    def handle(self, **options):
        from example.aliases.models import Author, Book, Publisher

        publishers = Publisher.create_samples(6)
        authors = Author.create_samples(10)
        c_publishers = Counter({o: c for o, c in zip(publishers, (7, 6, 5, 4, 3, 2))})
        c_authors = Counter({o: c for o, c in zip(authors, (8, 7, 6, 6, 5, 5, 4, 3, 2, 1))})

        books = Book.create_samples(c_publishers, c_authors)
