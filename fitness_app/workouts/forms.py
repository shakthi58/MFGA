from django import forms

from .models import MealLog, WorkoutEntry, WorkoutSession


class WorkoutSessionForm(forms.ModelForm):
    class Meta
        model = WorkoutSession
        fields = ['name', 'date', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Example: Leg day'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class WorkoutEntryForm(forms.ModelForm):
    class Meta:
        model = WorkoutEntry
        fields = ['exercise', 'sets', 'reps',
                  'weight', 'rpe', 'rest_seconds', 'notes']
        widgets = {
            'exercise': forms.Select(attrs={'class': 'form-select'}),
            'sets': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'reps': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.25', 'min': 0}),
            'rpe': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': 1, 'max': 10}),
            'rest_seconds': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class MealLogForm(forms.ModelForm):
    class Meta:
        model = MealLog
        fields = ['photo']
        widgets = {
            'photo': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }
