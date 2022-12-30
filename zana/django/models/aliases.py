import typing as t
from abc import ABC, abstractmethod
from collections import ChainMap, abc
from email.policy import default
from functools import cached_property, reduce, update_wrapper, wraps
from operator import attrgetter
from types import FunctionType
from types import GenericAlias as GenericAliasType
from types import MethodType
from weakref import WeakSet

from typing_extensions import Self
from zana.common import NotSet, cached_attr

from django.core.exceptions import ImproperlyConfigured
from django.db import models as m
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce

if t.TYPE_CHECKING:
    class Model(m.Model):
        __query_aliases__: t.Final[t.ChainMap[str, "alias"]] = ...


_T = t.TypeVar("_T")
_T_Src = t.TypeVar("_T_Src")
_T_Model = t.TypeVar("_T_Model", bound="ImplementsAliases", covariant=True)
_T_Expr = t.Union[Combinable, str, m.Field, 'alias', t.Callable[[_T_Model], t.Union[Combinable, str, m.Field, 'alias']]]


def _error_attrgetter(msg: str):
    __tracebackhide__ = True

    def fget(self):
        nonlocal msg
        __tracebackhide__ = True
        raise AttributeError(msg)

    return fget

def _none_attrgetter():
    def fget(self):
        pass
    return fget


def _patch_model(cls: t.Type[_T_Model]):
    conf = cls.__query_aliases__
    if conf:
        aliases: dict = None
        annotations = {n: m.F(n) for n, a in conf.items() if a.annotate}

        def aka_init():
            nonlocal aliases
            if aliases is None:
                aliases = { n: a.get_expression(cls) for n, a in conf.items() }
            else:
                raise ValueError('No second calls')
            return aliases
        
        if not getattr(cls.refresh_from_db, "_loads_aliases_", None):
            orig_refresh_from_db = cls.refresh_from_db
            @wraps(orig_refresh_from_db)
            def refresh_from_db(self, fields=None):
                aka = aliases.keys()
                if fields:
                    fields = set(fields)
                    aka = aka & fields
                    fields -= aka 

                for a in aka:
                    delattr(self, a)
                orig_refresh_from_db(self, fields)

            refresh_from_db._loads_aliases_ = True
            cls.refresh_from_db = refresh_from_db
        
        for man in cls._meta.managers:
            if not getattr(man.get_queryset, "_loads_aliases_", None):
                orig_get_qs = man.get_queryset.__func__
                if annotations:
                    @wraps(orig_get_qs)
                    def get_queryset():
                        nonlocal orig_get_qs, man, aliases, annotations
                        return orig_get_qs(man).alias(**aliases or aka_init()).annotate(**annotations)
                else:
                    @wraps(orig_get_qs)
                    def get_queryset():
                        nonlocal orig_get_qs, man, aliases
                        return orig_get_qs(man).alias(**aliases or aka_init())

                get_queryset._loads_aliases_ = True
                man.get_queryset = get_queryset



class ImplementsAliases(ABC, m.Model if t.TYPE_CHECKING else object):

    __query_aliases__: abc.Mapping[str, 'alias']

    @classmethod
    def __subclasshook__(cls, sub: type):
        if cls is ImplementsAliases and issubclass(sub, m.Model):
            if isinstance(getattr(sub, "__query_aliases__", None), abc.Mapping):
                return True
        return NotImplemented
    
    @classmethod
    def prepare(cls, subclass: type[_T_Model]):
        if not "__query_aliases__" in subclass.__dict__:
            subclass.__query_aliases__ = ChainMap(
                {},
                *(
                    m.maps[0]
                    for b in subclass.__mro__
                    if isinstance(m := b.__dict__.get("__query_aliases__"), ChainMap)
                )
            )

        return cls.register(subclass)



class GenericAlias:

    __slots__ = '__alias__', '__args__', '__origin__',

    def __new__(cls, alias: 'alias[_T]', origin, *args) -> Self:
        self = object.__new__(cls)
        self.__alias__, self.__args__, self.__origin__ = alias, args, origin
        return self

    def __call__(self) -> 'alias':
        return self.__alias__('__'.join(self.__args__))

    def __getattr__(self, name: str):
        return self.__class__(self.__alias__, self.__origin__, *self.__args__, name)

    def contribute_to_class(self, cls: t.Type[_T_Model], name: str):
        return self().contribute_to_class(cls, name)


class alias(t.Generic[_T]):
    __class_getitem__ = classmethod(GenericAliasType)

    name: str
    cache: bool
    attr: str
    expression: _T_Expr
    annotate: bool
    field: t.Optional[m.Field]
    default: t.Any

    fget: t.Union[abc.Callable[[_T_Model], _T], bool]
    fset: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool]
    fdel: abc.Callable[[_T_Model], t.NoReturn]
    doc: str

    if t.TYPE_CHECKING:
        def __new__(cls,
            expression: _T_Expr = None,
            getter: t.Union[abc.Callable[[_T_Model], _T], bool] = None,
            setter: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool] = None,
            deleter: abc.Callable[[_T_Model], t.NoReturn] = None,
            *,
            annotate: bool = None,
            attr: str = None,
            doc: str = None,
            field: m.Field=None, 
            default=None,
            cache:bool=None,
        ) -> _T | Self:
            ...
        
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
        field: m.Field=None,
        default=NotSet,
        cache:bool=None,
    ) -> None:
        self.annotate, self.attr, self.expression = annotate, attr, expression
        self.fget, self.fset, self.fdel, self.doc = getter, setter, deleter, doc
        self.field, self.default, self.cache = field, default, cache
    
    def getter(self, fget: t.Callable | bool ) -> _T | Self:
        return self.evolve(getter=fget)

    def setter(self, fset: t.Callable | bool) -> _T | Self:
        return self.evolve(setter=fset)

    def deleter(self, fdel: t.Callable) -> _T | Self:
        return self.evolve(deleter=fdel)

    def __getitem__(self, src: _T_Src) -> _T_Src:
        return GenericAlias(self, src)

    def __call__(self, expression: _T_Expr):
        return self.evolve(expression=expression)

    def __repr__(self) -> str:
        attr = self.attr
        return f"{self.__class__.__name__}({self.expression!r}, {attr=!r})"

    def _evolve_kwargs(self, kwargs: dict) -> dict:
        return dict(
            expression=self.expression,
            getter=self.fget,
            setter=self.fset,
            deleter=self.fdel,
            annotate=self.annotate,
            attr=self.attr,
            doc=self.doc,
            field=self.field,
            default=self.default,
            cache=self.cache,
        ) | kwargs

    def evolve(self, **kwargs) -> _T | Self:
        return self.__class__(**self._evolve_kwargs(kwargs))

    def get_expression(self, cls: t.Type[m.Model]):
        expr = self.expression
        if isinstance(expr, (FunctionType, staticmethod, classmethod, MethodType)):
            expr = expr(cls)

        if isinstance(expr, str):
            expr = m.F(expr)
        elif isinstance(expr, m.Field):
            expr = m.F(expr.name)
        
        if self.field:
            expr = m.ExpressionWrapper(expr, output_field=self.field)

        if not self.default in (NotSet, None):
            expr = Coalesce(expr, self.default)

        return expr

    def _prepare(self, cls: t.Type[_T_Model], name: str):
        annotate, attr, cache, expression = self.annotate, self.attr, self.cache, self.expression
        fget, fset, fdel = self.fget, self.fset, self.fdel

        if attr is None:
            lookup = attr
            if isinstance(expression, m.F):
                lookup = expression.name
            elif isinstance(expression, str):
                lookup = expression
            elif isinstance(expression, m.Field):
                lookup = expression.attname
            attr = lookup and lookup.replace('__', '.')

        annotate = not (fget or fset or attr) if annotate is None else not not annotate

        if cache is None:
            cache = annotate or not attr

        if fset is True and (not attr or annotate or cache):
            if not attr:
                msg = f"Cannot resolve attribute for implicit `setter`. " \
                    f"Either provide the `attr` name or a custom `setter`"
            else:
                msg = (
                    "%s aliases cannot have an implicit `setter`. "
                    "Either provide custom `setter` or set `%s` to `False`." 
                ) % (('Annotated', 'annotate') if annotate else ('Cached', 'cache'))
            raise ImproperlyConfigured(f"alias {name!r} on {cls.__name__!r}. {msg}")

        if fget is None:
            fget = not not (annotate or attr)

        self.annotate, self.attr, self.cache, self.expression = annotate, attr, cache, expression
        self.fget, self.fset, self.fdel, self.name = fget, fset, fdel, name

    def contribute_to_class(self, cls: t.Type[_T_Model], name: str):
        cls = ImplementsAliases.prepare(cls)
        self._prepare(cls, name)
        cls.__query_aliases__[name], descriptor = self, self.create_descriptor(cls)

        if hasattr(descriptor, '__set_name__'):
            descriptor.__set_name__(cls, name)

        setattr(cls, name, descriptor)

    def create_descriptor(self, cls):
        ret = (cached_attr if self.cache else property)(
            self.make_getter(),
            self.make_setter(),
            self.make_deleter(),
            doc=self.doc,
        )
        
        return ret

    def make_getter(self):
        attr, default, fget = self.attr, self.default, self.fget
        if fget is True:
            fget = (attr and attrgetter(attr)) or _error_attrgetter(self.name)
        
        if fget and not default is NotSet:
            fget_ = fget
            @wraps(fget_)
            def fget(self):
                nonlocal default, fget_
                try:
                    val = fget_(self)
                except AttributeError:
                    val = None
                return default if val is None else val

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
        # __tracebackhide__ = True
        # func, name = self.fdel, self.name
        # if func is True:
        #     def func(self: _T_Model):
        #         __tracebackhide__ = True
        #         nonlocal name
        #         try:
        #             del self.__dict__[name]
        #         except KeyError:
        #             raise AttributeError(name)

        return self.fdel

