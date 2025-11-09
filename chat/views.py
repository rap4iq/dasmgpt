from django.core.checks import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from .models import ChatSession, Message
from .tasks import get_ai_response
from django.views.decorators.http import require_POST
import json
from django.template.loader import render_to_string
import io
import pandas as pd
from django.http import HttpResponse
from sqlalchemy import create_engine
from django.conf import settings


@login_required
def chat_list(request):
    """
    Отображает ГЛАВНУЮ страницу.
    Показывает список чатов слева и "заглушку" справа.
    """
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')

    # Мы больше не создаем чат автоматически, даем пользователю выбор

    return render(request, 'chat/chat_list.html', {
        'sessions': sessions,
        'session': None,  # Нет активной сессии
        'messages': []
    })


@login_required
def chat_detail(request, session_id):
    """
    Отображает страницу с АКТИВНЫМ чатом.
    Использует ТОТ ЖЕ шаблон, но передает в него данные о сессии.
    """
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    messages = session.messages.all()  # .all() возьмет ordering из Meta

    return render(request, 'chat/chat_list.html', {
        'sessions': sessions,
        'session': session,  # ПЕРЕДАЕМ АКТИВНУЮ СЕССИЮ
        'messages': messages
    })

@login_required
def new_chat(request):
    # Этот view теперь работает идеально
    session = ChatSession.objects.create(user=request.user)
    return redirect('chat_detail', session_id=session.id)


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

    return JsonResponse({'status': 'pending'})


@require_POST
@login_required
def rename_chat(request, session_id):
    """
    View для переименования чата.
    Принимает JSON: {"new_title": "Новое имя"}
    """
    try:
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)

        if session.user != request.user:
            return HttpResponseForbidden("У вас нет прав на этот чат")

        data = json.loads(request.body)
        new_title = data.get('new_title', '').strip()

        if not new_title:
            return HttpResponseBadRequest("Название не может быть пустым")

        session.title = new_title
        session.save(update_fields=['title'])

        return JsonResponse({'status': 'success', 'new_title': new_title})

    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@require_POST
@login_required
def delete_chat(request, session_id):
    """
    View для удаления чата.
    """
    try:
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)

        # Проверяем, что пользователь является владельцем
        if session.user != request.user:
            return HttpResponseForbidden("У вас нет прав на этот чат")

        session.delete()

        # Возвращаем 'success', чтобы JavaScript мог перенаправить на главную
        return JsonResponse({'status': 'success', 'redirect_url': '/'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def download_excel(request, message_id):
    """
    Находит SQL-запрос из сообщения, выполняет его
    и возвращает результат в виде Excel-файла.
    """
    try:
        # 1. Находим сообщение и проверяем права
        message = get_object_or_404(Message, id=message_id)
        if message.session.user != request.user and not request.user.is_staff:
            return HttpResponseForbidden("У вас нет прав на этот файл")

        # 2. Получаем SQL из data_payload
        sql_query = message.data_payload.get('sql_query')
        if not sql_query or not sql_query.strip().upper().startswith('SELECT'):
            return HttpResponseBadRequest("В этом сообщении нет данных для выгрузки.")

        # 3. Подключаемся к БД (тот же код, что и в tasks.py)
        db_config = settings.DATABASES['default']
        if 'postgresql' in db_config['ENGINE']:
            db_user = db_config.get('USER', '')
            db_pass = db_config.get('PASSWORD', '')
            db_host = db_config.get('HOST', 'localhost')
            db_port = db_config.get('PORT', '5432')
            db_name = db_config.get('NAME', 'dasmdb')
            engine_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        else:
            # (Если у вас SQLite)
            db_path = db_config['NAME']
            engine_url = f"sqlite:///{db_path}"

        engine = create_engine(engine_url)

        # 4. Повторно выполняем SQL
        df = pd.read_sql(sql_query, engine)

        # 5. Создаем Excel-файл в памяти
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Data')

        output.seek(0)

        # 6. Отдаем файл пользователю
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="dasm_data.xlsx"'
        return response

    except Exception as e:
        messages.error(request, f"Ошибка при создании Excel: {e}")
        return redirect(request.META.get('HTTP_REFERER', 'chat_list'))