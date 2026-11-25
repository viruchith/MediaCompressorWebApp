"""Unit tests for the API endpoints."""

import json


class TestHealthCheck:
    def test_healthz_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["database"] == "ok"

    def test_api_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert "workers" in data
        assert "queue" in data

    def test_help_page_returns_200(self, client):
        resp = client.get("/help")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "User Guide & Help" in html
        assert "Quick 3-Step Guide" in html
        assert "Smart Social Media Handling" in html
        assert "breadcrumb-nav" in html
        assert "Dashboard" in html
        assert "favicon.ico" in html

    def test_about_page_returns_200(self, client):
        resp = client.get("/about")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Viruchith Ganesan" in html
        assert "https://viruchith.com/" in html
        assert "GNU General Public License" in html
        assert "breadcrumb-nav" in html
        assert "Dashboard" in html
        assert "favicon.ico" in html

    def test_favicon_endpoint_returns_200(self, client):
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200
        assert resp.mimetype == "image/vnd.microsoft.icon"


class TestVersion:
    def test_version_endpoint(self, client):
        resp = client.get("/api/v1/version")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "version" in data
        assert "author" in data


class TestJobCreation:
    def test_create_job_missing_input(self, client):
        resp = client.post("/api/v1/jobs", json={
            "output_folder": "/tmp/out",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["code"] == "MISSING_INPUT_FOLDER"

    def test_create_job_missing_output(self, client):
        resp = client.post("/api/v1/jobs", json={
            "input_folder": "/tmp/in",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["code"] == "MISSING_OUTPUT_FOLDER"

    def test_create_job_input_not_found(self, client):
        resp = client.post("/api/v1/jobs", json={
            "input_folder": "/nonexistent/path",
            "output_folder": "/tmp/out",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["code"] == "INPUT_NOT_FOUND"

    def test_create_job_success(self, client, sample_input_dir, sample_output_dir):
        resp = client.post("/api/v1/jobs", json={
            "input_folder": sample_input_dir,
            "output_folder": sample_output_dir,
            "image_profile": "balanced",
            "video_profile": "balanced",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "job_id" in data
        assert data["status"] == "scanning"

    def test_create_job_invalid_priority(self, client, sample_input_dir, sample_output_dir):
        resp = client.post("/api/v1/jobs", json={
            "input_folder": sample_input_dir,
            "output_folder": sample_output_dir,
            "priority": "not_a_number",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["code"] == "INVALID_PRIORITY"


class TestProfiles:
    def test_list_profiles(self, client):
        resp = client.get("/api/v1/profiles")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "balanced" in data
        assert "archival_lossless" in data

    def test_get_profile(self, client):
        resp = client.get("/api/v1/profiles/balanced")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "balanced"
        assert "image" in data
        assert "video" in data

    def test_get_nonexistent_profile(self, client):
        resp = client.get("/api/v1/profiles/nonexistent")
        assert resp.status_code == 404


class TestStats:
    def test_global_stats_empty(self, client):
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_jobs"] == 0
        assert data["total_files"] == 0


class TestQueueManagement:
    def test_clear_completed_empty(self, client):
        resp = client.post("/api/v1/clear_completed")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["deleted"] == 0


class TestDirectoryBrowser:
    def test_browse_default(self, client):
        resp = client.get("/api/v1/browse")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "current" in data
        assert "directories" in data
        assert isinstance(data["directories"], list)

    def test_browse_specific_path(self, client, tmp_path):
        sub1 = tmp_path / "photos"
        sub1.mkdir()
        sub2 = tmp_path / "videos"
        sub2.mkdir()
        hidden = tmp_path / ".hidden"
        hidden.mkdir()

        resp = client.get(f"/api/v1/browse?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current"] == str(tmp_path)
        assert "photos" in data["directories"]
        assert "videos" in data["directories"]
        assert ".hidden" not in data["directories"]

    def test_browse_nonexistent_directory(self, client):
        resp = client.get("/api/v1/browse?path=/path/that/does/not/exist_123456")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["code"] == "DIRECTORY_NOT_FOUND"
