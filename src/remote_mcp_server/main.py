import asyncio
import hashlib
import json
import math
import os

from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path
from typing import Any

import aiosqlite

from fastmcp import FastMCP
from fastmcp.server.auth.providers.auth0 import Auth0Provider
from fastmcp.server.dependencies import get_access_token


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DB_DIR = Path(
    os.environ.get(
        "EXPENSE_DB_DIR",
        "/tmp/expense-tracker",
    )
).expanduser()

DB_PATH = DB_DIR / "expenses.db"
CATEGORIES_PATH = BASE_DIR / "categories.json"

DB_TIMEOUT = 10.0


# Auth0 configuration
# Use safe defaults for non-secret configuration so FastMCP can
# inspect the server during the Docker build.

AUTH0_DOMAIN = (
    os.getenv(
        "AUTH0_DOMAIN",
        "dev-gm4ywt8jbfhyv8k.us.auth0.com",
    )
    .strip()
    .removeprefix("https://")
    .rstrip("/")
)

AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID", "")
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET", "")

AUTH0_AUDIENCE = os.getenv(
    "AUTH0_AUDIENCE",
    "https://expense-tracker-mcp-api",
)

MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "https://expense-tracker-mcp-server-ak.fastmcp.app",
).rstrip("/")


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def prepare_db_directory() -> None:
    """Create the database directory if it does not exist."""

    DB_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_DIR.is_dir():
        raise RuntimeError(
            f"Database path is not a directory: {DB_DIR}"
        )


async def init_db() -> None:
    """Initialize the SQLite database."""

    prepare_db_directory()

    async with aiosqlite.connect(
        str(DB_PATH),
        timeout=DB_TIMEOUT,
    ) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("SELECT 1")
        await db.commit()


# =========================================================
# USER ISOLATION
# =========================================================

def validate_user_id(user_id: str) -> str:
    """Validate an authenticated user's identity."""

    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError(
            "Authenticated user identity is missing."
        )

    if len(user_id) > 200:
        raise ValueError(
            "Authenticated user identity is invalid."
        )

    return user_id.strip()


def get_user_table(user_id: str) -> str:
    """
    Create a deterministic, SQL-safe table name from
    the authenticated user's identity.
    """

    user_id = validate_user_id(user_id)

    digest = hashlib.sha256(
        user_id.encode("utf-8")
    ).hexdigest()

    return f"expenses_{digest}"


async def ensure_user_table(
    db: aiosqlite.Connection,
    user_id: str,
) -> str:
    """Create the authenticated user's expense table."""

    table = get_user_table(user_id)

    await db.execute(
        f'''
        CREATE TABLE IF NOT EXISTS "{table}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT DEFAULT '',
            note TEXT DEFAULT ''
        )
        '''
    )

    await db.execute(
        f'''
        CREATE INDEX IF NOT EXISTS "idx_{table}_date"
        ON "{table}" (date)
        '''
    )

    return table


# =========================================================
# APPLICATION LIFESPAN
# =========================================================

@asynccontextmanager
async def app_lifespan(server):
    """Initialize the database when the server starts."""

    await init_db()

    yield {}


# =========================================================
# AUTHENTICATED USER IDENTITY
# =========================================================

def get_current_user_id() -> str:
    """
    Obtain the identity from FastMCP's validated access token.

    Never accept a user ID supplied by the MCP tool caller.
    """

    token = get_access_token()

    if token is None:
        raise PermissionError(
            "Authentication required."
        )

    subject = token.claims.get("sub")

    if not isinstance(subject, str) or not subject.strip():
        raise PermissionError(
            "The access token does not contain a valid subject."
        )

    return validate_user_id(subject)


# =========================================================
# AUTH0 CONFIGURATION
# =========================================================

auth = Auth0Provider(
    config_url=(
        "https://dev-gm4ywt8jbfhyv8k.us.auth0.com"
        "/.well-known/openid-configuration"
    ),
    client_id=AUTH0_CLIENT_ID,
    client_secret=AUTH0_CLIENT_SECRET,
    audience=AUTH0_AUDIENCE,
    base_url=MCP_SERVER_URL,
)


# =========================================================
# FASTMCP SERVER
# =========================================================

mcp = FastMCP(
    "ExpenseTracker",
    auth=auth,
    lifespan=app_lifespan,
)


# =========================================================
# INPUT VALIDATION
# =========================================================

def validate_date(
    value: str,
    field_name: str = "date",
) -> str:
    """Validate a date in YYYY-MM-DD format."""

    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        )

    try:
        parsed = Date.fromisoformat(value)

    except ValueError as exc:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        ) from exc

    if parsed.isoformat() != value:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        )

    return value


def validate_date_range(
    start_date: str,
    end_date: str,
) -> None:
    """Validate a date range."""

    validate_date(start_date, "start_date")
    validate_date(end_date, "end_date")

    if start_date > end_date:
        raise ValueError(
            "start_date must be on or before end_date."
        )


def validate_amount(amount: float) -> float:
    """Validate a positive, finite monetary amount."""

    if isinstance(amount, bool) or not isinstance(
        amount,
        (int, float),
    ):
        raise ValueError(
            "Amount must be a number."
        )

    amount = float(amount)

    if not math.isfinite(amount) or amount <= 0:
        raise ValueError(
            "Amount must be finite and greater than zero."
        )

    return amount


def validate_text(
    value: str,
    field_name: str,
    max_length: int = 500,
) -> str:
    """Validate and normalize text input."""

    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must be text."
        )

    value = value.strip()

    if len(value) > max_length:
        raise ValueError(
            f"{field_name} cannot exceed "
            f"{max_length} characters."
        )

    return value


# =========================================================
# TOOL 1: ADD EXPENSE
# =========================================================

@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
):
    """
    Add an expense for the currently authenticated user.

    The user's identity is obtained from the access token.
    """

    user_id = get_current_user_id()

    date = validate_date(date)
    amount = validate_amount(amount)

    category = validate_text(
        category,
        "category",
        100,
    )

    subcategory = validate_text(
        subcategory,
        "subcategory",
        100,
    )

    note = validate_text(
        note,
        "note",
        2000,
    )

    if not category:
        raise ValueError(
            "Category cannot be empty."
        )

    async with aiosqlite.connect(
        str(DB_PATH),
        timeout=DB_TIMEOUT,
    ) as db:

        table = await ensure_user_table(
            db,
            user_id,
        )

        async with db.execute(
            f'''
            INSERT INTO "{table}"
                (date, amount, category, subcategory, note)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                date,
                amount,
                category,
                subcategory,
                note,
            ),
        ) as cursor:

            expense_id = cursor.lastrowid

        await db.commit()

    return {
        "status": "ok",
        "id": expense_id,
        "message": "Expense added successfully.",
    }


# =========================================================
# TOOL 2: LIST EXPENSES
# =========================================================

@mcp.tool()
async def list_expenses(
    start_date: str,
    end_date: str,
):
    """
    List expenses belonging only to the authenticated user.
    """

    user_id = get_current_user_id()

    validate_date_range(
        start_date,
        end_date,
    )

    async with aiosqlite.connect(
        str(DB_PATH),
        timeout=DB_TIMEOUT,
    ) as db:

        table = await ensure_user_table(
            db,
            user_id,
        )

        db.row_factory = aiosqlite.Row

        async with db.execute(
            f'''
            SELECT
                id,
                date,
                amount,
                category,
                subcategory,
                note
            FROM "{table}"
            WHERE date BETWEEN ? AND ?
            ORDER BY date ASC, id ASC
            ''',
            (
                start_date,
                end_date,
            ),
        ) as cursor:

            rows = await cursor.fetchall()

    return [
        dict(row)
        for row in rows
    ]


# =========================================================
# TOOL 3: SUMMARIZE EXPENSES
# =========================================================

@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: str | None = None,
):
    """
    Summarize expenses belonging only to the authenticated user.
    """

    user_id = get_current_user_id()

    validate_date_range(
        start_date,
        end_date,
    )

    query = '''
        SELECT
            category,
            SUM(amount) AS total_amount
        FROM "{table}"
        WHERE date BETWEEN ? AND ?
    '''

    params: list[Any] = [
        start_date,
        end_date,
    ]

    if category is not None:
        category = validate_text(
            category,
            "category",
            100,
        )

        query += " AND category = ?"
        params.append(category)

    query += '''
        GROUP BY category
        ORDER BY category ASC
    '''

    async with aiosqlite.connect(
        str(DB_PATH),
        timeout=DB_TIMEOUT,
    ) as db:

        table = await ensure_user_table(
            db,
            user_id,
        )

        db.row_factory = aiosqlite.Row

        async with db.execute(
            query.format(table=table),
            params,
        ) as cursor:

            rows = await cursor.fetchall()

    return [
        dict(row)
        for row in rows
    ]


# =========================================================
# TOOL 4: UPDATE EXPENSE
# =========================================================

@mcp.tool()
async def update_expense(
    expense_id: int,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None = None,
):
    """
    Update an expense belonging to the authenticated user.

    The expense ID is looked up only in that user's table.
    """

    user_id = get_current_user_id()

    if (
        isinstance(expense_id, bool)
        or not isinstance(expense_id, int)
        or expense_id <= 0
    ):
        raise ValueError(
            "expense_id must be a positive integer."
        )

    updates: list[str] = []
    params: list[Any] = []

    if date is not None:
        updates.append("date = ?")
        params.append(
            validate_date(date)
        )

    if amount is not None:
        updates.append("amount = ?")
        params.append(
            validate_amount(amount)
        )

    if category is not None:
        category = validate_text(
            category,
            "category",
            100,
        )

        if not category:
            raise ValueError(
                "Category cannot be empty."
            )

        updates.append("category = ?")
        params.append(category)

    if subcategory is not None:
        updates.append("subcategory = ?")
        params.append(
            validate_text(
                subcategory,
                "subcategory",
                100,
            )
        )

    if note is not None:
        updates.append("note = ?")
        params.append(
            validate_text(
                note,
                "note",
                2000,
            )
        )

    if not updates:
        return {
            "status": "error",
            "message": "No fields provided to update.",
        }

    params.append(expense_id)

    async with aiosqlite.connect(
        str(DB_PATH),
        timeout=DB_TIMEOUT,
    ) as db:

        table = await ensure_user_table(
            db,
            user_id,
        )

        query = (
            f'UPDATE "{table}" '
            f'SET {", ".join(updates)} '
            "WHERE id = ?"
        )

        async with db.execute(
            query,
            params,
        ) as cursor:

            affected = cursor.rowcount

        await db.commit()

    if affected == 0:
        return {
            "status": "error",
            "message": (
                "Expense not found in this user's table."
            ),
        }

    return {
        "status": "ok",
        "message": (
            f"Expense {expense_id} updated successfully."
        ),
    }


# =========================================================
# TOOL 5: DELETE EXPENSE
# =========================================================

@mcp.tool()
async def delete_expense(
    expense_id: int,
):
    """
    Delete an expense belonging only to the authenticated user.
    """

    user_id = get_current_user_id()

    if (
        isinstance(expense_id, bool)
        or not isinstance(expense_id, int)
        or expense_id <= 0
    ):
        raise ValueError(
            "expense_id must be a positive integer."
        )

    async with aiosqlite.connect(
        str(DB_PATH),
        timeout=DB_TIMEOUT,
    ) as db:

        table = await ensure_user_table(
            db,
            user_id,
        )

        async with db.execute(
            f'DELETE FROM "{table}" WHERE id = ?',
            (expense_id,),
        ) as cursor:

            affected = cursor.rowcount

        await db.commit()

    if affected == 0:
        return {
            "status": "error",
            "message": (
                "Expense not found in this user's table."
            ),
        }

    return {
        "status": "ok",
        "message": (
            f"Expense {expense_id} deleted successfully."
        ),
    }


# =========================================================
# RESOURCE: EXPENSE CATEGORIES
# =========================================================

@mcp.resource(
    "expense://categories",
    mime_type="application/json",
)
async def categories():
    """Read the expense categories from categories.json."""

    def read_categories():
        with open(
            CATEGORIES_PATH,
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    return await asyncio.to_thread(
        read_categories
    )


# =========================================================
# ENTRY POINT
# =========================================================

def main():
    """Start the remote MCP server."""

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(
            os.getenv("PORT", "8000")
        ),
    )


if __name__ == "__main__":
    main()