import unittest
from unittest.mock import patch
from utils.bounded_cache import BoundedCache

class BoundedCacheTests(unittest.TestCase):
    def test_budget_and_oversized_entry(self):
        cache=BoundedCache(120,max_bytes=4096,max_items=3)
        for i in range(20): cache[i]='x'*1000
        self.assertLessEqual(cache.used_bytes,4096)
        self.assertLessEqual(len(cache),3)
        cache['huge']='y'*10000
        self.assertNotIn('huge',cache)
        cache.clear(); self.assertEqual(cache.used_bytes,0)

    def test_expiry_releases_references_without_another_insertion(self):
        with patch('utils.bounded_cache.time.monotonic',return_value=0):
            cache=BoundedCache(120);cache['expired']=[1,2,3]
        with patch('utils.bounded_cache.time.monotonic',return_value=121):
            cache.prune()
        self.assertEqual(cache.used_bytes,0)
        self.assertEqual(len(cache),0)

if __name__=='__main__': unittest.main()
