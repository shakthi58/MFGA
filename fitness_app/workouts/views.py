import json
import logging
from urllib import error, request

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import WorkoutEntryForm, WorkoutSessionForm
from .models import AIInteraction, WorkoutSession

logger = logging.getLogger(__name__)


def _average_session_volume(sessions):
    if not sessions:
        return 0

    total_volume = 0
    for session in sessions:
        for entry in session.entries.all():
            total_volume += entry.volume()
    return total_volume / len(sessions)


def _exercise_progression_summary(sessions):
    exercise_stats = {}
    for session in sessions:
        for entry in session.entries.all():
            name = entry.exercise.name
            weight_value = float(entry.weight)
            volume_value = entry.volume()
            if name not in exercise_stats:
                exercise_stats[name] = {"max_weight": weight_value, "max_volume": volume_value}
                continue
            exercise_stats[name]["max_weight"] = max(exercise_stats[name]["max_weight"], weight_value)
            exercise_stats[name]["max_volume"] = max(exercise_stats[name]["max_volume"], volume_value)
    return exercise_stats


def _build_progress_feedback(user):
    sessions = list(
        WorkoutSession.objects.filter(user=user)
        .order_by("date", "created_at")
        .prefetch_related("entries", "entries__exercise")
    )
    if len(sessions) < 2:
        return (
            "You are just getting started. Log at least 2 sessions to unlock trend-based AI feedback "
            "on intensity, volume, and consistency."
        )

    split_index = max(1, len(sessions) // 2)
    earlier_block = sessions[:split_index]
    recent_block = sessions[split_index:]

    earlier_avg_volume = _average_session_volume(earlier_block)
    recent_avg_volume = _average_session_volume(recent_block)
    volume_delta = recent_avg_volume - earlier_avg_volume

    first_date = sessions[0].date
    last_date = sessions[-1].date
    span_days = max((last_date - first_date).days, 1)
    sessions_per_week = (len(sessions) / span_days) * 7

    early_exercises = _exercise_progression_summary(earlier_block)
    recent_exercises = _exercise_progression_summary(recent_block)
    improved_exercises = []
    for exercise_name, recent_values in recent_exercises.items():
        early_values = early_exercises.get(exercise_name)
        if not early_values:
            continue
        if recent_values["max_weight"] > early_values["max_weight"]:
            improved_exercises.append(exercise_name)

    feedback_lines = []
    if volume_delta > 0:
        feedback_lines.append(
            f"Your average session volume is up by {volume_delta:.1f}, showing progressive overload."
        )
    elif volume_delta < 0:
        feedback_lines.append(
            f"Your average session volume is down by {abs(volume_delta):.1f}; consider adding a gradual load increase."
        )
    else:
        feedback_lines.append("Your average session volume is stable. Add a small progression target next week.")

    feedback_lines.append(f"You are training at about {sessions_per_week:.1f} sessions/week.")

    if improved_exercises:
        top_improvements = ", ".join(improved_exercises[:3])
        feedback_lines.append(f"Strength trend looks positive for: {top_improvements}.")
    else:
        feedback_lines.append(
            "No exercise has a clear upward load trend yet. Try increasing weight or reps on one key lift."
        )

    if sessions_per_week < 2:
        feedback_lines.append("Consistency is the biggest unlock now; target at least 2 sessions/week.")
    elif sessions_per_week > 4:
        feedback_lines.append("Great consistency. Keep 1 lighter recovery session to sustain progress.")
    else:
        feedback_lines.append("Your consistency is solid. Keep your current cadence and progress slowly.")

    return "\n".join(feedback_lines)


def _build_workout_summary_for_prompt(user):
    sessions = list(
        WorkoutSession.objects.filter(user=user)
        .order_by("date", "created_at")
        .prefetch_related("entries", "entries__exercise")
    )
    if not sessions:
        return "No workout sessions logged yet."

    lines = []
    for session in sessions[-12:]:
        entry_parts = []
        for entry in session.entries.all():
            entry_parts.append(
                f"{entry.exercise.name}: {entry.sets}x{entry.reps} @ {entry.weight}kg"
            )
        session_line = f"- {session.date}: " + ("; ".join(entry_parts) if entry_parts else "No entries")
        lines.append(session_line)
    return "\n".join(lines)


def _generate_groq_feedback(user):
    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        return _build_progress_feedback(user)

    model_name = getattr(settings, "GROQ_MODEL", "llama-3.1-8b-instant")
    workout_summary = _build_workout_summary_for_prompt(user)
    system_prompt = (
        "You are an elite strength and conditioning coach. Analyze workout progression over time and provide "
        "clear, practical guidance. Keep tone motivational but direct. Do not invent workouts not in input."
    )
    user_prompt = (
        "Use this workout history to provide coaching feedback.\n"
        "Return 4 short sections with these headers: Trend, What is improving, Risk to watch, Next-week plan.\n"
        "Include concrete progression suggestions.\n\n"
        f"Workout history:\n{workout_summary}"
    )

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 450,
    }
    try:
        req = request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "fitness-app/1.0 (+django)",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()
    except error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = "<no response body>"
        logger.warning(
            "Groq feedback generation failed with status %s. Response: %s",
            exc.code,
            error_body,
        )
        return _build_progress_feedback(user)
    except (error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.warning("Groq feedback generation failed: %s", exc)
        return _build_progress_feedback(user)


@login_required(login_url='/admin/login/')
def session_list(request):
    sessions = WorkoutSession.objects.filter(
        user=request.user).prefetch_related('entries').order_by('-date', '-created_at')
    latest_ai_feedback = AIInteraction.objects.filter(user=request.user).first()

    if request.method == 'POST' and request.POST.get('action') == 'generate_ai_feedback':
        prompt = "Analyze my workout progression and share actionable coaching feedback."
        response = _generate_groq_feedback(request.user)
        AIInteraction.objects.create(user=request.user, prompt=prompt, response=response)
        return redirect('workouts:session_list')

    return render(request, 'workouts/session_list.html', {
        'sessions': sessions,
        'latest_ai_feedback': latest_ai_feedback,
    })


@login_required(login_url='/admin/login/')
def session_create(request):
    if request.method == 'POST':
        form = WorkoutSessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.user = request.user
            session.save()
            return redirect('workouts:session_detail', pk=session.pk)
    else:
        form = WorkoutSessionForm()

    return render(request, 'workouts/session_form.html', {'form': form})


@login_required(login_url='/admin/login/')
def session_detail(request, pk):
    session = get_object_or_404(WorkoutSession, pk=pk, user=request.user)
    if request.method == 'POST':
        entry_form = WorkoutEntryForm(request.POST)
        if entry_form.is_valid():
            entry = entry_form.save(commit=False)
            entry.session = session
            entry.save()
            return redirect('workouts:session_detail', pk=pk)
    else:
        entry_form = WorkoutEntryForm()

    return render(request, 'workouts/session_detail.html', {
        'session': session,
        'entry_form': entry_form,
    })
