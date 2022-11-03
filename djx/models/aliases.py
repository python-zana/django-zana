from abc import ABC, abstractmethod
from functools import reduce, wraps
from operator import attrgetter
from types import FunctionType
import typing as t
from collections import ChainMap, abc
from typing_extensions import Self
from weakref import WeakSet

from django.db import models as m


if t.TYPE_CHECKING:
    class Model(m.Model):
        __query_aliases__: t.Final[t.ChainMap[str, "aliasfield"]] = ...


_T = t.TypeVar("_T")
_T_Model = t.TypeVar("_T_Model", bound="ImplementsAliases", covariant=True)



def _attribute_error_getter(msg: str):
    __tracebackhide__ = True

    def fget(self):
        nonlocal msg
        __tracebackhide__ = True
        raise AttributeError(msg)

    return fget


def _patch_model(cls: t.Type[_T_Model]):
    conf, annotate = cls.__query_aliases__, []
    aliases = {
        n: a.express(cls)
        for n, a in conf.items()
        if not (a.annotate and annotate.append(n))
    }
    annotations = {n: m.F(n) for n in annotate}

    if aliases:
        for man in cls._meta.managers:
            if not hasattr(man.get_queryset, "auto_aliased"):
                fn = man.get_queryset.__func__
                if annotations:
                    def get_queryset():
                        nonlocal fn, man, aliases, annotations
                        return fn(man).alias(**aliases).annotate(**annotations)
                else:
                    def get_queryset():
                        nonlocal fn, man, aliases
                        return fn(man).alias(**aliases)

                get_queryset.auto_aliased = None
                man.get_queryset = get_queryset



class ImplementsAliases(Model if t.TYPE_CHECKING else ABC):
    @classmethod
    def __subclasshook__(cls, sub: type):
        if cls is ImplementsAliases and issubclass(sub, m.Model):
            if isinstance(getattr(sub, "__query_aliases__", None), abc.Mapping):
                return True
        return NotImplemented


class AliasDescriptor(property):

    field: "aliasfield" = None

    def __init__(
        self, fget=None, fset=None, fdel=None, doc: str = None, *, field: "aliasfield"
    ) -> None:
        super().__init__(fget, fset, fdel, doc)
        self.field = field


class aliasfield(property[_T] if t.TYPE_CHECKING else t.Generic[_T]):

    descriptor_class: t.ClassVar[t.Type[AliasDescriptor]] = AliasDescriptor

    name: str
    attr: str
    expression: t.Any = None
    annotate: bool = None
    fget: t.Union[abc.Callable, bool]
    fset: t.Union[abc.Callable, bool]
    fdel: t.Union[abc.Callable, bool]
    doc: str

    def __init__(
        self,
        expression=None,
        fget: t.Union[abc.Callable, bool] = None,
        fset: t.Union[abc.Callable, bool] = None,
        fdel: t.Union[abc.Callable, bool] = None,
        *,
        annotate: bool = None,
        attr: str = None,
        doc: str = None,
    ) -> None:
        self.annotate, self.attr, self.expression = annotate, attr, expression
        self.fget, self.fset, self.fdel, self.doc = fget, fset, fdel, doc

    def getter(self, fget: t.Callable[[_T_Model], _T]):
        return self._evolve(fget=fget)

    def setter(self, fset: t.Callable[[_T_Model, _T], t.NoReturn]):
        return self._evolve(fset=fset)

    def deleter(self, fdel: t.Callable[[_T_Model], t.NoReturn]):
        return self._evolve(fdel=fdel)

    def __call__(self, expression):
        return self._evolve(expression=expression)

    def __repr__(self) -> str:
        attr = self.attr
        return f"{self.__class__.__name__}({self.expression!r}, {attr=!r})"

    def _evolve(self, **kwargs) -> Self:
        return self.__class__(
            **dict(
                expression=self.expression,
                fget=self.fget,
                fset=self.fset,
                fdel=self.fdel,
                annotate=self.annotate,
                attr=self.attr,
                doc=self.doc,
            )
            | kwargs
        )

    def express(self, cls: t.Type[m.Model]):
        if isinstance(expr := self.expression, str):
            return m.F(expr)
        elif isinstance(expr, FunctionType):
            return expr(cls)
        return expr

    def _prepare(self, name: str):
        annotate, attr, expression = self.annotate, self.attr, self.expression
        fget, fset, fdel = self.fget, self.fset, self.fdel

        if annotate is None:
            annotate = not (fget or fset)

        if attr is None:
            if isinstance(expression, m.F):
                attr = expression.name.replace("__", ".")
            elif isinstance(expression, str):
                attr = expression.replace("__", ".")

        if annotate and fset is True:
            raise TypeError(f"annotated alias cannot have a setter")

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
            fget=self.make_getter(),
            fset=self.make_setter(),
            fdel=self.make_deleter(),
            doc=self.doc,
            field=self,
        )
        return ret

    def make_getter(self):
        __tracebackhide__ = True
        annotate, attr, name, fget = self.annotate, self.attr, self.name, self.fget
        if fget is True:
            fget = (attr and attrgetter(attr)) or (
                annotate and _attribute_error_getter(name)
            )

        if annotate:
            func = fget

            def fget(self):
                __tracebackhide__ = True
                nonlocal name, func
                try:
                    return self.__dict__[name]
                except KeyError:
                    return func(self)

        return fget or None

    def make_setter(self):
        __tracebackhide__ = True
        attr, name, func = self.attr, self.name, self.fset
        if func is True:
            if attr:
                *path, name = attr.split(".")

                def func(self, value):
                    __tracebackhide__ = True
                    nonlocal path, name
                    obj = reduce(getattr, path, self)
                    setattr(obj, name, value)

            else:

                def func(self: _T_Model, value):
                    nonlocal name
                    self.__dict__[name] = value

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

