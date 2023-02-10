import typing as t
from abc import ABC
from collections import abc
from functools import reduce, wraps
from itertools import chain
from operator import attrgetter
from types import FunctionType, MethodType

from typing_extensions import Self
from zana.common import cached_attr

from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.db import models as m
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce
from django.db.models.query_utils import FilteredRelation
from django.dispatch import receiver
from zana.django.models.fields import PseudoField

_T = t.TypeVar("_T")
_T_Src = t.TypeVar("_T_Src")
_T_Default = t.TypeVar("_T_Default")
_T_Model = t.TypeVar("_T_Model", bound="ImplementsAliases", covariant=True)
_T_Expr = t.Union[
    Combinable,
    str,
    t.Callable[[], Combinable | str],
]
_T_Func = FunctionType | staticmethod | classmethod | MethodType | type


def get_alias_field_names(model: type[_T_Model], default: _T_Default = None):
    if issubclass(model, ImplementsAliases):
        return model.__alias_fields__
    elif not issubclass(model, m.Model):
        raise TypeError(f"expected `Model` subclass. not `{model.__class__.__name__}`")
    return default


def get_alias_fields(model: type[_T_Model], default: _T_Default = None):
    if names := get_alias_field_names(model):
        opts = model._meta
        return t.cast(dict[str, "AliasField"], {n: opts.get_field(n) for n in names})
    return default


class ImplementsAliasesManager(
    ABC, m.Manager[_T_Model] if t.TYPE_CHECKING else t.Generic[_T_Model]
):
    model: type[_T_Model]
    _initial_alias_fields_: t.Final[abc.Mapping[str, Combinable]] = ...
    _initial_annotated_alias_fields_: t.Final[abc.Mapping[str, m.F]] = ...


class ImplementsAliases(ABC, m.Model if t.TYPE_CHECKING else object):
    __alias_fields__: set[str]

    @classmethod
    def setup_model(self, cls: type[_T_Model]):
        if not "__alias_fields__" in cls.__dict__:
            cls.__alias_fields__ = set()

        return self.register(cls)


class ExpressionBuilder(t.Generic[_T]):
    __slots__ = (
        "__alias__",
        "__args__",
        "__origin__",
    )
    __alias__: "AliasField[_T]"

    def __new__(cls, alias: "AliasField[_T]", origin, *args) -> Self:
        self = object.__new__(cls)
        self.__alias__, self.__args__, self.__origin__ = alias, args, origin
        return self

    def __call__(self) -> "AliasField":
        return self.__alias__._update(expression=m.F("__".join(self.__args__)))

    def __getattr__(self, name: str):
        return self.__class__(self.__alias__, self.__origin__, *self.__args__, name)

    def __getitem__(self, name: str):
        return self.__class__(self.__alias__, self.__origin__, *self.__args__, name)

    def contribute_to_class(self, cls: t.Type[_T_Model], name: str, *a, **kw):
        return self().contribute_to_class(cls, name, *a, **kw)


class BaseAliasDescriptor(property):
    field: "AliasField" = None

    def __init__(self, field: "AliasField") -> None:
        self.field = field
        super().__init__(field.get_getter(), field.get_setter(), field.get_deleter())


class DynamicAliasDescriptor(BaseAliasDescriptor, property):
    pass


class CachedAliasDescriptor(BaseAliasDescriptor, cached_attr[_T]):
    pass


class AliasField(PseudoField[_T, _T | m.expressions.Combinable], t.Generic[_T]):
    _POS_ARGS_ = [
        "expression",
        "getter",
        "setter",
        "deleter",
    ]

    _KWARGS_TO_ATTRS_ = {
        "expression": "expression",
        "getter": "fget",
        "setter": "fset",
        "deleter": "fdel",
        "annotate": "annotate",
        "path": "path",
        "cache": "cache",
        "defer": "defer",
    }
    _INIT_DEFAULTS_ = {
        "expression": None,
        "getter": None,
        "setter": None,
        "deleter": None,
        "default": None,
        "editable": False,
    }

    name: str
    expression: _T_Expr = None
    _init_args_: t.Final[set]

    # cache: bool
    # path: str
    # annotate: bool
    # defer: bool
    verbose_name: str

    _cached_descriptor_class_ = CachedAliasDescriptor
    _dynamic_descriptor_class_ = DynamicAliasDescriptor

    fget: abc.Callable[[_T_Model], _T] = None
    fset: abc.Callable[[_T_Model, _T], t.NoReturn] = None
    fdel: abc.Callable[[_T_Model], t.NoReturn] = None

    @t.overload
    def __init__(
        self,
        expression: _T_Expr = None,
        getter: t.Union[abc.Callable[[_T_Model], _T], bool] = None,
        setter: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool] = None,
        deleter: abc.Callable[[_T_Model], t.NoReturn] = None,
        *,
        annotate: bool = None,
        path: str = None,
        doc: str = None,
        cache: bool = None,
        defer: bool = None,
        **kwds,
    ) -> None:
        ...

    def __init__(self, *args, **kwds) -> None:
        self._init_args_ = set()
        args and kwds.update({k: v for k, v in zip(self._POS_ARGS_, args)})
        kwds, k2a = self._INIT_DEFAULTS_ | kwds, self._KWARGS_TO_ATTRS_
        super().__init__(**{k: v for k, v in kwds.items() if not k in k2a})
        self._update(kwds)

    @cached_attr
    def f(self):
        return m.F(self.name)

    @cached_attr
    def annotate(self):
        return False

    @cached_attr
    def cache(self):
        return not not self.annotate or not (self.fset or self.path)

    @cached_attr
    def defer(self):
        return False

    @cached_attr
    def query_annotation(self):
        return self.get_annotation()

    @cached_attr
    def path(self):
        if isinstance(expr := self.expression, str):
            return expr.replace("__", ".")
        elif isinstance(expr, m.F):
            return expr.name.replace("__", ".")

    def contribute_to_class(self, cls: type[_T_Model], name: str, private_only: bool = None):
        if private_only is None:
            private_only = cls._meta.proxy

        super().contribute_to_class(cls, name, private_only)

        setattr(self.__class__, "_p_Stack", getattr(self, "_p_Stack", [None]))
        if self._p_Stack[-1] != cls._meta.label:
            self._p_Stack.append(cls._meta.label)
            print(f"\n{cls._meta.label+' :':<24}")

        print(f"  - {self.creation_counter}) {name:<20} {private_only = } {id(self)}")

        cls = ImplementsAliases.setup_model(cls)
        cls.__alias_fields__.add(name)

    def at(self, src: _T_Src) -> _T_Src:
        return ExpressionBuilder[_T](self, src)

    def annotation(self, expression: _T_Expr):
        self._update(expression=expression)
        return expression

    def getter(self, fget: t.Callable[[t.Any], _T]):
        self._update(getter=fget)
        return fget

    def setter(self, fset: t.Callable[[t.Any], _T]):
        self._update(setter=fset)
        return fset

    def deleter(self, fdel: t.Callable):
        self._update(deleter=fdel)
        return fdel

    def _update(self, arg=(), **kwds):
        if isinstance(arg, abc.Mapping):
            arg = arg.items()
        k2a, ia = self._KWARGS_TO_ATTRS_, self._init_args_
        for kv in ((kv for kv in arg if kv[0] in k2a and kv[0] not in kwds), kwds.items()):
            for k, v in kv:
                setattr(self, k2a[k], v)
                ia.add(k)
        return self

    def get_expression(self) -> abc.Callable[[], m.expressions.Combinable]:
        expr = self.expression
        if isinstance(expr, _T_Func):
            expr = expr()
        if isinstance(expr, str):
            expr = m.F(expr)

        return expr

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        k2a, ia, defaults = self._KWARGS_TO_ATTRS_, self._init_args_, self._INIT_DEFAULTS_

        for a in ia:
            kwargs.setdefault(a, getattr(self, k2a[a]))

        for k, v in defaults.items():
            if k in kwargs and kwargs[k] == v:
                kwargs.pop(k)

        # cls = getattr(self, "model", "")
        # print(f"\n{name}: {cls and cls._meta.label}")
        # args and print(" -> ARGS:", *args, sep="\n    - ")
        # kwargs and print(
        #     " -> KWARGS:", *(f"{k:<16}: {v}" for k, v in kwargs.items()), sep="\n    - "
        # )
        return name, path, args, kwargs

    def get_annotation(self):
        expr, field = self.get_expression(), self.real_field

        if self.has_default() and (default := self.get_default()) is not None:
            expr = Coalesce(expr, default, output_field=field)
        elif field:
            expr = m.ExpressionWrapper(expr, output_field=field)
        return expr

    def get_descriptor_class(self):
        return getattr(self, f"_{'cached' if self.cache else 'dynamic'}_descriptor_class_")

    def get_getter(self):
        fget = self.fget
        if fget in (True, None):
            if (path := self.path) is not None:
                fget = attrgetter(path)
            else:
                annotate, defer, name = self.annotate, self.defer, self.name

                def fget(self: _T_Model):
                    nonlocal name, defer, annotate
                    if self._state.adding:
                        raise AttributeError(name)
                    qs = self._meta.base_manager.filter(pk=self.pk)
                    if defer:
                        qs = qs = qs.alias(name)
                    if annotate is False:
                        qs = qs.annotate(name)
                    return qs.values_list(name, flat=True).get()

        if fget and self.has_default():
            fget_, field = fget, self

            @wraps(fget_)
            def fget(self):
                nonlocal field, fget_
                try:
                    val = fget_(self)
                except AttributeError:
                    val = None
                return field.get_default() if val is None else val

        return fget or None

    def get_setter(self):
        attr, func = self.path, self.fset
        if func is True and attr:
            *path, name = attr.split(".")

            def func(self: m.Model, value):
                nonlocal path, name
                obj = reduce(getattr, path, self) if path else self
                setattr(obj, name, value)

        return func or None

    def get_deleter(self):
        return self.fdel

    def check(self, **kwargs):
        return super().check(**kwargs) + [
            *self._check_setter(),
        ]

    def _check_setter(self):
        path, annotate, cache, errors = self.path, self.annotate, self.cache, []
        if self.fset is True and (not path or annotate or cache):
            label = f"{self.__class__.__qualname__}"
            if annotate:
                errors.append(
                    checks.Error(
                        f"Annotated {label} cannot have an implicit setter=True",
                        hint=(
                            "Set annotate=False, use a custom `setter` function, "
                            "or remove setter=True argument on the field."
                        ),
                        obj=self,
                        id="aliases_field.E003",
                    )
                )
            elif cache:
                errors.append(
                    checks.Error(
                        f"Cached {label} cannot have an implicit `setter=True. ",
                        hint=(
                            "Set cache=False, use a custom `setter` function, "
                            "or remove setter=True argument on the field."
                        ),
                        obj=self,
                        id="aliases_field.E004",
                    )
                )
            else:
                errors.append(
                    checks.Error(
                        f"{label}s with setter=True must have a `path`.",
                        hint=(
                            "Explicitly set `attr`, use a custom `setter` function, "
                            "or remove setter=True argument on the field."
                        ),
                        obj=self,
                        id="aliases_field.E005",
                    )
                )

        return errors


@receiver(m.signals.class_prepared, weak=False)
def __on_class_prepared(sender: type[_T_Model], **kwds):
    if issubclass(sender, ImplementsAliases):
        print(f"-> {sender._meta.label:<18} prepared ...")


class _Patcher:
    """Monkey patch Manager, Queryset and Model classes"""

    @staticmethod
    def model(cls: type[_T_Model]):
        mro = (b.refresh_from_db for b in cls.__mro__ if "refresh_from_db" in b.__dict__)
        # if not all(getattr(b, "_loads_alias_fields_", None) for b in mro):
        #     orig_refresh_from_db = cls.refresh_from_db

        #     @wraps(orig_refresh_from_db)
        #     def refresh_from_db(self, using=None, fields=None):
        #         nonlocal orig_refresh_from_db
        #         if dct := get_alias_fields(self.__class__):
        #             if fields_ := fields:
        #                 fields = list(fields)
        #                 aliases = (n for n in fields if not (n in dct and not fields.remove(n)))
        #             else:
        #                 aliases = (n for n, a in dct.items() if a.cache)

        #             for aka in aliases:
        #                 with suppress(AttributeError):
        #                     delattr(self, aka)

        #             if not fields and fields_:
        #                 return

        #         orig_refresh_from_db(self, using, fields)

        #     refresh_from_db._loads_alias_fields_ = True
        #     cls.refresh_from_db = refresh_from_db

    @staticmethod
    def manager(cls: type["ImplementsAliasesManager[_T_Model]"]):
        if not getattr(cls.get_queryset, "_loads_alias_fields_", False):
            base_get_queryset = cls.get_queryset

            @wraps(base_get_queryset)
            def get_queryset(self: cls, *args, **kwargs):
                qs = base_get_queryset(self, *args, **kwargs)
                if aliases := self._initial_alias_fields_:
                    qs = qs.alias(**aliases)
                    if annotations := self._initial_annotated_alias_fields_:
                        qs = qs.annotate(**annotations)

                return qs

            get_queryset._loads_alias_fields_ = True
            cls.get_queryset = get_queryset

            if not getattr(cls, "_initial_alias_fields_", None):

                @cached_attr
                def _initial_alias_fields_(self: m.Manager[_T_Model]):
                    model = self.model
                    aliases = get_alias_fields(model, {})
                    return {n: a.query_annotation for n, a in aliases.items() if not a.defer}

                @cached_attr
                def _initial_annotated_alias_fields_(self: m.Manager[_T_Model]):
                    model = self.model
                    aliases = get_alias_fields(model, {})
                    return {n: m.F(n) for n, a in aliases.items() if not a.defer and a.annotate}

                _initial_alias_fields_.__set_name__(cls, "_initial_alias_fields_")
                _initial_annotated_alias_fields_.__set_name__(
                    cls, "_initial_annotated_alias_fields_"
                )

                cls._initial_alias_fields_ = _initial_alias_fields_
                cls._initial_annotated_alias_fields_ = _initial_annotated_alias_fields_

    @staticmethod
    def queryset(cls: type[m.QuerySet[_T_Model]]):
        if not getattr(cls.annotate, "_loads_alias_fields_", None):
            orig_annotate = cls.annotate

            @wraps(orig_annotate)
            def annotate(self: cls[_T_Model], *args, **kwds):
                nonlocal orig_annotate
                if aliases := args and get_alias_field_names(self.model):
                    args = [
                        a
                        for a in args
                        if not (
                            (
                                n := a
                                if isinstance(a, str)
                                else a.name
                                if isinstance(a, m.F)
                                else None
                            )
                            and n not in kwds
                            and n in aliases
                            and (kwds.setdefault(n, m.F(n) if a is n else a),)
                        )
                    ]
                return orig_annotate(self, *args, **kwds)

            annotate._loads_alias_fields_ = True
            cls.annotate = annotate

        if not getattr(cls.alias, "_loads_alias_fields_", None):
            orig_alias = cls.alias

            @wraps(orig_alias)
            def alias(self: cls[_T_Model], *args, **kwds):
                nonlocal orig_alias
                if aliases := args and get_alias_field_names(self.model):
                    aka: AliasField
                    model, opts = self.model, self.model._meta
                    annotate = {}
                    args = [
                        a
                        for a in args
                        if not (
                            (
                                n := a
                                if isinstance(a, str)
                                else a.name
                                if isinstance(a, m.F)
                                else None
                            )
                            and n in aliases
                            and n not in kwds
                            and (aka := opts.get_field(n))
                            and kwds.setdefault(n, aka.query_annotation)
                            and (aka.annotate and annotate.setdefault(n, m.F(n) if a is n else a),)
                        )
                    ]
                    if annotate:
                        return orig_alias(self, *args, **kwds).annotate(**annotate)

                return orig_alias(self, *args, **kwds)

            alias._loads_alias_fields_ = True
            cls.alias = alias

        if not getattr(cls._annotate, "_loads_alias_fields_", None):
            orig__annotate = cls._annotate

            @wraps(orig__annotate)
            def _annotate(self: cls[_T_Model], args, kwargs, select=True):
                model = self.model
                aliases = get_alias_field_names(model, ())
                self._validate_values_are_expressions(
                    args + tuple(kwargs.values()), method_name="annotate"
                )
                annotations = {}

                for arg in args:
                    # The default_alias property may raise a TypeError.
                    try:
                        if arg.default_alias in kwargs:
                            raise ValueError(
                                "The named annotation '%s' conflicts with the "
                                "default name for another annotation." % arg.default_alias
                            )
                    except TypeError:
                        raise TypeError("Complex annotations require an alias")
                    annotations[arg.default_alias] = arg
                annotations.update(kwargs)

                clone: cls[_T_Model] = self._chain()
                names = self._fields
                if names is None:
                    names = set(
                        chain.from_iterable(
                            (field.name, field.attname)
                            if hasattr(field, "attname")
                            else (field.name,)
                            for field in model._meta.get_fields()
                        )
                    )
                    if aliases:
                        names -= aliases

                for alias, annotation in annotations.items():
                    if alias in names:
                        raise ValueError(
                            "The annotation '%s' conflicts with a field on " "the model." % alias
                        )
                    if isinstance(annotation, FilteredRelation):
                        clone.query.add_filtered_relation(annotation, alias)
                    else:
                        clone.query.add_annotation(
                            annotation,
                            alias,
                            is_summary=False,
                            select=select,
                        )
                for alias, annotation in clone.query.annotations.items():
                    if alias in annotations and annotation.contains_aggregate:
                        if clone._fields is None:
                            clone.query.group_by = True
                        else:
                            clone.query.set_group_by()
                        break

                return clone

            _annotate._loads_alias_fields_ = True
            cls._annotate = _annotate

    @classmethod
    def patch(cls, *args) -> None:
        for obj in args:
            if issubclass(obj, m.Model):
                cls.model(obj)
            elif issubclass(obj, m.Manager):
                cls.manager(obj)
            elif issubclass(obj, m.QuerySet):
                cls.queryset(obj)
            else:  # pragma: no cover
                raise TypeError(
                    f"expected a subclass of {m.Model | m.Manager | m.QuerySet}"
                    f"but got {obj.__name__}."
                )

    @classmethod
    def install(cls):  # pragma: no cover
        cls.patch(m.Model, m.Manager, m.QuerySet)
        try:
            from polymorphic.managers import PolymorphicManager  # type: ignore
            from polymorphic.query import PolymorphicQuerySet  # type: ignore
        except ImportError:
            pass
        else:
            _Patcher.patch(PolymorphicManager, PolymorphicQuerySet)


_Patcher.install()
