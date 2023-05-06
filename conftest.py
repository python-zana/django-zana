import typing as t
from collections import defaultdict
from logging import getLogger

import pytest as pyt

from tests import faker

if t.TYPE_CHECKING:
    from django.db import models as m

logger = getLogger(__name__)


_covers = defaultdict[str, set[str]](set[str])
_covered = defaultdict(lambda: defaultdict(set))
_cov_marker_tests = set()


@pyt.fixture(scope="session")
def implementations():
    from tests.app.models import TestModel

    return {s: {*imp} for s, imp in TestModel.implemented.items()}


@pyt.fixture(scope="session", autouse=True)
def coverage_tasks(
    implementations: dict[type["m.Field"], set[str]], request: pyt.FixtureRequest
):
    from tests.app.models import TestModel

    tasks = {
        (test, cov, impl)
        for test, covs in _covers.items()
        for impl, req in implementations.items()
        for cov in req & covs
    }
    orig = len(tasks)
    # try:
    yield tasks
    # finally:

    rem = len(tasks)

    for test, spec, impl in sorted(
        tasks, key=lambda v: (*v[:-1], TestModel.get_field_name(v[-1]))
    ):
        logger.error(
            f"{test}[{str(spec)!r}] '{impl.__module__}::{impl.__qualname__}' not covered"
        )

    if request.session.testsfailed and not _cov_marker_tests:
        return

    del tasks, implementations
    assert rem == 0, f"{rem}/{orig}  ({round(rem/orig*100, 2)}%) tasks were not covered"


@pyt.fixture(autouse=True)
def fake():
    try:
        yield faker.ufake
    finally:
        faker.ufake.clear()
    return {}


@pyt.fixture()
def factories():
    from tests.app.models import FIELD_FACTORIES

    return FIELD_FACTORIES


def node_key(item: pyt.Item):
    return item.nodeid.replace(item.name, item.f)


def pytest_collection_modifyitems(config, items: list[pyt.Function]):
    from tests.app.models import ExprSource

    for i in range(len(items)):
        item = items[i]
        key = item.function.__name__
        if mk := item.get_closest_marker("field_cov"):
            key = item.function.__name__
            _covers[key].update(mk.args or ExprSource)
            item.add_marker(pyt.mark.covered_test(key))
    items.sort(
        key=lambda it: "test_coverage" == it.function.__name__
        and (_cov_marker_tests.add(it.nodeid) or True)
    )


@pyt.fixture(autouse=True)
def _check_covers(request: pyt.FixtureRequest, coverage_tasks: set):
    if mk := request.node.get_closest_marker("covered_test"):
        test = mk.args[0]
        if all(f in request.fixturenames for f in ("field", "source")):
            field = request.getfixturevalue("field")
            source = request.getfixturevalue("source")
            coverage_tasks.discard((test, source, field))
