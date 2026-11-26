from django.urls import path

from branch_access import views

urlpatterns = [path("", views.WorkingBranchView.as_view(), name="working-branch")]
