import os


def _env(primary, fallback=None, default=None):
    value = os.environ.get(primary)
    if value is not None:
        return value
    if fallback:
        fallback_value = os.environ.get(fallback)
        if fallback_value is not None:
            return fallback_value
    return default


def _build_postgres_uri(default_host="localhost"):
    user = _env("DATABASE_USER", "DB_USER", "appuser")
    password = _env("DATABASE_PASSWORD", "DB_PASS", "apppassword")
    host = _env("DATABASE_HOST", "DB_HOST", default_host)
    port = _env("DATABASE_PORT", "DB_PORT", "5432")
    name = _env("DATABASE_NAME", "DB_NAME", "ecommerce")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    JWT_ACCESS_TOKEN_EXPIRES = 3600


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = _build_postgres_uri(default_host="localhost")


class StagingConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _build_postgres_uri(default_host="localhost")


class ProductionConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _build_postgres_uri(default_host="localhost")


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_SECRET_KEY = "test-secret-key"


config_map = {
    "development": DevelopmentConfig,
    "staging": StagingConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")
    return config_map.get(config_name, DevelopmentConfig)
