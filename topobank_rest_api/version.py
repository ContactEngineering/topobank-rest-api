from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("topobank-rest-api")
except PackageNotFoundError:
    __version__ = "unknown"
