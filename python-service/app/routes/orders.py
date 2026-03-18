from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.models.order import Order, OrderItem
from app.models.product import Product

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/", methods=["GET"])
@jwt_required()
def list_orders():
    user_id = get_jwt_identity()

    orders = Order.query.filter_by(user_id=int(user_id)).all()

    result = []
    for order in orders:
        order_data = order.to_dict()
        order_data["items"] = []
        for item in order.items:
            item_data = item.to_dict()
            if item.product:
                item_data["product_name"] = item.product.name
            order_data["items"].append(item_data)
        result.append(order_data)

    return jsonify({
        "orders": result,
        "count": len(result),
    }), 200


@orders_bp.route("/<int:order_id>", methods=["GET"])
@jwt_required()
def get_order(order_id):
    user_id = get_jwt_identity()
    order = Order.query.filter_by(id=order_id, user_id=int(user_id)).first()

    if not order:
        return jsonify({"error": "Order not found"}), 404

    return jsonify({"order": order.to_dict(include_items=True)}), 200


@orders_bp.route("/", methods=["POST"])
@jwt_required()
def create_order():
    user_id = get_jwt_identity()
    data = request.get_json()

    if not data or not data.get("items"):
        return jsonify({"error": "Order must include at least one item"}), 400

    subtotal = 0
    order_items = []

    for item_data in data["items"]:
        product = Product.query.get(item_data.get("product_id"))
        if not product:
            return jsonify({"error": f"Product {item_data.get('product_id')} not found"}), 404

        quantity = item_data.get("quantity", 1)

        if product.stock < quantity:
            return jsonify({
                "error": f"Insufficient stock for {product.name}. Available: {product.stock}"
            }), 400

        item_total = float(product.price) * quantity
        subtotal += item_total

        order_items.append({
            "product": product,
            "quantity": quantity,
            "unit_price": float(product.price),
            "total_price": item_total,
        })

    # Calculate tax and discount
    from app.services.payment_service import calculate_tax, apply_discount

    tax = calculate_tax(subtotal)
    discount_amount = 0
    discount_code = data.get("discount_code")

    if discount_code:
        subtotal, discount_amount = apply_discount(subtotal, discount_code)

    total = subtotal + tax - discount_amount

    order = Order(
        user_id=int(user_id),
        subtotal=subtotal,
        tax=tax,
        discount_amount=discount_amount,
        total=total,
        discount_code=discount_code,
    )
    db.session.add(order)
    db.session.flush()

    for item_data in order_items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item_data["product"].id,
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            total_price=item_data["total_price"],
        )
        db.session.add(order_item)

        # Reduce stock
        item_data["product"].stock -= item_data["quantity"]

    db.session.commit()

    return jsonify({"order": order.to_dict(include_items=True)}), 201
