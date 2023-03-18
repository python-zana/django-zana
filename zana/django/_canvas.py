import math
import operator
import typing as t
from collections import ChainMap, abc
from functools import reduce
from logging import getLogger
from operator import attrgetter
from types import GenericAlias

from typing_extensions import Self as T_Self
from zana.types.collections import FrozenDict
from zana.utils import cached_attr, pipeline

_T = t.TypeVar("_T")
_RT = t.TypeVar("_RT")


_T_Arg = t.TypeVar("_T_Arg")
_T_Kwarg = t.TypeVar("_T_Kwarg", bound=FrozenDict, covariant=True)
_T_Key = t.TypeVar("_T_Key", slice, int, str, t.SupportsIndex, abc.Hashable)
_T_Fn = t.TypeVar("_T_Fn", bound=abc.Callable)
_T_Attr = t.TypeVar("_T_Attr", bound=str)

T_ManySignatures = list | tuple | abc.Sequence | abc.Iterator
T_OneOrManySignatures = T_ManySignatures

logger = getLogger(__name__)
_object_new = object.__new__
_empty_dict = FrozenDict()


class _notset(t.Protocol):
    pass


def ensure_signature(obj=_notset):
    if isinstance(obj, Signature):
        return obj
    elif obj is _notset:
        return Return()
    else:
        return Ref(obj)


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


class Signature(t.Generic[_RT, _T, _T_Arg, _T_Kwarg]):
    __slots__ = "__args__", "__kwargs__", "__dict__", "__weakref__"
    __class_getitem__ = classmethod(GenericAlias)

    __args__: t.Final[tuple[_T_Arg, ...]]
    __kwargs__: t.Final[_T_Kwarg]

    _min_args_: t.Final = 0
    _max_args_: t.Final = math.inf
    _default_args_: t.Final = ()
    _default_kwargs_: t.Final = FrozenDict()
    _required_kwargs_: t.Final = frozenset[str]()
    _extra_kwargs_: t.Final = False
    _allowed_kwargs_: t.Final = frozenset[str]()
    _allows_merging_: t.Final[bool] = True
    _merge_types_: t.Final[set[type[T_Self]]]

    if t.TYPE_CHECKING:
        __args__ = __kwargs__ = None

    def __init_subclass__(
        cls,
        args=None,
        kwargs=None,
        required_kwargs=None,
        min_args=None,
        max_args=None,
        extra_kwargs=None,
        merge=None,
        **kwds,
    ) -> None:
        super().__init_subclass__(**kwds)
        if merge is not None:
            cls._allows_merging_ = not not merge

        if cls._allows_merging_:
            cls._merge_types_ = set(cls)
        else:
            cls._merge_types_ = frozenset()

        if min_args is not None:
            cls._min_args_ = min_args
        if max_args is not None:
            cls._max_args_ = max_args

        if args is not None:
            cls._default_args_ = tuple(args.split() if isinstance(args, str) else args)
        if kwargs is not None:
            cls._default_kwargs_ = FrozenDict(kwargs)

        if required_kwargs is not None:
            cls._required_kwargs_ = dict.fromkeys(
                args.split() if isinstance(args, str) else args
            ).keys()

        if extra_kwargs is not None:
            cls._extra_kwargs_ = not not extra_kwargs

        if cls._extra_kwargs_:
            cls._allowed_kwargs_ = cls._default_kwargs_.keys()
        else:
            cls._allowed_kwargs_ = {}.keys()

    @classmethod
    def construct(cls, args=(), kwargs=FrozenDict()):
        self: cls = _object_new(cls)
        self.__args__, self.__kwargs__ = args, kwargs
        return self

    # @classmethod
    # def _parse_params_(cls, args, kwargs) -> tuple[tuple[_T_Arg, ...], FrozenDict[str, _T_Kwarg]]:
    #     args, kwargs = tuple(args), FrozenDict(kwargs)

    def __new__(cls: type[T_Self], *args, **kwargs) -> T_Self:
        args, kwargs = tuple(args), FrozenDict(kwargs)

        if not (cls._min_args_ <= len(args) <= cls._max_args_):
            raise TypeError(
                f"{cls.__name__} expected "
                f"{' to '.join(map(str, {cls._min_args_, cls._max_args_}))}"
                f" arguments but got {len(args)}."
            )
        elif d_args := cls._default_args_:
            args = args + d_args[len(args) :]

        kw_keys = kwargs.keys()
        if missed := cls._required_kwargs_ - kw_keys:
            missed, s = list(map(repr, missed)), "s" if len(missed) > 1 else ""
            raise TypeError(
                f"{cls.__name__} is missing required keyword only argument{s} "
                f"{' and '.join(filter(None, (', '.join(missed[:-1]), missed[-1])))}."
            )
        elif extra := cls._extra_kwargs_ is False and kw_keys - cls._allowed_kwargs_:
            extra, s = list(map(repr, extra)), "s" if len(missed) > 1 else ""
            allowed = list(map(repr, cls._allowed_kwargs_))
            raise TypeError(
                f"{cls.__name__} got unexpected keyword only argument{s} "
                f"{' and '.join(filter(None, (', '.join(extra[:-1]), extra[-1])))}. "
                f"Allowed "
                f"{' and '.join(filter(None, (', '.join(allowed[:-1]), allowed[-1])))}."
            )
        elif d_kwargs := cls._default_kwargs_:
            kwargs = d_kwargs | kwargs

        return cls.construct(args, FrozenDict(kwargs))

    @property
    def __ident__(self):
        return self.__args__, self.__kwargs__

    def _(self):
        return self

    def extend(self, *args, **kwds):
        return self.__class__(*self.__args__, *args, **self.__kwargs__ | kwds)

    def __repr__(self):
        params = map(repr, self.__args__), (f"{k}={v!r}" for k, v in self.__kwargs__.items())
        return f"{self.__class__.__name__}({', '.join(p for ps in params for p in ps)})"

    def __reduce__(self):
        return self.__class__.construct, (self.__args__, self.__kwargs__)

    def __copy__(self):
        return self.construct(self.__args__, self.__kwargs__)

    def __eq__(self, o: T_Self) -> bool:
        return o.__class__ is self.__class__ and o.__ident__ == self.__ident__

    def __ne__(self, o: T_Self) -> bool:
        return o.__class__ is not self.__class__ or o.__ident__ != self.__ident__

    def __hash__(self) -> int:
        return hash(self.__ident__)

    def __add__(self, o: T_OneOrManySignatures):
        if o.__class__ is self.__class__ and o.__kwargs__ == self.__kwargs__:
            return self.construct(self.__args__ + o.__args__, self.__kwargs__)
        return NotImplemented

    # def __radd__(self, o: T_OneOrManySignatures):
    #     if o.__class__ is self.__class__ and o.__kwargs__ == self.__kwargs__:
    #         return self.construct(o.__args__ + self.__args__, self.__kwargs__)
    #     return NotImplemented

    def __or__(self, o):
        if isinstance(o, Signature):
            if self.can_merge(o):
                return self._merge(o)
            return Chain(self, o)._()
        elif isinstance(o, T_ManySignatures):
            return Chain(self, *o)._()
        return NotImplemented

    def __ror__(self, o):
        if not isinstance(o, T_OneOrManySignatures):
            return NotImplemented
        return Chain(*o, self)._()

    def can_merge(self, o: T_Self):
        return o.__class__ in self._merge_types_ and o.__kwargs__ == self.__kwargs__

    def merge(self: T_Self, o: T_Self):
        if not self.can_merge(o):
            raise TypeError(f"{self!r}  be merged with {o!r}")
        return self._merge(o)

    def _merge(self, o):
        return self.construct(self.__args__ + o.__args__, self.__kwargs__ | o.__kwargs__)

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


T_OneOrManySignatures = Signature | T_OneOrManySignatures


class Ref(Signature[_RT, _RT, _RT, None], t.Generic[_RT], min_args=1):
    __slots__ = ()

    def __new__(cls, object: _RT):
        return cls.construct((object,))

    def __call__(this, /, self=None) -> _RT:
        return this.__args__[0]

    def __radd__(self, o: T_OneOrManySignatures):
        if isinstance(o, Signature):
            return self
        return NotImplemented

    def _merge(self, o: T_Self):
        return o


class Return(Signature[_RT, _RT, _RT, None], t.Generic[_RT]):
    __slots__ = ()

    def __new__(cls):
        return cls.construct()

    def __call__(this, /, self: _RT) -> _RT:
        return self

    def __add__(self, o: T_OneOrManySignatures):
        if o.__class__ is self.__class__:
            return o
        return NotImplemented

    def _merge(self, o: T_Self):
        return o


class Attr(Signature[_RT, _T, _T_Attr], min_args=1, kwargs={"default": _notset}):
    __slots__ = ()

    def __new__(cls, *args, **kwargs):
        return super()._parse_params_(
            (at for arg in args for at in (arg.split(".") if isinstance(arg, str) else (arg,))),
            kwargs,
        )

    def __call__(self, obj) -> _RT:
        __tracebackhide__ = True
        args = self.__args__
        try:
            for arg in args:
                obj = getattr(obj, arg)
        except AttributeError as e:
            if (obj := self.__kwargs__["default"]) is _notset:
                raise AttributeSignatureError(self) from e
        return obj

    def set(self, obj, val):
        __tracebackhide__ = True
        args = self.__args__
        try:
            for arg in args[:-1]:
                obj = getattr(obj, arg)
            setattr(obj, args[-1], val)
        except AttributeError as e:
            raise AttributeSignatureError(self) from e

    def delete(self, obj):
        __tracebackhide__ = True
        args = self.__args__
        try:
            for arg in args[:-1]:
                obj = getattr(obj, arg)
            delattr(obj, args[-1])
        except AttributeError as e:
            raise AttributeSignatureError(self) from e


class Item(Signature[_RT, _T_Key], min_args=1, kwargs={"default": _notset}):
    __slots__ = ()

    def __call__(self, obj) -> _RT:
        __tracebackhide__ = True
        args = self.__args__
        try:
            for arg in args:
                obj = obj[arg]
        except LookupError as e:
            if (obj := self.__kwargs__["default"]) is _notset:
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
        __tracebackhide__ = True
        args = self.__args__
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
        __tracebackhide__ = True
        args = self.__args__
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


_slice_to_tuple = attrgetter("start", "stop", "step")


def _to_slice(val):
    __tracebackhide__ = True
    if isinstance(val, slice):
        return val
    elif isinstance(val, int):
        return slice(val, (val + 1) or None)
    else:
        return slice(*val)


class Slice(Item[_RT, slice], min_args=1):
    __slots__ = ()

    @classmethod
    def _parse_params_(cls, args, kwargs):
        __tracebackhide__ = True
        args, kwargs = super()._parse_params_(map(_to_slice, args), kwargs)
        if kwargs != cls._default_kwargs_:
            names, s = list(map(repr, kwargs)), "s" if len(kwargs) > 1 else ""
            names = " and ".join(filter(None, (", ".join(names[:-1]), names[-1])))
            raise TypeError(f"{cls.__name__} got unexpected keyword argument{s} {names}")
        return args, kwargs

    def __hash__(self) -> int:
        return hash(tuple(map(_slice_to_tuple, self.__args__)))

    def deconstruct(self):
        path, args, kwargs = super().deconstruct()
        args = [_slice_to_tuple(s) for s in args]
        return path, args, kwargs


class Call(Signature, merge=False):
    __slots__ = ()

    def __call__(self, obj, /, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return obj(*a, *args, **kwargs | kw)


class Func(Signature[_RT, _T_Fn], min_args=1, merge=False):
    __slots__ = ()

    @property
    def __wrapped__(self):
        return self.__args__[0]

    def __call__(self, /, *a, **kw):
        args, kwargs = self.__args__, self.__kwargs__
        return args[0](*a, *args[1:], **kwargs | kw)


_builtin_operator_names = {
    "__lt__": "lt",
    "__le__": "le",
    "__eq__": "eq",
    "__ne__": "ne",
    "__ge__": "ge",
    "__gt__": "gt",
    "__not__": "not_",
    "__abs__": "abs",
    "__add__": "add",
    "__and__": "and_",
    "__floordiv__": "floordiv",
    "__index__": "index",
    "__inv__": "inv",
    "__invert__": "invert",
    "__lshift__": "lshift",
    "__mod__": "mod",
    "__mul__": "mul",
    "__matmul__": "matmul",
    "__neg__": "neg",
    "__or__": "or_",
    "__pos__": "pos",
    "__pow__": "pow",
    "__rshift__": "rshift",
    "__sub__": "sub",
    "__truediv__": "truediv",
    "__xor__": "xor",
    "__concat__": "concat",
    "__contains__": "contains",
    "__delitem__": "delitem",
    "__getitem__": "getitem",
    "__setitem__": "setitem",
    "__iadd__": "iadd",
    "__iand__": "iand",
    "__iconcat__": "iconcat",
    "__ifloordiv__": "ifloordiv",
    "__ilshift__": "ilshift",
    "__imod__": "imod",
    "__imul__": "imul",
    "__imatmul__": "imatmul",
    "__ior__": "ior",
    "__ipow__": "ipow",
    "__irshift__": "irshift",
    "__isub__": "isub",
    "__itruediv__": "itruediv",
    "__ixor__": "ixor",
}

_builtin_operators = {k: getattr(operator, k) for k in _builtin_operator_names.values()}

_builtin_operator_names = FrozenDict(
    _builtin_operator_names | {v: k for k, v in _builtin_operators.items()}
)
_builtin_operators = FrozenDict(_builtin_operators)
_user_operators, _user_operators_names = {}, {}


ALL_OPERATORS = ChainMap(_builtin_operators, _user_operators)


OperationOptions = t.TypedDict("OperationOptions", operator=str)


class Operation(
    Signature[_RT, _T, Signature, OperationOptions],
    min_args=1,
    kwargs={"operator": _notset},
    required_kwargs="operator",
):
    @classmethod
    def _parse_params_(cls, args, kwargs) -> tuple[tuple[_T_Arg, ...], FrozenDict[str, _T_Kwarg]]:
        args, kwargs = super()._parse_params_(args, kwargs)
        if args[0] not in ALL_OPERATORS:
            raise ValueError(f"invalid operator name {args[0]}")
        return args, kwargs

    @property
    def operator(self):
        return ALL_OPERATORS[self.__kwargs__["operator"]]

    __wrapped__ = operator

    def __call__(this, /, self):
        return this.operator(*(o(self) for o in this.__args__))


class ChainOptions(t.TypedDict, total=False):
    args: tuple
    kwargs: FrozenDict
    tap: int | tuple[int, int, int]


def _merge_chain_args(a: tuple[Signature], b: Signature):
    if not a:
        return (b,)
    elif isinstance(o := a[-1], Signature) and o.can_merge(b):
        return a[:-1] + (o.merge(b, _check=False),)
    else:
        return a + (b,)


class Chain(
    Signature[_RT, _T, Signature, ChainOptions],
    abc.Sequence[Signature],
    kwargs={"args": (), "kwargs": FrozenDict(), "tap": -1},
):
    __slots__ = ()

    @classmethod
    def _parse_params_(cls, args: tuple[Signature], kwargs):
        args, kwargs = super()._parse_params_(args, kwargs)
        args = reduce(
            _merge_chain_args,
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

    def _(self):
        return args[0] if len(args := self.__args__) == 1 else self

    def __str__(self) -> str:
        return " | ".join(map(repr, self))

    def __len__(self):
        return len(self.__args__)

    def __contains__(self, x):
        return x in self.__args__

    @t.overload
    def __getitem__(self, key: int) -> Signature:
        ...

    @t.overload
    def __getitem__(self, key: slice) -> T_Self:
        ...

    def __getitem__(self, key):
        val = self.__args__[key]
        if isinstance(key, slice):
            val = self.construct(val, self.__kwargs__)
        return val

    def __iter__(self):
        return iter(self.__args__)

    def __reversed__(self):
        return reversed(self.__args__)


class SupportsSignature(t.Protocol[_RT]):
    def _(self) -> Signature[_RT]:
        ...


def _var_operator_method(nm, op):
    def method(self: Var, /, *args):
        return self.__extend__(Operation(*map(ensure_signature, args), operator=op))

    method.__name__ = nm
    return method


class Var(t.Generic[_T, _RT]):
    __slots__ = ("_Var__signature",)
    __signature: Signature[_RT]

    __class_getitem__ = classmethod(GenericAlias)

    for nm, op in _builtin_operator_names.items():
        vars()[nm] = _var_operator_method(nm, op)
    del nm, op

    def __new__(cls: type[T_Self], sig: Signature[_RT] = Chain()) -> _T | SupportsSignature[_RT]:
        self = _object_new(cls)
        object.__setattr__(self, "_Var__signature", sig)
        return self

    def _(self):
        return self.__signature

    def __extend__(self, *expr):
        return self.__class__(self.__signature | expr)

    def __getattr__(self, name: str):
        return self.__extend__(Attr(name))

    def __getitem__(self, key):
        cls = Slice if isinstance(key, slice) else Item
        return self.__extend__(cls(key))

    def __call__(self, /, *args, **kwargs):
        return self.__extend__(Call(*args, **kwargs))

    def __or__(self, o):
        return self.__extend__(Operation(ensure_signature(o), operator="or_"))

    def __add__(self, o):
        return self.__extend__(Operation(ensure_signature(o), operator="add"))
