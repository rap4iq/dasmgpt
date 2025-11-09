from django.urls import path
from . import views_admin

urlpatterns = [
    path("dashboard/", views_admin.admin_dashboard, name="admin_dashboard"),
    path("toggle-active/<int:user_id>/", views_admin.toggle_active, name="toggle_active"),
    path("make-admin/<int:user_id>/", views_admin.make_admin, name="make_admin"),
    path("user-chats/<int:user_id>/", views_admin.user_chat_list, name="user_chat_list"),
    path("user-chats/<int:user_id>/<int:session_id>/", views_admin.admin_user_chat_detail, name="admin_user_chat_detail"),
]
