from django.urls import path
from . import views

app_name = 'organizations'

urlpatterns = [
    path('', views.organization_list, name='list'),
    path('create/', views.organization_create, name='create'),
    path('<int:org_id>/', views.organization_detail, name='detail'),
    path('<int:org_id>/update/', views.organization_update, name='update'),
    path('<int:org_id>/members/', views.member_manage, name='members'),
    path('<int:org_id>/members/invite/', views.member_invite, name='member_invite'),
] 