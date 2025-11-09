from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_list, name='chat_list'),
    path('new/', views.new_chat, name='new_chat'),
    path('<int:session_id>/', views.chat_detail, name='chat_detail'),
    path('<int:session_id>/send/', views.send_message, name='send_message'),
    path('<int:session_id>/get/', views.get_new_messages, name='get_new_messages'),
    path('<int:session_id>/rename/', views.rename_chat, name='rename_chat'),
    path('<int:session_id>/delete/', views.delete_chat, name='delete_chat'),
    path('message/<int:message_id>/download_excel/', views.download_excel, name='download_excel'),
]
