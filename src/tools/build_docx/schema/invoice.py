from __future__ import annotations

from typing import Any

InvoiceAmount = float | str


REQUIRED_STRING_FIELDS = (
    "invoice_no",
    "invoice_date",
    "due_date",
    "billing_period",
    "property_name",
    "property_address",
    "bill_to",
    "payment_terms",
)

REQUIRED_AMOUNT_FIELDS = ("subtotal", "gst", "total")
OPTIONAL_STRING_DEFAULTS = {
    "assumptions": "To be confirmed.",
}
BUSINESS_PROFILE_STRING_FIELDS = ("business_name", "trading_name", "abn")
CONTACT_STRING_FIELDS = ("email", "phone")
PAYMENT_STRING_FIELDS = ("method", "account_name", "bsb", "account_number")


def validate_invoice_data(payload: dict[str, Any]) -> dict[str, Any]:
    invoice: dict[str, Any] = {}
    for field_name in REQUIRED_STRING_FIELDS:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invoice field '{field_name}' must be a non-empty string.")
        invoice[field_name] = value.strip()
    for field_name, default_value in OPTIONAL_STRING_DEFAULTS.items():
        value = payload.get(field_name)
        invoice[field_name] = value.strip() if isinstance(value, str) and value.strip() else default_value

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Invoice field 'items' must be a non-empty list.")
    invoice["items"] = [_validate_item(item) for item in items]

    for field_name in REQUIRED_AMOUNT_FIELDS:
        invoice[field_name] = _validate_amount(payload.get(field_name), field_name)
    invoice["business_profile"] = _validate_business_profile(payload.get("business_profile"))
    return invoice


def _validate_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Invoice item must be an object.")
    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Invoice item field 'description' must be a non-empty string.")
    return {
        "description": description.strip(),
        "amount": _validate_amount(item.get("amount"), "items.amount"),
    }


def _validate_amount(value: Any, field_name: str) -> InvoiceAmount:
    if isinstance(value, bool):
        raise ValueError(f"Invoice field '{field_name}' must be a number or string.")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"Invoice field '{field_name}' must be a number or non-empty string.")


def _validate_business_profile(value: Any) -> dict[str, Any]:
    profile = value if isinstance(value, dict) else {}
    contact = profile.get("contact") if isinstance(profile.get("contact"), dict) else {}
    payment = profile.get("payment") if isinstance(profile.get("payment"), dict) else {}
    return {
        **{
            field_name: _validate_optional_text(profile.get(field_name))
            for field_name in BUSINESS_PROFILE_STRING_FIELDS
        },
        "contact": {
            field_name: _validate_optional_text(contact.get(field_name))
            for field_name in CONTACT_STRING_FIELDS
        },
        "payment": {
            field_name: _validate_optional_text(payment.get(field_name))
            for field_name in PAYMENT_STRING_FIELDS
        },
    }


def _validate_optional_text(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "To be confirmed"
