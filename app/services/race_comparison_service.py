import math
import numpy as np
import pandas as pd

from app.services.session_cache_service import (
    get_loaded_session,
)

from app.services.team_normalizer import (
    normalize_team_name,
)


class RaceComparisonService:
    
    def get_race_lap(
        self,
        year: int,
        round_number: int,
        driver: str,
        lap_number: int,
    ):
        """
        Returns the FastF1 Lap object for the requested
        driver and race lap number.
        """

        session = get_loaded_session(
            year,
            round_number
        )

        driver_laps = (
            session.laps
            .pick_drivers(driver.upper())
        )

        matching_laps = driver_laps.loc[
            driver_laps["LapNumber"] == lap_number
        ]

        if matching_laps.empty:
            raise ValueError(
                f"Lap {lap_number} not found for driver '{driver}'."
            )

        return matching_laps.iloc[0]
    
    
    def build_track_map(
        self,
        year: int,
        round_number: int
    ):
        """
        Returns:
        - Closed track polyline
        - Track bounds
        - Start/finish line
        """

        session = get_loaded_session(
            year,
            round_number
        )

        reference_lap = session.laps.pick_fastest()
        
        circuit_info = session.get_circuit_info()
        corners = circuit_info.corners

        telemetry = reference_lap.get_telemetry()
        
        max_distance = float(telemetry["Distance"].max())

        sector_markers = self.build_sector_markers(
            reference_lap,
            max_distance
        )

        sector1_rd = sector_markers[0]["rd"]
        sector2_rd = sector_markers[1]["rd"]

        points = []

        sector1 = []
        sector2 = []
        sector3 = []
        
        corner_markers = []

        xs = []
        ys = []

        for _, row in telemetry.iterrows():

            x = row["X"]
            y = row["Y"]

            if x is None or y is None:
                continue

            x = round(float(x), 2)
            y = round(float(y), 2)

            rd = float(row["Distance"]) / max_distance

            point = {
                "x": x,
                "y": y
            }

            points.append(point)

            #
            # Build colored sectors
            #

            if rd <= sector1_rd:

                if not sector1:
                    sector1.append(point)

                sector1.append(point)

            elif rd <= sector2_rd:

                if not sector2:
                    sector2.append(point)

                sector2.append(point)

            else:

                if not sector3:
                    sector3.append(point)

                sector3.append(point)

            xs.append(x)
            ys.append(y)

        if len(points) < 2:
            raise ValueError(
                "Unable to build track map."
            )

        #
        # Close sector polylines
        #

        if sector1 and sector2:
            sector1.append(sector2[0])

        if sector2 and sector3:
            sector2.append(sector3[0])

        if sector3 and sector1:
            sector3.append(sector1[0])

        #
        # Keep the full track closed
        #

        points.append(points[0])

        bounds = {
            "minX": round(min(xs), 2),
            "maxX": round(max(xs), 2),
            "minY": round(min(ys), 2),
            "maxY": round(max(ys), 2)
        }

        # --------------------------
        # START / FINISH LINE
        # --------------------------

        start_point = points[0]
        second_point = points[1]

        dx = (
            second_point["x"]
            - start_point["x"]
        )

        dy = (
            second_point["y"]
            - start_point["y"]
        )

        length = math.sqrt(
            dx * dx +
            dy * dy
        )

        if length == 0:
            length = 1

        dx /= length
        dy /= length

        px = -dy
        py = dx

        line_half_width = 80

        start_finish = {
            "x1": round(
                start_point["x"] + px * line_half_width,
                2
            ),
            "y1": round(
                start_point["y"] + py * line_half_width,
                2
            ),
            "x2": round(
                start_point["x"] - px * line_half_width,
                2
            ),
            "y2": round(
                start_point["y"] - py * line_half_width,
                2
            )
        }

        width = round(
            bounds["maxX"] - bounds["minX"],
            2
        )

        height = round(
            bounds["maxY"] - bounds["minY"],
            2
        )
        
        #
        # Corner markers
        #

        for _, row in corners.iterrows():

            corner_markers.append({
                "number": int(row["Number"]),
                "x": round(float(row["X"]), 2),
                "y": round(float(row["Y"]), 2),
                "angle": round(float(row["Angle"]), 2),
                "distance": round(float(row["Distance"]), 2),
            })

        return {
            "sector1": sector1,
            "sector2": sector2,
            "sector3": sector3,
            
            "corners": corner_markers,

            "bounds": bounds,

            "width": width,

            "height": height,

            "startPoint": {
                "x": start_point["x"],
                "y": start_point["y"]
            },

            "startFinish": start_finish
        }
        
    
    def resample_telemetry_to_reference_distance(
        self,
        telemetry: pd.DataFrame,
        reference_telemetry: pd.DataFrame,
        reference_distances: np.ndarray,
    ) -> list[dict]:
        """
        Resample telemetry onto a canonical track-distance axis.

        The canonical axis comes from Driver A's reference lap.
        Each driver's XY telemetry is projected onto that reference
        track before interpolation.
        """

        source = (
            telemetry[
                [
                    "Distance",
                    "Time",
                    "Speed",
                    "RPM",
                    "Throttle",
                    "Brake",
                    "nGear",
                    "X",
                    "Y",
                ]
            ]
            .dropna(subset=["Distance", "X", "Y"])
            .copy()
            .reset_index(drop=True)
        )

        if len(source) < 2:
            raise ValueError(
                "Telemetry must contain at least two valid samples."
            )

        # Remove repeated source-distance samples.
        source_distance = source["Distance"].to_numpy(dtype=float)

        unique_indices = np.r_[
            True,
            np.diff(source_distance) > 0,
        ]

        source = source.iloc[unique_indices].reset_index(drop=True)

        source_distance = source["Distance"].to_numpy(dtype=float)
        source_x = source["X"].to_numpy(dtype=float)
        source_y = source["Y"].to_numpy(dtype=float)

        if len(source_distance) < 2:
            raise ValueError(
                "Telemetry must contain at least two increasing distance samples."
            )

        # ------------------------------------------------------------
        # Build canonical reference track segments
        # ------------------------------------------------------------

        reference = (
            reference_telemetry[
                ["Distance", "X", "Y"]
            ]
            .dropna(subset=["Distance", "X", "Y"])
            .copy()
            .reset_index(drop=True)
        )

        reference_distance = (
            reference["Distance"]
            .to_numpy(dtype=float)
        )

        reference_x = (
            reference["X"]
            .to_numpy(dtype=float)
        )

        reference_y = (
            reference["Y"]
            .to_numpy(dtype=float)
        )

        reference_unique = np.r_[
            True,
            (
                np.diff(reference_distance) > 0
            ),
        ]

        reference_distance = reference_distance[
            reference_unique
        ]
        reference_x = reference_x[
            reference_unique
        ]
        reference_y = reference_y[
            reference_unique
        ]

        if len(reference_distance) < 2:
            raise ValueError(
                "Reference telemetry must contain at least two valid samples."
            )

        segment_x = (
            reference_x[1:] -
            reference_x[:-1]
        )

        segment_y = (
            reference_y[1:] -
            reference_y[:-1]
        )

        segment_length_squared = (
            segment_x * segment_x +
            segment_y * segment_y
        )

        # ------------------------------------------------------------
        # Project each driver's telemetry point onto the reference
        # track and obtain the canonical reference distance.
        # ------------------------------------------------------------

        projected_distance = np.empty(
            len(source),
            dtype=float,
        )

        reference_max_distance = float(
            reference_distance[-1]
        )

        source_start_distance = float(
            source_distance[0]
        )

        source_end_distance = float(
            source_distance[-1]
        )

        segment_count = len(reference_distance) - 1

        for index, (x, y, distance) in enumerate(
            zip(
                source_x,
                source_y,
                source_distance,
            )
        ):

            # Use the driver's own distance only to estimate which
            # portion of the reference track we should search.
            expected_distance = np.interp(
                distance,
                [
                    source_start_distance,
                    source_end_distance,
                ],
                [
                    reference_distance[0],
                    reference_max_distance,
                ],
            )

            expected_index = int(
                np.searchsorted(
                    reference_distance,
                    expected_distance,
                    side="left",
                )
            )

            expected_segment = min(
                max(expected_index, 0),
                segment_count - 1,
            )

            # Search a local window around the expected progress.
            # This prevents projection onto a nearby but wrong section
            # of the circuit.
            search_radius = 40

            start_segment = max(
                0,
                expected_segment - search_radius,
            )

            end_segment = min(
                segment_count - 1,
                expected_segment + search_radius,
            )

            indices = np.arange(
                start_segment,
                end_segment + 1,
            )

            x1 = reference_x[indices]
            y1 = reference_y[indices]

            dx = segment_x[indices]
            dy = segment_y[indices]

            length_squared = (
                segment_length_squared[indices]
            )

            px = x - x1
            py = y - y1

            factor = (
                px * dx +
                py * dy
            )

            valid_lengths = (
                length_squared > 0
            )

            factor = np.divide(
                factor,
                length_squared,
                out=np.zeros_like(factor),
                where=valid_lengths,
            )

            factor = np.clip(
                factor,
                0.0,
                1.0,
            )

            projected_x = (
                x1 +
                dx * factor
            )

            projected_y = (
                y1 +
                dy * factor
            )

            squared_error = (
                (x - projected_x) ** 2 +
                (y - projected_y) ** 2
            )

            best_local_index = int(
                np.argmin(squared_error)
            )

            best_segment = int(
                indices[best_local_index]
            )

            best_factor = float(
                factor[best_local_index]
            )

            d1 = reference_distance[
                best_segment
            ]

            d2 = reference_distance[
                best_segment + 1
            ]

            projected_distance[index] = (
                d1 +
                (d2 - d1) *
                best_factor
            )

        # The projection must move monotonically forward around the lap.
        projected_distance = np.maximum.accumulate(
            projected_distance
        )

        projected_distance = np.clip(
            projected_distance,
            reference_distance[0],
            reference_max_distance,
        )

        # Remove duplicate projected positions.
        projected_unique_indices = np.r_[
            True,
            np.diff(projected_distance) > 0,
        ]

        projected_distance = projected_distance[
            projected_unique_indices
        ]

        source = source.iloc[
            projected_unique_indices
        ].reset_index(drop=True)

        if len(projected_distance) < 2:
            raise ValueError(
                "Unable to establish a valid canonical track distance."
            )

        target_distance = np.asarray(
            reference_distances,
            dtype=float,
        )

        # ------------------------------------------------------------
        # Interpolate telemetry values onto the canonical distance.
        # ------------------------------------------------------------

        numeric_columns = [
            "Time",
            "Speed",
            "RPM",
            "Throttle",
            "X",
            "Y",
        ]

        interpolated = {}

        for column in numeric_columns:

            values = (
                source[column]
                .dt.total_seconds()
                .to_numpy(dtype=float)
                if column == "Time"
                else source[column]
                .to_numpy(dtype=float)
            )

            interpolated[column] = np.interp(
                target_distance,
                projected_distance,
                values,
            )

        # Brake is binary/categorical.
        brake_values = (
            source["Brake"]
            .astype(bool)
            .to_numpy()
        )

        brake_numeric = (
            brake_values.astype(float)
        )

        brake_interpolated = np.interp(
            target_distance,
            projected_distance,
            brake_numeric,
        )

        # Gear is discrete.
        gear_source = (
            source["nGear"]
            .to_numpy(dtype=int)
        )

        gear_indices = np.searchsorted(
            projected_distance,
            target_distance,
            side="left",
        )

        gear_indices = np.clip(
            gear_indices,
            0,
            len(gear_source) - 1,
        )

        rows = []

        for index, distance in enumerate(
            target_distance
        ):

            rows.append({
                "idx": index,

                "rd": round(
                    float(
                        distance /
                        reference_max_distance
                    )
                    if reference_max_distance > 0
                    else 0,
                    5,
                ),

                "t": round(
                    float(
                        interpolated["Time"][index]
                    ),
                    3,
                ),

                "d": round(
                    float(distance),
                    2,
                ),

                "speed": int(
                    round(
                        interpolated["Speed"][index]
                    )
                ),

                "rpm": int(
                    round(
                        interpolated["RPM"][index]
                    )
                ),

                "throttle": round(
                    float(
                        interpolated["Throttle"][index]
                    ),
                    1,
                ),

                "brake": (
                    100
                    if brake_interpolated[index] >= 0.5
                    else 0
                ),

                "gear": int(
                    gear_source[
                        gear_indices[index]
                    ]
                ),

                "x": round(
                    float(
                        interpolated["X"][index]
                    ),
                    2,
                ),

                "y": round(
                    float(
                        interpolated["Y"][index]
                    ),
                    2,
                ),
            })

        return rows
        
    
    def build_driver_payload(
        self,
        year: int,
        round_number: int,
        driver: str,
        lap_number: int,
        reference_telemetry: pd.DataFrame,
        reference_distances: np.ndarray,
        reference_max_distance: float,
    ):
        """
        Returns telemetry payload for
        the requested race lap.
        """

        session = get_loaded_session(
            year,
            round_number
        )

        lap = self.get_race_lap(
            year,
            round_number,
            driver,
            lap_number
        )

        telemetry = lap.get_telemetry()

        max_distance = float(
            telemetry["Distance"].max()
        )
        
        sector_markers = self.build_sector_markers(
            lap,
            max_distance
        )

        telemetry_rows = self.resample_telemetry_to_reference_distance(
            telemetry,
            reference_telemetry,
            reference_distances,
        )

        result_row = (
            session.results
            .loc[
                session.results["Abbreviation"]
                == driver.upper()
            ]
            .iloc[0]
        )
        
        driver_info = session.get_driver(driver.upper())
        
        
        
        normalized_team_name = normalize_team_name(
            result_row["TeamName"]
        )

        start_row = telemetry.iloc[0]
        end_row = telemetry.iloc[-1]

        return {
            "driver": driver.upper(),
            
            "driverName": driver_info["LastName"],

            "teamName": normalized_team_name,

            "teamColor": result_row["TeamColor"],

            "position": int(
                result_row["Position"]
            ),

            "lapNumber": int(
                lap["LapNumber"]
            ),

            "driverNumber": str(
                lap["DriverNumber"]
            ),

            "compound": (
                str(lap["Compound"]).upper()
                if lap["Compound"] is not None
                else None
            ),

            "tyreAge": (
                int(lap["TyreLife"])
                if lap["TyreLife"] is not None
                else None
            ),

            "freshTyre": (
                bool(lap["FreshTyre"])
                if lap["FreshTyre"] is not None
                else None
            ),

            "stint": (
                int(lap["Stint"])
                if lap["Stint"] is not None
                else None
            ),

            "lapTime": round(
                lap["LapTime"].total_seconds(),
                3
            ),

            "sector1": round(
                lap["Sector1Time"].total_seconds(),
                3
            ),

            "isSector1SessionFastest": False,

            "sector2": round(
                lap["Sector2Time"].total_seconds(),
                3
            ),

            "isSector2SessionFastest": False,

            "sector3": round(
                lap["Sector3Time"].total_seconds(),
                3
            ),

            "isSector3SessionFastest": False,
            
            "sectorMarkers": sector_markers,

            "sampleCount": len(
                telemetry_rows
            ),

            "maxDistance": round(
                reference_max_distance,
                2
            ),

            "startPoint": {
                "x": round(
                    float(start_row["X"]),
                    2
                ),
                "y": round(
                    float(start_row["Y"]),
                    2
                )
            },

            "endPoint": {
                "x": round(
                    float(end_row["X"]),
                    2
                ),
                "y": round(
                    float(end_row["Y"]),
                    2
                )
            },

            "telemetry": telemetry_rows
        }
        
        
    def build_comparison_payload(
        self,
        year: int,
        round_number: int,
        driver_a: str,
        lap_a: int,
        driver_b: str | None = None,
        lap_b: int | None = None,
    ):

        # ----------------------------------------
        # COMMON REFERENCE DISTANCE AXIS
        # ----------------------------------------

        reference_lap = self.get_race_lap(
            year,
            round_number,
            driver_a,
            lap_a,
        )

        reference_telemetry = reference_lap.get_telemetry()

        reference_distances = (
            reference_telemetry["Distance"]
            .to_numpy(dtype=float)
        )

        reference_max_distance = float(
            reference_telemetry["Distance"].max()
        )

        driver_a_payload = self.build_driver_payload(
            year,
            round_number,
            driver_a,
            lap_a,
            reference_telemetry,
            reference_distances,
            reference_max_distance,
        )

        driver_b_payload = None

        if driver_b and lap_b is not None:
            driver_b_payload = self.build_driver_payload(
                year,
                round_number,
                driver_b,
                lap_b,
                reference_telemetry,
                reference_distances,
                reference_max_distance,
            )

        session = get_loaded_session(
            year,
            round_number,
        )

        return {
            "year": year,

            "grandPrix": session.event["EventName"],

            "sessionPart": "R",

            "trackMap": self.build_track_map(
                year,
                round_number,
            ),

            "driverA": driver_a_payload,

            "driverB": driver_b_payload,
        }
        
    
    def build_sector_markers(
        self,
        lap,
        max_distance: float
    ):
        """
        Returns sector boundaries as relative distance.

        Example:
        S1 end = 0.26
        S2 end = 0.69
        """

        telemetry = lap.get_telemetry()

        sector1_end = (
            lap["Sector1Time"].total_seconds()
        )

        sector2_end = (
            sector1_end +
            lap["Sector2Time"].total_seconds()
        )

        times = telemetry["Time"].dt.total_seconds().to_numpy()
        distances = telemetry["Distance"].to_numpy()

        sector_markers = []

        for sector_name, sector_time in [
            ("S1", sector1_end),
            ("S2", sector2_end),
        ]:

            #
            # Find the first telemetry sample after the sector time
            #
            after_index = next(
                (
                    i
                    for i, t in enumerate(times)
                    if t >= sector_time
                ),
                len(times) - 1,
            )

            before_index = max(0, after_index - 1)

            t1 = times[before_index]
            t2 = times[after_index]

            d1 = distances[before_index]
            d2 = distances[after_index]

            #
            # Linear interpolation
            #
            if t2 == t1:
                distance = d1
            else:
                ratio = (sector_time - t1) / (t2 - t1)
                distance = d1 + ratio * (d2 - d1)

            sector_markers.append({
                "sector": sector_name,
                "time": round(sector_time, 3),
                "rd": round(distance / max_distance, 5),
                "d": round(distance, 2),
            })

        return sector_markers