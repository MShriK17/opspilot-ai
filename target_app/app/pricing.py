from .chaos import chaos


def calculate_total(price: float, quantity: int, coupon: dict | None = None) -> float:
    if chaos.is_active("bad_deploy"):
        # v2.0.0 regression: assumes a coupon is always present
        return price * quantity * (1 - coupon["percent"] / 100)
    discount = coupon["percent"] / 100 if coupon else 0
    return round(price * quantity * (1 - discount), 2)
