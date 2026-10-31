from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.generic import View
from .forms import AuthForm, RegistrationForm


class AuthView(View):
    def get(self, request):
        return render(request, 'user/auth.html', {'form': AuthForm()})

    def post(self, request):
        form = AuthForm(request.POST)
        if form.is_valid():
            user = authenticate(request, username=form.cleaned_data['email'].lower(),
                                password=form.cleaned_data['password'])
            if user is not None:
                login(request, user)
                return redirect('dashboard:index')
            form.add_error(None, 'Неверный логин или пароль.')
        return render(request, 'user/auth.html', {'form': form})


class RegistrationView(View):
    def get(self, request):
        return render(request, 'user/registration.html', {'form': RegistrationForm()})

    def post(self, request):
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except IntegrityError:
                form.add_error('email', 'Этот email уже зарегистрирован.')
            else:
                login(request, user)
                return redirect('dashboard:index')
        return render(request, 'user/registration.html', {'form': form})


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect('dashboard:index')
