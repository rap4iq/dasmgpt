# from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth.decorators import login_required
# from .models import ChatSession, Message
#
# @login_required
# def chat_list(request):
#     sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
#     return render(request, 'chat/chat_list.html', {'sessions': sessions})
#
# @login_required
# def chat_detail(request, session_id):
#     session = get_object_or_404(ChatSession, id=session_id, user=request.user)
#     messages = session.messages.order_by('created_at')
#     return render(request, 'chat/chat_detail.html', {'session': session, 'messages': messages})
#
# @login_required
# def new_chat(request):
#     session = ChatSession.objects.create(user=request.user, title="Новый чат")
#     return redirect('chat_detail', session_id=session.id)
#
# @login_required
# def send_message(request, session_id):
#     session = get_object_or_404(ChatSession, id=session_id, user=request.user)
#
#     if request.method == 'POST':
#         content = request.POST.get('message', '').strip()
#         if content:
#             # сообщение от пользователя
#             Message.objects.create(session=session, role='user', content=content)
#
#             # ответ DasmGPT (заглушка)
#             ai_reply = f"Вы сказали: {content}. Ответ DasmGPT появится позже."
#             Message.objects.create(session=session, role='ai', content=ai_reply)
#
#     return redirect('chat_detail', session_id=session.id)
# chat/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from .models import ChatSession, Message
from .tasks import get_ai_response  # <--- ИМПОРТИРУЕМ НАШУ БУДУЩУЮ ЗАДАЧU
import json
from django.template.loader import render_to_string

@login_required
def chat_list(request):
    # Ваш код идеален
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    # Добавим создание чата, если их нет, для удобства
    if not sessions.exists():
        ChatSession.objects.create(user=request.user, title="Новый чат")
        sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')

    return render(request, 'chat/chat_list.html', {'sessions': sessions})


@login_required
def chat_detail(request, session_id):
    # Ваш код идеален
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    messages = session.messages.all()  # .all() возьмет ordering из Meta
    return render(request, 'chat/chat_detail.html', {'session': session, 'messages': messages})


@login_required
def new_chat(request):
    # Ваш код идеален
    session = ChatSession.objects.create(user=request.user)
    return redirect('chat_detail', session_id=session.id)


# ----------------------------------------------------------------
# КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: send_message
# ----------------------------------------------------------------
@login_required
def send_message(request, session_id):
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)

    if request.method == 'POST':
        try:
            # Мы ожидаем JSON от fetch-запроса, а не POST-формы
            data = json.loads(request.body)
            content = data.get('message', '').strip()
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")

        if content:
            # 1. Сообщение от пользователя (сохраняем сразу)
            user_message = Message.objects.create(
                session=session,
                role='user',
                content=content
            )

            # 2. Запускаем фоновую задачу Celery для ИИ
            # Передаем ID, т.к. Celery не любит объекты Django
            get_ai_response.delay(session_id=session.id, user_prompt=content)

            # 3. Немедленно отвечаем фронтенду, что задача принята
            # Фронтенд на это покажет "DasmGPT печатает..."
            return JsonResponse({
                'status': 'processing',
                'user_message_html': render_to_string(
                    'chat/components/message_block.html',
                    {'message': user_message}
                )  # Отправляем HTML нового сообщения (для HTMX/AJAX)
            })

    return HttpResponseBadRequest("Invalid request")


# Нам понадобится еще один view, который фронтенд будет "опрашивать" (poll)
# Или мы можем использовать WebSockets, но polling проще для MVP

@login_required
def get_new_messages(request, session_id):
    """
    View для AJAX-polling. Ищет новые сообщения от 'ai'.
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)

    # Ищем сообщения от 'ai', которые фронтенд еще не видел
    # (Это упрощенная логика; лучше передавать 'last_message_id' от фронтенда)
    last_message_id = request.GET.get('last_message_id')

    if last_message_id:
        messages = session.messages.filter(
            id__gt=last_message_id,
            role='ai'
        ).order_by('created_at')
    else:
        # Если это первая загрузка, ищем только последнее AI сообщение
        messages = session.messages.filter(role='ai').order_by('-created_at')[:1]

    if messages:
        # Как только нашли - отправляем
        ai_message = messages.first()
        return JsonResponse({
            'status': 'success',
            'message_html': render_to_string(
                'chat/components/message_block.html',
                {'message': ai_message}
            ),
            'message_id': ai_message.id,
            'data_payload': ai_message.data_payload  # <--- Отправляем JSON для Plotly
        })

    return JsonResponse({'status': 'pending'})  # "Ответа пока нет"


# Не забудьте импортировать render_to_string
