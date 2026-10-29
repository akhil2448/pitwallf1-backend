import fastf1

from app.config.settings import settings


def init_fastf1_cache() -> None:
    # Configure the correct cache directory first.
    fastf1.Cache.configure(
        cache_dir=settings.FASTF1_CACHE_DIR
    )

    # Production serves only data already present in its cache.
    # Local development and ingestion remain online.
    
    ## REMOVING THIS LOGIC AS IT BREAKS THE JOLPICA RESULTS CALL
    # if settings.ENV.lower() == "production":
    #     fastf1.Cache.offline_mode(True)