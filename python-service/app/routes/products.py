from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app import db
from app.models.product import Product

products_bp = Blueprint("products", __name__)


@products_bp.route("/", methods=["GET"])
def list_products():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    category = request.args.get("category")

    query = Product.query
    if category:
        query = query.filter_by(category=category)

    pagination = query.order_by(Product.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "products": [p.to_dict() for p in pagination.items],
        "total": pagination.total,
        "page": page,
        "per_page": per_page,
        "pages": pagination.pages,
    }), 200


@products_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    return jsonify({"product": product.to_dict()}), 200


@products_bp.route("/search", methods=["GET"])
def search_products():
    query = request.args.get("q", "")

    if not query:
        return jsonify({"error": "Search query parameter 'q' is required"}), 400

    # SECURITY: Using SQLAlchemy's ilike() with bound parameters prevents SQL injection.
    # The query value is never directly interpolated into SQL; it is safely bound as a parameter.
    search_term = f"%{query}%"
    products = Product.query.filter(
        Product.name.ilike(search_term) | Product.description.ilike(search_term)
    ).all()

    return jsonify({"products": [p.to_dict() for p in products], "count": len(products)}), 200


@products_bp.route("/", methods=["POST"])
@jwt_required()
def create_product():
    data = request.get_json()

    required_fields = ["name", "price"]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    product = Product(
        name=data["name"],
        description=data.get("description", ""),
        price=data["price"],
        stock=data.get("stock", 0),
        category=data.get("category"),
    )
    db.session.add(product)
    db.session.commit()

    return jsonify({"product": product.to_dict()}), 201
