import copy
import re
import typing as t
from abc import ABC
from collections import abc
from contextlib import suppress
from functools import reduce, wraps
from itertools import chain, repeat
from logging import getLogger
from operator import methodcaller, or_, setitem
from threading import RLock
from types import FunctionType, GenericAlias, MethodType, NoneType, new_class
from weakref import WeakKeyDictionary

from typing_extensions import Self
from zana.canvas import maybe_compose
from zana.types import NotSet
from zana.types.collections import DefaultDict, FrozenDict
from zana.util import cached_attr
from zana.util.operator import pipeline

from django.conf import settings
from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.db import models as m
from django.db.models.functions import Coalesce
from django.db.models.query_utils import FilteredRelation
from django.dispatch import receiver

try:
    from psycopg.types.json import Jsonb
except ImportError:
    Jsonb = None

from . import PseudoField

if t.TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper


_T = t.TypeVar("_T")
_KT = t.TypeVar("_KT")
_FT = t.TypeVar("_FT")
_VT = t.TypeVar("_VT")
_T_Src = t.TypeVar("_T_Src")
_T_Default = t.TypeVar("_T_Default")
_T_Model = t.TypeVar("_T_Model", bound="ImplementsAliases", covariant=True)
_T_Field = t.TypeVar("_T_Field", bound=m.Field, covariant=True)
_T_Expr = t.Union[
    m.expressions.Combinable,
    str,
    t.Callable[[], m.expressions.Combinable | str],
]
_T_Func = FunctionType | staticmethod | classmethod | MethodType | type

logger = getLogger(__name__)
debug = settings.DEBUG and logger.debug


def get_alias_fields(model: type[_T_Model], default: _T_Default = None):
    fields = getattr(model, "_alias_fields_", None)
    if fields and isinstance(fields, ModelAliasFields):
        return fields
    return default


class ModelAliasFields(abc.Mapping[str, "AliasField"], t.Generic[_T_Model]):
    __slots__ = (
        "model",
        "_ready",
        "_populated",
        "_lock",
        "fields",
        "local",
        "eager",
        "deferred",
        "selected",
        "cached",
        "dynamic",
    )
    _static_attrs_ = "model", "_populated", "_ready", "_lock"

    _reset_attrs_ = tuple({*__slots__} - {*_static_attrs_})

    model: t.Final[type[_T_Model]]

    local: t.Final[abc.Mapping[str, "AliasField"]]
    fields: t.Final[abc.Mapping[str, "AliasField"]]
    eager: t.Final[abc.Mapping[str, "AliasField"]]
    deferred: t.Final[abc.Mapping[str, "AliasField"]]
    selected: t.Final[abc.Mapping[str, "AliasField"]]
    cached: t.Final[abc.Mapping[str, "AliasField"]]

    _populated: t.Final[bool]
    _ready: t.Final[bool]
    _lock: t.Final[RLock]

    def __init__(self, model: type[_T_Model]) -> None:
        self.model, self._lock, self._populated, self._ready = (
            model,
            RLock(),
            False,
            False,
        )

    def prepare(self):
        with self._lock:
            if not self._ready:
                self._prepare()
                self.clear()
                self._ready = True

    def _prepare(self):
        cls = self.model
        if cls._meta.proxy:
            concrete = cls._meta.concrete_model
            for b in cls.__mro__[1:][::-1]:
                own = self.fields
                if issubclass(b, ImplementsAliases):
                    if b._meta.proxy or (
                        b._meta.abstract and not issubclass(concrete, b)
                    ):
                        for n, af in b._alias_fields_.local.items():
                            if n not in own:
                                cls._meta.add_field(copy.deepcopy(af), True)
                            elif own[n] != af:
                                raise ImproperlyConfigured(
                                    f"cannot override AliasField `{af!s}` in `{cls._meta.label}`"
                                )

    def populate(self):
        with self._lock:
            if not self._populated:
                self._populate()
                self._populated = True

    def _populate(self):
        eager, defer, select, cache, dynamic, local, fields = map(dict, repeat((), 7))
        lf = self.model._meta.local_fields
        for field in sorted(self.model._meta.fields):
            if isinstance(field, AliasField):
                name, maps = field.name, [fields]
                maps.append(cache if field.cache else dynamic)
                maps.append(defer if field.defer else eager)
                field.model is self.model and maps.append(local)
                field.select and maps.append(select)
                [map.setdefault(name, field) for map in maps]

        self.fields, self.eager, self.deferred, self.selected = (
            fields,
            eager,
            defer,
            select,
        )
        self.local, self.cached, self.dynamic = local, cache, dynamic

    def clear(self):
        with self._lock:
            if self._populated:
                for at in self._reset_attrs_:
                    if hasattr(self, at):
                        delattr(self, at)
            self._populated = False

    def __bool__(self):
        return True

    def __len__(self) -> int:
        self._populated or self.populate()
        return len(self.fields)

    def __iter__(self):
        self._populated or self.populate()
        return iter(self.fields)

    def __contains__(self, key: str):
        self._populated or self.populate()
        return key in self.fields

    def __getitem__(self, key: str):
        self._populated or self.populate()
        return self.fields[key]

    def __getattr__(self, attr: str):
        if attr in self._static_attrs_ or self._populated:  # pragma: no cover
            raise AttributeError(attr)

        self.populate()
        return getattr(self, attr)

    def __hash__(self) -> int:
        return hash(self.model)

    def __eq__(self, other: Self):
        return other.__class__ is self.__class__ and other.model == self.model

    def __ne__(self, other: Self):
        return not other == self

    def __repr__(self) -> str:
        self._populated or self.populate()
        attrs = [
            f"{at} = {fn(getattr(self, at))!r}"
            for at, fn in zip(
                (
                    "fields",
                    "local",
                    "eager",
                    "deferred",
                    "selected",
                    "cached",
                    "dynamic",
                ),
                repeat(pipeline([methodcaller("values"), list])),
            )
        ]
        attr_str = ", ".join(attrs)
        return f"{self.__class__.__name__}[{self.model._meta.label}]({attr_str})"

    def keys(self):
        self._populated or self.populate()
        return self.fields.keys()

    def values(self):
        self._populated or self.populate()
        return self.fields.values()

    def items(self):
        self._populated or self.populate()
        return self.fields.items()


class ImplementsAliasesManager(
    ABC, m.Manager[_T_Model] if t.TYPE_CHECKING else t.Generic[_T_Model]
):
    model: type[_T_Model]
    _initial_alias_fields_: t.Final[abc.Mapping[str, m.expressions.Combinable]] = ...
    _initial_annotated_alias_fields_: t.Final[abc.Mapping[str, m.F]] = ...


class ImplementsAliases(ABC, m.Model if t.TYPE_CHECKING else object):
    _alias_fields_: t.Final[ModelAliasFields[Self]] = None

    @classmethod
    def setup(self, cls):
        if not "_alias_fields_" in cls.__dict__:
            cls._alias_fields_ = ModelAliasFields(cls)

        self.register(cls)
        cls._alias_fields_.clear()
        return cls


class BaseAliasDescriptor:
    field: "AliasField" = None

    def __init__(self, field: "AliasField") -> None:
        self.field = field
        super().__init__(field.get_getter(), field.get_setter(), field.get_deleter())


class DynamicAliasDescriptor(BaseAliasDescriptor, property):
    pass


class CachedAliasDescriptor(BaseAliasDescriptor, cached_attr[_T]):
    pass


class ConcreteTypeRegistryType(type):
    _internal_type_map_: abc.Mapping[type[_T_Field], "type[_T_Field | AliasField]"]
    _name_type_map_: abc.Mapping[type[_T_Field], "type[_T_Field] | type[AliasField]"]
    _json_compat_types_: abc.Mapping[
        type[_T_Field], "type[_T_Field] | type[m.JSONField]"
    ]
    _base_: t.Final[type["AliasField"]]
    _basename_: t.Final[str]
    _lock_: RLock
    _concrete_init_defaults_: abc.Mapping[type[_T_Field], abc.Mapping[str, t.Any]]

    def __new__(self, name, bases, nspace: dict, /, **kw) -> None:
        cls = super().__new__(self, name, bases, nspace, **kw)
        cls._lock_ = RLock()
        cls._internal_type_map_, cls._name_type_map_, cls._json_compat_types_ = (
            {},
            {},
            {},
        )
        return cls

    def __set_name__(self, owner: type["AliasField"], name: str):
        if not hasattr(self, "_base_"):
            self._base_ = owner

        if not hasattr(self, "_basename_"):
            self._basename_ = owner.__name__.replace("Field", "")

    def __dir__(self):  # pragma: no cover
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

    def __call__(
        self: type["ConcreteTypeRegistry"], cls: type[_T_Field], /, name: str = None
    ):
        c2t: dict[type[cls], type[cls] | type["AliasField"]]
        n2t: dict[str, type[cls] | type["AliasField"]]

        assert isinstance(cls, type) and issubclass(cls, m.Field)
        c2t, n2t = self._internal_type_map_, self._name_type_map_

        with self._lock_:
            assert (
                c not in c2t for c in (cls, cls)
            ), f"type for concrete base {cls.__name__} already exists"
            name = self._new_name_(name or cls.__name__)
            module, qualname = self.__module__, f"{self.__qualname__}.{name}"

            n2t[name] = c2t[cls] = c2t[cls] = new_class(
                name,
                (self._base_, cls),
                None,
                methodcaller(
                    "update",
                    self._new_class_dict_(
                        cls,
                        {
                            "__module__": module,
                            "__qualname__": qualname,
                            "_internal_field_type_": cls,
                        },
                    ),
                ),
            )
        return n2t[name]

    def json_compat_type(
        self, base: type[_T_Field], json_base: type[m.JSONField] = m.JSONField
    ) -> type[_T_Field] | type[m.JSONField]:
        json_base = json_base or m.JSONField
        base = base or json_base
        key = json_base, base
        assert issubclass(json_base, m.JSONField)

        if klass := self._json_compat_types_.get(key):
            return klass

        with self._lock_:
            if klass := self._json_compat_types_.get(key):  # pragma: no cover
                return klass

            if issubclass(base, json_base):
                return self._json_compat_types_.setdefault(key, base)

            dump_vendors = {"postgresql", "mysql"}
            non_dump_types = NoneType | _JSONString
            if Jsonb:
                non_dump_types |= Jsonb

            class Base(base):
                pass

            class JSONCompatBase(json_base, Base):
                _has_base_from_db_value_ = hasattr(base, "from_db_value")
                __module__ = base.__module__
                __name__ = base.__name__
                __qualname__ = base.__qualname__

                def get_internal_type(self):
                    return super(Base, self).get_internal_type()

                def get_prep_value(self, value, *, dump=None, prepared=True):
                    values = [value, None, None]
                    vcls = type(value)
                    if not (dump and prepared):
                        value = super(Base, self).get_prep_value(value)
                        values[1] = value
                    if dump and value is not None:
                        value = super().get_prep_value(value)
                        if isinstance(value, str):
                            value = _JSONString(value)
                        values[2] = value
                    return value

                def should_json_dump(self, value, conn: "BaseDatabaseWrapper"):
                    return (
                        not isinstance(value, non_dump_types)
                        and conn.vendor in dump_vendors
                    )

                def get_db_prep_value(
                    self, value, connection: "BaseDatabaseWrapper", prepared=False
                ):
                    values = [value, None, None]
                    value = super().get_db_prep_value(value, connection, prepared)
                    values[1] = value
                    if self.should_json_dump(value, connection):
                        value = self.get_prep_value(value, dump=True)
                        values[2] = value
                    return value

                def from_db_value(self, value, expr, connection: "BaseDatabaseWrapper"):
                    nonlocal base, json_base
                    if value is not None:
                        if isinstance(value, (str, bytes, bytearray)):
                            if connection.vendor in dump_vendors:
                                value = json_base.from_db_value(
                                    self, value, expr, connection
                                )
                        if self._has_base_from_db_value_:
                            value = base.from_db_value(self, value, expr, connection)
                    return value

                def formfield(self, **kwargs):
                    return super(Base, self).formfield(**kwargs)

            klass = self._json_compat_types_.setdefault(key, JSONCompatBase)
            return klass

    def _new_name_(self, base: str):
        n2t = self._name_type_map_.keys() | self.__dict__.keys()
        with self._lock_:
            base = f"{base.replace('Field', '')}{self._basename_}Field"
            for i in range(1000):
                name = f"{base}_{i:03}" if i else base
                if name not in n2t:
                    return name
            else:  # pragma: no cover
                raise RuntimeError(
                    f"unable to find a unique qualname for {name[:-3]!r}"
                )

    def _new_class_dict_(self: type[Self], cls: type[_T_Field], nspace: dict):
        by_type, defaults = self._concrete_init_defaults_, self._base_._INIT_DEFAULTS_
        return nspace | {
            "_INIT_DEFAULTS_": reduce(
                or_,
                [*(by_type[b] for b in cls.__mro__[::-1] if b in by_type), defaults],
            )
        }


class _JSONString(str):
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__.strip('_')}({self!s})"

    def __reduce__(self):  # pragma: no cover
        return self.__class__, (str(self),)


class ConcreteTypeRegistry(metaclass=ConcreteTypeRegistryType):
    _concrete_init_defaults_ = {
        m.CharField: {
            "max_length": 255,
        },
        m.DecimalField: {
            "max_digits": 36,
            "decimal_places": 9,
        },
    }


def _weak_cached(func=None, *, key=None, by_params: bool = None):
    def decorator(fn: _T) -> _T:
        name, keyfn = fn.__name__, key
        if isinstance(key, str):  # pragma: no cover
            name, keyfn = key, None
        if keyfn is None:
            if by_params:
                keyfn = lambda s, a, kw: (name, a, FrozenDict(kw))
            else:
                keyfn = lambda s, a, kw: name

        @wraps(fn)
        def wrapper(self: "AliasField", *args, **kwds):
            cache, ck = self._weak_cache_, keyfn(self, args, kwds)
            if ck not in cache:
                with self._lock_:
                    if ck not in cache:
                        return cache.setdefault(ck, fn(self, *args, **kwds))
            return cache[ck]

        return wrapper

    return decorator if func is None else decorator(func)


class AliasField(PseudoField, t.Generic[_T_Field, _T]):
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
        "select": "select",
        "coalesce": "_coalesce",
        "cache": "cache",
        "defer": "defer",
        "cast": "cast",
        "wrap": "_wrap",
        "json": "json",
        "json_options": "_json_options",
    }
    _INIT_DEFAULTS_ = DefaultDict(
        (),
        NotSet,
        expression=None,
        getter=None,
        setter=None,
        deleter=None,
        defer=False,
        cast=None,
        default=None,
        json=None,
        select=False,
        wrap=None,
        coalesce=False,
        json_options=lambda: dict(encoder=None, decoder=None),
    )
    _NULLABLE_INIT_DEFAULTS_ = {"select", "coalesce", "defer", "json_options"}

    name: str
    expression: _T_Expr = None
    _init_args_: t.Final[set]
    json: bool

    verbose_name: str
    # _source: str | Composable
    _coalesce: _T_Expr | bool | None
    _cached_descriptor_class_ = CachedAliasDescriptor
    _dynamic_descriptor_class_ = DynamicAliasDescriptor

    cast: bool
    fget: abc.Callable[[_T_Model], _T] = None
    fset: abc.Callable[[_T_Model, _T], t.NoReturn] = None
    fdel: abc.Callable[[_T_Model], t.NoReturn] = None
    _internal_field_type_: t.Final[type[_T_Field]] = None
    _internal_json_field_type_: t.Final[type[_T_Field | m.JSONField]] = None
    _weak_cache_map_: t.Final[dict[Self, dict[str, t.Any]]] = WeakKeyDictionary()
    _lock_: t.Final = RLock()

    @t.final
    class types(ConcreteTypeRegistry):
        pass

    def __class_getitem__(cls, params: tuple[type[_T_Field], ...] | type[_T_Field]):
        if not isinstance(params, (tuple, list)):
            params = (params,)

        if cls._internal_field_type_ is None:
            if isinstance(param := params[0], type) and issubclass(param, m.Field):
                cls, params = cls.types[param], params[1:]
        return GenericAlias(cls, params)

    def __new__(
        cls: type[Self], *a, internal: _T_Field = None, **kw
    ) -> _T | Self | _T_Field:
        if internal is not None and cls._internal_field_type_ is None:
            cls = cls.types[
                internal if isinstance(internal, type) else internal.__class__
            ]

        self: _T | Self | _T_Field = object.__new__(cls)
        return self

    def __init_subclass__(cls, **kw) -> None:
        cls._internal_field_type_ = cls.__dict__.get("_internal_field_type_")
        cls._lock_ = cls.__dict__.get("_lock_", RLock())
        return super().__init_subclass__(**kw)

    @t.overload
    def __init__(
        self,
        expression: _T_Expr = None,
        getter: t.Union[abc.Callable[[_T_Model], _T], bool] = None,
        setter: abc.Callable[[_T_Model, _T], t.NoReturn] = None,
        deleter: abc.Callable[[_T_Model], t.NoReturn] = None,
        *,
        select: bool = None,
        cache: bool = None,
        defer: bool = None,
        cast: bool = None,
        wrap: bool = None,
        coalesce: _T_Expr | bool | None,
        json: bool = False,
        json_options: abc.Mapping[str, t.Any] = None,
        internal: _T_Field = None,
        **kwds,
    ) -> None:
        ...

    def __init__(self, *args, internal: _T_Field = None, **kwds) -> None:
        self._init_args_ = set()
        args = args and kwds.update({k: v for k, v in zip(self._POS_ARGS_, args)}) or ()
        kwds, k2a = self._init_defaults_ | kwds, self._KWARGS_TO_ATTRS_
        local = {k: kwds.pop(k) for k in list(kwds) if k in k2a}

        if internal is not None:
            my_internal = self._internal_field_type_
            if internal.__class__ is my_internal:
                *_, args, kwargs = internal.deconstruct()
                kwds |= kwargs
            elif internal is not my_internal:
                raise TypeError(f"expected {my_internal} but got {internal}")

        super().__init__(*args, **kwds)
        self.alias_evolve(local)

    @property
    def _weak_cache_(self):
        if (cache := self._weak_cache_map_.get(self)) is None:
            cache = self._weak_cache_map_.setdefault(self, {})
        return cache

    @cached_attr
    def _init_defaults_(self):
        return self._INIT_DEFAULTS_ | {
            k: v() if callable(v) else v for k, v in self._INIT_DEFAULTS_.items()
        }

    @cached_attr
    def f(self):
        return m.F(self.name)

    @cached_attr
    def coalesce(self):
        if (val := self._coalesce) is True:
            default, val = self.get_default(), None
            if default is not None:
                val = m.Value(default, self.get_internal_field())
        return val or None

    @cached_attr
    def cache(self):
        return not not self.select or not self.fset

    @property
    def json_field_options(self):
        return {"encoder": None, "decoder": None} | (self._json_options or {})

    @property
    def wrap(self) -> bool:
        cast, wrap = self.cast, self._wrap
        if wrap and cast:
            raise TypeError(
                f"{self} arguments `wrap=True` and `cast=True` are mutually exclusive."
            )
        elif wrap is None:
            wrap = not (cast or self.is_json)
        return not not wrap

    @property
    @_weak_cached
    def is_json(self):
        if self.json is not None:
            return self.json

        for cls in self.get_concrete_field_path()[0][::-1]:
            if isinstance(cls, m.JSONField) or (
                isinstance(cls, AliasField) and cls.is_json
            ):
                return True

    def alias_evolve(self, arg=(), **kwds):
        if isinstance(arg, abc.Mapping):
            arg = arg.items()
        k2a, ia = self._KWARGS_TO_ATTRS_, self._init_args_
        for kv in (
            ((kv for kv in arg if kv[0] not in kwds), kwds.items()) if kwds else (arg,)
        ):
            for k, v in kv:
                setattr(self, k2a[k], maybe_compose(v)), ia.add(k)
        return self

    if t.TYPE_CHECKING:
        alias_evolve: type[Self]

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

    def has_expression(self):
        return self.expression is not None

    @_weak_cached
    def get_expression(self) -> m.expressions.Combinable:
        expr = self.expression
        if isinstance(expr, _T_Func):
            expr = expr()
        if isinstance(expr, str):
            expr = m.F(expr)

        return expr

    @_weak_cached
    def get_annotation(self):
        expr, internal = self.get_expression(), self.get_internal_field()
        if expr is not None:
            cast, coalesce, wrap = self.cast, self.coalesce, self.wrap
            if wrap and internal:
                expr = m.ExpressionWrapper(expr, internal)
            if coalesce is not None:
                expr = Coalesce(expr, coalesce)
            if cast and internal:
                expr = m.functions.Cast(expr, internal)
        return expr

    @_weak_cached
    def get_internal_json_field(self) -> m.JSONField:
        if not self.is_json:
            return
        internal, (path, part) = (
            self._internal_field_type_,
            self.get_concrete_field_path(),
        )
        base = m.JSONField
        for field in path[::-1]:
            f_cls = field.__class__
            if issubclass(f_cls, base):
                base = f_cls
                break

        args, kwds = (), {}
        if not (internal or part) and path and not isinstance(path[-1], base):
            if isinstance(path[-1], AliasField):
                if field := path[-1].get_internal_field(json=False):
                    internal = field.__class__
                    *_, args, kwds = field.deconstruct()
            else:
                internal = path[-1].__class__
                *_, args, kwds = path[-1].deconstruct()
        elif internal:
            *_, args, kwds = internal.deconstruct(self)

        cls = self.__class__.types.json_compat_type(internal, base)
        kwds |= self.json_field_options
        return cls(*args, **kwds)

    @_weak_cached(by_params=True)
    def get_internal_field(self, *, json: bool = None) -> m.Field:
        if json is not False and self.is_json:
            return self.get_internal_json_field()

        cls, (path, part) = self._internal_field_type_, self.get_concrete_field_path()
        args, kwds = (), {}
        if not (cls or part) and path:
            if isinstance(path[-1], AliasField):
                if field := path[-1].get_internal_field(json=False):
                    cls = field.__class__
                    *_, args, kwds = field.deconstruct()
            else:
                cls = path[-1].__class__
                *_, args, kwds = path[-1].deconstruct()
        elif cls:
            *_, args, kwds = cls.deconstruct(self)

        if cls is not None:
            return cls(*args, **kwds)

    def get_deconstructing_internal_field(self):
        if (cls := self._internal_field_type_) is not None:
            *_, args, kwds = cls.deconstruct(self)
            nulls = self._NULLABLE_INIT_DEFAULTS_
            for k, v in self._init_defaults_.items():
                if k in kwds and (kwds[k] == v or (k in nulls and kwds[k] is None)):
                    kwds.pop(k)
            return cls(*args, **kwds)

    def get_concrete_field_path(self) -> tuple[tuple[_T_Field, ...], str | None]:
        expr = self.get_expression()
        if not (hasattr(self, "model") and isinstance(expr, m.F)):
            return (), None

        model, path, field, (seg, _, rem) = (
            self.model,
            [],
            None,
            expr.name.partition("__"),
        )
        while seg:
            try:
                field = model._meta.get_field(seg)
            except Exception:
                rem = f"{seg}__{rem}" if rem else seg
                break
            else:
                path.append(field)
                if isinstance(field, AliasField):
                    a_path, a_rem = field.get_concrete_field_path()
                    path.extend(a_path)
                    field = path[-1]
                    if not field.is_relation:
                        if a_rem:
                            rem = f"{a_rem}__{rem}" if rem else a_rem
                        break
                elif not field.is_relation:
                    break
                model = field.related_model
                seg, _, rem = rem.partition("__")

        return tuple(path), rem or None

    def contribute_to_class(
        self, cls: type[_T_Model], name: str, private_only: bool = None
    ):
        if private_only is None:
            private_only = cls._meta.proxy

        super().contribute_to_class(cls, name, private_only=private_only)

        cls = ImplementsAliases.setup(cls)

        if descriptor := self.get_descriptor():
            if hasattr(descriptor, "__set_name__"):
                descriptor.__set_name__(cls, self.attname)
            setattr(cls, self.attname, descriptor)

    def deconstruct(self):
        k2a, ia, defaults = (
            self._KWARGS_TO_ATTRS_,
            self._init_args_,
            self._init_defaults_,
        )
        (name, path), cls = (
            t.cast(tuple[str, str], super().deconstruct()[:2]),
            self.__class__,
        )

        nulls = self._NULLABLE_INIT_DEFAULTS_
        args, kwargs = [], {
            k: v
            for k in ia
            if ((v := getattr(self, k2a[k])) is None and k in nulls) or v != defaults[k]
        }
        if self._internal_field_type_:
            kwargs["internal"] = self.get_deconstructing_internal_field()

        base, prefix = (
            cls.types._base_,
            __name__[: __name__.index(".models.fields.") + 8],
        )
        path = path.replace(f"{__name__}.", prefix, 1)
        path = re.sub(f"\.{base.__name__}\.types\..+", f".{base.__name__}", path)
        return name, path, args, kwargs

    def check(self, **kwargs):
        return super().check(**kwargs) + [
            *self._check_alias_expression(),
            *self._check_access_mutators(),
        ]

    def _check_access_mutators(self) -> list[checks.Error]:
        errors, k2a = [], self._KWARGS_TO_ATTRS_

        tp, gt = abc.Callable | None, abc.Callable | bool | None
        for i, arg in enumerate(("getter", "setter", "deleter"), 2):
            val, tt = getattr(self, k2a[arg]), gt if arg == "getter" else tp
            if not isinstance(val, tt):
                errors += [
                    checks.Error(
                        f"{arg} argument cannot be of type {val.__class__.__name__}.",
                        hint=(f"Ensure {arg} argument is of type {tt}."),
                        obj=self,
                        id=f"AliasField.E{i:03}",
                    )
                ]

        return errors

    def _check_alias_expression(self):
        cast, internal, errors = self.cast, self.get_internal_field(), []
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
                    id="AliasField.E001",
                )
            ]
        return errors

    def get_descriptor(self):
        if (cls := self.get_descriptor_class()) is not None:
            return cls(self)

    def get_descriptor_class(self):
        return getattr(
            self, f"_{'cached' if self.cache else 'dynamic'}_descriptor_class_"
        )

    def get_getter(self):
        fget = self.fget
        if fget in (True, None):
            select, defer, name = self.select, self.defer, self.name

            def fget(self: _T_Model):
                nonlocal name, defer, select
                if self._state.adding:
                    raise AttributeError(name)
                qs = self._meta.base_manager.filter(pk=self.pk)
                if defer:
                    qs = qs.alias(name)
                if not select:
                    qs = qs.annotate(name)
                return qs.values_list(name, flat=True).get()

        if fget and self.has_default():
            fget_, field = fget, self

            @wraps(fget_)
            def fget(self):
                nonlocal field, fget_
                try:
                    val = fget_(self)
                except (AttributeError, LookupError):
                    val = None
                return field.get_default() if val is None else val

        return fget or None

    def get_setter(self):
        return self.fset

    def get_deleter(self):
        return self.fdel


@receiver(m.signals.class_prepared, weak=False)
def __on_class_prepared(sender: type[_T_Model], **kwds):
    if issubclass(sender, ImplementsAliases):
        ImplementsAliases.setup(sender)._alias_fields_.prepare()


class _Patcher:
    """Monkey patch Manager, Queryset and Model classes"""

    @staticmethod
    def model(cls: type[_T_Model]):
        mro = (
            b.refresh_from_db for b in cls.__mro__ if "refresh_from_db" in b.__dict__
        )
        if not all(getattr(b, "_zana_checks_alias_fields_", None) for b in mro):
            orig_refresh_from_db = cls.refresh_from_db

            @wraps(orig_refresh_from_db)
            def refresh_from_db(self: _T_Model, using=None, fields=None):
                nonlocal orig_refresh_from_db
                cls = self.__class__
                if a_conf := get_alias_fields(cls):
                    if fields_ := fields and set(fields):
                        fields = fields_ - a_conf.keys()
                        aliases = fields_ & a_conf.cached.keys()
                    else:
                        aliases = a_conf.cached

                    for aka in aliases:
                        with suppress(AttributeError):
                            delattr(self, aka)

                    if fields_ and not fields:
                        return

                orig_refresh_from_db(self, using, fields)

            refresh_from_db._zana_checks_alias_fields_ = True
            cls.refresh_from_db = refresh_from_db

    @staticmethod
    def manager(cls: type["ImplementsAliasesManager[_T_Model]"]):
        if not getattr(cls.get_queryset, "_zana_checks_alias_fields_", False):
            base_get_queryset = cls.get_queryset

            @wraps(base_get_queryset)
            def get_queryset(self: cls, *args, **kwargs):
                qs = base_get_queryset(self, *args, **kwargs)
                if (aliases := self._initial_alias_fields_) is None:
                    return qs

                qs = qs.alias(**aliases)
                if annotations := self._initial_annotated_alias_fields_:
                    qs = qs.annotate(**annotations)

                return qs

            get_queryset._zana_checks_alias_fields_ = True
            cls.get_queryset = get_queryset

            if not getattr(cls, "_initial_alias_fields_", None):

                @cached_attr
                def _initial_alias_fields_(self: m.Manager[_T_Model]):
                    if aliases := get_alias_fields(self.model):
                        return {n: a.get_annotation() for n, a in aliases.eager.items()}

                @cached_attr
                def _initial_annotated_alias_fields_(self: m.Manager[_T_Model]):
                    if aliases := get_alias_fields(self.model):
                        return {
                            n: a.f for n, a in aliases.selected.items() if not a.defer
                        }

                _initial_alias_fields_.__set_name__(cls, "_initial_alias_fields_")
                _initial_annotated_alias_fields_.__set_name__(
                    cls, "_initial_annotated_alias_fields_"
                )

                cls._initial_alias_fields_ = _initial_alias_fields_
                cls._initial_annotated_alias_fields_ = _initial_annotated_alias_fields_

    @staticmethod
    def queryset(cls: type[m.QuerySet[_T_Model]]):
        if not getattr(cls.annotate, "_zana_checks_alias_fields_", None):
            orig_annotate = cls.annotate

            @wraps(orig_annotate)
            def annotate(self: cls[_T_Model], *args, **kwds):
                nonlocal orig_annotate
                if aliases := args and get_alias_fields(self.model):
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
                            and kwds.setdefault(n, (an := m.F(n) if a is n else a))
                            is an
                        )
                    ]
                return orig_annotate(self, *args, **kwds)

            annotate._zana_checks_alias_fields_ = True
            cls.annotate = annotate

        if not getattr(cls.alias, "_zana_checks_alias_fields_", None):
            orig_alias = cls.alias

            @wraps(orig_alias)
            def alias(self: cls[_T_Model], *args, **kwds):
                nonlocal orig_alias
                if aliases := args and get_alias_fields(self.model):
                    aka: AliasField
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
                            and (aka := aliases.get(n))
                            and kwds.setdefault(n, (an := aka.get_annotation())) is an
                            and (aka.select and setitem(annotate, n, aka.f) or True)
                        )
                    ]
                    if annotate:
                        return orig_alias(self, *args, **kwds).annotate(**annotate)

                return orig_alias(self, *args, **kwds)

            alias._zana_checks_alias_fields_ = True
            cls.alias = alias

        if not getattr(cls._annotate, "_zana_checks_alias_fields_", None):
            orig__annotate = cls._annotate

            @wraps(orig__annotate)
            def _annotate(self: cls[_T_Model], args, kwargs, select=True):
                model = self.model
                aliases = get_alias_fields(model, ())
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
                                "default name for another annotation."
                                % arg.default_alias
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
                        names -= aliases.keys()

                for alias, annotation in annotations.items():
                    if alias in names:
                        raise ValueError(
                            "The annotation '%s' conflicts with a field on "
                            "the model." % alias
                        )
                    if isinstance(annotation, FilteredRelation):
                        clone.query.add_filtered_relation(annotation, alias)
                    else:
                        clone.query.add_annotation(annotation, alias, select=select)
                for alias, annotation in clone.query.annotations.items():
                    if alias in annotations and annotation.contains_aggregate:
                        if clone._fields is None:
                            clone.query.group_by = True
                        else:
                            clone.query.set_group_by()
                        break

                return clone

            _annotate._zana_checks_alias_fields_ = True
            cls._annotate = _annotate

    @classmethod
    def install(cls):
        cls.model(m.Model), cls.queryset(m.QuerySet), cls.manager(m.Manager)

        try:
            from polymorphic.managers import PolymorphicManager  # type: ignore
            from polymorphic.query import PolymorphicQuerySet  # type: ignore
        except ImportError:
            pass
        else:
            cls.queryset(PolymorphicQuerySet), cls.manager(PolymorphicManager)


_Patcher.install()
