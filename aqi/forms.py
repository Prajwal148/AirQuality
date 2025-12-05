# aqi/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import UserVisibility


class SignUpForm(UserCreationForm):
    become_admin = forms.BooleanField(
        required=False,
        label="Request admin privileges",
        help_text="If checked, you'll be redirected to verify an admin promo code after signup."
    )

    class Meta:
        model = User
        # Only include model fields here. password1/password2 are provided by UserCreationForm.
        fields = ("username",)

        widgets = {
            "username": forms.TextInput(attrs={
                "placeholder": "Choose a username",
                "autocomplete": "username",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # UX hints for password fields
        self.fields["password1"].widget.attrs.update({
            "autocomplete": "new-password",
            "placeholder": "Create a password",
        })
        self.fields["password2"].widget.attrs.update({
            "autocomplete": "new-password",
            "placeholder": "Confirm your password",
        })

    def clean_username(self):
        """
        Provide a friendlier, case-insensitive duplicate check
        (e.g., 'Alice' conflicts with 'alice').
        """
        uname = self.cleaned_data.get("username", "")
        if User.objects.filter(username__iexact=uname).exists():
            raise forms.ValidationError("This username is already taken.")
        return uname


class AdminSelectUserForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.order_by("username"),
        required=True,
        label="Select user"
    )


class VisibilityForm(forms.ModelForm):
    class Meta:
        model = UserVisibility
        fields = [
            "can_pm2_5", "can_pm10", "can_o3",
            "can_co", "can_no2", "can_so2", "can_aqi"
        ]


class BecomeAdminForm(forms.Form):
    promo_code = forms.CharField(
        label="Admin promo code",
        strip=True,
        widget=forms.PasswordInput(attrs={
            "autocomplete": "off",
            "placeholder": "Enter promo code"
        }),
    )
