from django.urls import path
from . import views, api_views
from .user_auth import logout_view

urlpatterns = [
    # ── Pages ─────────────────────────────────────────────────────────────────
    path('',                              views.index,           name='index'),
    path('my-team/',                      views.my_team,         name='my_team'),
    path('my-department/',                views.my_department,   name='my_department'),
    path('pathways/',                     views.pathways_manage, name='pathways_manage'),
    path('employee/<str:employee_wwid>/', views.employee_detail, name='employee_detail'),
    path('team/<str:mgr_wwid>/',           views.team_detail,     name='team_detail'),
    path('logout/',                       logout_view,           name='logout'),

    # ── Auth API ───────────────────────────────────────────────────────────────
    path('api/set-user-info/',       api_views.set_user_info,          name='api_set_user_info'),
    path('api/auth-event/',          api_views.auth_client_event,      name='api_auth_event'),
    path('api/bootstrap-user/',      api_views.bootstrap_user_session, name='api_bootstrap_user'),
    # ── Training actions ───────────────────────────────────────────────────────
    path('api/mark-complete/',       api_views.mark_course_complete,   name='api_mark_complete'),
    path('api/assign-pathway/',      api_views.assign_pathway,         name='api_assign_pathway'),
    path('api/remove-pathway/',      api_views.remove_pathway,         name='api_remove_pathway'),
    path('api/remove-course/',        api_views.remove_course,          name='api_remove_course'),

    # ── Pathway CRUD ───────────────────────────────────────────────────────────
    path('api/pathway/add-course/',                  api_views.add_pathway_course,    name='api_add_course'),
    path('api/pathway/edit-course/<int:course_id>/', api_views.edit_pathway_course,   name='api_edit_course'),
    path('api/pathway/delete-course/<int:course_id>/', api_views.delete_pathway_course, name='api_delete_course'),
    path('api/pathway/edit/',                        api_views.edit_pathway,          name='api_edit_pathway'),
    path('api/pathway/delete/',                      api_views.delete_pathway,        name='api_delete_pathway'),

    # ── Team management ────────────────────────────────────────────────────────
    path('api/employee/<str:employee_wwid>/', api_views.employee_data, name='api_employee_data'),
]
