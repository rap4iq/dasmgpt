from django.urls import path
from . import views_admin

urlpatterns = [
    path("dashboard/", views_admin.admin_dashboard, name="admin_dashboard"),
    path("toggle-active/<int:user_id>/", views_admin.toggle_active, name="toggle_active"),
    path("make-admin/<int:user_id>/", views_admin.make_admin, name="make_admin"),
]
