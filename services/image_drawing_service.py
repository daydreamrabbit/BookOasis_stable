# -*- coding: utf-8 -*-
"""Validation and service boundary for per-user image drawing layers."""
import json
import re

from repositories.image_drawing_repository import ImageDrawingRepository


PAGE_KEY_RE = re.compile(r"^\d{1,7}:(?:full|left|right)$")
MAX_PAGE_KEY_LEN = 32
MAX_STROKES = 500
MAX_POINTS_PER_STROKE = 4000
MAX_STROKES_JSON_LEN = 2_000_000
ALLOWED_PEN_TYPES = {"pen", "highlighter", "pencil"}
ALLOWED_BRUSH_TYPES = {"round", "soft", "square"}
ALLOWED_SHAPES = {"freehand", "line", "rect", "ellipse"}


def _number(value, minimum=0.0, maximum=1.0):
    value = float(value)
    if value != value or value < minimum or value > maximum:
        raise ValueError("그림 좌표가 올바르지 않습니다.")
    return value


def _validate_strokes(strokes):
    if not isinstance(strokes, list) or len(strokes) > MAX_STROKES:
        raise ValueError("그림 데이터가 너무 큽니다.")

    normalized = []
    for stroke in strokes:
        if not isinstance(stroke, dict):
            raise ValueError("그림 데이터 형식이 올바르지 않습니다.")
        pen_type = str(stroke.get("pen_type") or "pen").strip().lower()
        brush_type = str(stroke.get("brush_type") or "round").strip().lower()
        shape = str(stroke.get("shape") or "freehand").strip().lower()
        if pen_type not in ALLOWED_PEN_TYPES or brush_type not in ALLOWED_BRUSH_TYPES or shape not in ALLOWED_SHAPES:
            raise ValueError("지원하지 않는 그림 도구입니다.")

        color = str(stroke.get("color") or "#000000").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("색상 값이 올바르지 않습니다.")

        try:
            size = float(stroke.get("size", 6))
        except (TypeError, ValueError):
            raise ValueError("브러시 크기가 올바르지 않습니다.")
        if size < 1 or size > 128:
            raise ValueError("브러시 크기가 올바르지 않습니다.")

        points = stroke.get("points")
        if not isinstance(points, list) or not points or len(points) > MAX_POINTS_PER_STROKE:
            raise ValueError("그림 선 데이터가 올바르지 않습니다.")
        normalized_points = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2 or len(point) > 3:
                raise ValueError("그림 좌표가 올바르지 않습니다.")
            pressure = _number(point[2], 0.0, 1.0) if len(point) == 3 else 0.5
            normalized_points.append([_number(point[0]), _number(point[1]), pressure])

        normalized.append({
            "pen_type": pen_type,
            "brush_type": brush_type,
            "shape": shape,
            "color": color,
            "size": round(size, 2),
            "points": normalized_points,
        })

    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_STROKES_JSON_LEN:
        raise ValueError("그림 데이터가 너무 큽니다.")
    return normalized, encoded


class ImageDrawingService:
    @staticmethod
    def get_book_drawings(db_type, book_id, user_id):
        rows = ImageDrawingRepository.get_book_drawings(db_type, int(book_id), int(user_id))
        result = []
        for row in rows:
            page_key = str(row.get("page_key") or "")
            if len(page_key) > MAX_PAGE_KEY_LEN or not PAGE_KEY_RE.fullmatch(page_key):
                continue
            try:
                strokes = json.loads(row.get("strokes_json") or "[]")
                strokes, _encoded = _validate_strokes(strokes)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            result.append({"page_key": page_key, "strokes": strokes})
        return result

    @staticmethod
    def save_page_drawing(db_type, book_id, user_id, page_key, strokes):
        page_key = str(page_key or "").strip()
        if len(page_key) > MAX_PAGE_KEY_LEN or not PAGE_KEY_RE.fullmatch(page_key):
            raise ValueError("페이지 식별자가 올바르지 않습니다.")
        normalized, encoded = _validate_strokes(strokes)
        if normalized:
            ImageDrawingRepository.save_page_drawing(db_type, int(book_id), int(user_id), page_key, encoded)
        else:
            ImageDrawingRepository.delete_page_drawing(db_type, int(book_id), int(user_id), page_key)
        return normalized

    @staticmethod
    def delete_page_drawing(db_type, book_id, user_id, page_key):
        page_key = str(page_key or "").strip()
        if len(page_key) > MAX_PAGE_KEY_LEN or not PAGE_KEY_RE.fullmatch(page_key):
            raise ValueError("페이지 식별자가 올바르지 않습니다.")
        return ImageDrawingRepository.delete_page_drawing(db_type, int(book_id), int(user_id), page_key)
