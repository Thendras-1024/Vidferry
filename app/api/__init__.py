"""HTTP API blueprints grouped by business domain."""


def register_blueprints(app):
    """Register migrated blueprints.

    No blueprints are registered in phase one because current routes are still
    loaded by ``sau_backend``. Keep this function as the stable integration
    point for later route extraction.
    """
    return app
