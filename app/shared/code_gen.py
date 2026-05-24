import random
import string


def generate_project_code() -> str:
    """Generate a 6-character uppercase alphanumeric project code."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
