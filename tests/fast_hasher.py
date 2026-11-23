"""Test-only Argon2 with minimal cost; still produces `argon2$` hashes. Production keeps the default cost."""

from django.contrib.auth.hashers import Argon2PasswordHasher


class FastArgon2PasswordHasher(Argon2PasswordHasher):
    time_cost = 1
    memory_cost = 8
    parallelism = 1
