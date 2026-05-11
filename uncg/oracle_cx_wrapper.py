import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import oracledb as db


class OracleDBError(RuntimeError):
    """Raised when the OracleDB wrapper hits an execution or lifecycle error."""


class OracleDB:
    """Thin Oracle DB helper with safe connection and cursor lifecycle handling."""

    _client_initialized = False

    def __init__(self, username: str, password: str, dsn: Optional[str] = None, label: str = "db"):
        """Store credentials/connection metadata and resolve a default DSN if omitted."""
        self.username = username
        self.password = password
        self.label = label
        self.conn: Optional[db.Connection] = None
        if dsn:
            self.dsn = dsn
        else:
            host = "dlo-db01.uncg.edu"
            service_name = "UGDEV8.sndbssub.vcndbsnetwork.oraclevcn.com"
            port = "1521"
            self.dsn = (
                f"(description = (retry_count=20)(retry_delay=3)(address=(protocol=tcp)"
                f"(port={port})(host={host}))"
                f"(connect_data=(service_name={service_name}))"
                f"(security=(ssl_server_dn_match=yes)))"
            )

    @classmethod
    def _ensure_client_initialized(cls) -> None:
        """Initialize Oracle thick client once; continue if thin mode is sufficient."""
        if cls._client_initialized:
            return
        try:
            db.init_oracle_client()
        except Exception as exc:  # noqa: BLE001 - Thin mode may not require client init.
            logging.debug(f"init_oracle_client() skipped/failed; continuing: {exc}")
        cls._client_initialized = True

    def __enter__(self) -> "OracleDB":
        """Open a connection when entering a with-block."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Always close the connection when exiting a with-block."""
        self.close()

    def connect(self) -> None:
        """Open a database connection and raise OracleDBError on failure."""
        try:
            self._ensure_client_initialized()
            self.conn = db.connect(user=self.username, password=self.password, dsn=self.dsn)
            logging.info(f"Connected {self.label} as {self.username} to DSN: {self.dsn}")
        except db.DatabaseError as db_err:
            logging.error(f"Connection failed for {self.label} ({self.username}): {db_err}")
            raise OracleDBError(f"Unable to connect {self.label} to {self.dsn}") from db_err
        except TypeError as type_err:
            logging.error(f"Invalid connection params for {self.label}: {type_err}")
            raise OracleDBError(f"Invalid connection parameters for {self.label}") from type_err

    def close(self) -> None:
        """Close the connection if open and reset local connection state."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None
            logging.info(f"Connection {self.label} closed")

    @contextmanager
    def _cursor(self):
        """Yield a cursor and guarantee closure even if query execution fails."""
        if self.conn is None:
            raise OracleDBError(f"{self.label} is not connected")
        cursor = self.conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def oracle_query(
        self,
        sql_code: str,
        parameters: Optional[Dict[str, Any]] = None,
        col_name: bool = True,
        verbose: bool = False,
    ) -> List[Any]:
        """Run SELECT SQL and return rows as dicts (default) or tuples."""
        try:
            with self._cursor() as cursor:
                cursor.prepare(sql_code)
                cursor.execute(None, parameters or {})

                if col_name:
                    columns = [col[0] for col in (cursor.description or [])]
                    cursor.rowfactory = lambda *args: dict(zip(columns, args))

                rows: List[Any] = []
                for chunk in iter(lambda: cursor.fetchmany(size=5000), []):
                    rows.extend(chunk)
        except db.DatabaseError as db_err:
            detail = f"Parameters: {parameters}\\nReturned query: {sql_code}" if parameters else f"Query: {sql_code}"
            logging.error(detail)
            logging.error(str(db_err))
            raise OracleDBError(f"Query failed on {self.label}") from db_err

        if verbose:
            logging.debug(f"Returned query ({self.label}): {sql_code}")
        return rows

    def oracle_execute(
        self,
        sql_code: str,
        parameters: Optional[Dict[str, Any]] = None,
        verbose: bool = False,
        commit: bool = False,
    ) -> None:
        """Run non-query SQL with optional commit."""
        try:
            with self._cursor() as cursor:
                cursor.prepare(sql_code)
                cursor.execute(None, parameters or {})
            if commit and self.conn is not None:
                self.conn.commit()
        except db.DatabaseError as db_err:
            detail = f"Parameters: {parameters}\\nExecute: {sql_code}" if parameters else f"Execute: {sql_code}"
            logging.error(detail)
            logging.error(str(db_err))
            raise OracleDBError(f"Execute failed on {self.label}") from db_err

        if verbose:
            logging.debug(f"Execute ({self.label}): {sql_code}")

    def query_test(self) -> List[Any]:
        """Run a simple connectivity check query and return the result rows."""
        date_query = self.oracle_query("select sysdate from dual", parameters=None, col_name=True, verbose=True)
        logging.info(date_query)
        return date_query


class OracleCompareSession:
    """Manage two OracleDB connections (for example dev/prod) for comparisons."""

    def __init__(self, left_db: OracleDB, right_db: OracleDB):
        """Store the left/right OracleDB objects used for comparison queries."""
        self.left_db = left_db
        self.right_db = right_db

    def __enter__(self) -> "OracleCompareSession":
        """Connect both databases when entering a with-block."""
        self.left_db.connect()
        self.right_db.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Close both database connections when leaving a with-block."""
        self.left_db.close()
        self.right_db.close()

    @staticmethod
    def _as_hashable(row: Any) -> Tuple[Any, ...]:
        """Convert a row into a hashable tuple so rows can be compared via sets."""
        if isinstance(row, dict):
            return tuple(sorted(row.items()))
        if isinstance(row, (list, tuple)):
            return tuple(row)
        return (row,)

    def compare_query(
        self,
        sql_code: str,
        *,
        left_parameters: Optional[Dict[str, Any]] = None,
        right_parameters: Optional[Dict[str, Any]] = None,
        col_name: bool = True,
    ) -> Dict[str, Any]:
        """Run the same query against both DBs and return difference summary."""
        left_rows = self.left_db.oracle_query(
            sql_code,
            parameters=left_parameters,
            col_name=col_name,
        )
        right_rows = self.right_db.oracle_query(
            sql_code,
            parameters=right_parameters,
            col_name=col_name,
        )

        left_map = {self._as_hashable(row): row for row in left_rows}
        right_map = {self._as_hashable(row): row for row in right_rows}

        left_keys = set(left_map)
        right_keys = set(right_map)

        only_left = [left_map[key] for key in (left_keys - right_keys)]
        only_right = [right_map[key] for key in (right_keys - left_keys)]

        return {
            "left_label": self.left_db.label,
            "right_label": self.right_db.label,
            "left_count": len(left_rows),
            "right_count": len(right_rows),
            "match": not only_left and not only_right,
            "only_left": only_left,
            "only_right": only_right,
        }