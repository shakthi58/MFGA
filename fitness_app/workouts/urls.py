from django.urls import path

from . import views

app_name = 'workouts'

urlpatterns = [
    path('', views.session_list, name='session_list'),
    path('sessions/new/', views.session_create, name='session_create'),
    path('sessions/<int:pk>/', views.session_detail, name='session_detail'),
]
