from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.models.order import Order
from app.services.payment_service import calculate_tax, apply_discount

payments_bp = Blueprint("payments", __name__)


@payments_bp.route("/calculate", methods=["POST"])
@jwt_required()
def calculate_total():
    """Calculate the total for a cart before placing an order."""
    data = request.get_json()

    if not data or "subtotal" not in data:
        return jsonify({"error": "Missing required field: subtotal"}), 400

    subtotal = float(data["subtotal"])
    discount_code = data.get("discount_code")

    tax = calculate_tax(subtotal)

    discount_amount = 0
    discounted_subtotal = subtotal
    if discount_code:
        discounted_subtotal, discount_amount = apply_discount(subtotal, discount_code)

    total = discounted_subtotal + tax

    return jsonify({
        "subtotal": subtotal,
        "discount_code": discount_code,
        "discount_amount": discount_amount,
        "discounted_subtotal": discounted_subtotal,
        "tax": tax,
        "total": total,
    }), 200


@payments_bp.route("/checkout", methods=["POST"])
@jwt_required()
def checkout():
    """Process payment for an order."""
    data = request.get_json()

    if not data or "order_id" not in data:
        return jsonify({"error": "Missing required field: order_id"}), 400

    user_id = get_jwt_identity()
    order = Order.query.filter_by(id=data["order_id"], user_id=int(user_id)).first()

    if not order:
        return jsonify({"error": "Order not found"}), 404

    if order.status != "pending":
        return jsonify({"error": f"Order is already {order.status}"}), 400

    # Simulate payment processing
    order.status = "paid"
    logging.info(f"Payment processed for order {order.id}, total: {order.total}")
    db.session.commit()

    return jsonify({
        "message": "Payment processed successfully",
        "order": order.to_dict(),
    }), 200
