import math
import typing as t
from collections import abc
from functools import reduce
from logging import getLogger
from operator import attrgetter, or_
from types import GenericAlias

from typing_extensions import Self
from zana.common import cached_attr, pipeline
from zana.types.collections import FrozenDict
from zana.types.enums import StrEnum

_T = t.TypeVar("_T")
_RT = t.TypeVar("_RT")

_T_Arg = t.TypeVar("_T_Arg")
_T_Kwarg = t.TypeVar("_T_Kwarg")
_T_Key = t.TypeVar("_T_Key", slice, int, str, t.SupportsIndex, abc.Hashable)
_T_Fn = t.TypeVar("_T_Fn", bound=abc.Callable)
_T_Attr = t.TypeVar("_T_Attr", bound=str)

# _T_Fn = FunctionType | staticmethod | classmethod | MethodType | type

logger = getLogger(__name__)
_notset = object()


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


class Signature(t.Generic[_RT, _T, _T_Arg, _T_Kwarg]):
    __slots__ = "__args__", "__kwargs__", "__dict__", "__weakref__"
    __class_getitem__ = classmethod(GenericAlias)

    __args__: tuple[_T_Arg, ...]
    __kwargs__: FrozenDict[str, _T_Kwarg]
    __identity__: tuple

    # __type__: t.ClassVar[SigType] = ...

    _min_args_: t.Final = 0
    _max_args_: t.Final = math.inf
    _default_args_: t.Final = ()
    _default_kwargs_: t.Final = FrozenDict()
    _required_kwargs_: t.Final = frozenset[str]()
    _can_merge_: t.Final[bool] = True

    # __type_map: t.Final = {}

    # @staticmethod
    # def _register_type(cls=None, type: str = None):
    #     def decorator(klass):
    #         if type and Signature.__type_map.setdefault(type or klass.__type__, klass) is not klass:
    #             raise TypeError(f"Signature {type = } already registered")
    #         return klass

    #     if cls is None:
    #         return decorator
    #     return decorator(cls)

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
        # if type is None:
        #     type = cls.__dict__["__type__"]
        # elif "__type__" in cls.__dict__:
        #     raise TypeError(
        #         f"`type` class kwarg used together with `__type__` attribute in {cls.__name__}."
        #     )

        # cls.__type__ = type
        # cls._register_type(cls)

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

    # @classmethod
    # def construct(cls, typ: str, args: abc.Iterable = (), kwargs: abc.Mapping = FrozenDict()):
    #     return cls.__type_map[typ](*args, **kwargs)

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
    def _parse_params_(cls, args, kwargs) -> tuple[tuple[_T_Arg, ...], FrozenDict[str, _T_Kwarg]]:
        args, kwargs = tuple(args), FrozenDict(kwargs)
        return args + cls._default_args_[len(args) :], cls._default_kwargs_ | kwargs

    @property
    def __ident__(self):
        return self.__args__, self.__kwargs__

    @property
    def args(self):
        return self.__args__

    @property
    def kwargs(self):
        return self.__kwargs__

    def extend(self, *args, **kwds):
        return self.__class__(*self.__args__, *args, **self.__kwargs__ | kwds)

    def __repr__(self):
        params = map(repr, self.__args__), (f"{k}={v!r}" for k, v in self.__kwargs__.items())
        return f"{self.__class__.__name__}({', '.join(p for ps in params for p in ps)})"

    def __reduce__(self):
        return self._new_, (self.__args__, self.__kwargs__)

    def __eq__(self, o: Self) -> bool:
        return o.__class__ is self.__class__ and o.__ident__ == self.__ident__

    def __ne__(self, o: Self) -> bool:
        return o.__class__ is not self.__class__ or o.__ident__ != self.__ident__

    def __hash__(self) -> int:
        return hash(self.__ident__)

    # def __contains__(self, x):
    #     return x == self

    # def __len__(self):
    #     return 1

    # def __iter__(self):
    #     yield self

    # def __reversed__(self):
    #     yield self

    def __or__(self, o: abc.Callable):
        if isinstance(o, Signature):
            if len(chain := self._chain(o)) == 1:
                return chain[0]
            chain = Chain(*chain)
        elif isinstance(o, (abc.Sequence, abc.Iterator)):
            chain = Chain(self, *o)
        else:
            return NotImplemented

        return chain[0] if len(chain) == 1 else chain

    def __ror__(self, o: abc.Callable):
        if not isinstance(o, (abc.Sequence, abc.Iterator)):
            return NotImplemented
        chain = Chain(*o, self)
        return chain[0] if len(chain) == 1 else chain

    def _chain(self: Self, o: Self):
        if self._can_merge_with(o):
            return (self._merge(o),)
        return self, o

    def _can_merge_with(self, o: Self):
        return (
            self._can_merge_ and o.__class__ is self.__class__ and o.__kwargs__ == self.__kwargs__
        )

    def _merge(self: Self, o: Self):
        if not self._can_merge_with(o):
            raise TypeError(f"{self!r}  be merged with {o!r}")
        return self._new_(self.__args__ + o.__args__, self.__kwargs__ | o.__kwargs__)

    def __call__(self, *a, **kw) -> _RT:
        raise NotImplementedError(f"{self!r} getter not supported")

    def get(self, obj: _T) -> _RT:
        return self(obj)

    def set(self, obj: _T, val: _RT):
        raise NotImplementedError(f"{self!r} setter not supported")

    def delete(self, obj: _T):
        raise NotImplementedError(f"{self!r} deleter not supported")

    def deconstruct(self):
        path = f"{self.__class__.__module__}.{self.__class__.__name__}"
        args, kwargs = self.__args__, dict(self.__kwargs__)
        d_args, d_kwargs = self._default_args_, self._default_kwargs_
        if d_args and len(d_args) == len(args):
            for i in range(len(d_args)):
                if args[i:] == d_args[i:]:
                    args = args[:i]
                    break
        for k, v in d_kwargs.items():
            if k in kwargs and kwargs[k] == v:
                del kwargs[k]

        return path, list(args), kwargs


class Attr(Signature[_RT, _T, _T_Attr], min_args=1):
    __slots__ = ()

    @classmethod
    def _parse_params_(cls, args, kwargs):
        return super()._parse_params_(
            (at for arg in args for at in (arg.split(".") if isinstance(arg, str) else (arg,))),
            kwargs,
        )

    def __call__(self, obj) -> _RT:
        args = self.args
        try:
            for arg in args:
                obj = getattr(obj, arg)
        except AttributeError as e:
            if (obj := self.__kwargs__.get("default", _notset)) is _notset:
                raise AttributeSignatureError(self) from e
        return obj

    def set(self, obj, val):
        args = self.args
        try:
            for arg in args[:-1]:
                obj = getattr(obj, arg)
            setattr(obj, args[-1], val)
        except AttributeError as e:
            raise AttributeSignatureError(self) from e

    def delete(self, obj):
        args = self.args
        try:
            for arg in args[:-1]:
                obj = getattr(obj, arg)
            delattr(obj, args[-1])
        except AttributeError as e:
            raise AttributeSignatureError(self) from e


class Item(Signature[_RT, _T_Key], min_args=1):
    __slots__ = ()

    def __call__(self, obj) -> _RT:
        args = self.args
        try:
            for arg in args:
                obj = obj[arg]
        except LookupError as e:
            if (obj := self.kwargs.get("default", _notset)) is _notset:
                cls = (
                    KeySignatureError
                    if isinstance(e, KeyError)
                    else IndexSignatureError
                    if isinstance(e, IndexError)
                    else LookupSignatureError
                )
                raise cls(self) from e
        return obj

    def set(self, obj, val):
        args = self.args
        try:
            for arg in args[:-1]:
                obj = obj[arg]
            obj[args[-1]] = val
        except LookupError as e:
            raise (
                KeySignatureError
                if isinstance(e, KeyError)
                else IndexSignatureError
                if isinstance(e, IndexError)
                else LookupSignatureError
            )(self) from e

    def delete(self, obj):
        args = self.args
        try:
            for arg in args[:-1]:
                obj = obj[arg]
            del obj[args[-1]]
        except LookupError as e:
            raise (
                KeySignatureError
                if isinstance(e, KeyError)
                else IndexSignatureError
                if isinstance(e, IndexError)
                else LookupSignatureError
            )(self) from e


class Slice(Item[_RT, slice], min_args=1):
    __slots__ = ("_args",)

    _slice_to_tuple = staticmethod(attrgetter("start", "stop", "step"))

    @classmethod
    def _slice_tuple(cls, obj):
        if isinstance(obj, slice):
            return cls._slice_to_tuple(obj)
        else:
            return tuple(obj)

    @classmethod
    def _parse_params_(cls, args, kwargs):
        args = map(cls._slice_tuple, args)
        return super()._parse_params_(args, kwargs)

    @property
    def args(self):
        try:
            return self._args
        except AttributeError:
            self._args = args = tuple(slice(*a) for a in self.__args__)
            return args


class Call(Signature, merge=False):
    __slots__ = ()

    def __call__(self, obj, /, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return obj(*a, *args, **kwargs | kw)


class Func(Signature[_RT, _T_Fn], min_args=1, merge=False):
    __slots__ = ()

    @property
    def func(self):
        return self.__args__[0]

    @property
    def args(self):
        return self.__args__[1:]

    def __call__(self, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return args[0](*a, *args[1:], **kwargs | kw)


class _ChainOptions(t.TypedDict, total=False):
    args: tuple
    kwargs: FrozenDict
    tap: int | tuple[int, int, int]


def _chain_reducer_(a: tuple[Signature], b: Signature):
    return a[:-1] + a[-1]._chain(b) if a else (b,)


class Chain(
    Signature[_RT, _T, Signature],
    abc.Sequence[Signature],
    kwargs={"args": (), "kwargs": FrozenDict(), "tap": -1},
):
    __slots__ = ()
    __kwargs__: _ChainOptions

    @classmethod
    def _parse_params_(cls, args: tuple[Signature], kwargs):
        args, kwargs = super()._parse_params_(args, kwargs)
        args = reduce(
            _chain_reducer_,
            (
                a
                for it in args
                for a in (
                    it
                    if isinstance(it, cls) and it.__kwargs__ == kwargs
                    else (it,)
                    if isinstance(it, Signature)
                    else it
                )
            ),
            (),
        )
        return args, kwargs

    @cached_attr
    def __call__(self) -> abc.Callable[[t.Any], _T]:
        return pipeline(self.__args__, **self.__kwargs__)

    @cached_attr
    def set(self):
        func = pipeline(self.__args__[:-1] + (self.__args__[-1].set,), **self.__kwargs__)
        ln = len(self.__args__)
        if not func.tap or func.tap.indices(ln) != (ln - 1, ln, 1):
            raise TypeError(f"chain must be tapped at the end to allow `__set__`")
        return func

    @cached_attr
    def delete(self):
        func = pipeline(self.__args__[:-1] + (self.__args__[-1].delete,), **self.__kwargs__)
        ln = len(self.__args__)
        if not func.tap or func.tap.indices(ln) != (ln - 1, ln, 1):
            raise TypeError(f"chain must be tapped at the end to allow `__delete__`")
        return func

    def __len__(self):
        return len(self.__args__)

    def __contains__(self, x):
        return x in self.__args__

    @t.overload
    def __getitem__(self, key: int) -> Signature:
        ...

    @t.overload
    def __getitem__(self, key: slice) -> Self:
        ...

    def __getitem__(self, key):
        val = self.__args__[key]
        if isinstance(key, slice):
            val = self._new_(val, self.__kwargs__)
        return val

    def __iter__(self):
        return iter(self.__args__)

    def __reversed__(self):
        return reversed(self.__args__)
