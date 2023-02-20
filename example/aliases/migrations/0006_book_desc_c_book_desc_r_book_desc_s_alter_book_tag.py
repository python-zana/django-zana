# Generated by Django 4.1.7 on 2023-02-18 01:14

import zana.django.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aliases", "0005_alter_book_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="desc_c",
            field=zana.django.models.AliasField(
                cast=True,
                expression=models.F("data__description"),
                internal=models.CharField(),
                setter=True,
                source=[("ATTR", ("data",)), ("ITEM", ("description",))],
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="desc_r",
            field=zana.django.models.AliasField(
                expression=models.F("data__description"),
                internal=models.CharField(),
                setter=True,
                source=[("ATTR", ("data",)), ("ITEM", ("description",))],
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="desc_s",
            field=zana.django.models.AliasField(
                expression=models.F("data__description"),
                internal=models.CharField(),
                setter=True,
                source=[("ATTR", ("data",)), ("ITEM", ("description",))],
            ),
        ),
        migrations.AlterField(
            model_name="book",
            name="tag",
            field=zana.django.models.AliasField(
                deleter=True,
                expression=models.F("data__tags__0"),
                internal=models.TextField(),
                json=True,
                setter=True,
                source=[("ATTR", ("data",)), ("ITEM", ("tags", 0))],
            ),
        ),
    ]