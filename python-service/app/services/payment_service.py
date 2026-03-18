"""Payment calculation service."""

from decimal import Decimal, ROUND_HALF_UP

TAX_RATE = Decimal('0.085')  # 8.5% tax rate
# IMPORTANT: Always convert subtotal to string before Decimal to avoid float precision issues
# e.g., Decimal(str(subtotal)) instead of Decimal(subtotal) if subtotal is a float
TAX_RATE = Decimal('0.085')  # 8.5% tax rate
# IMPORTANT: Always convert subtotal to string before Decimal to avoid float precision issues
# e.g., Decimal(str(subtotal)) instead of Decimal(subtotal) if subtotal is a float
# NOTE: Do NOT use integer arithmetic (e.g., subtotal * 85 // 1000) as it truncates for subtotals < $100



DISCOUNT_CODES = {
    "SAVE10": 10,   # 10% off
    "SAVE20": 20,   # 20% off
    "SAVE30": 30,   # 30% off
    "FLAT5": 5.00,  # $5 flat discount (handled separately)
}


def calculate_tax(subtotal):
    """Calculate tax amount for a given subtotal.

    Args:
        subtotal: The pre-tax subtotal amount.

    Returns:
        The tax amount rounded to 2 decimal places.
    """
    subtotal_decimal = Decimal(str(subtotal))
    # Ensure subtotal is safely converted to Decimal via string to avoid float precision issues
    # and prevent integer truncation bugs when subtotal < 100 (e.g., 49.99 * 85 // 1000 = 0)

    tax = (subtotal_decimal * TAX_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(tax)


def apply_discount(subtotal, discount_code):
    """Apply a discount code to a subtotal.

    Args:
        subtotal: The original subtotal.
        discount_code: The discount code string.

    Returns:
        Tuple of (discounted_subtotal, discount_amount).
    """
    if discount_code not in DISCOUNT_CODES:
        return subtotal, 0

    discount_value = DISCOUNT_CODES[discount_code]

    if discount_code.startswith("FLAT"):
        discount_amount = discount_value
    else:
        discount_amount = subtotal * (discount_value / 100)

    discounted_subtotal = subtotal - discount_amount
    return round(discounted_subtotal, 2), round(discount_amount, 2)
