from django.urls import path

from transfers import views

urlpatterns = [
    path("dispatches/", views.DispatchListCreateView.as_view(), name="dispatches"),
    path("dispatches/waiting/", views.DispatchWaitingView.as_view(), name="dispatches-waiting"),
    path("dispatches/<int:id>/", views.DispatchDetailView.as_view(), name="dispatch-detail"),
    path("dispatches/<int:id>/receive/", views.DispatchReceiveView.as_view(), name="dispatch-receive"),
    path("shortfalls/", views.ShortfallListView.as_view(), name="shortfalls"),
    path("shortfalls/<int:id>/resolve/", views.ShortfallResolveView.as_view(), name="shortfall-resolve"),
]
