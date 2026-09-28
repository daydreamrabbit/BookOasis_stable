# -*- coding: utf-8 -*-
from repositories.series_delete_repository_shared import delete_series_by_anchor, delete_series_batch


class SeriesDeleteRepository:
    @staticmethod
    def delete_series_batch(db_type, targets):
        return delete_series_batch(db_type, targets, '?')

    @staticmethod
    def delete_series_by_anchor(db_type, book_id, expected_library_id=None):
        return delete_series_by_anchor(db_type, book_id, expected_library_id, '?')
