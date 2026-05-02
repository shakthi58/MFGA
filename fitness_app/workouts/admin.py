from django.contrib import admin

from .models import WorkoutSession, Exercise, WorkoutEntry, Goal, AIInteraction


@admin.register(WorkoutSession)
class WorkoutSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'date', 'created_at')
    search_fields = ('user__username', 'name', 'notes')
    list_filter = ('date',)


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'muscle_group', 'is_active')
    search_fields = ('name', 'muscle_group')
    list_filter = ('category', 'is_active')


@admin.register(WorkoutEntry)
class WorkoutEntryAdmin(admin.ModelAdmin):
    list_display = ('session', 'exercise', 'sets', 'reps', 'weight', 'rpe')
    search_fields = ('session__name', 'exercise__name', 'notes')
    list_filter = ('exercise__category',)


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'goal_type', 'deadline', 'completed')
    search_fields = ('user__username', 'title', 'target_value')
    list_filter = ('goal_type', 'completed')


@admin.register(AIInteraction)
class AIInteractionAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at')
    search_fields = ('user__username', 'prompt', 'response')
    list_filter = ('created_at',)
