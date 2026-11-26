from django.urls import path

from inventory import import_views, stock_views, views

urlpatterns = [
    path("item-categories/", views.CategoryListView.as_view(), name="item-categories"),
    path("brands/", views.BrandListCreateView.as_view(), name="brands"),
    path("brands/<int:id>/", views.BrandDetailView.as_view(), name="brand-detail"),
    path("item-field-definitions/", views.FieldDefinitionListView.as_view(), name="item-field-definitions"),
    path("item-imports/", import_views.ItemImportView.as_view(), name="item-imports"),
    path("items/", views.ItemListCreateView.as_view(), name="items"),
    path("costed-items/", views.CostedItemListView.as_view(), name="costed-items"),
    path("costed-items/<int:id>/", views.CostedItemDetailView.as_view(), name="costed-item-detail"),
    path("items/<int:id>/", views.ItemDetailView.as_view(), name="item-detail"),
    path("items/<int:id>/status/", views.ItemStatusView.as_view(), name="item-status"),
    path("items/<int:id>/image/", views.ItemImageView.as_view(), name="item-image"),
    path("items/<int:id>/branch-availability/", stock_views.BranchAvailabilityView.as_view()),
    path("stock/movements/", stock_views.StockMovementListView.as_view(), name="stock-movements"),
    path("stock/", stock_views.StockListView.as_view(), name="stock"),
    path("costed-stock/", stock_views.CostedStockListView.as_view(), name="costed-stock"),
]
