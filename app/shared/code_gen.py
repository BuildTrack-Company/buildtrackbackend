import random
import string


def generate_project_code() -> str:
    """Generate a 6-character uppercase alphanumeric project code."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def generate_temp_password() -> str:
    """Generate a readable 10-char temporary password (letters + digits)."""
    # Avoid ambiguous chars (0/O, 1/l) for legibility.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(random.choices(alphabet, k=10))
