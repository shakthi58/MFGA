from django.conf import settings
from django.db import models
from django.utils import timezone


class WorkoutSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workout_sessions',
    )
    name = models.CharField(max_length=120, blank=True,
                            help_text='Optional session title')
    date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return self.name or f"Workout on {self.date}"


class Exercise(models.Model):
    CATEGORY_CHOICES = [
        ('strength', 'Strength'),
        ('conditioning', 'Conditioning'),
        ('mobility', 'Mobility'),
        ('power', 'Power'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=120)
    category = models.CharField(
        max_length=24, choices=CATEGORY_CHOICES, default='strength')
    muscle_group = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = ('name', 'category')

    def __str__(self):
        return self.name


class WorkoutEntry(models.Model):
    session = models.ForeignKey(
        WorkoutSession,
        on_delete=models.CASCADE,
        related_name='entries',
    )
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.PROTECT,
        related_name='entries',
    )
    sets = models.PositiveSmallIntegerField(default=3)
    reps = models.PositiveSmallIntegerField(default=8)
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    rpe = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        help_text='Rate of perceived exertion, 1.0-10.0',
    )
    rest_seconds = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['session', 'exercise']

    def __str__(self):
        return f"{self.exercise.name}: {self.sets}x{self.reps} @ {self.weight}"

    def volume(self):
        return self.sets * self.reps * float(self.weight)


class Goal(models.Model):
    GOAL_TYPE_CHOICES = [
        ('strength', 'Strength'),
        ('hypertrophy', 'Hypertrophy'),
        ('endurance', 'Endurance'),
        ('mobility', 'Mobility'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='goals',
    )
    title = models.CharField(max_length=120)
    goal_type = models.CharField(
        max_length=24, choices=GOAL_TYPE_CHOICES, default='strength')
    target_value = models.CharField(
        max_length=64, help_text='Example: 200 lbs squat or 5 weekly sessions')
    deadline = models.DateField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['completed', 'deadline']

    def __str__(self):
        return self.title


class AIInteraction(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_interactions',
    )
    prompt = models.TextField()
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"AI tip for {self.user.username} @ {self.created_at:%Y-%m-%d %H:%M}"


class MealLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='meal_logs',
    )
    food_name = models.CharField(max_length=120)
    photo = models.FileField(upload_to='meal_photos/')
    calories = models.PositiveIntegerField(default=0)
    protein_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    carbs_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    fat_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    fiber_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    ai_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.food_name} ({self.user.username})"
