from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AIInteraction, Exercise, WorkoutEntry, WorkoutSession
from .views import _build_progress_feedback


class GenAIFeedbackTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='coach_user',
            password='testpass123',
        )
        self.exercise = Exercise.objects.create(name='Squat', category='strength')

    def test_build_progress_feedback_with_minimal_data(self):
        session = WorkoutSession.objects.create(
            user=self.user,
            name='Only session',
            date=timezone.localdate(),
        )
        WorkoutEntry.objects.create(
            session=session,
            exercise=self.exercise,
            sets=3,
            reps=5,
            weight=Decimal('100.00'),
        )

        feedback = _build_progress_feedback(self.user)
        self.assertIn('at least 2 sessions', feedback)

    @patch('workouts.views._generate_groq_feedback')
    def test_post_generate_feedback_creates_ai_interaction(self, mock_generate_feedback):
        mock_generate_feedback.return_value = 'Mocked AI feedback'
        first_date = timezone.localdate() - timedelta(days=7)
        second_date = timezone.localdate()

        first_session = WorkoutSession.objects.create(
            user=self.user,
            name='Week 1',
            date=first_date,
        )
        second_session = WorkoutSession.objects.create(
            user=self.user,
            name='Week 2',
            date=second_date,
        )
        WorkoutEntry.objects.create(
            session=first_session,
            exercise=self.exercise,
            sets=3,
            reps=5,
            weight=Decimal('80.00'),
        )
        WorkoutEntry.objects.create(
            session=second_session,
            exercise=self.exercise,
            sets=3,
            reps=5,
            weight=Decimal('90.00'),
        )

        self.client.login(username='coach_user', password='testpass123')
        response = self.client.post(
            reverse('workouts:session_list'),
            {'action': 'generate_ai_feedback'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AIInteraction.objects.filter(user=self.user).count(), 1)
        interaction = AIInteraction.objects.get(user=self.user)
        self.assertIn('Analyze my workout progression', interaction.prompt)
        self.assertEqual('Mocked AI feedback', interaction.response)
