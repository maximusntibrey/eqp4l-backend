from django.urls import path

from sales import views

urlpatterns = [
    path("sales/", views.SaleListCreateView.as_view(), name="sales"),
    path("sales/<int:id>/", views.SaleDetailView.as_view(), name="sale-detail"),
    path("sales/<int:id>/cancel/", views.SaleCancelView.as_view(), name="sale-cancel"),
    path("costed-sales/", views.CostedSaleListView.as_view(), name="costed-sales"),
    path("costed-sales/<int:id>/", views.CostedSaleDetailView.as_view(), name="costed-sale-detail"),
]
