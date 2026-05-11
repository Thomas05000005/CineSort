"""Tests pour cinesort.infra._http_utils (audit ID-ROB-001)."""

from __future__ import annotations

import unittest

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cinesort.infra._http_utils import (
    DEFAULT_BACKOFF_BASE,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_STATUS_CODES,
    make_session_with_retry,
)


class TestMakeSessionWithRetry(unittest.TestCase):
    def test_returns_session_instance(self):
        session = make_session_with_retry()
        try:
            self.assertIsInstance(session, requests.Session)
        finally:
            session.close()

    def test_default_user_agent(self):
        session = make_session_with_retry()
        try:
            self.assertEqual(session.headers.get("User-Agent"), "CineSort/7.6")
        finally:
            session.close()

    def test_custom_user_agent(self):
        session = make_session_with_retry(user_agent="MyApp/1.0")
        try:
            self.assertEqual(session.headers.get("User-Agent"), "MyApp/1.0")
        finally:
            session.close()

    def test_adapter_mounted_for_http_and_https(self):
        session = make_session_with_retry()
        try:
            http_adapter = session.get_adapter("http://example.com")
            https_adapter = session.get_adapter("https://example.com")
            self.assertIsInstance(http_adapter, HTTPAdapter)
            self.assertIsInstance(https_adapter, HTTPAdapter)
        finally:
            session.close()

    def test_retry_config_max_attempts(self):
        session = make_session_with_retry(max_attempts=5)
        try:
            adapter = session.get_adapter("https://example.com")
            retry = adapter.max_retries
            self.assertIsInstance(retry, Retry)
            self.assertEqual(retry.total, 5)
            self.assertEqual(retry.connect, 5)
            self.assertEqual(retry.read, 5)
            self.assertEqual(retry.status, 5)
        finally:
            session.close()

    def test_retry_config_status_forcelist(self):
        session = make_session_with_retry()
        try:
            adapter = session.get_adapter("https://example.com")
            retry = adapter.max_retries
            self.assertEqual(tuple(retry.status_forcelist), DEFAULT_RETRY_STATUS_CODES)
            for code in (429, 500, 502, 503, 504):
                self.assertIn(code, retry.status_forcelist)
        finally:
            session.close()

    def test_retry_config_backoff_factor(self):
        session = make_session_with_retry()
        try:
            adapter = session.get_adapter("https://example.com")
            retry = adapter.max_retries
            self.assertEqual(retry.backoff_factor, DEFAULT_BACKOFF_BASE)
            self.assertTrue(retry.respect_retry_after_header)
            self.assertFalse(retry.raise_on_status)
        finally:
            session.close()

    def test_defaults_constants(self):
        self.assertEqual(DEFAULT_MAX_ATTEMPTS, 3)
        self.assertEqual(DEFAULT_BACKOFF_BASE, 0.5)


if __name__ == "__main__":
    unittest.main()
