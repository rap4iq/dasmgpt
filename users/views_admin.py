from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import User

def admin_required(view_func):
    return user_passes_test(lambda u: u.is_staff)(view_func)

@admin_required
def admin_dashboard(request):
    users = User.objects.all().order_by("-date_joined")
    return render(request, "users/admin_dashboard.html", {"users": users})

@admin_required
def toggle_active(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_active = not user.is_active
    user.save()
    messages.success(request, f"Статус пользователя {user.email} изменён.")
    return redirect("admin_dashboard")

@admin_required
def make_admin(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_staff = True
    user.is_superuser = True
    user.save()
    messages.success(request, f"{user.email} теперь администратор.")
    return redirect("admin_dashboard")
