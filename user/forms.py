from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from user.models import User


class RegistrationForm(forms.Form):
    email = forms.EmailField(max_length=150)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise ValidationError('Этот email уже зарегистрирован.')
        return email

    def clean(self):
        data = super().clean()
        if data.get('password1') and data.get('password2'):
            if data['password1'] != data['password2']:
                self.add_error('password2', 'Пароли не совпадают.')
            try:
                validate_password(data['password1'], User(username=data.get('email', ''), email=data.get('email', '')))
            except ValidationError as exc:
                self.add_error('password1', exc)
        return data

    def save(self):
        email = self.cleaned_data['email']
        return User.objects.create_user(username=email, email=email, password=self.cleaned_data['password1'])


class AuthForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
