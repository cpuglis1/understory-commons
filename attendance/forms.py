from django import forms

from core.models import Session

from .models import Participant


class SessionForm(forms.ModelForm):
    class Meta:
        model = Session
        fields = ["scheduled_date", "notes"]
        widgets = {
            "scheduled_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ParticipantForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ["display_name"]
        labels = {"display_name": "Name (first name or nickname is fine)"}
