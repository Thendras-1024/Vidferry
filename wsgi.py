"""Production WSGI module. Serve this module with a single Waitress process."""

from app import create_app, initialize_runtime
from run_production import _validate_production_config


_validate_production_config()
app = create_app()
initialize_runtime()
