# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, request, session

from services.image_drawing_service import ImageDrawingService


image_drawing_bp = Blueprint("image_drawings", __name__)


def _current_user_id():
    user_id = session.get("user_id")
    if not user_id and isinstance(session.get("user"), dict):
        user_id = session["user"].get("id")
    return user_id


def _db_type():
    value = str(request.args.get("db_type", "general") or "general").lower()
    return value if value in {"general", "adult"} else "general"


@image_drawing_bp.route("/api/v1/books/<int:book_id>/drawings", methods=["GET"])
def get_book_drawings(book_id):
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    try:
        drawings = ImageDrawingService.get_book_drawings(_db_type(), book_id, user_id)
        return jsonify({"success": True, "drawings": drawings})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@image_drawing_bp.route("/api/v1/books/<int:book_id>/drawings", methods=["PUT"])
def save_book_drawing(book_id):
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "요청 형식이 올바르지 않습니다."}), 400
    try:
        strokes = ImageDrawingService.save_page_drawing(
            _db_type(), book_id, user_id, payload.get("page_key"), payload.get("strokes")
        )
        return jsonify({"success": True, "page_key": payload.get("page_key"), "strokes": strokes})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@image_drawing_bp.route("/api/v1/books/<int:book_id>/drawings", methods=["DELETE"])
def delete_book_drawing(book_id):
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "요청 형식이 올바르지 않습니다."}), 400
    try:
        deleted = ImageDrawingService.delete_page_drawing(
            _db_type(), book_id, user_id, payload.get("page_key")
        )
        return jsonify({"success": True, "deleted": deleted})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
