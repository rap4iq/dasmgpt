from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import User
from django.db.models import Count
from chat.models import ChatSession, Message

def admin_required(view_func):
    return user_passes_test(lambda u: u.is_staff)(view_func)

@admin_required
def admin_dashboard(request):
    users = User.objects.annotate(
        chat_count=Count('chat_sessions')
    ).order_by("-date_joined")
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


@admin_required
def user_chat_list(request, user_id):
    """
    Показывает список чатов ДЛЯ КОНКРЕТНОГО пользователя.
    """
    target_user = get_object_or_404(User, id=user_id)

    sessions = ChatSession.objects.filter(user=target_user).order_by('-created_at')

    return render(request, "users/admin_user_chats.html", {
        'target_user': target_user,
        'sessions': sessions,
        'session': None,  # По умолчанию активного чата нет
        'messages': []
    })


@admin_required
def admin_user_chat_detail(request, user_id, session_id):
    """
    Показывает КОНКРЕТНЫЙ чат КОНКРЕТНОГО пользователя.
    (Read-only)
    """
    target_user = get_object_or_404(User, id=user_id)
    sessions = ChatSession.objects.filter(user=target_user).order_by('-created_at')

    session = get_object_or_404(ChatSession, id=session_id, user=target_user)
    messages = session.messages.all()

    return render(request, "users/admin_user_chats.html", {
        'target_user': target_user,
        'sessions': sessions,
        'session': session,  # <--- Передаем активную сессию
        'messages': messages
    })