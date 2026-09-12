import random
import string

from fastapi.testclient import TestClient

from app.core.config import settings


def random_lower_string() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=32))


def random_email() -> str:
    return f"{random_lower_string()}@{random_lower_string()}.com"


def get_superuser_token_headers(client: TestClient) -> dict[str, str]:
    # Imported here: tests.utils.user imports this module, so a module-level
    # import would be circular.
    from tests.utils.user import user_authentication_headers

    return user_authentication_headers(
        client=client,
        email=settings.FIRST_SUPERUSER,
        password=settings.FIRST_SUPERUSER_PASSWORD,
    )
