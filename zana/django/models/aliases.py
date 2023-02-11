import re
import typing as t
from abc import ABC
from collections import ChainMap, abc, defaultdict
from contextlib import suppress
from enum import Enum
from functools import reduce, wraps
from itertools import chain
from logging import getLogger
from operator import attrgetter, methodcaller
from threading import Lock, RLock
from types import FunctionType, GenericAlias, MethodType, new_class

from typing_extensions import Self
from zana.common import cached_attr
from zana.types import NotSet

from django.conf import settings
from django.core import checks
from django.db import models as m
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce
from django.db.models.query_utils import FilteredRelation
from django.dispatch import receiver

_T = t.TypeVar("_T")
_KT = t.TypeVar("_KT")
_FT = t.TypeVar("_FT")
_VT = t.TypeVar("_VT")
_T_Src = t.TypeVar("_T_Src")
_T_Default = t.TypeVar("_T_Default")
_T_Model = t.TypeVar("_T_Model", bound="ImplementsAliases", covariant=True)
_T_Field = t.TypeVar("_T_Field", bound="m.Field")
_T_Expr = t.Union[
    Combinable,
    str,
    t.Callable[[], Combinable | str],
]
_T_Func = FunctionType | staticmethod | classmethod | MethodType | type

logger = getLogger(__name__)
debug = settings.DEBUG and logger.debug


def get_alias_field_names(model: type[_T_Model], default: _T_Default = None):
    if issubclass(model, ImplementsAliases):
        return model.__alias_fields__.keys()
    elif not issubclass(model, m.Model):
        raise TypeError(f"expected `Model` subclass. not `{model.__class__.__name__}`")
    return default


def get_alias_fields(model: type[_T_Model], default: _T_Default = None):
    if issubclass(model, ImplementsAliases):
        return model.__alias_fields__
    elif not issubclass(model, m.Model):
        raise TypeError(f"expected `Model` subclass. not `{model.__class__.__name__}`")
    return default


class FallbackDict(dict[_KT, _VT | _FT], t.Generic[_KT, _FT, _VT]):
    __slots__ = ("fallback",)
    fallback: t.Final[_FT]

    __dict_init = dict.__init__

    def __init__(self, fallback: _FT = None, /, *args, **kwargs):
        self.fallback = fallback
        self.__dict_init(*args, **kwargs)

    def __missing__(self, key: _KT):
        return self.fallback


class ImplementsAliasesManager(
    ABC, m.Manager[_T_Model] if t.TYPE_CHECKING else t.Generic[_T_Model]
):
    model: type[_T_Model]
    _initial_alias_fields_: t.Final[abc.Mapping[str, Combinable]] = ...
    _initial_annotated_alias_fields_: t.Final[abc.Mapping[str, m.F]] = ...


# class _AliasFieldDict:
#     def __missing__(self, key):


class ImplementsAliases(ABC, m.Model if t.TYPE_CHECKING else object):
    __alias_fields__: ChainMap[str, "AliasField"]

    @classmethod
    def setup_model(self, cls: type[_T_Model]):
        if not "__alias_fields__" in cls.__dict__:
            cls.__alias_fields__ = ChainMap(
                {},
                *(
                    m.maps[0]
                    for b in cls.__mro__
                    if isinstance(m := b.__dict__.get("__alias_fields__"), ChainMap)
                ),
            )

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
        args = self.__args__
        return self.__alias__.alias_evolve(expression=m.F("__".join(args)), path=".".join(args))

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


class ConcreteTypeRegistry(type):
    _internal_type_map_: t.Final[abc.Mapping[type[_T_Field], "type[_T_Field | AliasField]"]]
    _name_type_map_: t.Final[abc.Mapping[type[_T_Field], "type[_T_Field] | type[AliasField]"]]
    _base_: t.Final[type["AliasField"]]
    _basename_: t.Final[str]

    def __init__(self, name, bases, nspace, /, **kw) -> None:
        self._internal_type_map_, self._name_type_map_, self._lock_ = {}, {}, RLock()

    def __set_name__(self, owner: type["AliasField"], name: str):
        if not hasattr(self, "_base_"):
            self._base_ = owner

        if not hasattr(self, "_basename_"):
            self._basename_ = owner.__name__.replace("Field", "")

    def __dir__(self):
        return self._name_type_map_.keys()

    def __getattr__(self, name: str) -> t.Any:
        try:
            return self._name_type_map_[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __getitem__(self, cls: type[_T_Field]):
        with self._lock_:
            try:
                return self._internal_type_map_[cls]
            except KeyError:
                return self(cls)

    def __call__(self, cls: type[_T_Field], /, name: str = None):
        c2t: dict[type[cls], type[cls] | type["AliasField"]]
        n2t: dict[str, type[cls] | type["AliasField"]]
        base, c2t, n2t = self._base_, self._internal_type_map_, self._name_type_map_

        assert isinstance(cls, type) and issubclass(cls, m.Field)

        with self._lock_:
            assert cls not in c2t, f"type for concrete base {cls.__name__} already exists"
            name = self._new_name_(name or cls.__name__)
            n2t[name] = c2t[cls] = new_class(
                name,
                (base, cls),
                None,
                methodcaller(
                    "update",
                    {
                        "__module__": self.__module__,
                        "__qualname__": f"{self.__qualname__}.{name}",
                        "_internal_alias_type_": cls,
                    },
                ),
            )
        return n2t[name]

    def _new_name_(self, base: str):
        n2t = self._name_type_map_
        with self._lock_:
            base = f"{base.replace('Field', '')}{self._basename_}Field"
            for i in range(1000):
                name = f"{base}_{i:03}" if i else base
                if name not in n2t:
                    return name
            else:  # pragma: no cover
                raise RuntimeError(f"unable to find a unique qualname for {name[:-3]!r}")


class AliasField(m.Field, t.Generic[_T_Field, _T]):
    _POS_ARGS_ = [
        "expression",
        "getter",
        "setter",
        "deleter",
    ]

    _KWARGS_TO_ATTRS_ = {
        "expression": "alias_expression",
        "getter": "alias_fget",
        "setter": "alias_fset",
        "deleter": "alias_fdel",
        "annotate": "alias_annotate",
        "path": "alias_path",
        "cache": "alias_cache",
        "defer": "alias_defer",
        "cast": "alias_cast",
    }
    _INIT_DEFAULTS_ = FallbackDict(
        NotSet,
        expression=None,
        getter=None,
        setter=None,
        deleter=None,
        editable=False,
        default=None,
        cast=None,
    )

    name: str
    alias_expression: _T_Expr = None
    _init_args_: t.Final[set]

    verbose_name: str

    _cached_descriptor_class_ = CachedAliasDescriptor
    _dynamic_descriptor_class_ = DynamicAliasDescriptor

    alias_cast: bool
    alias_fget: abc.Callable[[_T_Model], _T] = None
    alias_fset: abc.Callable[[_T_Model, _T], t.NoReturn] = None
    alias_fdel: abc.Callable[[_T_Model], t.NoReturn] = None

    _internal_alias_type_: t.Final[type[_T_Field]] = None

    @t.final
    class types(metaclass=ConcreteTypeRegistry):
        pass

    def __class_getitem__(cls, params: tuple[type[_T_Field], ...] | type[_T_Field]):
        if not isinstance(params, (tuple, list)):
            params = (params,)

        if cls._internal_alias_type_ is None:
            if isinstance(param := params[0], type) and issubclass(param, m.Field):
                cls, params = cls.types[param], params[1:]
        return GenericAlias(cls, params)

    def __new__(cls: type[Self], *a, internal: _T_Field = None, **kw) -> _T | Self | _T_Field:
        if internal is not None and cls._internal_alias_type_ is None:
            cls = cls.types[internal if isinstance(internal, type) else internal.__class__]

        self: _T | Self | _T_Field = object.__new__(cls)
        return self

    def __init_subclass__(cls, **kw) -> None:
        cls._internal_alias_type_ = cls.__dict__.get("_internal_alias_type_")
        return super().__init_subclass__(**kw)

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
        cast: bool = None,
        internal: _T_Field = None,
        **kwds,
    ) -> None:
        ...

    def __init__(self, *args, internal: _T_Field = None, **kwds) -> None:
        self._init_args_ = set()
        args = args and kwds.update({k: v for k, v in zip(self._POS_ARGS_, args)}) or ()
        kwds, k2a = self._INIT_DEFAULTS_ | kwds, self._KWARGS_TO_ATTRS_
        local = {k: kwds.pop(k) for k in list(kwds) if k in k2a}

        if internal is not None:
            my_internal = self._internal_alias_type_
            if internal.__class__ is my_internal:
                *_, args, kwargs = internal.deconstruct()
                kwds |= kwargs
            elif internal is not my_internal:
                raise TypeError(f"expected {my_internal} but got {internal}")

        super().__init__(*args, **kwds)
        self.alias_evolve(local)

    @cached_attr
    def f(self):
        return m.F(self.name)

    @cached_attr
    def alias_annotate(self):
        return False

    @cached_attr
    def alias_cache(self):
        return not not self.alias_annotate or not (self.alias_fset or self.alias_path)

    @cached_attr
    def alias_defer(self):
        return False

    @cached_attr
    def alias_annotation(self):
        return self.get_alias_annotation()

    @cached_attr
    def alias_path(self):
        if isinstance(expr := self.alias_expression, str):
            return expr.replace("__", ".")
        elif isinstance(expr, m.F):
            return expr.name.replace("__", ".")

    def get_internal_alias_field(self, *, deconstruct: bool = None):
        if (cls := self._internal_alias_type_) is not None:
            *_, args, kwds = cls.deconstruct(self)
            if deconstruct is True:
                for k, v in self._INIT_DEFAULTS_.items():
                    if k in kwds and kwds[k] == v:
                        kwds.pop(k)
            return cls(*args, **kwds)

    def db_type(self, connection):
        return None

    def get_attname_column(self):
        return self.get_attname(), None

    def contribute_to_class(self, cls: type[_T_Model], name: str, private_only: bool = None):
        if private_only is None:
            private_only = cls._meta.proxy

        super().contribute_to_class(cls, name, private_only)

        cls = ImplementsAliases.setup_model(cls)
        cls.__alias_fields__[name] = self

        if descriptor := self.get_descriptor():
            if hasattr(descriptor, "__set_name__"):
                descriptor.__set_name__(cls, self.attname)
            setattr(cls, self.attname, descriptor)

        setattr(self.__class__, "_p_Stack", getattr(self, "_p_Stack", [None]))
        if self._p_Stack[-1] != cls._meta.label:
            self._p_Stack.append(cls._meta.label)
            debug and debug(f"\n{cls._meta.label+' :':<24}")

        debug and debug(
            f"  - {self.creation_counter}) {name:<20} {self.get_internal_type():<20} {id(self)}"
        )

    def deconstruct(self):
        k2a, ia, defaults = self._KWARGS_TO_ATTRS_, self._init_args_, self._INIT_DEFAULTS_
        name, path = t.cast(tuple[str, str], super().deconstruct()[:2])

        args, kwargs = [], {k: v for k in ia for v in (getattr(self, k2a[k]),) if v != defaults[k]}
        if self._internal_alias_type_:
            kwargs["internal"] = self.get_internal_alias_field(deconstruct=True)

        if path.startswith(f"{__name__}.AliasField.types."):
            path = f"{__name__}.AliasField"
        return name, path, args, kwargs

    def check(self, **kwargs):
        return super().check(**kwargs) + [
            *self._check_alias_expression(),
            *self._check_alias_setter(),
        ]

    def _check_alias_setter(self):
        path, annotate, cache, errors = self.alias_path, self.alias_annotate, self.alias_cache, []
        if self.alias_fset is True and (not path or annotate or cache):
            label = f"{self.__class__.__qualname__}"
            if annotate:
                errors += [
                    checks.Error(
                        f"Annotated {label} cannot have an implicit setter=True",
                        hint=(
                            "Set annotate=False, use a custom `setter` function, "
                            "or remove setter=True argument on the field."
                        ),
                        obj=self,
                        id="AliasField.E003",
                    )
                ]
            elif cache:
                errors += [
                    checks.Error(
                        f"Cached {label} cannot have an implicit `setter=True. ",
                        hint=(
                            "Set cache=False, use a custom `setter` function, "
                            "or remove setter=True argument on the field."
                        ),
                        obj=self,
                        id="AliasField.E004",
                    )
                ]
            else:
                errors += [
                    checks.Error(
                        f"{label}s with setter=True must have a `path`.",
                        hint=(
                            "Explicitly set `attr`, use a custom `setter` function, "
                            "or remove setter=True argument on the field."
                        ),
                        obj=self,
                        id="AliasField.E005",
                    )
                ]

        return errors

    def _check_alias_expression(self):
        cast, internal, errors = self.alias_cast, self._internal_alias_type_, []
        label = self.__class__.__name__
        if cast and internal is None:
            errors += [
                checks.Error(
                    f"{label} with cast=True must have an internal type",
                    hint=(
                        f"Set internal=Field() argument, "
                        f"remove cast=True argument, or use {label}[FieldClass]() "
                        f"to create field with `FieldClass` as the internal type."
                    ),
                    obj=self,
                    id="AliasField.E002",
                )
            ]
        return errors

    def get_descriptor(self):
        if (cls := self.get_descriptor_class()) is not None:
            return cls(self)

    def get_descriptor_class(self):
        return getattr(self, f"_{'cached' if self.alias_cache else 'dynamic'}_descriptor_class_")

    def alias_evolve(self, arg=(), **kwds):
        if isinstance(arg, abc.Mapping):
            arg = arg.items()
        k2a, ia = self._KWARGS_TO_ATTRS_, self._init_args_
        for kv in ((kv for kv in arg if kv[0] not in kwds), kwds.items()) if kwds else (arg,):
            for k, v in kv:
                setattr(self, k2a[k], v)
                ia.add(k)
        return self

    def at(self, src: _T_Src) -> _T_Src:
        return ExpressionBuilder[_T](self, src)

    def annotation(self, expression: _T_Expr):
        self.alias_evolve(expression=expression)
        return expression

    def getter(self, fget: t.Callable[[t.Any], _T]):
        self.alias_evolve(getter=fget)
        return fget

    def setter(self, fset: t.Callable[[t.Any], _T]):
        self.alias_evolve(setter=fset)
        return fset

    def deleter(self, fdel: t.Callable):
        self.alias_evolve(deleter=fdel)
        return fdel

    def get_alias_expression(self) -> abc.Callable[[], m.expressions.Combinable]:
        expr = self.alias_expression
        if isinstance(expr, _T_Func):
            expr = expr()
        if isinstance(expr, str):
            expr = m.F(expr)

        return expr

    def get_alias_annotation(self):
        cast, expr = self.alias_cast, self.get_alias_expression()
        if not cast:
            expr = m.ExpressionWrapper(expr, self)
        if self.has_default() and (default := self.get_default()) is not None:
            expr = Coalesce(expr, m.Value(default, self))

        if internal := cast and self.get_internal_alias_field():
            expr = m.functions.Cast(expr, internal)

        return expr

    def get_getter(self):
        fget = self.alias_fget
        if fget in (True, None):
            if (path := self.alias_path) is not None:
                fget = attrgetter(path)
            else:
                annotate, defer, name = self.alias_annotate, self.alias_defer, self.name

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
        attr, func = self.alias_path, self.alias_fset
        if func is True and attr:
            *path, name = attr.split(".")

            def func(self: m.Model, value):
                nonlocal path, name
                obj = reduce(getattr, path, self) if path else self
                setattr(obj, name, value)

        return func or None

    def get_deleter(self):
        return self.alias_fdel


@receiver(m.signals.class_prepared, weak=False)
def __on_class_prepared(sender: type[_T_Model], **kwds):
    if issubclass(sender, ImplementsAliases):
        debug and debug(f"-> {sender._meta.label:<18} prepared ...")


class _Patcher:
    """Monkey patch Manager, Queryset and Model classes"""

    @staticmethod
    def model(cls: type[_T_Model]):
        mro = (b.refresh_from_db for b in cls.__mro__ if "refresh_from_db" in b.__dict__)
        if not all(getattr(b, "_loads_alias_fields_", None) for b in mro):
            orig_refresh_from_db = cls.refresh_from_db

            @wraps(orig_refresh_from_db)
            def refresh_from_db(self: _T_Model, using=None, fields=None):
                nonlocal orig_refresh_from_db
                cls = self.__class__
                if a_dict := get_alias_fields(cls):
                    if fields_ := fields and set(fields):
                        fields = fields_ - a_dict.keys()
                        aliases = (n for n in fields_ & a_dict.keys() if a_dict[n].alias_cache)
                    else:
                        aliases = (n for n, a in a_dict.items() if a.alias_cache)

                    for aka in aliases:
                        with suppress(AttributeError):
                            delattr(self, aka)

                    if fields_ and not fields:
                        return

                orig_refresh_from_db(self, using, fields)

            refresh_from_db._loads_alias_fields_ = True
            cls.refresh_from_db = refresh_from_db

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
                    return {n: a.alias_annotation for n, a in aliases.items() if not a.alias_defer}

                @cached_attr
                def _initial_annotated_alias_fields_(self: m.Manager[_T_Model]):
                    model = self.model
                    aliases = get_alias_fields(model, {})
                    return {
                        n: a.f
                        for n, a in aliases.items()
                        if not a.alias_defer and a.alias_annotate
                    }

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
                            and kwds.setdefault(n, aka.alias_annotation)
                            and (
                                aka.alias_annotate
                                and annotate.setdefault(n, m.F(n) if a is n else a),
                            )
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
