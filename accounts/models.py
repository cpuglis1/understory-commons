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
        return user

    def create_superuser(self, email: str, display_name: str, **extra_fields) -> "User":
        raise NotImplementedError(
            "Use the bootstrap_org management command to create the first coordinator."
        )


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
