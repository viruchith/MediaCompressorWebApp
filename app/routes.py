import json
import logging
import os
from flask import Blueprint, jsonify, render_template, request

from app.compression.profiles import PROFILES
from app.compression.settings import get_effective_settings
from app import db
from app.config import config
from app.utils.manifest import build_job_manifest

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)
web_bp = Blueprint("web", __name__)


def error_response(message: str, code: str, status: int = 400):
    return jsonify({"error": message, "code": code}), status


def get_json_or_form():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


# --- Web UI routes ---

@web_bp.route("/")
def index():
    return render_template("index.html")


@web_bp.route("/settings")
def settings_page():
    return render_template("settings.html")


@web_bp.route("/jobs/<int:job_id>")
def job_detail_page(job_id):
    job = db.get_job(job_id)
    if not job:
        return render_template("job_detail.html", job=None), 404
    return render_template("job_detail.html", job=job.to_dict())


# --- API v1 ---

@api_bp.route("/jobs", methods=["GET"])
def list_jobs():
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 20, type=int)
    limit = min(limit, 100)
    result = db.list_jobs(page=page, limit=limit)
    return jsonify(result.to_dict(item_key="jobs"))


@api_bp.route("/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return error_response("Job not found", "JOB_NOT_FOUND", 404)
    return jsonify(job.to_dict())


def _create_job_from_data(data: dict):
    input_folder = data.get("input_folder") or data.get("inputFolderPath")
    output_folder = data.get("output_folder") or data.get("outputFolderPath")

    if not input_folder:
        return {"error": "input_folder is required", "code": "MISSING_INPUT_FOLDER"}, 400
    if not output_folder:
        return {"error": "output_folder is required", "code": "MISSING_OUTPUT_FOLDER"}, 400
    if not os.path.exists(input_folder):
        return {"error": "Input folder does not exist", "code": "INPUT_NOT_FOUND"}, 400

    os.makedirs(output_folder, exist_ok=True)

    profile = data.get("profile", "balanced")
    priority = int(data.get("priority", 0))
    preserve_metadata = data.get("preserve_metadata", True)
    if isinstance(preserve_metadata, str):
        preserve_metadata = preserve_metadata.lower() in ("1", "true", "yes")

    image_overrides = data.get("image_settings", {})
    video_overrides = data.get("video_settings", {})
    if isinstance(image_overrides, str):
        image_overrides = json.loads(image_overrides)
    if isinstance(video_overrides, str):
        video_overrides = json.loads(video_overrides)

    image_settings, video_settings, errors = get_effective_settings(
        profile_name=profile,
        user_image_overrides=image_overrides,
        user_video_overrides=video_overrides,
        preserve_metadata=preserve_metadata,
    )
    if errors:
        return {"error": "; ".join(errors), "code": "INVALID_SETTINGS"}, 400

    job_id = db.create_job(
        input_folder, output_folder, image_settings, video_settings, profile,
    )

    file_batch = []
    for root, _, files in os.walk(input_folder):
        for filename in files:
            input_path = os.path.join(root, filename)
            ext = os.path.splitext(filename)[1][1:].lower()
            if ext in config.SUPPORTED_IMAGE_EXTENSIONS:
                ftype = "image"
            elif ext in config.SUPPORTED_VIDEO_EXTENSIONS:
                ftype = "video"
            else:
                continue
            relative = os.path.relpath(input_path, input_folder)
            output_path = os.path.join(output_folder, relative)
            file_batch.append((input_path, output_path, ftype))

    added = db.add_files_batch(
        job_id, file_batch, priority=priority, max_retries=config.MAX_RETRIES,
    )

    logger.info("Created job %d with %d files", job_id, added)
    return {
        "message": f"Job created with {added} files queued.",
        "job_id": job_id,
        "files_added": added,
    }, 201


@api_bp.route("/jobs", methods=["POST"])
def create_job():
    result, code = _create_job_from_data(get_json_or_form())
    return jsonify(result), code


@api_bp.route("/jobs/<int:job_id>/pause", methods=["PUT"])
def pause_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return error_response("Job not found", "JOB_NOT_FOUND", 404)
    db.update_job_status(job_id, "paused")
    return jsonify({"message": "Job paused", "job_id": job_id})


@api_bp.route("/jobs/<int:job_id>/resume", methods=["PUT"])
def resume_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return error_response("Job not found", "JOB_NOT_FOUND", 404)
    db.update_job_status(job_id, "active")
    return jsonify({"message": "Job resumed", "job_id": job_id})


@api_bp.route("/jobs/<int:job_id>", methods=["DELETE"])
def delete_job(job_id):
    if not db.delete_job(job_id):
        return error_response("Job not found", "JOB_NOT_FOUND", 404)
    return jsonify({"message": "Job deleted", "job_id": job_id})


@api_bp.route("/jobs/<int:job_id>/files", methods=["GET"])
def list_job_files(job_id):
    if not db.get_job(job_id):
        return error_response("Job not found", "JOB_NOT_FOUND", 404)
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 50, type=int)
    status = request.args.get("status", type=int)
    search = request.args.get("search")
    result = db.list_files_for_job(job_id, page=page, limit=limit, status=status, search=search)
    return jsonify({
        **result.to_dict(item_key="files"),
        "files": [f.to_dict() for f in result.items],
    })


@api_bp.route("/jobs/<int:job_id>/retry_failed", methods=["POST"])
def retry_failed(job_id):
    if not db.get_job(job_id):
        return error_response("Job not found", "JOB_NOT_FOUND", 404)
    count = db.retry_failed_files(job_id)
    return jsonify({"message": f"Retried {count} failed files", "retried": count})


@api_bp.route("/jobs/<int:job_id>/manifest", methods=["GET"])
def job_manifest(job_id):
    manifest = build_job_manifest(job_id)
    if not manifest:
        return error_response("Job not found", "JOB_NOT_FOUND", 404)
    return jsonify(manifest)


@api_bp.route("/files", methods=["GET"])
def list_files():
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 50, type=int)
    status = request.args.get("status", type=int)
    result = db.list_all_files(page=page, limit=limit, status=status)
    return jsonify({
        **result.to_dict(item_key="files"),
        "files": [f.to_dict() for f in result.items],
    })


@api_bp.route("/files/<int:file_id>", methods=["GET"])
def get_file(file_id):
    f = db.get_file(file_id)
    if not f:
        return error_response("File not found", "FILE_NOT_FOUND", 404)
    return jsonify(f.to_dict())


@api_bp.route("/profiles", methods=["GET"])
def list_profiles():
    profiles = {
        name: {"description": p["description"], "image": p["image"], "video": p["video"]}
        for name, p in PROFILES.items()
    }
    return jsonify(profiles)


@api_bp.route("/profiles/<name>", methods=["GET"])
def get_profile(name):
    profile = PROFILES.get(name)
    if not profile:
        return error_response("Profile not found", "PROFILE_NOT_FOUND", 404)
    return jsonify({"name": name, **profile})


@api_bp.route("/stats", methods=["GET"])
def global_stats():
    return jsonify(db.get_global_stats())


@api_bp.route("/clear_completed", methods=["POST"])
def clear_completed():
    deleted = db.clear_completed_files()
    return jsonify({"message": f"Cleared {deleted} completed files.", "deleted": deleted})


# --- Deprecated legacy routes ---

@web_bp.route("/files", methods=["GET"])
def legacy_files():
    return jsonify(db.get_all_files_legacy())


@web_bp.route("/queue_counts", methods=["GET"])
def legacy_queue_counts():
    return jsonify(db.get_queue_counts())


@web_bp.route("/folder", methods=["POST"])
def legacy_folder():
    result, code = _create_job_from_data(request.form.to_dict())
    return jsonify(result), code


@web_bp.route("/clear_completed", methods=["POST"])
def legacy_clear_completed():
    return clear_completed()
