from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask.json.provider import DefaultJSONProvider

from datetime import datetime, date
from decimal import Decimal

db = SQLAlchemy()
jwt = JWTManager()


class CustomJSONProvider(DefaultJSONProvider):
    """Custom JSON encoder that handles datetime and Decimal types."""

    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def create_app(config_name=None):
    app = Flask(__name__)

    # Load configuration
    from app.config import get_config
    app.config.from_object(get_config(config_name))

    # Set custom JSON provider (Flask 2.3+/3.x compatible)
    app.json_provider_class = CustomJSONProvider
    app.json = app.json_provider_class(app)

    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    CORS(app)

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.products import products_bp
    from app.routes.orders import orders_bp
    from app.routes.payments import payments_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(products_bp, url_prefix="/api/products")
    app.register_blueprint(orders_bp, url_prefix="/api/orders")
    app.register_blueprint(payments_bp, url_prefix="/api/payments")

    # Create tables
    with app.app_context():
        from app.models import user, product, order
        db.create_all()

    return app
