import pytest


def pytest_configure(config):
    pass


# @pytest.fixture(params=["sqlite", "postgresql", "mysql", "oracle"])
# def db_backends(request: pytest.FixtureRequest, settings):
#     backend, conf = request.param, settings.DATABASES_BY_BACKENDS
#     if backend in conf:
#         if mark := request.node.get_closest_marker("using_db"):
#             if mark.kwargs.get(backend, backend in mark.args):
#                 settings.DATABASES = settings.DATABASES | {"default": conf[backend]}
#                 return

#     pytest.skip(f"Database backend {backend!r} is not available.")
