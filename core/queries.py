from django.db.models import QuerySet

from .models import Program


def programs_visible_to(user) -> QuerySet[Program]:
    """Return the Program queryset scoped to what this user may see.

    Coordinators see all programs in their org; facilitators see only
    the programs they are explicitly assigned to.
    No view should query Program.objects directly — always call this.
    """
    if user.role == "coordinator":
        return Program.objects.filter(organization=user.organization)
    return user.facilitated_programs.all()
