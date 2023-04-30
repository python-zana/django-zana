# Generated by Django 4.1.7 on 2023-03-29 23:30

from decimal import Decimal
from django.db import migrations, models
import django.db.models.aggregates
import django.db.models.expressions
import django.db.models.functions.math
import example.aliases.models
import zana.canvas.operator
import zana.django.models


class Migration(migrations.Migration):
    dependencies = [
        ("aliases", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="author",
            name="income",
            field=zana.django.models.AliasField(
                expression=example.aliases.models.Author.get_income,
                internal=models.DecimalField(decimal_places=2, max_digits=20),
            ),
        ),
        migrations.AddField(
            model_name="author",
            name="num_books",
            field=zana.django.models.AliasField(
                expression=django.db.models.aggregates.Count("books__pk"),
                internal=models.IntegerField(),
            ),
        ),
        migrations.AddField(
            model_name="author",
            name="publishers",
            field=zana.django.models.AliasField(
                expression=example.aliases.models.Author.get_publishers_annotation,
                getter=example.aliases.models.Author.get_publishers,
            ),
        ),
        migrations.AddField(
            model_name="author",
            name="rating",
            field=zana.django.models.AliasField(
                expression=django.db.models.functions.math.Ceil(
                    django.db.models.aggregates.Avg("books__rating")
                ),
                internal=models.IntegerField(
                    choices=[
                        (0, "None"),
                        (1, "Very Bad"),
                        (2, "Bad"),
                        (3, "Average"),
                        (4, "Good"),
                        (5, "Very Good"),
                    ],
                    default=example.aliases.models.Rating["NONE"],
                ),
                select=True,
            ),
        ),
        migrations.AddField(
            model_name="author",
            name="version",
            field=zana.django.models.AliasField(expression="updated_at"),
        ),
        migrations.AddField(
            model_name="book",
            name="chapters",
            field=zana.django.models.AliasField(expression="data__content__chapters"),
        ),
        migrations.AddField(
            model_name="book",
            name="commission",
            field=zana.django.models.AliasField(
                cache=False,
                expression=django.db.models.expressions.CombinedExpression(
                    models.F("price"), "*", models.F("publisher__commission")
                ),
                getter=example.aliases.models.Book.get_commission,
                internal=models.DecimalField(decimal_places=2, max_digits=20),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="commission_income",
            field=zana.django.models.AliasField(
                cache=False,
                expression=django.db.models.expressions.CombinedExpression(
                    models.F("commission"), "*", models.F("num_sold")
                ),
                getter=example.aliases.models.Book.get_commission_income,
                internal=models.DecimalField(decimal_places=2, max_digits=20),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="date",
            field=zana.django.models.AliasField(
                defer=True,
                expression="published_on__date",
                getter=zana.canvas.operator.call(
                    source=zana.canvas.operator.getattr(
                        "date", source=zana.canvas.operator.getattr("published_on")
                    )
                ),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="gross_income",
            field=zana.django.models.AliasField(
                cache=False,
                expression=django.db.models.expressions.CombinedExpression(
                    models.F("price"), "*", models.F("num_sold")
                ),
                getter=example.aliases.models.Book.get_gross_income,
                internal=models.DecimalField(decimal_places=2, max_digits=20),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="is_best_seller",
            field=zana.django.models.AliasField(
                expression="data__is_best_seller",
                getter=zana.canvas.operator.getitem(
                    "is_best_seller", source=zana.canvas.operator.getattr("data")
                ),
                internal=models.BooleanField(),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="is_short",
            field=zana.django.models.AliasField(
                expression=models.Case(
                    models.When(
                        num_pages__lte=models.Value(500), then=models.Value(True)
                    ),
                    default=models.Value(False),
                ),
                internal=models.BooleanField(),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="net_income",
            field=zana.django.models.AliasField(
                cache=False,
                expression=django.db.models.expressions.CombinedExpression(
                    models.F("net_price"), "*", models.F("num_sold")
                ),
                getter=example.aliases.models.Book.get_net_income,
                internal=models.DecimalField(decimal_places=2, max_digits=20),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="net_price",
            field=zana.django.models.AliasField(
                cache=False,
                expression=django.db.models.expressions.CombinedExpression(
                    models.F("price"), "-", models.F("commission")
                ),
                getter=example.aliases.models.Book.get_net_price,
                internal=models.DecimalField(decimal_places=2, max_digits=20),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="num_pages",
            field=zana.django.models.AliasField(
                cast=True,
                deleter=zana.canvas.operator.delitem(
                    "pages",
                    source=zana.canvas.operator.getitem(
                        "content", source=zana.canvas.operator.getattr("data")
                    ),
                ),
                expression="data__content__pages",
                getter=zana.canvas.operator.getitem(
                    "pages",
                    source=zana.canvas.operator.getitem(
                        "content", source=zana.canvas.operator.getattr("data")
                    ),
                ),
                internal=models.IntegerField(),
                setter=zana.canvas.operator.setitem(
                    "pages",
                    source=zana.canvas.operator.getitem(
                        "content", source=zana.canvas.operator.getattr("data")
                    ),
                ),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="published_by",
            field=zana.django.models.AliasField(
                deleter=zana.canvas.operator.delattr(
                    "name", source=zana.canvas.operator.getattr("publisher")
                ),
                expression="publisher__name",
                getter=zana.canvas.operator.getattr(
                    "name", source=zana.canvas.operator.getattr("publisher")
                ),
                setter=zana.canvas.operator.setattr(
                    "name", source=zana.canvas.operator.getattr("publisher")
                ),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="tag",
            field=zana.django.models.AliasField(
                deleter=zana.canvas.operator.delitem(
                    0,
                    source=zana.canvas.operator.getitem(
                        "tags", source=zana.canvas.operator.getattr("data")
                    ),
                ),
                expression="data__tags__0",
                getter=zana.canvas.operator.getitem(
                    0,
                    source=zana.canvas.operator.getitem(
                        "tags", source=zana.canvas.operator.getattr("data")
                    ),
                ),
                internal=models.TextField(),
                json=True,
                setter=zana.canvas.operator.setitem(
                    0,
                    source=zana.canvas.operator.getitem(
                        "tags", source=zana.canvas.operator.getattr("data")
                    ),
                ),
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="tags",
            field=zana.django.models.AliasField(
                expression="data__tags", getter=example.aliases.models.Book.get_tags
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="topics",
            field=zana.django.models.AliasField(
                expression="data__content__chapters__0__topics"
            ),
        ),
        migrations.AddField(
            model_name="book",
            name="version",
            field=zana.django.models.AliasField(expression="updated_at"),
        ),
        migrations.AddField(
            model_name="book",
            name="year",
            field=zana.django.models.AliasField(
                expression=models.F("published_on__year"),
                getter=zana.canvas.operator.getattr(
                    "year", source=zana.canvas.operator.getattr("published_on")
                ),
                internal=models.IntegerField(),
            ),
        ),
        migrations.AddField(
            model_name="publisher",
            name="income",
            field=zana.django.models.AliasField(
                expression=example.aliases.models.Publisher.get_income
            ),
        ),
        migrations.AddField(
            model_name="publisher",
            name="num_books",
            field=zana.django.models.AliasField(
                expression=django.db.models.aggregates.Count("books__pk"),
                internal=models.IntegerField(),
            ),
        ),
        migrations.AddField(
            model_name="publisher",
            name="rating",
            field=zana.django.models.AliasField(
                cast=True,
                expression=django.db.models.aggregates.Avg("books__rating"),
                internal=models.DecimalField(
                    decimal_places=2, default=Decimal("0.00"), max_digits=20
                ),
                select=True,
            ),
        ),
        migrations.AddField(
            model_name="publisher",
            name="version",
            field=zana.django.models.AliasField(expression="updated_at"),
        ),
    ]
