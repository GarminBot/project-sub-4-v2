"""
Baut strukturierte Lauf-Workouts fuer Garmin Connect.

WICHTIG: Wir bauen die Workout-Steps hier bewusst manuell aus den Low-Level-
Modellen (ExecutableStep, RepeatGroup) statt die create_*_step()-Hilfsfunktionen
der garminconnect-Library zu nutzen. Grund: diese Hilfsfunktionen unterstuetzen
nur Zeit-Endbedingungen (keine Distanz) und keine Puls-/Pace-Ziele - genau das,
was wir brauchen.

Jeder Step braucht eine korrekte, bei 1 beginnende `stepOrder` - sowohl auf der
obersten Ebene (Warmup=1, Repeat=2, Cooldown=3) als auch INNERHALB einer
Repeat-Gruppe (dort beginnt die Nummerierung fuer die Kind-Steps wieder bei 1).
Fehlt das oder ist es falsch verschachtelt, zeigt die Uhr faelschlicherweise
nur einen einzigen Step (z.B. "Aufwaermen") fuer die gesamte Dauer an - das war
der urspruengliche Bug.
"""

from __future__ import annotations

from typing import Any

from garminconnect import Garmin
from garminconnect.workout import (
    ConditionType,
    ExecutableStep,
    RepeatGroup,
    RunningWorkout,
    StepType,
    TargetType,
    WorkoutSegment,
)

RUNNING_SPORT_TYPE = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

_STEP_TYPE_MAP = {
    "warmup": (StepType.WARMUP, "warmup", 1),
    "cooldown": (StepType.COOLDOWN, "cooldown", 2),
    "interval": (StepType.INTERVAL, "interval", 3),
    "recovery": (StepType.RECOVERY, "recovery", 4),
}


def _resolve_target(target: dict[str, Any] | None) -> tuple[dict[str, Any], float | None, float | None]:
    """Wandelt ein target-Dict in (targetType, targetValueOne, targetValueTwo) um.

    Unterstuetzte target-Dicts:
      {"kind": "heart_rate", "min_bpm": 150, "max_bpm": 165}
      {"kind": "pace", "fast_sec_per_km": 270, "slow_sec_per_km": 300}  (4:30-5:00 min/km)
    """
    if not target:
        return {"workoutTargetTypeId": TargetType.NO_TARGET, "workoutTargetTypeKey": "no.target", "displayOrder": 1}, None, None

    kind = target.get("kind")
    if kind == "heart_rate":
        target_type = {"workoutTargetTypeId": TargetType.HEART_RATE_ZONE, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
        return target_type, float(target["min_bpm"]), float(target["max_bpm"])

    if kind == "pace":
        # Pace (Sekunden/km) -> Geschwindigkeit (m/s). Garmin speichert Pace-Ziele als
        # Geschwindigkeits-Range: targetValueOne = untere, targetValueTwo = obere Grenze.
        fast = float(target["fast_sec_per_km"])  # kleinere Zahl = schnelleres Pace
        slow = float(target["slow_sec_per_km"])
        v_min = 1000.0 / slow
        v_max = 1000.0 / fast
        target_type = {"workoutTargetTypeId": TargetType.PACE_ZONE, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}
        return target_type, v_min, v_max

    raise ValueError(f"Unbekannter target 'kind': {kind!r} (erlaubt: 'heart_rate', 'pace')")


def _build_executable_step(step: dict[str, Any], step_order: int) -> ExecutableStep:
    step_type_id, step_type_key, display_order = _STEP_TYPE_MAP[step["type"]]

    if "distance_meters" in step:
        end_condition = {"conditionTypeId": ConditionType.DISTANCE, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True}
        end_value = float(step["distance_meters"])
    else:
        end_condition = {"conditionTypeId": ConditionType.TIME, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
        end_value = float(step["duration_seconds"])

    target_type, v1, v2 = _resolve_target(step.get("target"))

    kwargs: dict[str, Any] = dict(
        stepOrder=step_order,
        stepType={"stepTypeId": step_type_id, "stepTypeKey": step_type_key, "displayOrder": display_order},
        endCondition=end_condition,
        endConditionValue=end_value,
        targetType=target_type,
    )
    if v1 is not None:
        kwargs["targetValueOne"] = v1
        kwargs["targetValueTwo"] = v2

    return ExecutableStep(**kwargs)


def _build_step(step: dict[str, Any], step_order: int) -> ExecutableStep | RepeatGroup:
    if step["type"] == "repeat":
        # Kind-Steps einer Repeat-Gruppe werden unabhaengig ab 1 durchnummeriert.
        children = [_build_step(s, i + 1) for i, s in enumerate(step["steps"])]
        return RepeatGroup(
            stepOrder=step_order,
            stepType={"stepTypeId": StepType.REPEAT, "stepTypeKey": "repeat", "displayOrder": 6},
            numberOfIterations=step["count"],
            workoutSteps=children,
            endCondition={"conditionTypeId": ConditionType.ITERATIONS, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
            endConditionValue=float(step["count"]),
        )
    return _build_executable_step(step, step_order)


def build_custom_workout(name: str, steps: list[dict[str, Any]]) -> RunningWorkout:
    built_steps = [_build_step(s, i + 1) for i, s in enumerate(steps)]
    total_secs = _estimate_duration(steps)
    return RunningWorkout(
        workoutName=name,
        estimatedDurationInSecs=total_secs,
        workoutSegments=[
            WorkoutSegment(segmentOrder=1, sportType=RUNNING_SPORT_TYPE, workoutSteps=built_steps)
        ],
    )


def _estimate_duration(steps: list[dict[str, Any]]) -> int:
    """Grobe Schaetzung in Sekunden, nur fuer das estimatedDurationInSecs-Feld
    (rein informativ, beeinflusst nicht die tatsaechliche Workout-Struktur).
    Distanz-Steps werden mit 5:30 min/km ueberschlagen."""
    total = 0.0
    for s in steps:
        if s["type"] == "repeat":
            inner = _estimate_duration(s["steps"])
            total += inner * s["count"]
        elif "duration_seconds" in s:
            total += s["duration_seconds"]
        elif "distance_meters" in s:
            total += s["distance_meters"] * 5.5 * 60 / 1000
    return int(total)


def build_interval_workout(
    name: str,
    warmup_secs: int,
    interval_meters: float,
    interval_count: int,
    recovery_secs: int,
    cooldown_secs: int,
    target_hr_min: int | None = None,
    target_hr_max: int | None = None,
    target_pace_fast_sec_per_km: int | None = None,
    target_pace_slow_sec_per_km: int | None = None,
) -> RunningWorkout:
    interval_target = None
    if target_hr_min is not None and target_hr_max is not None:
        interval_target = {"kind": "heart_rate", "min_bpm": target_hr_min, "max_bpm": target_hr_max}
    elif target_pace_fast_sec_per_km is not None and target_pace_slow_sec_per_km is not None:
        interval_target = {"kind": "pace", "fast_sec_per_km": target_pace_fast_sec_per_km, "slow_sec_per_km": target_pace_slow_sec_per_km}

    interval_step: dict[str, Any] = {"type": "interval", "distance_meters": interval_meters}
    if interval_target:
        interval_step["target"] = interval_target

    steps = [
        {"type": "warmup", "duration_seconds": warmup_secs},
        {
            "type": "repeat",
            "count": interval_count,
            "steps": [
                interval_step,
                {"type": "recovery", "duration_seconds": recovery_secs},
            ],
        },
        {"type": "cooldown", "duration_seconds": cooldown_secs},
    ]
    return build_custom_workout(name, steps)


def build_easy_run_workout(
    name: str,
    duration_secs: int,
    target_hr_min: int | None = None,
    target_hr_max: int | None = None,
    target_pace_fast_sec_per_km: int | None = None,
    target_pace_slow_sec_per_km: int | None = None,
) -> RunningWorkout:
    target = None
    if target_hr_min is not None and target_hr_max is not None:
        target = {"kind": "heart_rate", "min_bpm": target_hr_min, "max_bpm": target_hr_max}
    elif target_pace_fast_sec_per_km is not None and target_pace_slow_sec_per_km is not None:
        target = {"kind": "pace", "fast_sec_per_km": target_pace_fast_sec_per_km, "slow_sec_per_km": target_pace_slow_sec_per_km}

    step: dict[str, Any] = {"type": "warmup", "duration_seconds": duration_secs}
    if target:
        step["target"] = target

    return build_custom_workout(name, [step])


def upload_and_schedule(client: Garmin, workout: RunningWorkout, schedule_date: str | None):
    result = client.upload_running_workout(workout)
    workout_id = result["workoutId"]
    scheduled = False
    if schedule_date:
        client.schedule_workout(workout_id, schedule_date)
        scheduled = True
    return {
        "workoutId": workout_id,
        "workoutName": workout.workoutName,
        "scheduled": scheduled,
        "scheduleDate": schedule_date,
    }
