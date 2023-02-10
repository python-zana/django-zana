from django.contrib import admin

from .models import Author, Book, Publication, Publisher


class BookInlineAdmin(admin.TabularInline):
    model = Book
    fields = [
        "id",
        "title",
        "rating",
        "price",
    ]
    show_change_link = True
    show_full_result_count = True


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "name",
        "num_books",
        "rating",
        "income",
    ]


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "title",
        "rating",
        "price",
    ]


@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "title",
        "rating",
        "price",
        "period",
        "published_on",
    ]


@admin.register(Publisher)
class PublisherAdmin(admin.ModelAdmin):
    inlines = [BookInlineAdmin]
    list_display = [
        "pk",
        "name",
        "num_books",
        "rating",
        "commission",
        "income",
    ]
