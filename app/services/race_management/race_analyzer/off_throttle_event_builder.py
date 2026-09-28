from __future__ import annotations

from typing import Any


class OffThrottleEventBuilder:
    """
    Groups continuous off-throttle phases into
    reusable events and derives normalized metrics
    used by higher-level classifiers.

    Event statistics are normalized relative to
    the current lap, allowing downstream
    classifiers to remain independent of season,
    circuit and vehicle performance.
    """

    OFF_THROTTLE = {
        "ROLL",
        "LIFT",
    }

    @classmethod
    def build(
        cls,
        phases: list[dict[str, Any]],
        telemetry,
        zone_progress: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        context_lookup = {
            (
                phase["startTime"],
                phase["endTime"],
            ): phase
            for phase in phases
        }

        zone_lookup = {
            (
                z["startTime"],
                z["endTime"],
            ): z
            for z in zone_progress
        }

        events = []

        current = None

        for phase in phases:

            if phase["phase"] not in cls.OFF_THROTTLE:

                if current is not None:
                    events.append(current)
                    current = None

                continue

            key = (
                phase["startTime"],
                phase["endTime"],
            )

            context = context_lookup[key]
            zone = zone_lookup[key]

            phase_object = {
                #
                # Driving phase
                #
                "phase": phase["phase"],

                "startTime": phase["startTime"],
                "endTime": phase["endTime"],
                "duration": phase["duration"],

                "startDistance": phase["startDistance"],
                "endDistance": phase["endDistance"],

                #
                # Context
                #
                "previousPhase": context["previousPhase"],
                "nextPhase": context["nextPhase"],

                "previousIsBrake": context["previousIsBrake"],
                "nextIsBrake": context["nextIsBrake"],

                "previousIsThrottle": context["previousIsThrottle"],
                "nextIsThrottle": context["nextIsThrottle"],

                #
                # Zone
                #
                "zone": zone["zone"],
                "relationship": zone["relationship"],

                "entryProgress": zone["entryProgress"],
                "exitProgress": zone["exitProgress"],

                "distanceToEntry": zone["distanceToEntry"],
                "distanceToExit": zone["distanceToExit"],
            }

            #
            # Start a new off-throttle event.
            #
            if current is None:

                current = {
                    "startTime": phase["startTime"],
                    "endTime": phase["endTime"],
                    "startDistance": phase["startDistance"],
                    "endDistance": phase["endDistance"],
                    "phases": [],
                }

            #
            # If the corner relationship jumps
            # (AFTER -> BEFORE, INSIDE -> AFTER, etc.)
            # this is almost certainly a new event.
            #
            elif (
                current["phases"][-1]["relationship"],
                phase_object["relationship"],
            ) in {
                ("AFTER", "BEFORE"),
                ("AFTER", "ENTERS"),
                ("AFTER", "INSIDE"),
                ("INSIDE", "AFTER"),
                ("EXITS", "BEFORE"),
            }:

                events.append(current)

                current = {
                    "startTime": phase["startTime"],
                    "endTime": phase["endTime"],
                    "startDistance": phase["startDistance"],
                    "endDistance": phase["endDistance"],
                    "phases": [],
                }

            current["phases"].append(
                phase_object
            )

            current["endTime"] = phase["endTime"]
            current["endDistance"] = phase["endDistance"]

        if current is not None:
            events.append(current)
            
        lap_max_speed = float(
            telemetry["Speed"].max()
        )

        for event in events:

            event["phaseCount"] = len(
                event["phases"]
            )

            event["containsRoll"] = any(
                phase["phase"] == "ROLL"
                for phase in event["phases"]
            )

            event["containsLift"] = any(
                phase["phase"] == "LIFT"
                for phase in event["phases"]
            )

            event["startsWith"] = (
                event["phases"][0]["phase"]
            )

            event["endsWith"] = (
                event["phases"][-1]["phase"]
            )
            
            first = event["phases"][0]
            last = event["phases"][-1]
            
            event["previousIsThrottle"] = (
                first["previousIsThrottle"]
            )

            event["previousIsBrake"] = (
                first["previousIsBrake"]
            )

            event["nextIsThrottle"] = (
                last["nextIsThrottle"]
            )

            event["nextIsBrake"] = (
                last["nextIsBrake"]
            )
            
            #
            # Telemetry covering the entire off-throttle event.
            #
            start_phase = context_lookup[
                (
                    first["startTime"],
                    first["endTime"],
                )
            ]

            end_phase = context_lookup[
                (
                    last["startTime"],
                    last["endTime"],
                )
            ]

            start_index = start_phase["startIndex"]
            end_index = end_phase["endIndex"]

            segment = telemetry.iloc[
                start_index:end_index + 1
            ]

            start_sample = telemetry.iloc[start_index]
            end_sample = telemetry.iloc[end_index]

            event["firstRelationship"] = (
                first["relationship"]
            )

            event["lastRelationship"] = (
                last["relationship"]
            )

            event["entryProgress"] = (
                first["entryProgress"]
            )

            event["exitProgress"] = (
                last["exitProgress"]
            )

            event["distanceToEntry"] = (
                first["distanceToEntry"]
            )

            event["distanceToExit"] = (
                last["distanceToExit"]
            )

            event["startsBeforeCorner"] = (
                first["relationship"] == "BEFORE"
            )

            event["startsInsideCorner"] = (
                first["relationship"] == "INSIDE"
            )

            event["endsInsideCorner"] = (
                last["relationship"]
                in (
                    "INSIDE",
                    "EXITS",
                )
            )

            event["endsAfterCorner"] = (
                last["relationship"] == "AFTER"
            )

            event["zoneRelationship"] = (
                f"{first['relationship']} -> "
                f"{last['relationship']}"
            )

            event["duration"] = round(
                event["endTime"]
                - event["startTime"],
                3,
            )

            event["distance"] = round(
                event["endDistance"]
                - event["startDistance"],
                3,
            )
            
            event["zone"] = (
                first["zone"]
            )
            
            #
            # Event telemetry metrics.
            #
            event["startSpeed"] = float(
                start_sample["Speed"]
            )

            event["endSpeed"] = float(
                end_sample["Speed"]
            )

            event["averageSpeed"] = round(
                float(segment["Speed"].mean()),
                1,
            )

            event["minimumSpeed"] = round(
                float(segment["Speed"].min()),
                1,
            )

            event["maximumSpeed"] = round(
                float(segment["Speed"].max()),
                1,
            )
            
            event["speedRatio"] = round(
                event["maximumSpeed"] / lap_max_speed,
                3,
            )

            event["speedLoss"] = round(
                max(
                    0.0,
                    event["startSpeed"]
                    - event["endSpeed"],
                ),
                1,
            )
            
            event["averageDeceleration"] = round(
                event["speedLoss"]
                / max(event["duration"], 0.001),
                1,
            )
            
            event["speedDropPercent"] = round(
                (
                    event["speedLoss"]
                    / max(event["startSpeed"], 1)
                ) * 100,
                1,
            )

            event["startThrottle"] = float(
                start_sample["Throttle"]
            )

            event["endThrottle"] = float(
                end_sample["Throttle"]
            )

            event["averageThrottle"] = round(
                float(segment["Throttle"].mean()),
                1,
            )

            event["startRPM"] = int(
                start_sample["RPM"]
            )

            event["endRPM"] = int(
                end_sample["RPM"]
            )

            event["rpmLoss"] = max(
                0,
                event["startRPM"]
                - event["endRPM"],
            )

            event["startGear"] = int(
                start_sample["nGear"]
            )

            event["endGear"] = int(
                end_sample["nGear"]
            )

            event["gearChange"] = (
                event["endGear"]
                - event["startGear"]
            )

            event["startBrake"] = bool(
                start_sample["Brake"]
            )

            event["endBrake"] = bool(
                end_sample["Brake"]
            )

            event["startDRS"] = int(
                start_sample["DRS"]
            )

            event["endDRS"] = int(
                end_sample["DRS"]
            )
            
        
        max_speed_loss = max(
            0.001,
            max(
                (
                    event["speedLoss"]
                    for event in events
                ),
                default=0.0,
            ),
        )

        max_rpm_loss = max(
            1,
            max(
                (
                    event["rpmLoss"]
                    for event in events
                ),
                default=0,
            ),
        )

        max_distance = max(
            (
                event["distance"]
                for event in events
            ),
            default=0.001,
        )

        max_duration = max(
            (
                event["duration"]
                for event in events
            ),
            default=0.001,
        )
        
        for event in events:

            event["speedLossRatio"] = round(
                event["speedLoss"] / max_speed_loss,
                3,
            )

            event["rpmLossRatio"] = round(
                event["rpmLoss"] / max_rpm_loss,
                3,
            )

            event["distanceRatio"] = round(
                event["distance"] / max_distance,
                3,
            )

            event["durationRatio"] = round(
                event["duration"] / max_duration,
                3,
            )

        return events