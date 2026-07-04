import logging

from flask_socketio import emit

from app import db

logger = logging.getLogger(__name__)


def register_socket_handlers(socketio):
    @socketio.on("connect")
    def handle_connect():
        logger.info("Client connected")
        emit("connection_status", {"status": "connected"})
        emit("queue_counts", db.get_queue_counts())

    @socketio.on("disconnect")
    def handle_disconnect():
        logger.info("Client disconnected")

    @socketio.on("request_queue_counts")
    def handle_queue_counts_request():
        emit("queue_counts", db.get_queue_counts())
