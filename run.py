import logging
import shutil

from app import db
from app.config import config
from app.factory import create_app

logger = logging.getLogger(__name__)


def main():
    if not shutil.which("ffmpeg"):
        logger.warning(
            "ffmpeg is not installed or not in PATH — video compression will fail"
        )

    logger.info("Initializing database...")
    db.init_db()

    app, socketio, worker_manager = create_app()

    logger.info("Starting worker manager...")
    worker_manager.start()

    logger.info("Starting MediaCompressorWebApp on %s:%d", config.HOST, config.PORT)
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
