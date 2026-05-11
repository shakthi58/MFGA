import json
import logging
import base64
import mimetypes
import io
from decimal import Decimal, InvalidOperation
from urllib import error, request
from PIL import Image

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import MealLogForm, WorkoutEntryForm, WorkoutSessionForm
from .models import AIInteraction, MealLog, WorkoutEntry, WorkoutSession

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


def _extract_json_payload(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("No JSON object found", cleaned, 0)
    return json.loads(cleaned[start:end + 1])


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _call_groq_chat(messages, model_name, max_tokens=400, temperature=0.4):
    api_key = getattr(settings, "GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GROQ_API_KEY is missing")

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "fitness-app/1.0 (+django)",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def _prepare_image_for_model(photo):
    """Resize/compress uploaded images so vision inference is stable and affordable."""
    raw_bytes = photo.read()
    photo.seek(0)
    try:
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        # Keep enough detail for food recognition while avoiding huge payloads.
        img.thumbnail((1024, 1024))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        mime_type = getattr(photo, "content_type", "") or mimetypes.guess_type(photo.name)[0] or "image/jpeg"
        return raw_bytes, mime_type


def _generate_groq_feedback(user):
    if not getattr(settings, "GROQ_API_KEY", "").strip():
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

    try:
        return _call_groq_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model_name=model_name,
            max_tokens=450,
            temperature=0.4,
        )
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


def _estimate_meal_macros(photo):
    if not getattr(settings, "GROQ_API_KEY", "").strip():
        return {
            "food_name": "Unknown meal",
            "calories": 0,
            "protein_g": Decimal("0"),
            "carbs_g": Decimal("0"),
            "fat_g": Decimal("0"),
            "fiber_g": Decimal("0"),
            "ai_notes": "Set GROQ_API_KEY to enable image-based macro detection.",
        }

    file_bytes, mime_type = _prepare_image_for_model(photo)
    base64_image = base64.b64encode(file_bytes).decode("utf-8")
    image_data_uri = f"data:{mime_type};base64,{base64_image}"

    primary_model = getattr(settings, "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    fallback_model = getattr(settings, "GROQ_VISION_FALLBACK_MODEL", "llama-3.2-11b-vision-preview")
    system_prompt = (
        "You are a certified nutrition coach. Estimate macros from meal images. "
        "Return only valid JSON and do not include markdown."
    )
    user_text = (
        "Analyze this food photo and estimate macro nutrients for one serving.\n"
        "Respond with JSON using keys:\n"
        "food_name (string), calories (integer), protein_g (number), carbs_g (number), "
        "fat_g (number), fiber_g (number), ai_notes (string).\n"
        "Keep ai_notes short and practical."
    )

    payload_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_uri}},
            ],
        },
    ]

    try:
        try:
            raw_content = _call_groq_chat(
                messages=payload_messages,
                model_name=primary_model,
                max_tokens=350,
                temperature=0.2,
            )
        except error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = "<no response body>"
            logger.warning(
                "Meal estimation primary model failed with status %s. Response: %s",
                exc.code,
                error_body,
            )
            raw_content = _call_groq_chat(
                messages=payload_messages,
                model_name=fallback_model,
                max_tokens=350,
                temperature=0.2,
            )

        parsed = _extract_json_payload(raw_content)
        macros = {
            "food_name": str(parsed.get("food_name", "Unknown meal"))[:120] or "Unknown meal",
            "calories": max(int(parsed.get("calories", 0) or 0), 0),
            "protein_g": max(_to_decimal(parsed.get("protein_g", 0)), Decimal("0")),
            "carbs_g": max(_to_decimal(parsed.get("carbs_g", 0)), Decimal("0")),
            "fat_g": max(_to_decimal(parsed.get("fat_g", 0)), Decimal("0")),
            "fiber_g": max(_to_decimal(parsed.get("fiber_g", 0)), Decimal("0")),
            "ai_notes": str(parsed.get("ai_notes", "")).strip(),
        }
        # Avoid storing empty output as a successful analysis.
        if macros["calories"] == 0 and macros["protein_g"] == 0 and macros["carbs_g"] == 0 and macros["fat_g"] == 0:
            macros["ai_notes"] = (macros["ai_notes"] + " " if macros["ai_notes"] else "") + (
                "Low-confidence estimate. Try a clearer image with one meal item."
            )
        return macros
    except Exception as exc:
        logger.warning("Meal macro estimation failed: %s", exc)
        return {
            "food_name": "Unknown meal",
            "calories": 0,
            "protein_g": Decimal("0"),
            "carbs_g": Decimal("0"),
            "fat_g": Decimal("0"),
            "fiber_g": Decimal("0"),
            "ai_notes": "AI could not estimate this image. Try a clearer photo.",
        }


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


@login_required(login_url='/admin/login/')
def meal_log_list_create(request):
    meal_logs = MealLog.objects.filter(user=request.user)
    error_text = ""

    if request.method == 'POST':
        form = MealLogForm(request.POST, request.FILES)
        if form.is_valid():
            photo = form.cleaned_data['photo']
            if photo.size > 8 * 1024 * 1024:
                error_text = "Image is too large. Please upload an image under 8 MB."
            else:
                macros = _estimate_meal_macros(photo)
                MealLog.objects.create(
                    user=request.user,
                    food_name=macros["food_name"],
                    photo=photo,
                    calories=macros["calories"],
                    protein_g=macros["protein_g"],
                    carbs_g=macros["carbs_g"],
                    fat_g=macros["fat_g"],
                    fiber_g=macros["fiber_g"],
                    ai_notes=macros["ai_notes"],
                )
                return redirect('workouts:meal_log_list')
    else:
        form = MealLogForm()

    return render(request, 'workouts/meal_log_list.html', {
        'form': form,
        'meal_logs': meal_logs,
        'error_text': error_text,
    })


@login_required(login_url='/admin/login/')
def session_delete(request, pk):
    session = get_object_or_404(WorkoutSession, pk=pk, user=request.user)
    if request.method == 'POST':
        session.delete()
        return redirect('workouts:session_list')
    return render(request, 'workouts/session_confirm_delete.html', {'session': session})


@login_required(login_url='/admin/login/')
def entry_delete(request, pk, entry_id):
    session = get_object_or_404(WorkoutSession, pk=pk, user=request.user)
    entry = get_object_or_404(WorkoutEntry, pk=entry_id, session=session)
    if request.method == 'POST':
        entry.delete()
        return redirect('workouts:session_detail', pk=session.pk)
    return render(request, 'workouts/entry_confirm_delete.html', {'session': session, 'entry': entry})
