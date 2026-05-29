from django.http import Http404
from django.shortcuts import get_object_or_404, render

from core.models import Program
from core.services.snapshots import current_published


def program_detail(request, slug: str):
    program = get_object_or_404(Program, slug=slug, is_archived=False)
    snapshot = current_published(program)
    if snapshot is None:
        raise Http404("No published profile for this program.")
    return render(
        request,
        "discovery/program_detail.html",
        {"snapshot": snapshot, "payload": snapshot.payload},
    )
