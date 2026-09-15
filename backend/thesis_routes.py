"""Thesis API, protected by the existing project membership authorization."""

from functools import wraps
import uuid

import psycopg2
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from backend.auth import require_project_role
from common import thesis_service
from common import thesis_files
from common.document_service import validate_role
from db.db import create_task
from workers.queue_conn import redis_conn, DEFAULT_RETRY
from rq import Queue


thesis_api = Blueprint("thesis", __name__)


def _json_errors(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except thesis_service.ThesisNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        except (ValueError, BadRequest, UnsupportedMediaType):
            return jsonify({"error": "perfil JSON inválido"}), 400
        except psycopg2.IntegrityError:
            current_app.logger.exception("Thesis integrity conflict")
            return jsonify({"error": "conflicto de integridad de tesis"}), 409
        except psycopg2.Error:
            current_app.logger.exception("Thesis database failure")
            return jsonify({"error": "error interno de tesis"}), 500
    return wrapper


@thesis_api.route("/api/projects/<project_id>/thesis", methods=["POST"])
@_json_errors
@require_project_role("editor")
def create_thesis(project_id):
    profile, created = thesis_service.create_thesis(project_id, request.get_json())
    return jsonify({"profile": profile, "created": created}), (201 if created else 200)


@thesis_api.route("/api/projects/<project_id>/thesis/structure", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_structure(project_id):
    return jsonify(thesis_service.get_structure(project_id))


@thesis_api.route("/api/projects/<project_id>/thesis/profile", methods=["PUT"])
@_json_errors
@require_project_role("editor")
def thesis_profile(project_id):
    return jsonify({"profile": thesis_service.update_profile(project_id, request.get_json())})


@thesis_api.route("/api/projects/<project_id>/thesis/files", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_upload_files(project_id):
    # Check ownership and Thesis existence even for an empty or malformed batch.
    thesis_files.list_files(project_id)
    role = validate_role(request.form.get("declared_role", "unknown"))
    files = request.files.getlist("files[]")
    if not files:
        return jsonify({"error": "se requiere al menos un archivo en files[]"}), 400
    result = {"batch_id": str(uuid.uuid4()), "accepted": [], "reused": [], "rejected": []}
    for file in files:
        try:
            item = thesis_files.upload_file(project_id, file, role)
            item.pop("fragments", None)
            result["reused" if item["reused"] else "accepted"].append(item)
        except (ValueError, OSError, psycopg2.Error):
            current_app.logger.exception("Thesis file rejected")
            result["rejected"].append({"filename": file.filename, "error": "archivo inválido o no se pudo almacenar"})
    return jsonify(result), (202 if result["accepted"] or result["reused"] else 400)


@thesis_api.route("/api/projects/<project_id>/thesis/files", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_list_files(project_id):
    return jsonify({"files": thesis_files.list_files(project_id)})


@thesis_api.route("/api/projects/<project_id>/thesis/files/<file_id>", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_file_detail(project_id, file_id):
    return jsonify(thesis_files.file_detail(project_id, file_id))


@thesis_api.route("/api/projects/<project_id>/thesis/files/<file_id>/classify", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_classify_file(project_id, file_id):
    thesis_files.list_files(project_id)
    from common.thesis_classifier import classify_file
    from common.thesis_placements import generate_for_file
    result = classify_file(project_id, file_id)
    result["placement"] = generate_for_file(project_id, file_id)
    return jsonify(result)


@thesis_api.route("/api/projects/<project_id>/thesis/files/link", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_link_file(project_id):
    thesis_files.list_files(project_id)
    file, created = thesis_files.link_document(project_id, request.get_json())
    return jsonify(file), (201 if created else 200)


@thesis_api.route("/api/projects/<project_id>/thesis/placements", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_placements(project_id):
    from common.thesis_placements import list_suggestions
    return jsonify({"suggestions": list_suggestions(project_id, request.args.get("status"))})


@thesis_api.route("/api/projects/<project_id>/thesis/placements/<suggestion_id>", methods=["PUT"])
@_json_errors
@require_project_role("editor")
def thesis_review_placement(project_id, suggestion_id):
    from common.thesis_placements import review_suggestion
    claims = getattr(request, "jwt_claims", {})
    result = review_suggestion(project_id, suggestion_id, request.get_json(), claims.get("sub", "unknown"))
    return jsonify(result)


@thesis_api.route("/api/projects/<project_id>/thesis/chapters/<chapter_id>/sources", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_add_source(project_id, chapter_id):
    from common import thesis_versions
    claims = getattr(request, "jwt_claims", {})
    return jsonify(thesis_versions.add_source(project_id, chapter_id, request.get_json(), claims.get("sub"))), 201


@thesis_api.route("/api/projects/<project_id>/thesis/chapters/<chapter_id>/sources", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_list_sources(project_id, chapter_id):
    from common import thesis_versions
    return jsonify({"sources": thesis_versions.list_sources(project_id, chapter_id)})


@thesis_api.route("/api/projects/<project_id>/thesis/chapters/<chapter_id>/versions", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_create_version(project_id, chapter_id):
    from common import thesis_versions
    claims = getattr(request, "jwt_claims", {})
    return jsonify({"version": thesis_versions.create_version(project_id, chapter_id, request.get_json(), claims.get("sub"))}), 201


@thesis_api.route("/api/projects/<project_id>/thesis/chapters/<chapter_id>/versions", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_list_versions(project_id, chapter_id):
    from common import thesis_versions
    return jsonify({"versions": thesis_versions.list_versions(project_id, chapter_id)})


@thesis_api.route("/api/projects/<project_id>/thesis/versions/<version_id>/claims", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_create_claim(project_id, version_id):
    from common import thesis_versions
    return jsonify({"claim": thesis_versions.create_claim(project_id, version_id, request.get_json())}), 201


@thesis_api.route("/api/projects/<project_id>/thesis/versions/<version_id>/claims", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_list_claims(project_id, version_id):
    from common import thesis_versions
    return jsonify({"claims": thesis_versions.list_claims(project_id, version_id)})


@thesis_api.route("/api/projects/<project_id>/thesis/claims/<claim_id>/sources", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_add_claim_source(project_id, claim_id):
    from common import thesis_versions
    return jsonify({"source": thesis_versions.add_claim_source(project_id, claim_id, request.get_json())}), 201


def _enqueue_thesis_task(project_id, queue_name, payload, handler):
    task_id = str(uuid.uuid4())
    create_task(task_id, queue_name, payload, project_id=project_id)
    Queue(queue_name, connection=redis_conn).enqueue(handler, task_id, payload, job_id=task_id, retry=DEFAULT_RETRY, job_timeout=300)
    return task_id


@thesis_api.route("/api/projects/<project_id>/thesis/chapters/<chapter_id>/generate", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_generate_chapter(project_id, chapter_id):
    payload = request.get_json(silent=True) or {}
    task_id = _enqueue_thesis_task(project_id, "thesis_generate", {"project_id": project_id, "chapter_id": chapter_id, "instructions": payload.get("instructions", "")}, "workers.plugins.thesis_generate.handle")
    return jsonify({"task_id": task_id, "status": "queued"}), 202


@thesis_api.route("/api/projects/<project_id>/thesis/versions/<version_id>/verify", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_verify_version(project_id, version_id):
    task_id = _enqueue_thesis_task(project_id, "thesis_verify", {"project_id": project_id, "version_id": version_id}, "workers.plugins.thesis_verify.handle")
    return jsonify({"task_id": task_id, "status": "queued"}), 202


@thesis_api.route("/api/projects/<project_id>/thesis/versions/<version_id>/overlap", methods=["GET"])
@_json_errors
@require_project_role("viewer")
def thesis_get_overlap(project_id, version_id):
    from common import thesis_overlap
    return jsonify(thesis_overlap.get_check(project_id, version_id) or {"status": "pending", "version_id": version_id})


@thesis_api.route("/api/projects/<project_id>/thesis/versions/<version_id>/overlap", methods=["POST"])
@_json_errors
@require_project_role("editor")
def thesis_run_overlap(project_id, version_id):
    from common import thesis_overlap
    claims = getattr(request, "jwt_claims", {})
    task_id = _enqueue_thesis_task(project_id, "thesis_check_overlap", {"project_id": project_id, "version_id": version_id, "checked_by": claims.get("sub")}, "workers.plugins.thesis_overlap.handle")
    return jsonify({"task_id": task_id, "status": "queued"}), 202
