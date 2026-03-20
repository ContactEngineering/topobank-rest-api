from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("topobank-rest-api")
except PackageNotFoundError:
    __version__ = "unknown"
