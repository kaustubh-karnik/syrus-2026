import pytest
from app import create_app, db as _db
from app.models.user import User
from app.models.product import Product
from app.models.order import Order, OrderItem
import bcrypt


@pytest.fixture(scope="session")
def app():
    """Create application for testing."""
    app = create_app("testing")
    return app


@pytest.fixture(scope="function")
def db(app):
    """Create a fresh database for each test."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def client(app, db):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def sample_user(db):
    """Create a sample user for testing."""
    password_hash = bcrypt.hashpw(
        "testpassword123".encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    user = User(
        email="test@example.com",
        password_hash=password_hash,
        name="Test User",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def sample_products(db):
    """Create sample products for testing."""
    products = [
        Product(name="Widget A", description="A basic widget", price=29.99, stock=100, category="widgets"),
        Product(name="Widget B", description="A premium widget", price=49.99, stock=50, category="widgets"),
        Product(name="Gadget X", description="An electronic gadget", price=199.99, stock=25, category="gadgets"),
        Product(name="Gadget Y", description="A smart gadget", price=299.99, stock=10, category="gadgets"),
        Product(name="Tool Z", description="A handy tool", price=15.99, stock=200, category="tools"),
    ]
    for p in products:
        db.session.add(p)
    db.session.commit()
    return products


@pytest.fixture
def auth_token(client, sample_user):
    """Get a JWT token for the sample user."""
    from flask_jwt_extended import create_access_token
    from flask import current_app

    with current_app.app_context():
        token = create_access_token(identity=str(sample_user.id))
    return token


@pytest.fixture
def sample_orders(db, sample_user, sample_products):
    """Create sample orders with items for testing."""
    orders = []
    for i in range(5):
        order = Order(
            user_id=sample_user.id,
            subtotal=79.98,
            tax=6.80,
            discount_amount=0,
            total=86.78,
            status="pending",
        )
        db.session.add(order)
        db.session.flush()

        for j in range(3):
            product = sample_products[j % len(sample_products)]
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=1,
                unit_price=float(product.price),
                total_price=float(product.price),
            )
            db.session.add(item)

        orders.append(order)

    db.session.commit()
    return orders
