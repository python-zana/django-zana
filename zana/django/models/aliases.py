import typing as t
from abc import ABC, abstractmethod
from collections import ChainMap, abc
from email.policy import default
from functools import cached_property, reduce, wraps
from operator import attrgetter
from types import FunctionType, MethodType
from weakref import WeakSet

from typing_extensions import Self

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

_empty = object()

def _attribute_error_getter(msg: str):
    __tracebackhide__ = True

    def fget(self):
        nonlocal msg
        __tracebackhide__ = True
        raise AttributeError(msg)

    return fget


def _patch_model(cls: t.Type[_T_Model]):
    conf = cls.__query_aliases__

    if not conf:
        return

    aliases: dict = None
    annotations = {n: m.F(n) for n, a in conf.items() if a.annotate}

    def aka_init():
        nonlocal aliases
        if aliases is None:
            aliases = { n: a.get_expression(cls) for n, a in conf.items() }
        else:
            raise ValueError('No second calls')
        return aliases

    for man in cls._meta.managers:
        if not getattr(man.get_queryset, "_loads_aliases_", None):
            fn = man.get_queryset.__func__
            if annotations:
                def get_queryset():
                    nonlocal fn, man, aliases, annotations
                    return fn(man).alias(**aliases or aka_init()).annotate(**annotations)
            else:
                def get_queryset():
                    nonlocal fn, man, aliases
                    return fn(man).alias(**aliases or aka_init())

            get_queryset._loads_aliases_ = True
            man.get_queryset = get_queryset



class ImplementsAliases(Model if t.TYPE_CHECKING else ABC):
    @classmethod
    def __subclasshook__(cls, sub: type):
        if cls is ImplementsAliases and issubclass(sub, m.Model):
            if isinstance(getattr(sub, "__query_aliases__", None), abc.Mapping):
                return True
        return NotImplemented


class AliasDescriptor(property):

    field: "alias" = None

    def __init__(
        self, fget=None, fset=None, fdel=None, doc: str = None, *, field: "alias"
    ) -> None:
        super().__init__(fget, fset, fdel, doc)
        self.field = field


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




class alias(property[_T] if t.TYPE_CHECKING else t.Generic[_T]):

    descriptor_class: t.ClassVar[t.Type[AliasDescriptor]] = AliasDescriptor

    name: str
    attr: str
    expression: _T_Expr
    annotate: bool
    field: t.Optional[m.Field]
    default: t.Any

    fget: t.Union[abc.Callable[[_T_Model], _T], bool]
    fset: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool]
    fdel: t.Union[abc.Callable[[_T_Model], t.NoReturn], bool]
    doc: str

    if t.TYPE_CHECKING:
        def __new__(cls,
        expression: _T_Expr = None,
        getter: t.Union[abc.Callable[[_T_Model], _T], bool] = None,
        setter: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool] = None,
        deleter: t.Union[abc.Callable[[_T_Model], t.NoReturn], bool] = None,
        *,
        annotate: bool = None,
        attr: str = None,
        doc: str = None,
        field: m.Field=None, 
        default=None,
        ):
            return super().__new__(cls)
        
        def __get__(self, obj: _T_Model, typ: type[_T_Model] = None) -> t.Union[_T, Self]:
            ...
   
   
    def __init__(
        self,
        expression: _T_Expr = None,
        getter: t.Union[abc.Callable[[_T_Model], _T], bool] = None,
        setter: t.Union[abc.Callable[[_T_Model, _T], t.NoReturn], bool] = None,
        deleter: t.Union[abc.Callable[[_T_Model], t.NoReturn], bool] = None,
        *,
        annotate: bool = None,
        attr: str = None,
        doc: str = None,
        field: m.Field=None,
        default=_empty,
    ) -> None:
        self.annotate, self.attr, self.expression = annotate, attr, expression
        self.fget, self.fset, self.fdel, self.doc = getter, setter, deleter, doc
        self.field, self.default = field, default
    
    def getter(self, fget: t.Callable[[_T_Model], _T]):
        return self.evolve(getter=fget)

    def setter(self, fset: t.Callable[[_T_Model, _T], t.NoReturn]):
        return self.evolve(setter=fset)

    def deleter(self, fdel: t.Callable[[_T_Model], t.NoReturn]):
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
        ) | kwargs

    def evolve(self, **kwargs) -> t.Union[_T, Self]:
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

        if not self.default in (_empty, None):
            expr = Coalesce(expr, self.default)

        return expr

    def _prepare(self, name: str):
        annotate, attr, expression = self.annotate, self.attr, self.expression
        fget, fset, fdel = self.fget, self.fset, self.fdel

        if annotate is None:
            annotate = not (fget or fset)

        if attr is None:
            lookup = attr
            if isinstance(expression, m.F):
                lookup = expression.name
            elif isinstance(expression, str):
                lookup = expression
            attr = lookup and lookup.replace('__', '.')

        if fset is True and not (annotate or attr) :
            raise TypeError(f"cannot create a setter")

        if fget is None:
            fget = not not (annotate or attr)

        if fset is None:
            fset = not not annotate

        if fdel is None:
            fdel = not not annotate

        self.annotate, self.attr, self.expression = annotate, attr, expression
        self.fget, self.fset, self.fdel, self.name = fget, fset, fdel, name

    def contribute_to_class(self, cls: t.Type[_T_Model], name: str):
        self._prepare(name)
        if not "__query_aliases__" in cls.__dict__:
            cls.__query_aliases__ = ChainMap(
                {},
                *(
                    b.__query_aliases__.maps[0]
                    for b in cls.__mro__
                    if "__query_aliases__" in b.__dict__
                ),
            )

        cls.__query_aliases__[name] = self
        setattr(cls, name, self.create_descriptor(cls))

    def create_descriptor(self, cls):
        ret = self.descriptor_class(
            self.make_getter(),
            self.make_setter(),
            self.make_deleter(),
            doc=self.doc,
            field=self,
        )
        return ret

    def make_getter(self):
        __tracebackhide__ = True
        annotate, attr, name, fget, default = self.annotate, self.attr, self.name, self.fget, self.default
        if fget is True:
            fget = (attr and attrgetter(attr)) or (
                annotate and _attribute_error_getter(name)
            )
        
        if not default is _empty:
            default_func, default = fget, self.default

            def fget(self):
                __tracebackhide__ = True
                nonlocal name, default, default_func
                val = default_func(self)
                return default if val is None else val


        if annotate:
            ann_func = fget

            def fget(self):
                __tracebackhide__ = True
                nonlocal name, ann_func
                try:
                    return self.__dict__[name]
                except KeyError:
                    return ann_func(self)

        return fget or None

    def make_setter(self):
        __tracebackhide__ = True
        annotate, attr, name, func = self.annotate, self.attr, self.name, self.fset
        if func is True:
            if annotate:
                def func(self: _T_Model, value):
                    nonlocal name
                    self.__dict__[name] = value
            else:
                *path, name = attr.split(".")
                def func(self, value):
                    __tracebackhide__ = True
                    nonlocal path, name
                    obj = reduce(getattr, path, self)
                    setattr(obj, name, value)
                

        return func or None

    def make_deleter(self):
        __tracebackhide__ = True
        func, name = self.fdel, self.name
        if func is True:
            def func(self: _T_Model):
                __tracebackhide__ = True
                nonlocal name
                try:
                    del self.__dict__[name]
                except KeyError:
                    raise AttributeError(name)

        return func or None

