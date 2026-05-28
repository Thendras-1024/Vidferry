"""HTTP API route modules grouped by business domain.

Routes are loaded by ``app.backend.runtime`` during the modular transition so
legacy decorators keep their behavior while each domain lives in its own file.
"""


def register_blueprints(app):
    """Reserved integration point for future Flask Blueprint registration."""
    return app
