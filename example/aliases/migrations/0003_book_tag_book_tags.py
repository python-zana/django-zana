# Generated by Django 4.1.6 on 2023-02-15 15:58

import zana.django.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aliases", "0002_author_income_author_num_books_author_publishers_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="tag",
            field=zana.django.models.AliasField(
                expression=models.F("data__tags__0"),
                setter=True,
                source=[("ATTR", ("data",)), ("ITEM", (("tags", 0), {}))],
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="tags",
            field=zana.django.models.AliasField(
                expression=models.F("data__tags"),
                setter=True,
                source=[("ATTR", ("data",)), ("ITEM", ("tags",))],
            ),
        ),
    ]
