import fastf1
import pandas as pd
from datetime import datetime,timezone

from app.services.session_data_availability_service import (
    SessionDataAvailabilityService,
)

def _make_json_safe(value):
    if pd.isna(value):
        return None

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()

    return value

def _format_local_display(value):
    if pd.isna(value):
        return None

    return value.strftime("%b %-d, %-I:%M %p")


def generate_year_schedule(year: int) -> dict:

    schedule_df = fastf1.get_event_schedule(year)

    schedule_df = schedule_df[
        schedule_df["RoundNumber"] > 0
    ]
    
    now = datetime.now(timezone.utc)

    races = []
    
    availability_service = SessionDataAvailabilityService()

    for _, row in schedule_df.iterrows():

        race_date = row["Session5Date"]

        if pd.notna(race_date):

            if race_date.astimezone(timezone.utc) > now:
                continue

        races.append({
            "round": int(row["RoundNumber"]),
            "country": row["Country"],
            "location": row["Location"],
            "officialName": row["OfficialEventName"],
            "raceName": row["EventName"],
            "eventDate": _make_json_safe(row["EventDate"]),

            "qualifyingName": row["Session4"],
            "qualifyingDate": _make_json_safe(row["Session4Date"]),
            "qualifyingDateUtc": _make_json_safe(row["Session4DateUtc"]),
            "qualifyingLocalDisplay": _format_local_display(
                row["Session4Date"]
            ),

            "raceSessionName": row["Session5"],
            "raceDate": _make_json_safe(row["Session5Date"]),
            "raceDateUtc": _make_json_safe(row["Session5DateUtc"]),
            "raceLocalDisplay": _format_local_display(
                row["Session5Date"]
            ),
            
            "qualifyingDataStatus": availability_service.get_session_status(
                year, int(row["RoundNumber"]), "Q"
            ),
            "raceDataStatus": availability_service.get_session_status(
                year, int(row["RoundNumber"]), "R"
            ),
        })

    return {
        "year": year,
        "races": races
    }