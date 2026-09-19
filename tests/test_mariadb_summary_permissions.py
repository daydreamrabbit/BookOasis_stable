import unittest
from unittest.mock import Mock, patch

from repositories.mariadb.series_repository import SeriesRepository


class MariaDBSummaryPermissionTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.cursor = self.connection.cursor.return_value
        self.cursor.fetchone.return_value = {'is_ready': 1}
        self.cursor.fetchall.return_value = []

    def test_non_admin_summary_uses_single_permission_lookup_and_keeps_paging(self):
        self.cursor.fetchall.side_effect = [
            [{'library_id': 3}, {'library_id': 8}],
            [],
        ]
        with patch(
            'repositories.mariadb.series_repository.database.get_connection',
            return_value=self.connection,
        ):
            rows = SeriesRepository._fetch_summary_rows(
                db_type='general',
                library_id='all',
                user_id=42,
                role='member',
                limit=61,
                offset=122,
                favorite_user_id=17,
                sort='asc',
            )

        self.assertEqual(rows, [])
        permission_statement, permission_params = self.cursor.execute.call_args_list[-2].args
        statement, params = self.cursor.execute.call_args_list[-1].args
        normalized_sql = ' '.join(statement.split())

        self.assertEqual(
            ' '.join(permission_statement.split()),
            'SELECT library_id FROM user_category_permissions '
            'WHERE user_id = %s AND has_access = 1',
        )
        self.assertEqual(permission_params, (42,))
        self.assertIn('s.library_id IN (%s,%s)', normalized_sql)
        self.assertNotIn('EXISTS (SELECT 1 FROM user_category_permissions', normalized_sql)
        self.assertIn(
            'ORDER BY s.library_id ASC, s.sort_series_name ASC, '
            's.representative_book_id ASC LIMIT %s OFFSET %s',
            normalized_sql,
        )
        self.assertEqual(params, (17, 3, 8, 61, 122))
        self.connection.close.assert_called_once()

    def test_admin_summary_does_not_add_user_permission_filter(self):
        with patch(
            'repositories.mariadb.series_repository.database.get_connection',
            return_value=self.connection,
        ):
            SeriesRepository._fetch_summary_rows(
                db_type='general',
                library_id='all',
                user_id=42,
                role='admin',
                limit=61,
                offset=0,
                favorite_user_id=42,
            )

        statement, params = self.cursor.execute.call_args_list[-1].args
        self.assertNotIn('user_category_permissions', statement)
        self.assertEqual(params, (42, 61, 0))


if __name__ == '__main__':
    unittest.main()
