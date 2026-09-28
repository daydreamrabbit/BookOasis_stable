import unittest

from api.routes.settings_routes import (
    PUBLIC_UI_SETTING_KEYS,
    USER_OVERRIDABLE_SETTING_KEYS,
)


class MetadataConnectionSettingTest(unittest.TestCase):
    def test_setting_is_public_and_user_overridable(self):
        key = 'SHOW_METADATA_CONNECTION_STATUS'
        self.assertIn(key, PUBLIC_UI_SETTING_KEYS)
        self.assertIn(key, USER_OVERRIDABLE_SETTING_KEYS)


if __name__ == '__main__':
    unittest.main()
