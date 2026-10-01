import pandas as pd
import numpy as np


TARGET_TIMING_LOOPS = 60

def apply_coordinate_transform(xy, coordinate_transform):
    """
    Apply the shared track coordinate transformation.

    Transformation order:
    1. Rotate using circuit rotation.
    2. Translate using the shared track center.

    The same transformation is used for:
    - track-map geometry
    - driver telemetry
    """
    angle = coordinate_transform["rotationRadians"]

    rotation_matrix = np.array([
        [np.cos(angle), np.sin(angle)],
        [-np.sin(angle), np.cos(angle)],
    ])

    transformed = (
        np.asarray(xy, dtype=float)
        .dot(rotation_matrix)
    )

    transformed[:, 0] -= coordinate_transform["centerX"]
    transformed[:, 1] -= coordinate_transform["centerY"]

    return transformed


def build_track_metrics(session):
    """
    Single authoritative track metrics source.

    Also defines the shared coordinate transform used by:
    - track-map geometry
    - driver telemetry
    """

    fastest_lap = session.laps.pick_fastest()

    tel = fastest_lap.get_telemetry().copy()
    tel = tel.add_distance()
    tel = tel.sort_values("Distance")

    tel["LapDistance"] = (
        tel["Distance"] - tel["Distance"].min()
    )

    track_length = float(
        tel["LapDistance"].max()
    )

    timing_loop_count = TARGET_TIMING_LOOPS

    timing_loop_spacing = (
        track_length / timing_loop_count
    )

    # --------------------------------------------------
    # SHARED COORDINATE TRANSFORM
    # --------------------------------------------------

    circuit_info = session.get_circuit_info()

    angle = np.deg2rad(circuit_info.rotation)

    rotation_matrix = np.array([
        [np.cos(angle), np.sin(angle)],
        [-np.sin(angle), np.cos(angle)],
    ])

    rotated = (
        tel[["X", "Y"]]
        .to_numpy()
        .dot(rotation_matrix)
    )

    # Same center used by the track map.
    center_x = (
        rotated[:, 0].max()
        + rotated[:, 0].min()
    ) / 2

    center_y = (
        rotated[:, 1].max()
        + rotated[:, 1].min()
    ) / 2

    return {
        "trackLength": round(track_length, 3),

        "timingLoopCount": timing_loop_count,

        "timingLoopSpacing": round(
            timing_loop_spacing,
            3
        ),

        # --------------------------------------------------
        # SHARED X/Y TRANSFORMATION
        # --------------------------------------------------

        "coordinateTransform": {
            "rotationRadians": float(angle),
            "centerX": float(center_x),
            "centerY": float(center_y),
        },
    }