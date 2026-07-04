import json
import logging
import logging.handlers
import signal
import sys

from flask import Flask, jsonify, render_template_string
from flask_socketio import SocketIO

from app.version import VERSION, APP_AUTHOR, APP_COPYRIGHT_YEAR, APP_NAME, GITHUB_URL
from app.config import config
from app import db
from app.routes import api_bp, web_bp
from app.sockets import register_socket_handlers
from app.workers.manager import WorkerManager

_worker_manager: WorkerManager = None  # type: ignore


def setup_logging():
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    if config.LOG_JSON:
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                log_data = {
                    "timestamp": self.formatTime(record),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                if hasattr(record, "file_id"):
                    log_data["file_id"] = record.file_id
                return json.dumps(log_data)
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def create_app() -> tuple:
    setup_logging()
    logger = logging.getLogger(__name__)

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = config.SECRET_KEY

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")

    register_socket_handlers(socketio)

    @app.context_processor
    def inject_app_metadata():
        return {
            "app_version": VERSION,
            "version": VERSION,
            "author": APP_AUTHOR,
            "copyright_year": APP_COPYRIGHT_YEAR,
            "app_name": APP_NAME,
            "github_url": GITHUB_URL,
        }

    @app.errorhandler(404)
    def not_found(e):
        if request_wants_json():
            return jsonify({"error": "Not found", "code": "NOT_FOUND"}), 404
        return (
            render_template_string(
                "<!DOCTYPE html><html><head><title>404 Not Found</title>"
                '<link rel="stylesheet" href="{{ url_for(\'static\', filename=\'css/style.css\') }}">'
                "</head><body><header><h1>404 — Not Found</h1></header>"
                '<div class="card"><p>The page you requested was not found.</p>'
                '<a href="/">Back to home</a></div></body></html>'
            ),
            404,
        )

    @app.errorhandler(500)
    def server_error(e):
        logger.error("Internal server error: %s", e)
        if request_wants_json():
            return jsonify({"error": "Internal server error", "code": "INTERNAL_ERROR"}), 500
        return (
            render_template_string(
                "<!DOCTYPE html><html><head><title>500 Server Error</title>"
                '<link rel="stylesheet" href="{{ url_for(\'static\', filename=\'css/style.css\') }}">'
                "</head><body><header><h1>500 — Internal Server Error</h1></header>"
                '<div class="card"><p>Something went wrong. Please try again later.</p>'
                '<a href="/">Back to home</a></div></body></html>'
            ),
            500,
        )

    global _worker_manager
    _worker_manager = WorkerManager(socketio, app)

    def shutdown_handler(signum, frame):
        logger.info("Received signal %s, shutting down gracefully...", signum)
        db.reset_processing_on_shutdown()
        if _worker_manager:
            _worker_manager.stop(wait=False)
        db.close_db()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    @app.before_request
    def ensure_db():
        pass  # lazy init via get_db()

    return app, socketio, _worker_manager


def get_worker_manager() -> WorkerManager:
    return _worker_manager


def request_wants_json():
    from flask import request
    return (
        request.accept_mimetypes.best_match(["application/json", "text/html"])
        == "application/json"
        or request.path.startswith("/api/")
    )
