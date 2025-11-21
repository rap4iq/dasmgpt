from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib import messages
# (НОВЫЙ ИМПОРТ)
from django.db import transaction

from .models import ChatSession, Message
from .tasks import get_ai_response
import json

import io
import pandas as pd
# (ИСПРАВЛЕН ИМПОРТ: DatabaseExecutor должен быть здесь, если используется в download_excel)
from ai_core.models import DataSource
from ai_core.db_executor import DatabaseExecutor
from sqlalchemy import create_engine


@login_required
def chat_list(request):
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'chat/chat_list.html', {
        'sessions': sessions,
        'session': None,
        'messages': []
    })


@login_required
def chat_detail(request, session_id):
    # Ищем по public_id (UUID), так как в URL у нас UUID
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    session = get_object_or_404(ChatSession, public_id=session_id, user=request.user)
    messages = session.messages.all()

    return render(request, 'chat/chat_list.html', {
        'sessions': sessions,
        'session': session,
        'messages': messages
    })


@login_required
def new_chat(request):
    session = ChatSession.objects.create(user=request.user)
    # Редирект на public_id
    return redirect('chat_detail', session_id=session.public_id)


@login_required
def send_message(request, session_id):
    # Ищем по public_id
    session = get_object_or_404(ChatSession, public_id=session_id, user=request.user)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            content = data.get('message', '').strip()
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")

        if content:
            # 1. Сообщение от пользователя
            user_message = Message.objects.create(
                session=session,
                role='user',
                content=content
            )

            # 2. (ИСПРАВЛЕНО) Запускаем Celery ТОЛЬКО после коммита транзакции
            # Мы передаем session.id (внутренний ID), так как tasks.py работает с ID
            transaction.on_commit(
                lambda: get_ai_response.delay(session_id=session.id, user_prompt=content)
            )

            return JsonResponse({
                'status': 'processing',
                'user_message_html': render_to_string(
                    'chat/components/message_block.html',
                    {'message': user_message}
                )
            })

    return HttpResponseBadRequest("Invalid request")


@login_required
def get_new_messages(request, session_id):
    # Ищем по public_id
    session = get_object_or_404(ChatSession, public_id=session_id, user=request.user)

    last_message_id = request.GET.get('last_message_id')
    messages_queryset = Message.objects.none()

    if last_message_id:
        messages_queryset = session.messages.filter(
            id__gt=last_message_id,
            role='ai'
        ).order_by('created_at')

    if messages_queryset:
        ai_message = messages_queryset.first()
        return JsonResponse({
            'status': 'success',
            'message_html': render_to_string(
                'chat/components/message_block.html',
                {'message': ai_message}
            ),
            'message_id': ai_message.id,
            'data_payload': ai_message.data_payload
        })

    return JsonResponse({'status': 'pending'})


@require_POST
@login_required
def rename_chat(request, session_id):
    try:
        # Ищем по public_id
        session = get_object_or_404(ChatSession, public_id=session_id, user=request.user)

        data = json.loads(request.body)
        new_title = data.get('new_title', '').strip()

        if not new_title:
            return HttpResponseBadRequest("Название не может быть пустым")

        session.title = new_title
        session.save(update_fields=['title'])

        return JsonResponse({'status': 'success', 'new_title': new_title})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@require_POST
@login_required
def delete_chat(request, session_id):
    try:
        # Ищем по public_id
        session = get_object_or_404(ChatSession, public_id=session_id, user=request.user)
        session.delete()
        return JsonResponse({'status': 'success', 'redirect_url': '/'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def download_excel(request, message_id):
    try:
        # message_id - это внутренний ID, он безопасен, так как проверяем права
        message = get_object_or_404(Message, id=message_id)
        if message.session.user != request.user and not request.user.is_staff:
            return HttpResponseForbidden("У вас нет прав на этот файл")

        sql_query = message.data_payload.get('sql_query')
        if not sql_query or not sql_query.strip().upper().startswith(('SELECT', 'WITH')):
            return HttpResponseBadRequest("В этом сообщении нет данных для выгрузки.")

        # Используем DatabaseExecutor
        active_datasource = DataSource.objects.filter(is_active=True).first()
        db_executor = DatabaseExecutor(datasource=active_datasource)

        df = db_executor.execute_query(sql_query)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Data')

        output.seek(0)

        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="dasm_data.xlsx"'
        return response

    except Exception as e:
        messages.error(request, f"Ошибка при создании Excel: {e}")
        return redirect(request.META.get('HTTP_REFERER', 'chat_list'))