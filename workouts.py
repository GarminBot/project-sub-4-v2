"""
Baut strukturierte Lauf-Workouts aus einer einfachen JSON-Beschreibung und laedt
sie via garminconnect hoch (+ optional Einplanung auf ein Datum).
"""

from __future__ import annotations

from typing import Any

from garminconnect import Garmin
from garminconnect.workout import (
    RunningWorkout,
    WorkoutSegment,
    create_cooldown_step,
    create_interval_step,
    create_recovery_step,
    create_repeat_group,
    create_warmup_step,
)

RUNNING_SPORT_TYPE = {"sportTypeId": 1, "sportTypeKey": "running"}


def _build_step(step: dict[str, Any]):
    step_type = step.get("type")

    if step_type == "warmup":
        return create_warmup_step(step["duration_seconds"])
    if step_type == "cooldown":
        return create_cooldown_step(step["duration_seconds"])
    if step_type == "interval":
        if "distance_meters" in step:
            return create_interval_step(distance_meters=step["distance_meters"])
        return create_interval_step(duration_seconds=step["duration_seconds"])
    if step_type == "recovery":
        if "distance_meters" in step:
            return create_recovery_step(distance_meters=step["distance_meters"])
        return create_recovery_step(duration_seconds=step["duration_seconds"])
    if step_type == "repeat":
        inner_steps = [_build_step(s) for s in step["steps"]]
        return create_repeat_group(repeat_count=step["count"], steps=inner_steps)

    raise ValueError(f"Unbekannter step type: {step_type!r}")


def build_custom_workout(name: str, steps: list[dict[str, Any]]) -> RunningWorkout:
    built_steps = [_build_step(s) for s in steps]
    return RunningWorkout(
        workoutName=name,
        workoutSegments=[
            WorkoutSegment(segmentOrder=1, sportType=RUNNING_SPORT_TYPE, workoutSteps=built_steps)
        ],
    )


def build_interval_workout(
    name: str,
    warmup_secs: int,
    interval_meters: float,
    interval_count: int,
    recovery_secs: int,
    cooldown_secs: int,
) -> RunningWorkout:
    steps = [
        {"type": "warmup", "duration_seconds": warmup_secs},
        {
            "type": "repeat",
            "count": interval_count,
            "steps": [
                {"type": "interval", "distance_meters": interval_meters},
                {"type": "recovery", "duration_seconds": recovery_secs},
            ],
        },
        {"type": "cooldown", "duration_seconds": cooldown_secs},
    ]
    return build_custom_workout(name, steps)


def build_easy_run_workout(name: str, duration_secs: int) -> RunningWorkout:
    return RunningWorkout(
        workoutName=name,
        estimatedDurationInSecs=duration_secs,
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType=RUNNING_SPORT_TYPE,
                workoutSteps=[create_warmup_step(duration_secs)],
            )
        ],
    )


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
