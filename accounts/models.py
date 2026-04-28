import contextlib
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(
        self,
        email: str,
        display_name: str,
        organization: "Organization",  # type: ignore[name-defined]  # noqa: F821
        role: str = "coordinator",
        **extra_fields,
    ) -> "User":
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(
            email=email,
            display_name=display_name,
            organization=organization,
            role=role,
            **extra_fields,
        )
        user.set_unusable_password()
        user.save(using=self._db)
        _assign_role_group(user, role)
        return user

    def create_superuser(self, email: str, display_name: str, **extra_fields) -> "User":
        raise NotImplementedError(
            "Use the bootstrap_org management command to create the first coordinator."
        )


def _assign_role_group(user: "User", role: str) -> None:
    from django.contrib.auth.models import Group

    group_name = "Coordinators" if role == "coordinator" else "Facilitators"
    with contextlib.suppress(Group.DoesNotExist):
        user.groups.add(Group.objects.get(name=group_name))


class User(AbstractBaseUser, PermissionsMixin):
    COORDINATOR = "coordinator"
    FACILITATOR = "facilitator"
    ROLE_CHOICES = [
        (COORDINATOR, "Coordinator"),
        (FACILITATOR, "Facilitator"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=200)
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.PROTECT,
        related_name="users",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    def __str__(self) -> str:
        return f"{self.display_name} <{self.email}>"


class MagicLinkToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="magic_links")
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")

    def __str__(self) -> str:
        return f"MagicLinkToken({self.user}, consumed={self.consumed_at is not None})"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            update_fields = kwargs.get("update_fields")
            if update_fields is None or set(update_fields) - {"consumed_at"}:
                raise ValueError("MagicLinkToken is append-only; only consumed_at may be updated.")
        super().save(*args, **kwargs)
