import typing as t
from abc import ABC
from collections import abc
from functools import reduce, wraps
from itertools import chain
from operator import attrgetter
from types import FunctionType, MethodType

from typing_extensions import Self
from zana.common import cached_attr

from django.core.exceptions import ImproperlyConfigured
from django.db import models as m
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce
from django.db.models.query_utils import FilteredRelation

_T = t.TypeVar("_T")
_T_Src = t.TypeVar("_T_Src")
_T_Default = t.TypeVar("_T_Default")
_T_Model = t.TypeVar("_T_Model", bound="ImplementsAliases", covariant=True)
_T_Expr = t.Union[
    Combinable,
    str,
    "AliasField",
    t.Callable[[_T_Model], t.Union[Combinable, str, "AliasField"]],
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


class AliasPathBuilder(t.Generic[_T]):
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
        aka = self.__alias__._set_attrs()
        aka.annotation("__".join(self.__args__))
        return aka

    def __getattr__(self, name: str):
        return self.__class__(self.__alias__, self.__origin__, *self.__args__, name)

    def __getitem__(self, name: str):
        return self.__class__(self.__alias__, self.__origin__, *self.__args__, name)

    def contribute_to_class(self, cls: t.Type[_T_Model], name: str):
        return self().contribute_to_class(cls, name)


class BaseAliasDescriptor:
    # __slots__ = ()

    field: "AliasField" = None

    # @property
    # def admin_order_field(self):
    #     return self.field.order_field

    # @property
    # def boolean(self):
    #     return self.field.boolean

    # @property
    # def short_description(self):
    #     return self.field.verbose_name


class DynamicAliasDescriptor(BaseAliasDescriptor, property):
    pass


class CachedAliasDescriptor(BaseAliasDescriptor, cached_attr[_T]):
    pass


class AliasField(m.Field, t.Generic[_T]):
    _KWARGS_TO_ATTRS_ = {
        "expression": "expression",
        "getter": "fget",
        "setter": "fset",
        "deleter": "fdel",
        "annotate": "annotate",
        "attr": "attr",
        "output_field": "output_field",
        "cache": "cache",
        "defer": "defer",
    }
    _FIELD_DEFAULTS_ = {
        "editable": False,
    }

    name: str
    cache: bool
    attr: str
    expression: _T_Expr
    annotate: bool
    defer: bool
    output_field: m.Field | None
    verbose_name: str
    order_field: t.Any
    boolean: bool

    fget: abc.Callable[[_T_Model], _T]
    fset: abc.Callable[[_T_Model, _T], t.NoReturn]
    fdel: abc.Callable[[_T_Model], t.NoReturn]

    def __init__(
        self,
        expression: _T_Expr = None,
        getter: t.Union[abc.Callable[[_T_Model], _T], bool] = None,
        setter: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool] = None,
        deleter: abc.Callable[[_T_Model], t.NoReturn] = None,
        *,
        annotate: bool = None,
        attr: str = None,
        doc: str = None,
        output_field: m.Field = None,
        cache: bool = None,
        defer: bool = None,
        **kwds,
    ) -> None:
        super().__init__(**self._FIELD_DEFAULTS_ | kwds)
        self._set_attrs(**{k: v for k, v in vars().items() if k in self._KWARGS_TO_ATTRS_})

    def db_type(self, connection):
        return None

    def get_attname_column(self):
        return self.get_attname(), None

    def contribute_to_class(self, cls: type[_T_Model], name: str, private_only=False):
        super().contribute_to_class(cls, name, private_only)

        cls = ImplementsAliases.setup_model(cls)
        self._prepare(cls, name)
        cls.__alias_fields__.add(name)

        descriptor = self.create_descriptor(cls)
        descriptor.field = self

        if hasattr(descriptor, "__set_name__"):
            descriptor.__set_name__(cls, name)

        setattr(cls, name, descriptor)

    def at(self, src: _T_Src) -> _T_Src:
        return AliasPathBuilder[_T](self, src)

    def annotation(self, expression: _T_Expr):
        self._set_attrs(expression=expression)
        return expression

    def getter(self, fget: t.Callable[[t.Any], _T]):
        self._set_attrs(getter=fget)
        return fget

    def setter(self, fset: t.Callable[[t.Any], _T]):
        self._set_attrs(setter=fset)
        return fset

    def deleter(self, fdel: t.Callable):
        self._set_attrs(deleter=fdel)
        return fdel

    def _set_attrs(self, **kwargs):
        k2a = self._KWARGS_TO_ATTRS_
        for k, v in kwargs.items():
            setattr(self, k2a[k], v)

    def get_expression(self, cls: t.Type[m.Model]):
        expr, field = self.expression, self.output_field
        if isinstance(expr, _T_Func):
            expr = expr(cls)

        if isinstance(expr, str):
            expr = m.F(expr)

        if self.has_default() and (default := self.get_default()) is not None:
            expr = Coalesce(expr, default, output_field=field)
        elif field:
            expr = m.ExpressionWrapper(expr, output_field=field)
        return expr

    def _prepare(self, cls: t.Type[_T_Model], name: str):
        annotate, attr, cache, expression = self.annotate, self.attr, self.cache, self.expression
        fget, fset, fdel, defer = self.fget, self.fset, self.fdel, self.defer

        if attr is None:
            lookup = attr
            if isinstance(expression, m.F):
                lookup = expression.name
            elif isinstance(expression, str):
                lookup = expression
            attr = lookup and lookup.replace("__", ".")

        annotate = fget is False and not (fset or attr) if annotate is None else not not annotate

        if cache is None:
            cache = annotate or not attr

        if fset is True and (not attr or annotate or cache):
            if not attr:
                msg = (
                    f"Cannot resolve attribute for implicit `setter`. "
                    f"Either provide the `attr` name or a custom `setter`"
                )
            else:
                msg = (
                    "%s aliases cannot have an implicit `setter`. "
                    "Either provide custom `setter` or set `%s` to `False`."
                ) % (("Annotated", "annotate") if annotate else ("Cached", "cache"))
            raise ImproperlyConfigured(f"alias {name!r} on {cls.__name__!r}. {msg}")

        self.annotate, self.attr, self.cache, self.expression = annotate, attr, cache, expression
        self.fget, self.fset, self.fdel, self.name, self.defer = fget, fset, fdel, name, defer

    def get_descriptor_class(self, cls):
        return CachedAliasDescriptor if self.cache else DynamicAliasDescriptor

    def create_descriptor(self, cls):
        ret = self.get_descriptor_class(cls)(
            self.make_getter(),
            self.make_setter(),
            self.make_deleter(),
            doc=self.help_text,
        )
        return ret

    def make_getter(self):
        anno, attr, defer, fget, name = self.annotate, self.attr, self.defer, self.fget, self.name
        if fget in (True, None):
            if attr:
                fget = attrgetter(attr)
            else:

                def fget(self: _T_Model):
                    nonlocal name, defer, anno
                    if self._state.adding:
                        raise AttributeError(name)
                    qs = self._meta.base_manager.filter(pk=self.pk)
                    if defer:
                        qs = qs = qs.alias(name)
                    if anno is False:
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

    def make_setter(self):
        attr, func = self.attr, self.fset
        if func is True:
            *path, name = attr.split(".")

            def func(self: m.Model, value):
                nonlocal path, name
                obj = reduce(getattr, path, self) if path else self
                setattr(obj, name, value)

        return func or None

    def make_deleter(self):
        return self.fdel


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
                    return {n: a.get_expression(model) for n, a in aliases.items() if not a.defer}

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
                            and kwds.setdefault(n, aka.get_expression(model))
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
