from django.urls import path
from . import views

app_name = 'education'

urlpatterns = [
    # Knowledge base
    path('knowledge-base/', views.knowledge_base, name='knowledge_base'),
    path('knowledge-base/create/', views.knowledge_post_create, name='knowledge_post_create'),
    path('knowledge-base/<int:post_id>/edit/', views.knowledge_post_edit, name='knowledge_post_edit'),
    path('api/knowledge-post/<int:post_id>/delete/', views.api_knowledge_post_delete, name='api_knowledge_post_delete'),
    path('api/knowledge-post/<int:post_id>/move/<str:direction>/', views.api_knowledge_post_move, name='api_knowledge_post_move'),
    path('api/knowledge-post/<int:post_id>/toggle-visibility/', views.api_knowledge_post_toggle_visibility, name='api_knowledge_post_toggle_visibility'),

    # News
    path('news/create/', views.news_create, name='news_create'),
    path('news/<int:news_id>/edit/', views.news_edit, name='news_edit'),
    path('api/news/<int:news_id>/delete/', views.api_news_delete, name='api_news_delete'),
    path('api/news/<int:news_id>/publish/', views.api_news_publish, name='api_news_publish'),
    path('api/news/<int:news_id>/toggle-visibility/', views.api_news_toggle_visibility, name='api_news_toggle_visibility'),
    path('api/news/<int:news_id>/move/<str:direction>/', views.api_news_move, name='api_news_move'),
    path('api/news/<int:news_id>/toggle-pin/', views.api_news_toggle_pin, name='api_news_toggle_pin'),

    # Document Library
    path('documents/', views.document_library, name='document_library'),
    path('documents/category/create/', views.document_category_create, name='document_category_create'),
    path('documents/category/<int:category_id>/edit/', views.document_category_edit, name='document_category_edit'),
    path('documents/create/', views.document_create, name='document_create'),
    path('documents/<int:document_id>/edit/', views.document_edit, name='document_edit'),
    path('api/document-category/<int:category_id>/delete/', views.api_document_category_delete, name='api_document_category_delete'),
    path('api/document-category/<int:category_id>/move/<str:direction>/', views.api_document_category_move, name='api_document_category_move'),
    path('api/document/<int:document_id>/delete/', views.api_document_delete, name='api_document_delete'),
    path('api/document/<int:document_id>/move/<str:direction>/', views.api_document_move, name='api_document_move'),
]
