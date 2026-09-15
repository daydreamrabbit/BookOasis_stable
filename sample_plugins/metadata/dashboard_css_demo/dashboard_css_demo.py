# -*- coding: utf-8 -*-
"""dashboard_css_demo - home_widget에서 dashboard.html/dashboard.css로 완전한 CSS와 이미지를
쓰는 예시. docs/guide_plugins.md §5-1 "커스텀 CSS/이미지" 절 참고. 위젯 내용은 정적이라
get_dashboard_data()는 아무 데이터도 필요로 하지 않는다 - success만 True면 프론트가
dashboard.html/css를 불러와 위젯 전용 Shadow DOM에 렌더링한다."""
from plugins.metadata.base import BaseMetadataProvider


class DashboardCssDemoMetadataProvider(BaseMetadataProvider):
    id = "dashboard_css_demo"
    name = "대시보드 CSS 데모"
    is_searchable = False
    config_schema = []
    home_widget = {
        "title": "CSS 데모 위젯",
        "subtitle": "dashboard.html/css 예시",
        "provider": "BookOasis",
        "icon": "fa-solid fa-palette",
        "order": 70,
        "layout": "grid",
        "size": 1,
        "sessions": "all",
    }

    def search(self, db_type, query):
        return []

    def apply(self, db_type, book_id, item_data):
        return False, "CSS 데모 위젯 플러그인은 메타데이터 적용을 지원하지 않습니다."

    def get_dashboard_data(self, db_type, limit=10):
        return {"success": True, "items": []}
