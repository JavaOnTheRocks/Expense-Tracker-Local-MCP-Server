
import asyncio
import json
import math
import os
from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path

import aiosqlite
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token




BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "expenses.db"
CATEGORIES_PATH = BASE_DIR / "categories.json"
DB_TIMEOUT = 10.0

# Local testing only. Never enable this on a public deployment.
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

AUTH_ISSUER = os.getenv("AUTH_ISSUER")
AUTH_AUDIENCE = os.getenv("AUTH_AUDIENCE")
AUTH_JWKS_URI = os.getenv("AUTH_JWKS_URI")

auth = None

if DEV_MODE:
    print(
        "WARNING: Development mode enabled. Authentication is disabled. "
        "Use this mode only on your local machine."
    )
elif all([AUTH_ISSUER, AUTH_AUDIENCE, AUTH_JWKS_URI]):
    auth = JWTVerifier(
        jwks_uri=AUTH_JWKS_URI,
        issuer=AUTH_ISSUER,
        audience=AUTH_AUDIENCE,
    )



# =========================================================
# DATABASE INITIALIZATION
# =========================================================

async def init_db():
    """Create the expenses table and migrate older databases."""

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT '',
                user_id TEXT
            )
        """)

        async with db.execute("PRAGMA table_info(expenses)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}

        if "user_id" not in columns:
            await db.execute(
                "ALTER TABLE expenses ADD COLUMN user_id TEXT"
            )

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_expenses_user_date
            ON expenses(user_id, date)
        """)

        await db.commit()


@asynccontextmanager
async def app_lifespan(server):
    """Validate authentication and initialize the database."""

    # Ensure authentication is configured in production.
    if not DEV_MODE and not all(
        [AUTH_ISSUER, AUTH_AUDIENCE, AUTH_JWKS_URI]
    ):
        raise RuntimeError(
            "Authentication is not configured. "
            "Set AUTH_ISSUER, AUTH_AUDIENCE, and AUTH_JWKS_URI."
        )

    # Initialize the database.
    await init_db()

    yield {}


# Define the server exactly once, after app_lifespan.
mcp = FastMCP(
    "ExpenseTracker",
    auth=auth,
    lifespan=app_lifespan,
)


# =========================================================
# AUTHENTICATED USER IDENTITY
# =========================================================

def get_current_user_id() -> str:
    """
    Get the user ID from a verified token.

    Local development uses a fixed local-only identity.
    """
    token = get_access_token()

    if token is None:
        if DEV_MODE:
            return "local-dev-user"
        raise PermissionError("Authentication required.")

    claims = getattr(token, "claims", None) or {}
    user_id = getattr(token, "subject", None) or claims.get("sub")

    if not isinstance(user_id, str) or not user_id.strip():
        raise PermissionError("The access token has no valid subject.")

    return user_id


# =========================================================
# INPUT VALIDATION
# =========================================================

def validate_date(value: str, field_name: str) -> str:
    """Validate dates in YYYY-MM-DD format."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")

    try:
        parsed = Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        ) from exc

    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")

    return value


def validate_amount(amount: float) -> float:
    """Require a finite, positive amount."""

    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValueError("Amount must be a number.")

    amount = float(amount)

    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Amount must be finite and greater than zero.")

    return amount


def validate_text(
    value: str,
    field_name: str,
    max_length: int = 500,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")

    value = value.strip()

    if len(value) > max_length:
        raise ValueError(
            f"{field_name} cannot exceed {max_length} characters."
        )

    return value


def validate_date_range(start_date: str, end_date: str):
    validate_date(start_date, "start_date")
    validate_date(end_date, "end_date")

    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")


# =========================================================
# ADD EXPENSE
# =========================================================

@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
):
    """Add an expense for the current user."""

    user_id = get_current_user_id()

    date = validate_date(date, "date")
    amount = validate_amount(amount)
    category = validate_text(category, "category", 100)

    if not category:
        raise ValueError("Category cannot be empty.")

    subcategory = validate_text(subcategory, "subcategory", 100)
    note = validate_text(note, "note", 2000)

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        async with db.execute(
            """
            INSERT INTO expenses
                (date, amount, category, subcategory, note, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (date, amount, category, subcategory, note, user_id),
        ) as cursor:
            expense_id = cursor.lastrowid

        await db.commit()

    return {
        "status": "ok",
        "id": expense_id,
        "message": "Expense added successfully.",
    }


# =========================================================
# LIST EXPENSES
# =========================================================

@mcp.tool()
async def list_expenses(start_date: str, end_date: str):
    """List the current user's expenses within a date range."""

    user_id = get_current_user_id()
    validate_date_range(start_date, end_date)

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE user_id = ?
              AND date BETWEEN ? AND ?
            ORDER BY date ASC, id ASC
            """,
            (user_id, start_date, end_date),
        ) as cursor:
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


# =========================================================
# SUMMARIZE EXPENSES
# =========================================================

@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: str | None = None,
):
    """Summarize the current user's expenses by category."""

    user_id = get_current_user_id()
    validate_date_range(start_date, end_date)

    query = """
        SELECT category, SUM(amount) AS total_amount
        FROM expenses
        WHERE user_id = ?
          AND date BETWEEN ? AND ?
    """
    params = [user_id, start_date, end_date]

    if category is not None:
        category = validate_text(category, "category", 100)
        query += " AND category = ?"
        params.append(category)

    query += " GROUP BY category ORDER BY category ASC"

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


# =========================================================
# UPDATE EXPENSE
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
    """Update an expense belonging to the current user."""

    user_id = get_current_user_id()

    if isinstance(expense_id, bool) or not isinstance(expense_id, int):
        raise ValueError("expense_id must be an integer.")

    if expense_id <= 0:
        raise ValueError("expense_id must be positive.")

    allowed_fields = {
        "date": date,
        "amount": amount,
        "category": category,
        "subcategory": subcategory,
        "note": note,
    }

    updates = []
    params = []

    for field, value in allowed_fields.items():
        if value is None:
            continue

        if field == "date":
            value = validate_date(value, "date")

        elif field == "amount":
            value = validate_amount(value)

        elif field == "category":
            value = validate_text(value, "category", 100)
            if not value:
                raise ValueError("Category cannot be empty.")

        elif field == "subcategory":
            value = validate_text(value, "subcategory", 100)

        elif field == "note":
            value = validate_text(value, "note", 2000)

        updates.append(f"{field} = ?")
        params.append(value)

    if not updates:
        return {
            "status": "error",
            "message": "No fields provided to update.",
        }

    params.extend([expense_id, user_id])

    query = (
        f"UPDATE expenses SET {', '.join(updates)} "
        "WHERE id = ? AND user_id = ?"
    )

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        async with db.execute(query, params) as cursor:
            affected = cursor.rowcount

        await db.commit()

    if affected == 0:
        return {
            "status": "error",
            "message": "Expense not found or access denied.",
        }

    return {
        "status": "ok",
        "message": f"Expense {expense_id} updated successfully.",
    }


# =========================================================
# DELETE EXPENSE
# =========================================================

@mcp.tool()
async def delete_expense(expense_id: int):
    """Delete an expense belonging to the current user."""

    user_id = get_current_user_id()

    if isinstance(expense_id, bool) or not isinstance(expense_id, int):
        raise ValueError("expense_id must be an integer.")

    if expense_id <= 0:
        raise ValueError("expense_id must be positive.")

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        async with db.execute(
            """
            DELETE FROM expenses
            WHERE id = ? AND user_id = ?
            """,
            (expense_id, user_id),
        ) as cursor:
            affected = cursor.rowcount

        await db.commit()

    if affected == 0:
        return {
            "status": "error",
            "message": "Expense not found or access denied.",
        }

    return {
        "status": "ok",
        "message": f"Expense {expense_id} deleted successfully.",
    }


# =========================================================
# CATEGORIES RESOURCE
# =========================================================

@mcp.resource("expense://categories", mime_type="application/json")
async def categories():
    """Read shared categories from categories.json."""

    def read_categories():
        with CATEGORIES_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)

    return await asyncio.to_thread(read_categories)


# =========================================================
# SERVER ENTRY POINT
# =========================================================

def main():
    # Unauthenticated mode binds only to localhost.
    host = "127.0.0.1" if DEV_MODE else "0.0.0.0"

    mcp.run(
        transport="http",
        host=host,
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
