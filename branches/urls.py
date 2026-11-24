from django.urls import path

from branches import views

urlpatterns = [
    path("", views.BranchListCreateView.as_view(), name="branches"),
    path("<int:id>/", views.BranchDetailView.as_view(), name="branch"),
    path("<int:id>/deactivate/", views.BranchDeactivateView.as_view(), name="branch-deactivate"),
    path("<int:id>/activate/", views.BranchActivateView.as_view(), name="branch-activate"),
]
