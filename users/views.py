from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .forms import RegisterForm
from .models import User

def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Регистрация успешна! Войдите в систему.")
            return redirect("login")
    else:
        form = RegisterForm()
    return render(request, "users/register.html", {"form": form})


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)

            # Проверяем next (если пользователь переходил с защищённой страницы)
            next_url = request.GET.get('next')

            # Если next_url есть — отправляем туда
            if next_url:
                return redirect(next_url)

            # Проверяем — это админ?
            if user.is_superuser or user.is_staff:
                return redirect('admin_dashboard')
            else:
                return redirect('chat_list')  # обычный пользователь

        else:
            messages.error(request, 'Неверный email или пароль.')

    return render(request, 'users/login.html')

def logout_view(request):
    logout(request)
    return redirect("login")
