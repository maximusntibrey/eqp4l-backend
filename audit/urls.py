from django.urls import path

from audit import views

urlpatterns = [
    path("activity-log/", views.ActivityLogView.as_view(), name="activity-log"),
    path("activity-log/export/", views.ActivityLogExportView.as_view(), name="activity-log-export"),
]
