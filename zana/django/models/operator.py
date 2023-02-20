import math
import typing as t
from collections import abc
from functools import reduce
from itertools import chain
from logging import getLogger
from operator import attrgetter, or_
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


class SignatureError(Exception):
    pass


class AttributeSignatureError(SignatureError, AttributeError):
    ...


class LookupSignatureError(SignatureError, LookupError):
    ...


class KeySignatureError(LookupSignatureError, KeyError):
    ...


class IndexSignatureError(LookupSignatureError, IndexError):
    ...


class SigType(StrEnum):
    ATTR = "ATTR", "Attribute"
    CALL = "CALL", "Call"
    FUNC = "FUNC", "Function"
    METH = "METH", "Method"
    ITEM = "ITEM", "Item"
    SLICE = "SLICE", "Slice"
    OP = "OP", "Operation"


class Signature(t.Generic[_RT, _T_Op]):
    __slots__ = ("__args__", "__kwargs__", "__dict__", "__weakref__")
    __args__: tuple
    __type__: t.ClassVar[SigType] = ...

    _min_args_: t.Final = 0
    _max_args_: t.Final = math.inf
    _default_args_: t.Final = ()
    _default_kwargs_: t.Final = FrozenDict()
    _required_kwargs_: t.Final = frozenset[str]()
    _can_merge_: bool = None
    __type_map: t.Final = {}

    __class_getitem__ = classmethod(GenericAlias)

    @staticmethod
    def _register_type(cls=None, type: str = None):
        def decorator(klass):
            if type and Signature.__type_map.setdefault(type or klass.__type__, klass) is not klass:
                raise TypeError(f"Signature {type = } already registered")
            return klass

        if cls is None:
            return decorator
        return decorator(cls)

    def __init_subclass__(
        cls,
        type: SigType = None,
        args=None,
        kwargs=None,
        required_kwargs=None,
        min_args=None,
        max_args=None,
        merge=None,
        **kwds,
    ) -> None:
        super().__init_subclass__(**kwds)
        if type is None:
            type = cls.__dict__["__type__"]
        elif "__type__" in cls.__dict__:
            raise TypeError(
                f"`type` class kwarg used together with `__type__` attribute in {cls.__name__}."
            )

        cls.__type__ = type
        cls._register_type(cls)

        if merge is not None:
            cls._can_merge_ = merge

        if args is not None:
            cls._default_args_ = tuple(args)
        if kwargs is not None:
            cls._default_kwargs_ = FrozenDict(kwargs)

        if required_kwargs is not None:
            cls._required_kwargs_ = frozenset(required_kwargs)

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
        if missed := cls._required_kwargs_ - kwargs.keys():
            *missed, last = map(repr, missed)
            raise TypeError(
                f"{cls.__name__} is missing required keyword only arguments "
                f"{' or '.join(filter(None, (', '.join(missed), last)))}."
            )
        args, kwargs = cls._parse_params_(args, kwargs)
        return cls._new_(args, kwargs)

    @classmethod
    def _new_(cls, args=(), kwargs=FrozenDict()):
        self = super().__new__(cls)
        self.__args__, self.__kwargs__ = args, kwargs
        return self

    @classmethod
    def _parse_params_(cls, args, kwargs):
        args, kwargs = tuple(args), dict(kwargs)
        return args + cls._default_args_[len(args) :], cls._default_kwargs_ | kwargs

    def merge(self, *args, **kwds):
        return self.__class__(*self.__args__, *args, **self.__kwargs__ | kwds)

    def rmerge(self, *args, **kwds):
        return self.__class__(*args, *self.__args__, **kwds | self.__kwargs__)

    @property
    def operant(self) -> _T_Op:
        return self.__args__[0]

    @property
    def __ident__(self):
        return self.__type__, self.__args__, self.__kwargs__

    def __repr__(self):
        return f"{self.__class__.__name__}({', '.join(map(repr, self.__args__))})"

    def __reduce__(self):
        return self._new_, (self.__args__, self.__kwargs__)

    def __eq__(self, o: Self) -> bool:
        return isinstance(o, Signature) and o.__ident__ == self.__ident__

    def __ne__(self, o: Self) -> bool:
        return not isinstance(o, Signature) or o.__ident__ != self.__ident__

    def __hash__(self) -> int:
        return hash(self.__ident__)

    def __contains__(self, x):
        return x == self

    def __len__(self):
        return 1

    def __iter__(self):
        yield self
        # yield str(self.__type__)
        # args, kwargs = self.__args__, self.__kwargs__
        # if args or kwargs:
        #     yield args
        #     if kwargs:
        #         yield kwargs

    def __reversed__(self):
        yield self

    def __or__(self, o: abc.Callable):
        if isinstance(o, Signature) and o.__type__ == self.__type__ and self._can_merge_:
            return self.merge(*o.__args__, **o.__kwargs__)
        elif not isinstance(o, abc.Iterable):
            return NotImplemented
        return Chain._new_(tuple(chain(self, o)))

    def __ror__(self, o: abc.Callable):
        if isinstance(o, Signature) and o.__type__ == self.__type__ and self._can_merge_:
            return self.rmerge(*o.__args__, **o.__kwargs__)
        elif not isinstance(o, abc.Iterable):
            return NotImplemented
        return Chain._new_(tuple(chain(o, self)))

    def __call__(self, *a, **kw) -> _RT:
        raise NotImplementedError(f"{self!r} getter not supported")

    def get(self, obj) -> _RT:
        raise self(obj)

    def set(self, obj, val):
        raise NotImplementedError(f"{self!r} setter not supported")

    def delete(self, obj):
        raise NotImplementedError(f"{self!r} deleter not supported")

    def deconstruct(self):
        from zana.django import models

        mod, name = f"{self.__class__.__module__}", f"{self.__class__.__name__}"
        if mod.startswith(models.__name__) and getattr(models, name, ...) is self.__class__:
            mod = models.__name__
        return (f"{mod}.{name}", list(self.__args__), dict(self.__kwargs__))


class Attr(Signature[_RT, _T_Attr], type=SigType.ATTR, min_args=1, merge=True):
    __slots__ = ()

    @classmethod
    def _parse_params_(cls, args, kwargs):
        return super()._parse_params_(
            (at for arg in args for at in (arg.split(".") if isinstance(arg, str) else arg)),
            kwargs,
        )

    def __call__(self, obj) -> _RT:
        args = self.__args__
        try:
            for arg in args:
                obj = getattr(obj, arg)
        except AttributeError as e:
            raise AttributeSignatureError(self) from e
        else:
            return obj

    def set(self, obj, val):
        args = self.__args__
        try:
            for arg in args[:-1]:
                obj = getattr(obj, arg)
        except AttributeError as e:
            raise AttributeSignatureError(self) from e
        else:
            setattr(obj, args[-1], val)

    def delete(self, obj):
        args = self.__args__
        try:
            for arg in args[:-1]:
                obj = getattr(obj, arg)
        except AttributeError as e:
            raise AttributeSignatureError(self) from e
        else:
            delattr(obj, args[-1])


class Item(Signature[_RT, _T_Key], type=SigType.ITEM, min_args=1, merge=True):
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

    def __call__(self, obj) -> _RT:
        keys = self.keys
        try:
            for key in keys:
                obj = obj[key]
        except IndexError as e:
            raise IndexSignatureError(self) from e
        except KeyError as e:
            raise KeySignatureError(self) from e
        except LookupError as e:
            raise LookupSignatureError(self) from e
        else:
            return obj

    def set(self, obj, val):
        keys = self.keys
        try:
            for key in keys[:-1]:
                obj = obj[key]
        except IndexError as e:
            raise IndexSignatureError(self) from e
        except KeyError as e:
            raise KeySignatureError(self) from e
        except LookupError as e:
            raise LookupSignatureError(self) from e
        else:
            obj[keys[-1]] = val

    def delete(self, obj):
        keys = self.keys
        try:
            for key in keys[:-1]:
                obj = obj[key]
        except IndexError as e:
            raise IndexSignatureError(self) from e
        except KeyError as e:
            raise KeySignatureError(self) from e
        except LookupError as e:
            raise LookupSignatureError(self) from e
        else:
            del obj[keys[-1]]


_slice_to_tuple = attrgetter("start", "stop", "step")


class Slice(Item[_RT, slice], type=SigType.SLICE, min_args=1, max_args=3):
    __slots__ = ()

    def get_keys(self):
        return (slice(*a) for a in self.__args__)

    @classmethod
    def _parse_params_(cls, args, kwargs):
        print(cls, args, kwargs)
        args = (_slice_to_tuple(a) if isinstance(a, slice) else a for a in args)
        return super()._parse_params_(args, kwargs)


class Call(Signature, type=SigType.CALL):
    __slots__ = ()

    def __call__(self, obj, /, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return obj(*a, *args, **kwargs | kw)


class Func(Signature[_RT, _T_Fn], type=SigType.FUNC, min_args=1):
    __slots__ = ()

    def __call__(self, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return args[0](*a, *args[1:], **kwargs | kw)


class Meth(Func[_RT, _T_Fn], type=SigType.METH):
    __slots__ = ()

    def __call__(self, obj, /, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return getattr(obj, args[0])(*a, *args[1:], **kwargs | kw)


# def _accessor_reducer_(a: tuple[Signature], b: Signature):
#     return a[:-1] + a[-1].merge(b)


class Chain(Signature[_RT, _T_Fn], type="CHAIN", merge=True):
    __slots__ = ()

    ATTR: t.Final = SigType.ATTR
    CALL: t.Final = SigType.CALL
    ITEM: t.Final = SigType.ITEM
    SLICE: t.Final = SigType.SLICE
    OP: t.Final = SigType.OP

    __args__: tuple[Signature, ...]

    @classmethod
    def _parse_params_(cls, args, kwargs):
        if args:
            args = reduce(or_, (s for x in args for s in x))
        return super()._parse_params_((s for x in args for s in x), kwargs)

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

    def __len__(self):
        return len(self.__args__)

    def __contains__(self, x):
        return x in self.__args__

    def __iter__(self):
        return iter(self.__args__)

    def __reversed__(self):
        return reversed(self.__args__)

    # def __or__(self, o: abc.Callable):
    #     if isinstance(o, Chain):
    #         return self.merge(o)
    #     elif callable(o):
    #         return self.__class__(*self.__args__, o)
    #     else:
    #         return self.__class__(*self.__args__, *o)

    # def __ror__(self, o: abc.Callable):
    #     if isinstance(o, Chain):
    #         return o.merge(self)
    #     elif callable(o):
    #         return self.__class__(o, *self.__args__)
    #     else:
    #         return self.__class__(*o, *self.__args__)

    # def deconstruct(self):
    #     return (
    #         f"{self.__class__.__module__}.{self.__class__.__name__}",
    #         list(map(tuple, self.__args__)),
    #         {},
    #     )
