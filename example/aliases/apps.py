from django.apps import AppConfig


class AliasesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = f"{__package__}"

    def ready(self) -> None:
        import typing as t

        from zana.django.models.aliases import ImplementsAliases

        from .models import BaseModel, Paper

        def subclasses(cls):
            for sc in cls.__subclasses__():
                yield t.cast(type[cls] | type[ImplementsAliases], sc)
                yield from subclasses(sc)

        # for cls in subclasses(BaseModel):
        #     print(f"\n{cls._meta.label}")
        #     print(f" + aliases:", *cls.__alias_fields__, sep="\n    - ")
        #     print(
        #         f" + fields:",
        #         *(f"{f'{f!s}':<32}: {id(f)}" for f in cls._meta.get_fields(include_parents=True)),
        #         sep="\n    - ",
        #     )
