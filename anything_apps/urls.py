from django.urls import path
from . import views, api

app_name = 'apps'

urlpatterns = [
    path('', views.app_list, name='list'),
    path('<int:app_id>/', views.app_detail, name='detail'),
    path('generate/', views.generate_app, name='generate'),
    path('<int:app_id>/update/', views.app_update, name='update'),
    path('status/generation/<int:prompt_id>/', views.check_generation_status, name='check_generation'),
    path('status/update/<int:update_id>/', views.check_update_status, name='check_update'),
    path('<int:app_id>/pages/<slug:page_slug>/', views.render_app_page, name='render_page'),
    path('api/pages/<int:page_id>/', views.page_details_api, name='page_details_api'),
    
    # DataStore API endpoints
    path('api/<int:app_id>/data-store/', api.data_store_list, name='data_store_list'),
    path('api/<int:app_id>/data-store/<int:item_id>/', api.data_store_detail, name='data_store_detail'),
    path('api/<int:app_id>/data-store/create/', api.data_store_create, name='data_store_create'),
    path('api/<int:app_id>/data-store/<int:item_id>/update/', api.data_store_update, name='data_store_update'),
    path('api/<int:app_id>/data-store/<int:item_id>/delete/', api.data_store_delete, name='data_store_delete'),
] 