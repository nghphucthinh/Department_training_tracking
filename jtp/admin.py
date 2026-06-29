from django.contrib import admin
from .models import JTPAdminUser, JTPTeamMember, JTPAccessLog


@admin.register(JTPAdminUser)
class JTPAdminUserAdmin(admin.ModelAdmin):
    list_display  = ('isid', 'email', 'wwid', 'created_at')
    search_fields = ('isid', 'email', 'wwid')


@admin.register(JTPTeamMember)
class JTPTeamMemberAdmin(admin.ModelAdmin):
    list_display  = ('mgr_wwid', 'employee_name', 'employee_wwid', 'employee_email')
    list_filter   = ('mgr_wwid',)
    search_fields = ('employee_name', 'employee_wwid', 'mgr_wwid')


@admin.register(JTPAccessLog)
class JTPAccessLogAdmin(admin.ModelAdmin):
    list_display  = ('user_name', 'user_email', 'wwid', 'page_url', 'accessed_at')
    list_filter   = ('page_url',)
    search_fields = ('user_email', 'user_name', 'wwid')
    readonly_fields = ('accessed_at',)
