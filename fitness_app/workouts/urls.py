from django.urls import path

from . import views

app_name = 'workouts'

urlpatterns = [
    path('', views.session_list, name='session_list'),
    path('sessions/new/', views.session_create, name='session_create'),
    path('sessions/<int:pk>/', views.session_detail, name='session_detail'),
    path('sessions/<int:pk>/delete/', views.session_delete, name='session_delete'),
    path('sessions/<int:pk>/entries/<int:entry_id>/delete/', views.entry_delete, name='entry_delete'),
    path('meals/', views.meal_log_list_create, name='meal_log_list'),
]
