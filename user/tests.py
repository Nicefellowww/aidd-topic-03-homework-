from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from user.forms import RegistrationForm

User = get_user_model()

STRONG_PASSWORD = "V3ry-Str0ng-Pass!"


class RegistrationTests(TestCase):
    def test_registration_logs_user_in_and_normalizes_email(self):
        response = self.client.post(
            reverse("user:registration"),
            {
                "email": "New.User@Example.COM",
                "password1": STRONG_PASSWORD,
                "password2": STRONG_PASSWORD,
            },
        )
        self.assertRedirects(response, reverse("dashboard:index"))
        user = User.objects.get(username="new.user@example.com")
        self.assertEqual(user.email, "new.user@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_password_mismatch_is_reported(self):
        response = self.client.post(
            reverse("user:registration"),
            {
                "email": "user@example.com",
                "password1": STRONG_PASSWORD,
                "password2": "another-password",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "не совпадают")
        self.assertFalse(User.objects.filter(email="user@example.com").exists())

    def test_duplicate_email_is_case_insensitive(self):
        User.objects.create_user(
            username="user@example.com",
            email="user@example.com",
            password=STRONG_PASSWORD,
        )
        response = self.client.post(
            reverse("user:registration"),
            {
                "email": "USER@example.com",
                "password1": STRONG_PASSWORD,
                "password2": STRONG_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже зарегистрирован")
        self.assertEqual(User.objects.filter(email__iexact="user@example.com").count(), 1)

    def test_weak_password_is_rejected_by_django_validators(self):
        form = RegistrationForm(
            data={
                "email": "weak@example.com",
                "password1": "password",
                "password2": "password",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)


class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="user@example.com",
            email="user@example.com",
            password=STRONG_PASSWORD,
        )

    def test_login_is_case_insensitive_for_email(self):
        response = self.client.post(
            reverse("user:auth"),
            {"email": "USER@Example.com", "password": STRONG_PASSWORD},
        )
        self.assertRedirects(response, reverse("dashboard:index"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_invalid_credentials_show_message(self):
        response = self.client.post(
            reverse("user:auth"),
            {"email": "user@example.com", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Неверный логин или пароль")

    def test_missing_fields_do_not_raise_key_error(self):
        response = self.client.post(reverse("user:auth"), {})
        self.assertEqual(response.status_code, 200)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("user:logout"))
        self.assertEqual(response.status_code, 405)

        response = self.client.post(reverse("user:logout"))
        self.assertRedirects(response, reverse("dashboard:index"))
        self.assertNotIn("_auth_user_id", self.client.session)
