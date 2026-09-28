import unittest

from api.routes.settings_routes import (
    SETTING_VALUE_LIMITS,
    USER_OVERRIDABLE_SETTING_KEYS,
)


class PluginLayoutSettingsTest(unittest.TestCase):
    def test_plugin_layout_preferences_are_user_synced(self):
        for key in ('PLUGIN_DESK_ORDER', 'PLUGIN_SETTINGS_ORDER', 'PLUGIN_DESK_LOCKED'):
            self.assertIn(key, USER_OVERRIDABLE_SETTING_KEYS)

    def test_plugin_order_values_allow_a_full_plugin_list(self):
        self.assertGreaterEqual(SETTING_VALUE_LIMITS['PLUGIN_DESK_ORDER'], 8192)
        self.assertGreaterEqual(SETTING_VALUE_LIMITS['PLUGIN_SETTINGS_ORDER'], 8192)


if __name__ == '__main__':
    unittest.main()
