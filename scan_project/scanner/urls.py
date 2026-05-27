from django.urls import path
from . import views

urlpatterns = [
    path('', views.document_list, name='document_list'),
    path('document/<int:doc_id>/ignore/', views.ignore_document, name='ignore_document'),
    path('document/<int:doc_id>/rename/', views.rename_document, name='rename_document'),
]
