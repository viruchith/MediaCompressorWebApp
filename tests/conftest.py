"""Shared test fixtures."""

import os
import tempfile

import pytest

from app import db
from app.config import config
from app.factory import create_app


@pytest.fixture(autouse=True)
def tmp_database(tmp_path, monkeypatch):
    """Use a temporary database for each test to ensure isolation."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    # Reset thread-local connection so it picks up the new path
    if hasattr(db.local, "conn") and db.local.conn is not None:
        db.local.conn.close()
        db.local.conn = None
    db.init_db()
    yield db_path
    db.close_db()


@pytest.fixture
def app(tmp_database):
    """Create a Flask app for testing."""
    application, socketio, worker_manager = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def sample_input_dir(tmp_path):
    """Create a temporary input directory with sample files."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Create a small test image (1x1 pixel PNG)
    from PIL import Image
    img = Image.new("RGB", (10, 10), color="red")
    img.save(str(input_dir / "test.png"))
    img.save(str(input_dir / "test2.jpg"))

    # Create a non-media file (should be skipped)
    (input_dir / "readme.txt").write_text("not media")

    return str(input_dir)


@pytest.fixture
def sample_output_dir(tmp_path):
    """Create a temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return str(output_dir)
