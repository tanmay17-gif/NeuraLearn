import os
import httpx
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
load_dotenv()

class LightweightSupabase:
    """Lightweight Supabase REST client — no compiled deps needed."""
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL", "").rstrip('/')
        self.key = os.getenv("SUPABASE_KEY", "")
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def table(self, table_name: str, jwt: Optional[str] = None):
        return SupabaseTable(self, table_name, jwt=jwt)


class SupabaseTable:
    def __init__(self, client, table_name, jwt=None):
        self.client = client
        self.table_name = table_name
        self.jwt = jwt
        self._filters = {}
        self._select = "*"
        self._limit = None

    def _get_headers(self):
        headers = self.client.headers.copy()
        if self.jwt:
            headers["Authorization"] = f"Bearer {self.jwt}"
        return headers

    def select(self, query: str = "*"):
        self._select = query
        return self

    def eq(self, column: str, value: Any):
        self._filters[column] = f"eq.{value}"
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def execute(self):
        """Run a SELECT query."""
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {"select": self._select, **self._filters}
        if self._limit is not None:
            params["limit"] = str(self._limit)
        with httpx.Client(timeout=10) as client:
            response = client.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
        return _Result(response.json())

    def insert(self, data: Any):
        """Run an INSERT and return representation."""
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        headers = {
            **self._get_headers(),
            "Prefer": "return=representation",
        }
        # data can be a dict (single row) or list (multiple rows)
        with httpx.Client(timeout=10) as client:
            response = client.post(url, headers=headers, json=data)
            response.raise_for_status()
        return _Result(response.json())

    def upsert(self, data: Any, on_conflict: str = "user_id"):
        """Run an UPSERT (INSERT … ON CONFLICT DO UPDATE)."""
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        # on_conflict MUST be a query-string parameter for PostgREST upserts
        params = {"on_conflict": on_conflict}
        headers = {
            **self._get_headers(),
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        with httpx.Client(timeout=10) as client:
            response = client.post(url, headers=headers, params=params, json=data)
            response.raise_for_status()
        return _Result(response.json())

    def update(self, data: Dict[str, Any]):
        """Run an UPDATE on rows matching the current filters."""
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {**self._filters}
        headers = {
            **self._get_headers(),
            "Prefer": "return=representation",
        }
        with httpx.Client(timeout=10) as client:
            response = client.patch(url, headers=headers, params=params, json=data)
            response.raise_for_status()
        return _Result(response.json())

    def delete(self):
        """Run a DELETE on rows matching the current filters."""
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {**self._filters}
        with httpx.Client(timeout=10) as client:
            response = client.delete(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
        return _Result([])


class _Result:
    def __init__(self, data):
        self.data = data if isinstance(data, list) else [data]


# Module-level singleton
supabase = LightweightSupabase()

def verify_auth_token(token: str) -> str:
    """
    Verifies a Supabase JWT token and returns the user_id.
    Raises an exception if the token is invalid or expired.
    """
    if not supabase.url or not supabase.key:
        return "default_user" # Bypass for dev without supabase

    url = f"{supabase.url}/auth/v1/user"
    headers = {
        "apikey": supabase.key,
        "Authorization": f"Bearer {token}"
    }
    with httpx.Client(timeout=5) as client:
        response = client.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception("Invalid or expired authentication token.")
        data = response.json()
        return data.get("id")
