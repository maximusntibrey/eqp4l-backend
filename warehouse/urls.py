from django.urls import path

from warehouse import views

urlpatterns = [
    path("goods-receipts/", views.GoodsReceiptListCreateView.as_view(), name="goods-receipts"),
    path("goods-receipts/<int:id>/", views.GoodsReceiptDetailView.as_view(), name="goods-receipt-detail"),
]
