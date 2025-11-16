from django.urls import path
from . import views

urlpatterns = [
    path('invoices/', views.get_invoices, name='get_invoices'),
    path('invoices/create/', views.create_invoice, name='create_invoice'),
    path('invoices/delete/<int:pk>/', views.delete_invoice, name='delete_invoice'),
    path('upload_invoice_pdf/', views.upload_invoice_pdf, name='upload_invoice_pdf'),
]
