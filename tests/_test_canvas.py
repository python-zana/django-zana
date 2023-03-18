import math
from collections import abc
from copy import copy, deepcopy
from operator import or_
from types import SimpleNamespace
from unittest.mock import Mock

import pytest as pyt
from zana.common import try_import
from zana.types.collections import FrozenDict

from zana.django.canvas import (
    Attr,
    AttributeSignatureError,
    Call,
    Chain,
    Func,
    IndexSignatureError,
    Item,
    KeySignatureError,
    Signature,
    Slice,
)


class test_Signature:
    def test_config(self):
        assert Signature._allows_merging_ is True
        assert Signature._min_args_ == 0
        assert Signature._max_args_ == math.inf
        assert Signature._default_args_ == ()
        assert Signature._default_kwargs_ == {}

        class Plain(Signature):
            pass

        assert Plain._allows_merging_ == Signature._allows_merging_
        assert Plain._min_args_ == Signature._min_args_
        assert Plain._max_args_ == Signature._max_args_
        assert Plain._default_args_ == Signature._default_args_
        assert Plain._default_kwargs_ == Signature._default_kwargs_
        assert Plain._required_kwargs_ == Signature._required_kwargs_

        kwds = {
            "merge": False,
            "min_args": 1,
            "max_args": 5,
            "args": (Mock(), Mock()),
            "kwargs": {"x": Mock(), "y": Mock()},
            "required_kwargs": ("z",),
        }

        class Sub(Signature, **kwds):
            pass

        assert Sub._allows_merging_ == kwds["merge"]
        assert Sub._min_args_ == kwds["min_args"]
        assert Sub._max_args_ == kwds["max_args"]
        assert Sub._default_args_ == kwds["args"]
        assert Sub._default_kwargs_ == kwds["kwargs"]
        assert Sub._required_kwargs_ == frozenset(kwds["required_kwargs"])

        pyt.raises(TypeError, Sub)
        pyt.raises(TypeError, Sub, Mock())
        pyt.raises(TypeError, Sub, z=Mock())

        sig = Sub(Mock(), z=Mock())
        d_path, d_args, d_kwargs = sig.deconstruct()
        assert sig == Sub(*d_args, **d_kwargs)

        pyt.raises(TypeError, sig.merge, Plain())

    def test_basic(self):
        args, kwargs = tuple(Mock() for i in range(3)), {k: Mock() for k in "abc"}
        args_2 = tuple(Mock() for i in range(2))

        class Foo(Signature):
            pass

        class Bar(Foo):
            pass

        foo, foo_2, bar = Foo(*args, **kwargs), Foo(*args_2, **kwargs), Bar(*args, **kwargs)
        print(str(foo), repr(bar))
        assert isinstance(foo, Foo)
        assert isinstance(bar, Bar)
        assert isinstance(foo.__args__, tuple)
        assert isinstance(foo.__kwargs__, FrozenDict)
        assert foo.__ident__ == (foo.__args__, foo.__kwargs__) == (args, kwargs) == bar.__ident__
        assert foo == Foo(*args, **kwargs) == copy(foo)
        assert not foo != Foo(*args, **kwargs)
        assert foo != bar
        assert not foo == bar
        assert not foo == args, kwargs
        assert foo != args, kwargs
        assert foo.can_merge(foo_2)
        assert foo.merge(foo_2) == Foo(*args, *args_2, **kwargs) == foo.extend(*args_2)
        assert {Foo(*args, *args_2, **kwargs)} == {
            foo.merge(foo_2),
            foo.extend(*args_2, **kwargs),
            foo | foo_2,
            foo | [foo_2],
            [foo] | foo_2,
            foo | iter([foo_2]),
            iter([foo]) | foo_2,
        }

        pyt.raises(TypeError, or_, foo, object())
        pyt.raises(TypeError, or_, foo, {foo_2: None})
        pyt.raises(TypeError, or_, foo, set([foo_2]))

        pyt.raises(TypeError, or_, object(), foo)
        pyt.raises(TypeError, or_, {foo_2: None}, foo)
        pyt.raises(TypeError, or_, set([foo_2]), foo)

        assert [*(foo | bar)] == [foo, bar]
        assert foo.deconstruct() == (f"{__name__}.Foo", [*args], kwargs)


class test_Attr:
    def test_basic(self):
        cls, ex, args = Attr, Mock(tuple[str]), ("foo.bar.x",)
        sig = cls(*args)

        print(str(sig), repr(sig))
        assert isinstance(sig, cls)

        d_path, d_args, d_kwargs = sig.deconstruct()
        assert (
            sig
            == copy(sig)
            == deepcopy(sig)
            == Attr("foo.bar", "x")
            == Attr("foo", "bar", "x")
            == Attr("foo", "bar.x")
            == try_import(d_path)(*d_args, **d_kwargs)
        )
        assert {cls(*args, ex)} == {
            sig.extend(ex),
            sig.merge(cls(ex)),
            sig | cls(ex),
            sig | [cls(ex)],
            [sig] | cls(ex),
        }
        pyt.raises(TypeError, cls)

    def test_get_set_delete(self):
        default, x, y, z = Mock(), Mock(), Mock(), Mock()
        bar = SimpleNamespace(x=x, y=y)
        foo = SimpleNamespace(bar=bar)
        obj = SimpleNamespace(foo=foo)
        sig = Attr("foo.bar.x")

        val_x = sig(obj)
        assert val_x == x == sig.get(obj) == bar.x
        sig.set(obj, z)
        assert sig(obj) == z == sig.get(obj)
        sig.delete(obj)
        assert not hasattr(obj.foo.bar, "x")

        pyt.raises(AttributeSignatureError, sig, obj)
        pyt.raises(AttributeSignatureError, sig.get, obj)

        pyt.raises(AttributeSignatureError, sig, foo)
        pyt.raises(AttributeSignatureError, sig.get, foo)
        pyt.raises(AttributeSignatureError, sig.set, foo, z)
        pyt.raises(AttributeSignatureError, sig.delete, foo)

        sig = sig.extend(default=default)
        assert sig(obj) == sig(foo) == default == sig.get(foo) == sig.get(obj)

    def test_chaining(self):
        default = Mock()
        foo, bar, baz = Attr("foo"), Attr("bar"), Attr("baz", default=default)
        foo_bar = (foo | bar, bar | foo)
        assert all(isinstance(x, Attr) for x in foo_bar)
        foo_baz = (foo | baz, baz | foo)
        assert all(isinstance(x, Chain) for x in foo_baz)
        assert [*map(list, foo_baz)] == [[foo, baz], [baz, foo]]
        assert foo.extend(default=default) | baz == Attr("foo.baz", default=default)


class test_Item:
    def test_basic(self):
        cls, ex, args = Item, Mock(str), (-1, "bar", "x")
        sig = cls(*args)

        print(str(sig), repr(sig))
        assert isinstance(sig, cls)

        d_path, d_args, d_kwargs = sig.deconstruct()
        assert sig == copy(sig) == deepcopy(sig) == try_import(d_path)(*d_args, **d_kwargs)
        assert {cls(*args, ex)} == {
            sig.extend(ex),
            sig.merge(cls(ex)),
            sig | cls(ex),
            sig | [cls(ex)],
            [sig] | cls(ex),
        }
        pyt.raises(TypeError, cls)

    def test_get_set_delete(self):
        default, x, y, z = Mock(), Mock(), [Mock()], Mock()
        bar = dict(x=x, y=y)
        foo = dict(bar=bar)
        obj = [Mock, foo]
        sig = Item(-1, "bar", "x")

        val_x = sig(obj)
        assert val_x == x == sig.get(obj) == bar["x"]
        sig.set(obj, z)
        assert sig(obj) == z == sig.get(obj) == bar["x"]
        sig.delete(obj)
        assert "x" not in bar

        pyt.raises(KeySignatureError, sig, obj)
        pyt.raises(KeySignatureError, sig.get, obj)

        pyt.raises(KeySignatureError, sig, foo)
        pyt.raises(KeySignatureError, sig.get, foo)
        pyt.raises(KeySignatureError, sig.set, foo, z)
        pyt.raises(KeySignatureError, sig.delete, foo)

        sig = sig.extend(default=default)
        assert sig(obj) == sig(foo) == default == sig.get(foo) == sig.get(obj)
        pyt.raises(IndexSignatureError, Item(-1, "bar", "y", 2), obj)

    def test_chaining(self):
        default = Mock()
        foo, bar, baz = Item("foo"), Item("bar"), Item("baz", default=default)
        foo_bar = (foo | bar, bar | foo)
        assert all(isinstance(x, Item) for x in foo_bar)
        foo_baz = (foo | baz, baz | foo)
        assert all(isinstance(x, Chain) for x in foo_baz)
        assert [*map(list, foo_baz)] == [[foo, baz], [baz, foo]]
        assert foo.extend(default=default) | baz == Item("foo", "baz", default=default)


class test_Slice:
    def test_basic(self):
        cls, ex, args = Slice, Mock(slice), (slice(0, 3), (None, None, -1), (0, 2))
        sig = cls(*args)

        print(str(sig), repr(sig))
        assert isinstance(sig, cls)

        d_path, d_args, d_kwargs = sig.deconstruct()
        assert sig == copy(sig) == deepcopy(sig) == try_import(d_path)(*d_args, **d_kwargs)
        assert {cls(*args, ex)} == {
            sig.extend(ex),
            sig.merge(cls(ex)),
            sig | cls(ex),
            sig | [cls(ex)],
            [sig] | cls(ex),
        }
        pyt.raises(TypeError, cls)

    def test_get_chain(self):
        w, x, y, z = Mock(), Mock(), Mock(), Mock()
        obj = [w, x, y, z]
        sig = Slice(slice(0, 3), (None, None, -1), (0, 2))

        val = sig(obj)
        assert val == [y, x] == sig.get(obj)

    def test_get_set_delete(self):
        w, x, y, z = Mock(), Mock(), Mock(), Mock()
        a, b = Mock(), Mock()
        obj = [w, x, y, z]
        sig = Slice(slice(1, 3))
        val = sig(obj)
        assert val == [x, y] == obj[1:3] == sig.get(obj)
        sig.set(obj, [a, b])
        assert sig(obj) == obj[1:3] == [a, b]
        sig.delete(obj)
        assert obj == [w, z]


class test_Chain:
    def test_basic(self):
        cls, ex, args, flat_args = (
            Chain,
            Signature(),
            (Item(0, 3), Slice((None, None, -1)), Attr("abc", "xyz")),
            (Item(0), Item(3), Slice((None, None, -1)), Attr("abc"), Attr("xyz")),
        )
        sig = cls(*args)

        print(str(sig), repr(sig))
        assert isinstance(sig, cls)

        d_path, d_args, d_kwargs = sig.deconstruct()
        assert (
            sig
            == sig[:]
            == cls(reversed(sig))[::-1]
            == copy(sig)
            == deepcopy(sig)
            == try_import(d_path)(*d_args, **d_kwargs)
            == cls(*flat_args)
        )
        assert all(a in sig for a in args)

        assert {cls(*args, ex)} == {
            sig.extend(ex),
            sig.merge(cls(ex)),
            sig | cls(ex),
            sig | [cls(ex)],
            iter(sig) | cls(ex),
        }

    def test_get_set_delete(self):
        w, x, y, z = Mock(), Mock(), Mock(), Mock()
        a, b = Mock(), Mock()
        bar = SimpleNamespace(x=x, y=y)
        foo = dict(bar=bar)
        obj = [w, foo, z]
        sig = Chain(Item(1), Item("bar"), Attr("x"))

        val = sig(obj)
        assert val == x == sig.get(obj)
        sig.set(obj, z)
        assert sig(obj) == z == sig.get(obj)
        sig.delete(obj)

        assert not hasattr(bar, "x")
        pyt.raises(AttributeSignatureError, sig, obj)

        ex_sig = sig.extend(tap=0)
        pyt.raises(TypeError, lambda: ex_sig.set(obj, z))
        pyt.raises(TypeError, lambda: ex_sig.delete(obj))


class test_Call:
    def test_basic(self):
        cls, args, kwargs = Call, (1, 2, 3), dict(zip("xyz", "XYZ"))
        ex_args, ex_kwargs = (Mock(int), Mock(float), Mock(tuple)), {k: Mock(str) for k in "zab"}
        sig = cls(*args, **kwargs)

        print(str(sig), repr(sig))
        assert isinstance(sig, cls)

        d_path, d_args, d_kwargs = sig.deconstruct()
        assert sig == copy(sig) == deepcopy(sig) == try_import(d_path)(*d_args, **d_kwargs)
        assert {cls(*args, *ex_args, **kwargs | ex_kwargs)} == {sig.extend(*ex_args, **ex_kwargs)}

    def test_get(self):
        args, kwargs = (Mock(int), Mock(float), Mock(tuple)), {k: Mock(str) for k in "abc"}
        c_args, c_kwargs = (Mock(int), Mock(float), Mock(tuple)), {k: Mock(str) for k in "xyz"}
        obj = Mock(abc.Callable)
        sig = Call(*args, **kwargs)
        # assert (sig.args, sig.kwargs) == (args, kwargs)
        val = sig(obj, *c_args, **c_kwargs)
        obj.assert_called_once_with(*c_args, *args, **kwargs | c_kwargs)
        assert val == obj.return_value == sig.get(obj)

    def test_set_delete(self):
        sig, obj = Call(), Mock()
        pyt.raises(NotImplementedError, lambda: sig.set(obj, Mock()))
        pyt.raises(NotImplementedError, lambda: sig.delete(obj))


class test_Func:
    def test_basic(self):
        cls, args, kwargs = Func, (1, 2, 3), dict(zip("xyz", "XYZ"))
        ex_args, ex_kwargs = (Mock(int), Mock(float), Mock(tuple)), {k: Mock(str) for k in "zab"}
        sig = cls(dict, *args, **kwargs)

        print(str(sig), repr(sig))
        assert isinstance(sig, cls)

        assert sig.__wrapped__ is dict

        d_path, d_args, d_kwargs = sig.deconstruct()
        assert sig == copy(sig) == deepcopy(sig) == try_import(d_path)(*d_args, **d_kwargs)
        assert {cls(dict, *args, *ex_args, **kwargs | ex_kwargs)} == {
            sig.extend(*ex_args, **ex_kwargs)
        }

    def test_get(self):
        args, kwargs = (Mock(int), Mock(float), Mock(tuple)), {k: Mock(str) for k in "abc"}
        c_args, c_kwargs = (Mock(int), Mock(float), Mock(tuple)), {k: Mock(str) for k in "xyz"}
        obj = Mock(abc.Callable)
        sig = Func(obj, *args, **kwargs)
        val = sig(*c_args, **c_kwargs)
        obj.assert_called_once_with(*c_args, *args, **kwargs | c_kwargs)
        assert val == obj.return_value == sig.get(obj)

    def test_set_delete(self):
        sig, obj = Func(Mock()), Mock()
        pyt.raises(NotImplementedError, lambda: sig.set(obj, Mock()))
        pyt.raises(NotImplementedError, lambda: sig.delete(obj))
