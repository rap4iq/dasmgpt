from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import ChatSession, Message

@login_required
def chat_list(request):
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'chat/chat_list.html', {'sessions': sessions})

@login_required
def chat_detail(request, session_id):
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    messages = session.messages.order_by('created_at')
    return render(request, 'chat/chat_detail.html', {'session': session, 'messages': messages})

@login_required
def new_chat(request):
    session = ChatSession.objects.create(user=request.user, title="Новый чат")
    return redirect('chat_detail', session_id=session.id)

@login_required
def send_message(request, session_id):
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)

    if request.method == 'POST':
        content = request.POST.get('message', '').strip()
        if content:
            # сообщение от пользователя
            Message.objects.create(session=session, role='user', content=content)

            # ответ DasmGPT (заглушка)
            ai_reply = f"Вы сказали: {content}. Ответ DasmGPT появится позже."
            Message.objects.create(session=session, role='ai', content=ai_reply)

    return redirect('chat_detail', session_id=session.id)
