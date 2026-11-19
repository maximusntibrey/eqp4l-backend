"""factory-boy factories for the schema tests. Rows are built exactly as the ERD allows."""

import itertools
import uuid
from typing import Any, cast

import factory

from accounts.models import User, UserStatus
from branches.models import Branch
from inventory.models import Brand, Item, Subtype
from stock_ledger.models import Operation, OperationType

_login_numbers = itertools.count(7000)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    login_id = factory.LazyFunction(lambda: f"USR-{next(_login_numbers)}")
    full_name = factory.Sequence(lambda n: f"Person {n}")
    phone = "0240000000"
    status = UserStatus.ACTIVE
    password = "!"  # noqa: S105  # nosec B105 - unusable hash, not a secret


class BranchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Branch

    code = factory.Sequence(lambda n: f"BR-{n + 100:03d}")
    name = factory.Sequence(lambda n: f"Branch {n}")
    kind = "branch"
    status = "active"
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)


class BrandFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Brand

    name = factory.Sequence(lambda n: f"Brand {n}")


class SubtypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subtype

    category = "laptop"
    name = factory.Sequence(lambda n: f"Subtype {n}")


class ItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Item

    sku = factory.Sequence(lambda n: f"SKU-{n + 1}")
    name = factory.Sequence(lambda n: f"Item {n}")
    category = "laptop"
    subtype = factory.SubFactory(SubtypeFactory)
    brand = factory.SubFactory(BrandFactory)
    model_name = "Model X"
    mpn = "MPN-1"
    condition = "new"
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)


class OperationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Operation

    idempotency_key = factory.LazyFunction(uuid.uuid4)
    operation_type = OperationType.SUPPLIER_RECEIPT
    actor = factory.SubFactory(UserFactory)
    request_hash = "0" * 64


def make_branch(**kw: Any) -> Branch:
    return cast(Branch, BranchFactory(**kw))


def make_user(**kw: Any) -> User:
    return cast(User, UserFactory(**kw))


def make_item(**kw: Any) -> Item:
    return cast(Item, ItemFactory(**kw))


def make_operation(**kw: Any) -> Operation:
    return cast(Operation, OperationFactory(**kw))
