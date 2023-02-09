from django.contrib import admin

from .models import Author, Book, Novel, Publisher


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


@admin.register(Novel)
class NovelAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "title",
        "rating",
        "price",
        "date_released",
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
