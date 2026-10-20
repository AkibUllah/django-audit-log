from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from tests.testapp.models import Author, Book, Customer, Tag

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user("nadia", "nadia@example.com", "pass-12345")


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser("ops", "ops@example.com", "pass-12345")


@pytest.fixture
def author(db):
    return Author.objects.create(name="Humayun Ahmed", born=date(1948, 11, 13))


@pytest.fixture
def book(author):
    return Book.objects.create(
        title="Himu", author=author, price=Decimal("250.00"), published=date(1990, 1, 1)
    )


@pytest.fixture
def tags(db):
    return [Tag.objects.create(name=n) for n in ("fiction", "bangla", "classic")]


@pytest.fixture
def customer(db):
    return Customer.objects.create(
        name="Rahim Uddin",
        nid_number="1990123456789",
        phone="01711223344",
        balance=Decimal("1500.00"),
        notes="vip",
    )
