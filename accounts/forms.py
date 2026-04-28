from django import forms

from core.models import Program

from .models import User


class FacilitatorCreateForm(forms.Form):
    display_name = forms.CharField(max_length=200, label="Full name")
    email = forms.EmailField(label="Email address")
    programs = forms.ModelMultipleChoiceField(
        queryset=Program.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Assign to programs",
    )

    def __init__(self, *args, coordinator=None, **kwargs):
        super().__init__(*args, **kwargs)
        if coordinator is not None:
            self.fields["programs"].queryset = Program.objects.filter(
                coordinator=coordinator,
                is_archived=False,
            )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email
