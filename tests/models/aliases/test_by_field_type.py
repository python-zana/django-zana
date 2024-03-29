import typing as t
from types import UnionType
from uuid import UUID

import pytest as pyt
from zana.types.collections import DefaultDict, ReadonlyDict

from django.db import models as m
from tests.app.models import ExprSource as Src
from tests.app.models import T_Func, TestModel
from zana.django.models import AliasField

_VT = t.TypeVar("_VT", covariant=True)
_FT = t.TypeVar("_FT", bound=m.Field, covariant=True)
_MT = t.TypeVar("_MT", bound=TestModel, covariant=True)

_TF_Target = t.Literal["field", "json"]

pytestmark = [
    pyt.mark.django_db,
]


@pyt.fixture
def to_python(field):
    return TestModel.get_field(field, m.Field()).to_python


@pyt.fixture
def factory(factories, field):
    return factories[field]


@pyt.fixture
def field_name(field: type):
    return TestModel.get_field_name(field)


@pyt.fixture
def through():
    return ""


@pyt.fixture
def expression(field_name: str, through: str, field: m.Field, source: Src):
    through = f"{through}__".lstrip("_")
    match source:
        case Src.JSON:
            return f"{through}json__{field_name}"
        case Src.EVAL:
            return m.Case(
                m.When(
                    m.Q(**{f"{through}{field_name}__isnull": False}),
                    then=m.F(f"{through}{field_name}"),
                ),
                default=m.Value(None),
            )
        case _:
            return f"{through}{field_name}"


@pyt.fixture
def type_var(source: Src, field):
    if source != Src.FIELD:
        return field


@pyt.fixture
def cls(source: Src, field, type_var):
    return AliasField[type_var] if type_var is not None else AliasField


@pyt.fixture
def def_kwargs():
    return {}


@pyt.fixture
def define(source: Src, field, new, def_kwargs):
    def_kwargs = {"source": source, "field_type": field, **def_kwargs}

    def func(test=def_kwargs.pop("test", None), **kw):
        test = new() if test is None else test
        return TestModel.define(test=test, **def_kwargs | kw)

    return func


@pyt.fixture
def new(cls: type[AliasField], expression, kwargs: dict):
    def func(expression=expression, **kw):
        return cls(expression, **kwargs | kw)

    return func


@pyt.fixture
def model(define: T_Func[type[AliasField]]):
    return define()


@pyt.fixture
def kwargs(request: pyt.FixtureRequest, field, source):
    self: FieldTestCase = request.instance
    skw = getattr(self, f"{source}_source_kwargs", {})
    return {
        **self.default_kwargs,
        **self.default_source_kwargs.get(m.Field, {}),
        **self.default_source_kwargs.get(field, {}),
        **skw.get(m.Field, {}),
        **skw.get(field, {}),
    }


def test_coverage():
    assert True


@pyt.mark.field_cov(Src.FIELD, Src.EVAL, Src.JSON)
class FieldTestCase(t.Generic[_VT, _FT, _MT]):
    field_types: t.ClassVar[tuple[type[_FT]]]
    data_type: t.ClassVar[type[_VT]]
    all_sources: t.ClassVar = (Src.FIELD, Src.EVAL, Src.JSON)
    source_support: t.ClassVar = DefaultDict[type[_FT], bool]((), True)
    fixture: pyt.FixtureRequest
    default_kwargs: dict = ReadonlyDict()
    default_source_kwargs: dict = ReadonlyDict()
    json_source_kwargs: dict = ReadonlyDict()
    field_source_kwargs: dict = ReadonlyDict()

    source: Src
    field: type[_FT]

    def __init_subclass__(cls) -> None:
        if ob := cls.__orig_bases__:
            if args := ob[0].__args__:
                if "field_types" not in cls.__dict__:
                    if isinstance(arg := args[1], UnionType):
                        if all(
                            isinstance(a, type) and issubclass(a, m.Field)
                            for a in arg.__args__
                        ):
                            cls.field_types = tuple(arg.__args__)
                    elif isinstance(arg, type) and issubclass(arg, m.Field):
                        cls.field_types = (arg,)
                if "data_type" not in cls.__dict__:
                    if not isinstance(arg := args[0], t.TypeVar):
                        cls.data_type = arg

        if "field_fixture" not in cls.__dict__ and cls.field_types:

            @pyt.fixture(
                name="field",
                params=cls.field_types,
                ids=[f.__name__ for f in cls.field_types],
            )
            def field_fixture(self, request: pyt.FixtureRequest):
                return request.param

            cls.field_fixture = field_fixture

        if "source_fixture" not in cls.__dict__ and cls.all_sources:

            @pyt.fixture(name="source", params=cls.all_sources)
            def source_fixture(self: cls, request: pyt.FixtureRequest, field: type):
                if self.source_support[(source := request.param), field]:
                    return source
                pyt.skip(f"{field.__name__!r} does not support source {source!r}")

            cls.source_fixture = source_fixture
        super().__init_subclass__()

    # @pyt.mark.skip("")
    def test_basic(self, model: type[TestModel], field: type[_FT]):
        test, proxy = t.cast(
            list[type[AliasField]], [model.get_field("test"), model.get_field("proxy")]
        )
        # Ensure the field type automatically maps
        assert isinstance(test.get_internal_field(), field)
        # assert isinstance(proxy.get_internal_field(), field)

    # @pyt.mark.skip("")
    def test_direct_access(self, factory: T_Func[_VT], model: type[TestModel]):
        qs = model.objects.all()
        val_0, val_1 = factory(), factory()
        obj_0, obj_1 = (qs.create(value=v) for v in (val_0, val_1))

        # Test the values of each object
        for obj, expected in ((obj_0, val_0), (obj_1, val_1)):
            assert obj.value == expected
            assert obj.test == expected
            assert obj.proxy == expected

        # Test query return values
        for obj, expected in ((obj_0, val_0), (obj_1, val_1)):
            t_obj, p_obj = qs.get(test=expected), qs.get(proxy=expected)
            assert (
                (obj.pk, expected)
                == qs.annotate("test").values_list("pk", "test").get(test=expected)
                == (t_obj.pk, t_obj.test)
                == qs.annotate("proxy").values_list("pk", "proxy").get(proxy=expected)
                == (p_obj.pk, p_obj.proxy)
            )

        # swap values of the 2 objects and refresh
        for obj, expected in ((obj_0, val_1), (obj_1, val_0)):
            obj.value = expected
            obj.save()

        # Test the swapped values
        for obj, expected in ((obj_0, val_1), (obj_1, val_0)):
            assert obj.value == expected
            assert obj.test == expected
            assert obj.proxy == expected

    @pyt.mark.parametrize("through", ["foreignkey", "onetoonefield"])
    def test_fk_access(self, through, factory: T_Func[_VT], model: type[_MT]):
        qs = model.objects.all()

        val_0, val_1 = factory(), factory()
        rel_0, rel_1 = (qs.create(value=v) for v in (val_0, val_1))
        obj_0, obj_1 = (qs.create(**{through: r}) for r in (rel_0, rel_1))

        # Test the related (real) values of each object
        for rel, expected in ((rel_0, val_0), (rel_1, val_1)):
            assert rel.value == expected

        # Test the values of each object
        for obj, expected in ((obj_0, val_0), (obj_1, val_1)):
            assert obj.test == expected
            assert obj.proxy == expected

        # Test query return values
        for obj, expected in ((obj_0, val_0), (obj_1, val_1)):
            t_obj, p_obj = qs.get(test=expected), qs.get(proxy=expected)
            assert (
                (obj.pk, expected)
                == qs.annotate("test").values_list("pk", "test").get(test=expected)
                == (t_obj.pk, t_obj.test)
                == qs.annotate("proxy").values_list("pk", "proxy").get(proxy=expected)
                == (p_obj.pk, p_obj.proxy)
            )

        # swap values of the 2 objects and refresh
        for obj, expected in ((rel_0, val_1), (rel_1, val_0)):
            obj.value = expected
            obj.save()

        # Test the swapped related (real) values of each object
        for rel, expected in ((rel_0, val_1), (rel_1, val_0)):
            assert rel.value == expected

        obj_0.refresh_from_db(), obj_1.refresh_from_db()

        # Test the swapped values
        for obj, expected in ((obj_0, val_1), (obj_1, val_0)):
            assert obj.test == expected
            assert obj.proxy == expected

    @pyt.mark.parametrize("through", ["manytomanyfield"])
    def test_m2m_access(self, through, factory: T_Func[_VT], model: type[_MT]):
        qs = model.objects.all()

        val_0, val_1 = factory(), factory()
        rel_0, rel_1 = (qs.create(value=v) for v in (val_0, val_1))
        obj_0, obj_1 = (
            r.manytomanyfield.add(o := qs.create()) or o for r in (rel_0, rel_1)
        )

        # Test the related (real) values of each object
        for rel, expected in ((rel_0, val_0), (rel_1, val_1)):
            assert rel.value == expected

        # Test the values of each object
        for obj, expected in ((obj_0, val_0), (obj_1, val_1)):
            assert obj.test == expected
            assert obj.proxy == expected

        # Test query return values
        for obj, expected in ((obj_0, val_0), (obj_1, val_1)):
            t_obj, p_obj = qs.get(test=expected), qs.get(proxy=expected)
            assert (
                (obj.pk, expected)
                == qs.annotate("test").values_list("pk", "test").get(test=expected)
                == (t_obj.pk, t_obj.test)
                == qs.annotate("proxy").values_list("pk", "proxy").get(proxy=expected)
                == (p_obj.pk, p_obj.proxy)
            )

        # swap values of the 2 objects and refresh
        for obj, expected in ((rel_0, val_1), (rel_1, val_0)):
            obj.value = expected
            obj.save()

        # Test the swapped related (real) values of each object
        for rel, expected in ((rel_0, val_1), (rel_1, val_0)):
            assert rel.value == expected

        obj_0.refresh_from_db(), obj_1.refresh_from_db()

        # Test the swapped values
        for obj, expected in ((obj_0, val_1), (obj_1, val_0)):
            assert obj.test == expected
            assert obj.proxy == expected


TNumTypeField = (
    m.BigIntegerField
    | m.IntegerField
    | m.PositiveBigIntegerField
    | m.SmallIntegerField
    | m.PositiveSmallIntegerField
    | m.PositiveIntegerField
    | m.FloatField
    # | m.DecimalField
)

TStrField = (
    m.CharField
    | m.TextField
    | m.EmailField
    | m.SlugField
    | m.URLField
    | m.FileField
    | m.FilePathField
)
TDateTypeField = m.DateField | m.DateTimeField | m.TimeField | m.DurationField


class test_NumberFields(FieldTestCase[str, TNumTypeField, TestModel]):
    source_support = DefaultDict({(Src.JSON, m.DecimalField): False}, True)


class test_StrFields(FieldTestCase[str, TStrField, TestModel]):
    pass


class test_GenericIPAddressField(
    FieldTestCase[str, m.GenericIPAddressField, TestModel]
):
    pass


class test_BooleanField(FieldTestCase[bool, m.BooleanField, TestModel]):
    pass


class test_UUIDField(FieldTestCase[UUID, m.UUIDField, TestModel]):
    all_sources = (Src.FIELD, Src.EVAL)
    pass


class test_BinaryField(FieldTestCase[str, m.BinaryField, TestModel]):
    json_source_kwargs = {m.Field: dict(cast=True)}
    all_sources = (Src.FIELD, Src.EVAL)


class test_DateTypesFields(FieldTestCase[str, TDateTypeField, TestModel]):
    json_source_kwargs = {m.Field: dict(cast=True)}
    all_sources = (Src.FIELD, Src.EVAL)


class test_JSONField(FieldTestCase[dict, m.JSONField, TestModel]):
    pass


@pyt.mark.skip("")
class test_ForeignKey(FieldTestCase[bool, m.ForeignKey | m.OneToOneField, TestModel]):
    @pyt.fixture
    def factory(self, model: type[_MT]):
        return lambda *a, **kw: model.objects.create(*a, **kw)

    @pyt.fixture
    def type_var(self, source: Src, field):
        return field

    @pyt.fixture
    def kwargs(self, kwargs, type_var):
        if type_var:
            kwargs = {**kwargs, "to": "self"}
        return kwargs

    @pyt.fixture
    def def_kwargs(self, def_kwargs, field, kwargs):
        return {**def_kwargs, "proxy": AliasField[field]("test", **kwargs)}

    # @pyt.mark.skip("")
    # def test_basic(self, model: type[TestModel], field: type[_FT]):
    #     ...
