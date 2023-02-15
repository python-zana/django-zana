import math
import typing as t
from collections import abc
from functools import reduce
from logging import getLogger
from operator import attrgetter
from types import GenericAlias

from typing_extensions import Self
from zana.common import cached_attr, pipeline
from zana.types.collections import FrozenDict
from zana.types.enums import StrEnum

_T = t.TypeVar("_T")
_RT = t.TypeVar("_RT")
_T_Op = t.TypeVar("_T_Op")
_T_Key = t.TypeVar("_T_Key", slice, int, str, t.SupportsIndex, abc.Hashable)
_T_Fn = t.TypeVar("_T_Fn", bound=abc.Callable)
_T_Attr = t.TypeVar("_T_Attr", bound=str)

# _T_Fn = FunctionType | staticmethod | classmethod | MethodType | type

logger = getLogger(__name__)


# def attrsetter(*names: str):
#     def accessor(self, *values):
#         for n, v in zip(names, values):
#             setattr(self, n, v)

#     return accessor


# def attrdeleter(*names: str):
#     def accessor(self):
#         for name in names:
#             delattr(self, name)

#     return accessor


# def itemsetter(*keys):
#     def accessor(self, *values):
#         for key, value in zip(keys, values):
#             self[key] = value

#     return accessor


# def itemdeleter(*keys):
#     def accessor(self):
#         for key in keys:
#             del self[key]

#     return accessor


# def objectcaller(*args, **kwargs):
#     def call(self):
#         self(*args, **kwargs)

#     return call


# def functioncaller(func, /, *args, **kwargs):
#     def call(*a, **kw):
#         func(*a, *args, **kwargs | kw)

#     return call


class AccessType(StrEnum):
    ATTR = "ATTR", "Attribute"
    CALL = "CALL", "Call"
    FUNC = "FUNC", "Function"
    METH = "METH", "Method"
    ITEM = "ITEM", "Item"
    SLICE = "SLICE", "Slice"


class BaseAccessor(t.Generic[_RT, _T_Op]):
    __slots__ = ("__args__", "__kwargs__", "__dict__", "__weakref__")
    __args__: tuple
    __type__: t.ClassVar[AccessType] = ...

    _min_args_: t.Final = 0
    _max_args_: t.Final = math.inf
    _default_args_: t.Final = ()
    _default_kwargs_: t.Final = FrozenDict()

    __type_map: t.Final = {}

    __class_getitem__ = classmethod(GenericAlias)

    @staticmethod
    def _register_type(cls=None, type: str = None):
        def decorator(klass):
            if (
                type
                and BaseAccessor.__type_map.setdefault(type or klass.__type__, klass) is not klass
            ):
                raise TypeError(f"Accessible {type = } already registered")
            return klass

        if cls is None:
            return decorator
        return decorator(cls)

    def __init_subclass__(
        cls,
        type: AccessType = None,
        args=None,
        kwargs=None,
        min_args=None,
        max_args=None,
        merge=None,
        **kwds,
    ) -> None:
        super().__init_subclass__(**kwds)
        if type is None:
            type = cls.__dict__.get("__type__")
        elif "__type__" in cls.__dict__:
            raise TypeError(
                f"`type` class kwarg used together with `__type__` attribute in {cls.__name__}."
            )

        cls._register_type(cls, type)
        cls.__type__ = type

        if merge:

            def merge(self: Self, o: Self):
                cls = self.__class__
                if cls == o.__class__:
                    return (cls(*self.__args__, *o.__args__, **self.__kwargs__ | o.__kwargs__),)
                return self, o

            cls.merge = merge

        if args is not None:
            cls._default_args_ = tuple(args)
        if kwargs is not None:
            cls._default_kwargs_ = FrozenDict(kwargs)
        if min_args is not None:
            cls._min_args_ = min_args
        if max_args is not None:
            cls._max_args_ = max_args

    @classmethod
    def construct(cls, typ: str, args: abc.Iterable = (), kwargs: abc.Mapping = FrozenDict()):
        return cls.__type_map[typ](*args, **kwargs)

    def __new__(cls: type[Self], *args, **kwargs) -> Self:
        if not (cls._min_args_ <= len(args) <= cls._max_args_):
            raise TypeError(
                f"{cls.__name__} expected "
                f"{' to '.join(map(str, {cls._min_args_, cls._max_args_}))}"
                f" arguments but got {len(args)}."
            )

        self = super().__new__(cls)
        self.__args__, self.__kwargs__ = cls._parse_params_(args, kwargs)
        return self

    @classmethod
    def _parse_params_(cls, args, kwargs):
        args, kwargs = tuple(args), dict(kwargs)
        return args + cls._default_args_[len(args) :], cls._default_kwargs_ | kwargs

    @property
    def operant(self) -> _T_Op:
        return self.__args__[0]

    def __repr__(self):
        return f"{self.__class__.__name__}({', '.join(map(repr, self.__args__))})"

    def __reduce__(self):
        return BaseAccessor.construct, tuple(self)

    def __eq__(self, o: Self) -> bool:
        return o.__class__ == self.__class__ and tuple(o) == tuple(self)

    def __ne__(self, o: Self) -> bool:
        return o.__class__ != self.__class__ or tuple(o) != tuple(self)

    def __hash__(self) -> int:
        return hash(tuple(self))

    def __iter__(self):
        yield str(self.__type__)
        args, kwargs = self.__args__, self.__kwargs__
        if args or kwargs:
            yield args
            if kwargs:
                yield kwargs

    def __call__(self, *a, **kw) -> _RT:
        return self.get(*a, **kw)

    def get(self, obj) -> _RT:
        raise NotImplementedError(f"{self!r} getter not supported")

    def set(self, obj, val):
        raise NotImplementedError(f"{self!r} setter not supported")

    def delete(self, obj):
        raise NotImplementedError(f"{self!r} deleter not supported")

    def merge(self, other):
        return self, other

    def deconstruct(self):
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}",
            list(self.__args__),
            dict(self.__kwargs__),
        )


class Attr(BaseAccessor[_RT, _T_Attr], type=AccessType.ATTR, min_args=1, merge=True):
    __slots__ = ()

    @classmethod
    def _parse_params_(cls, args, kwargs):
        return super()._parse_params_(
            (at for arg in args for at in (arg.split(".") if isinstance(arg, str) else arg)),
            kwargs,
        )

    def get(self, obj) -> _RT:
        for arg in self.__args__:
            obj = getattr(obj, arg)
        return obj

    def set(self, obj, val):
        args = self.__args__
        for arg in args[:-1]:
            obj = getattr(obj, arg)
        setattr(obj, args[-1], val)

    def delete(self, obj):
        args = self.__args__
        for arg in args[:-1]:
            obj = getattr(obj, arg)
        delattr(obj, args[-1])


class Item(BaseAccessor[_RT, _T_Key], type=AccessType.ITEM, min_args=1, merge=True):
    __slots__ = ("__keys__",)

    @property
    def keys(self):
        try:
            return self.__keys__
        except AttributeError:
            self.__keys__ = rv = tuple(self.get_keys())
            return rv

    def get_keys(self):
        return self.__args__

    def get(self, obj) -> _RT:
        for key in self.keys:
            obj = obj[key]
        return obj

    def set(self, obj, val):
        keys = self.keys
        for key in keys[:-1]:
            obj = obj[key]
        obj[keys[-1]] = val

    def delete(self, obj):
        keys = self.keys
        for key in keys[:-1]:
            obj = obj[key]
        del obj[keys[-1]]


_slice_to_tuple = attrgetter("start", "stop", "step")


class Slice(Item[_RT, slice], type=AccessType.SLICE, min_args=1, max_args=3):
    __slots__ = ()

    def get_keys(self):
        return (slice(*a) for a in self.__args__)

    @classmethod
    def _parse_params_(cls, args, kwargs):
        args = (_slice_to_tuple(a) if isinstance(a, slice) else a for a in args)
        return super()._parse_params_(args, kwargs)


class Call(BaseAccessor, type=AccessType.CALL):
    __slots__ = ()

    def __call__(self, obj, /, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return obj(*a, *args, **kwargs | kw)


class Func(BaseAccessor[_RT, _T_Fn], type=AccessType.FUNC, min_args=1):
    __slots__ = ()

    def __call__(self, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return args[0](*a, *args[1:], **kwargs | kw)


class Meth(Func[_RT, _T_Fn], type=AccessType.METH):
    __slots__ = ()

    def __call__(self, obj, /, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return getattr(obj, args[0])(*a, *args[1:], **kwargs | kw)


def _accessor_reducer_(a: tuple[BaseAccessor], b: BaseAccessor):
    return a[:-1] + a[-1].merge(b)


class Accessor(BaseAccessor[_RT, _T_Fn], type="Accessor", merge=True):
    __slots__ = ()

    ATTR: t.Final = AccessType.ATTR
    CALL: t.Final = AccessType.CALL
    ITEM: t.Final = AccessType.ITEM
    SLICE: t.Final = AccessType.SLICE

    __args__: tuple[BaseAccessor, ...]

    # def __new__(cls, *src: AccessOperator) -> None:
    #     self = object.__new__(cls)
    #     it = (AccessOperator.construct(*x) for x in src)
    #     self.__args__ = reduce(_accessor_reducer_, it, (next(it),))
    #     return self

    @classmethod
    def _parse_params_(cls, args, kwargs):
        if args:
            it = (x if isinstance(x, BaseAccessor) else BaseAccessor.construct(*x) for x in args)
            args = reduce(_accessor_reducer_, it, (next(it),))
        return super()._parse_params_(args, kwargs)

    @cached_attr
    def get(self) -> abc.Callable[[t.Any], _T]:
        return pipeline(self.__args__)

    @cached_attr
    def set(self):
        return pipeline(self.__args__[:-1] + (self.__args__[-1].set,), tap=-1)

    @cached_attr
    def delete(self):
        return pipeline(self.__args__[:-1] + (self.__args__[-1].delete,), tap=-1)

    def __call__(self, *args, **kwds):
        return self.get(*args, **kwds)

    def __bool__(self):
        return not not self.__args__

    def __or__(self, o: abc.Callable):
        if isinstance(o, Accessor):
            return self.merge(o)
        elif callable(o):
            return self.__class__(*self.__args__, o)
        else:
            return self.__class__(*self.__args__, *o)

    def __ror__(self, o: abc.Callable):
        if isinstance(o, Accessor):
            return o.merge(self)
        elif callable(o):
            return self.__class__(o, *self.__args__)
        else:
            return self.__class__(*o, *self.__args__)

    def deconstruct(self):
        return (
            f"{self.__class__.__module__}.{self.__class__.__name__}",
            list(map(tuple, self.__args__)),
            {},
        )
