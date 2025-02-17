from django.urls import path
from . import views

app_name = 'apps'

urlpatterns = [
    path('', views.app_list, name='list'),
    path('<int:app_id>/', views.app_detail, name='detail'),
    path('generate/', views.generate_app, name='generate'),
    path('<int:app_id>/update/', views.app_update, name='update'),
    path('status/generation/<int:prompt_id>/', views.check_generation_status, name='check_generation'),
    path('status/update/<int:update_id>/', views.check_update_status, name='check_update'),
    path('<int:app_id>/pages/<slug:page_slug>/', views.render_app_page, name='render_page'),
] 