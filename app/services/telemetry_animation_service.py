import pandas as pd
import numpy as np
from app.utils.time_utils import convert_all_timedelta_columns
from app.services.track_metrics_service import apply_coordinate_transform


def _convert_session_time_column(series):
    return series.apply(
        lambda value: (
            None
            if pd.isna(value)
            else (
                lambda total_microseconds: (
                    f"{total_microseconds // 3_600_000_000:02}:"
                    f"{(total_microseconds % 3_600_000_000) // 60_000_000:02}:"
                    f"{(total_microseconds % 60_000_000) // 1_000_000:02}."
                    f"{total_microseconds % 1_000_000:06d}"
                )
            )(
                int(value.total_seconds() * 1_000_000)
            )
        )
    )


def build_driver_telemetry_chunks(
    session,
    driver_code,
    track_metrics,
    sample_rate_ms=100
):
    """
    Builds per-second telemetry snapshots for ONE driver.
    Returns: dict[int raceSecond -> telemetry snapshot]
    """

    # --------------------------------------------------
    # LAP TIMING DATA
    # --------------------------------------------------

    laps = (
        session.laps
        .pick_drivers([driver_code])[
            ["LapNumber", "LapStartTime", "Time"]
        ]
        .rename(columns={"Time": "LapEndTime"})
        .copy()
    )

    laps = convert_all_timedelta_columns(laps)

    # --------------------------------------------------
    # RACE START TIME (Lap 1 start)
    # --------------------------------------------------
    race_start_time = (
        session.laps
        .loc[session.laps["LapNumber"] == 1, "LapStartTime"]
        .min()
    )

    race_start_seconds = race_start_time.total_seconds()

    # --------------------------------------------------
    # RAW TELEMETRY
    # --------------------------------------------------

    telemetry = (
        session.laps
        .pick_drivers([driver_code])
        .get_telemetry()
        .copy()
    )

    # FastF1 cumulative distance (never resets)

    telemetry = telemetry.add_distance()

    telemetry["SessionTime"] = (
        _convert_session_time_column(
            telemetry["SessionTime"]
        )
    )

    # --------------------------------------------------
    # ATTACH LAP NUMBER USING TIMING WINDOWS
    # --------------------------------------------------
    #
    # For each telemetry sample, find the last lap whose
    # start time is <= the telemetry timestamp, then
    # verify that the timestamp is still before that
    # lap's end time.
    #
    # This preserves the original rule:
    #
    #     SessionTime >= LapStartTime
    #     SessionTime <  LapEndTime
    #
    # while avoiding a full telemetry scan for every lap.
    # --------------------------------------------------
    
    lap_starts = (
        pd.to_timedelta(
            laps["LapStartTime"]
        )
        .astype("int64")
        .to_numpy()
    )

    lap_ends = (
        pd.to_timedelta(
            laps["LapEndTime"]
        )
        .astype("int64")
        .to_numpy()
    )

    lap_numbers = (
        laps["LapNumber"]
        .to_numpy()
    )

    session_times = (
        pd.to_timedelta(
            telemetry["SessionTime"]
        )
        .astype("int64")
        .to_numpy()
    )

    #
    # Find the last lap whose start time is <=
    # each telemetry sample.
    #
    lap_indexes = (
        np.searchsorted(
            lap_starts,
            session_times,
            side="right",
        )
        - 1
    )

    #
    # Samples before the first lap are invalid.
    #
    valid = (
        lap_indexes >= 0
    )

    #
    # Avoid negative indexing when checking lap ends.
    #
    safe_indexes = np.where(
        valid,
        lap_indexes,
        0,
    )

    #
    # Preserve the original strict end boundary:
    #
    # SessionTime < LapEndTime
    #
    valid &= (
        session_times
        < lap_ends[safe_indexes]
    )

    #
    # Assign lap numbers.
    #
    assigned_laps = np.full(
        len(telemetry),
        np.nan,
    )

    assigned_laps[valid] = (
        lap_numbers[
            lap_indexes[valid]
        ]
    )

    telemetry["LapNumber"] = (
        assigned_laps
    )

    #
    # Remove telemetry that does not belong
    # to any valid lap.
    #
    telemetry = (
        telemetry
        .dropna(
            subset=["LapNumber"]
        )
        .copy()
    )

    telemetry["LapNumber"] = (
        telemetry["LapNumber"]
        .astype(int)
    )

    # --------------------------------------------------
    # RESAMPLE (200 ms)
    # --------------------------------------------------

    telemetry = telemetry.set_index(
        pd.to_timedelta(
            telemetry["SessionTime"]
        )
    )

    resampled = (
        telemetry[["Distance", "X", "Y", "LapNumber"]]
        .resample(f"{sample_rate_ms}ms")
        .last()
        .infer_objects(copy=False)
        .interpolate(method="linear")
        .reset_index()
    )
    
    # --------------------------------------------------
    # SHARED COORDINATE TRANSFORMATION
    # --------------------------------------------------

    coordinate_transform = track_metrics["coordinateTransform"]

    transformed_xy = apply_coordinate_transform(
        resampled[["X", "Y"]].to_numpy(),
        coordinate_transform,
    )

    resampled["X"] = transformed_xy[:, 0]
    resampled["Y"] = transformed_xy[:, 1]

    # Fix LapNumber AFTER resample
    resampled["LapNumber"] = (
        resampled["LapNumber"]
        .ffill()
        .astype(int)
    )

    # --------------------------------------------------
    # LAP DISTANCE (RESET PER LAP)
    # --------------------------------------------------
    resampled["LapDistance"] = (
        resampled["Distance"]
        - resampled.groupby("LapNumber")["Distance"].transform("min")
    )

    # --------------------------------------------------
    # CANONICAL TRACK LENGTH
    # --------------------------------------------------
    track_length = track_metrics["trackLength"]

    timing_loop_count = (
        track_metrics["timingLoopCount"]
    )

    # --------------------------------------------------
    # NORMALIZED TRACK POSITION (0.0 → 1.0)
    # --------------------------------------------------
    resampled["TrackPosition"] = (
        resampled["LapDistance"] / track_length
    ).clip(0.0, 0.999999)

    resampled["TimingLoopIndex"] = (
        np.floor(
            resampled["TrackPosition"] * timing_loop_count
        )
        .astype(int)
        .clip(0, timing_loop_count - 1)
    )
    
    # --------------------------------------------------
    # RACE DISTANCE (MONOTONIC, NEVER RESETS) ✅
    # --------------------------------------------------
    resampled["RaceDistance"] = (
        (resampled["LapNumber"] - 1) * track_length
        + resampled["LapDistance"]
    )

    # --------------------------------------------------
    # RACE-RELATIVE TIME
    # --------------------------------------------------
    resampled["RaceTime"] = (
        resampled["SessionTime"].dt.total_seconds()
        - race_start_seconds
    )

    resampled = resampled[resampled["RaceTime"] >= 0]

    # Bucket into integer race seconds
    resampled["RaceSecond"] = resampled["RaceTime"].astype(int)

    # --------------------------------------------------
    # DETECT TIMING LOOP CROSSINGS
    # --------------------------------------------------
    resampled["PreviousLoopIndex"] = (
        resampled["TimingLoopIndex"].shift(1)
    )

    resampled["PreviousLap"] = (
        resampled["LapNumber"].shift(1)
    )

    resampled["LoopChanged"] = (
        (
            resampled["TimingLoopIndex"]
            != resampled["PreviousLoopIndex"]
        )
        |
        (
            resampled["LapNumber"]
            != resampled["PreviousLap"]
        )
    )

    # Always treat first telemetry point as crossing
    resampled.loc[resampled.index[0], "LoopChanged"] = True

    # --------------------------------------------------
    # BUILD TIMING LOOP EVENTS
    # --------------------------------------------------

    timing_events = []

    loop_crossings = resampled[
        resampled["LoopChanged"]
    ]

    for _, row in loop_crossings.iterrows():
        timing_events.append({
            "driver": driver_code,
            "lap": int(row["LapNumber"]),
            "timingLoopIndex": int(row["TimingLoopIndex"]),
            "raceTime": round(float(row["RaceTime"]), 3),
            "raceDistance": round(float(row["RaceDistance"]),3)
        })

    # --------------------------------------------------
    # ONE SNAPSHOT PER SECOND
    # --------------------------------------------------
    #
    # Preserve the existing selection rule:
    #
    #   RaceSecond == 0  -> first sample
    #   other seconds    -> last sample
    #
    # Since RaceTime is sorted, the first/last occurrence
    # of each RaceSecond can be selected vectorially without
    # a Python groupby loop.
    # --------------------------------------------------

    resampled = resampled.sort_values(
        "RaceTime"
    )

    first_in_second = (
        ~resampled["RaceSecond"]
        .duplicated(
            keep="first"
        )
    )

    last_in_second = (
        ~resampled["RaceSecond"]
        .duplicated(
            keep="last"
        )
    )

    first_second_zero = (
        (resampled["RaceSecond"] == 0)
        & first_in_second
    )

    last_nonzero_second = (
        (resampled["RaceSecond"] != 0)
        & last_in_second
    )

    selected = (
        first_second_zero
        | last_nonzero_second
    )

    resampled = (
        resampled.loc[selected]
        .copy()
    )

    # --------------------------------------------------
    # BUILD FINAL CHUNKS
    # --------------------------------------------------

    chunks = {
        int(second): {
            "driver": driver_code,
            "lap": int(lap),
            "lapDistance": float(lap_distance),
            "raceDistance": float(race_distance),
            "trackPosition": float(track_position),
            "timingLoopIndex": int(timing_loop_index),
            "x": float(x),
            "y": float(y),
        }
        for (
            second,
            lap,
            lap_distance,
            race_distance,
            track_position,
            timing_loop_index,
            x,
            y,
        ) in resampled[
            [
                "RaceSecond",
                "LapNumber",
                "LapDistance",
                "RaceDistance",
                "TrackPosition",
                "TimingLoopIndex",
                "X",
                "Y",
            ]
        ].itertuples(
            index=False,
            name=None,
        )
    }

    return {
        "chunks": chunks,
        "timingEvents": timing_events
    }
