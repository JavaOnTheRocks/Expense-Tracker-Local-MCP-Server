import asyncio
import hashlib
import json
import math
import os
import re
from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path

import aiosqlite
from fastmcp import FastMCP


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

# Cloud containers should use a writable directory, not the source-code folder.
# Set EXPENSE_DB_DIR only if your hosting platform provides a persistent,
# writable mounted directory. Otherwise /tmp is a suitable writable location
# for a hackathon smoke test (but its contents may be lost on restart).
DB_DIR = Path(os.environ.get("EXPENSE_DB_DIR", "/tmp/expense-tracker")).expanduser()
DB_PATH = DB_DIR / "expenses.db"
CATEGORIES_PATH = BASE_DIR / "categories.json"
DB_TIMEOUT = 10.0


def prepare_db_directory() -> None:
    """Create and verify the directory used by SQLite."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_DIR.is_dir():
        raise RuntimeError(f"Expense database path is not a directory: {DB_DIR}")


# =========================================================
# USER TABLE MANAGEMENT
# =========================================================

def validate_user_id(user_id: str) -> str:
    """Validate a user identifier."""

    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string.")

    if len(user_id) > 200:
        raise ValueError("user_id cannot exceed 200 characters.")

    return user_id.strip()


def get_user_table(user_id: str) -> str:
    """
    Generate a deterministic SQLite table name for a user.

    Hashing avoids unsafe SQL identifiers and prevents raw user IDs
    from appearing in table names.
    """

    user_id = validate_user_id(user_id)

    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    return f"expenses_{digest}"


async def ensure_user_table(db: aiosqlite.Connection, user_id: str):
    """Create the user's table if it does not already exist."""

    table = get_user_table(user_id)

    # The table name contains only a fixed prefix and SHA-256 hex.
    await db.execute(f"""
        CREATE TABLE IF NOT EXISTS "{table}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT DEFAULT '',
            note TEXT DEFAULT ''
        )
    """)

    await db.execute(f"""
        CREATE INDEX IF NOT EXISTS "idx_{table}_date"
        ON "{table}" (date)
    """)

    return table


async def init_db():
    """Create the writable database directory and initialize SQLite."""
    prepare_db_directory()

    # Use SQLite's default journal mode for better compatibility with
    # constrained/ephemeral cloud filesystems. WAL can require sidecar files.
    async with aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("SELECT 1")
        await db.commit()


# =========================================================
# APPLICATION LIFESPAN
# =========================================================

@asynccontextmanager
async def app_lifespan(server):
    await init_db()
    yield {}


# =========================================================
# MCP SERVER
# =========================================================

mcp = FastMCP(
    "ExpenseTracker",
    lifespan=app_lifespan,
)


# =========================================================
# INPUT VALIDATION
# =========================================================

def validate_date(value: str, field_name: str = "date") -> str:
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


def validate_date_range(start_date: str, end_date: str):
    validate_date(start_date, "start_date")
    validate_date(end_date, "end_date")

    if start_date > end_date:
        raise ValueError(
            "start_date must be on or before end_date."
        )


def validate_amount(amount: float) -> float:
    if isinstance(amount, bool) or not isinstance(
        amount, (int, float)
    ):
        raise ValueError("Amount must be a number.")

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
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")

    value = value.strip()

    if len(value) > max_length:
        raise ValueError(
            f"{field_name} cannot exceed {max_length} characters."
        )

    return value


# =========================================================
# ADD EXPENSE
# =========================================================

@mcp.tool()
async def add_expense(
    user_id: str,
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
):
    """Add an expense to the specified user's separate table."""

    user_id = validate_user_id(user_id)
    date = validate_date(date)
    amount = validate_amount(amount)

    category = validate_text(category, "category", 100)
    subcategory = validate_text(subcategory, "subcategory", 100)
    note = validate_text(note, "note", 2000)

    if not category:
        raise ValueError("Category cannot be empty.")

    async with aiosqlite.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
    ) as db:
        table = await ensure_user_table(db, user_id)

        async with db.execute(f"""
            INSERT INTO "{table}"
                (date, amount, category, subcategory, note)
            VALUES (?, ?, ?, ?, ?)
        """, (
            date,
            amount,
            category,
            subcategory,
            note,
        )) as cursor:
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
async def list_expenses(
    user_id: str,
    start_date: str,
    end_date: str,
):
    """List expenses from the specified user's separate table."""

    user_id = validate_user_id(user_id)
    validate_date_range(start_date, end_date)

    async with aiosqlite.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
    ) as db:
        table = await ensure_user_table(db, user_id)
        db.row_factory = aiosqlite.Row

        async with db.execute(f"""
            SELECT id, date, amount, category, subcategory, note
            FROM "{table}"
            WHERE date BETWEEN ? AND ?
            ORDER BY date ASC, id ASC
        """, (start_date, end_date)) as cursor:
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


# =========================================================
# SUMMARIZE EXPENSES
# =========================================================

@mcp.tool()
async def summarize(
    user_id: str,
    start_date: str,
    end_date: str,
    category: str | None = None,
):
    """Summarize expenses from the specified user's table."""

    user_id = validate_user_id(user_id)
    validate_date_range(start_date, end_date)

    query = f"""
        SELECT category, SUM(amount) AS total_amount
        FROM "{{table}}"
        WHERE date BETWEEN ? AND ?
    """

    params = [start_date, end_date]

    if category is not None:
        category = validate_text(category, "category", 100)
        query += " AND category = ?"
        params.append(category)

    query += " GROUP BY category ORDER BY category ASC"

    async with aiosqlite.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
    ) as db:
        table = await ensure_user_table(db, user_id)

        # Only the generated table name is interpolated into SQL.
        query = query.format(table=table)

        db.row_factory = aiosqlite.Row

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


# =========================================================
# UPDATE EXPENSE
# =========================================================

@mcp.tool()
async def update_expense(
    user_id: str,
    expense_id: int,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None = None,
):
    """Update an expense only in the specified user's table."""

    user_id = validate_user_id(user_id)

    if isinstance(expense_id, bool) or not isinstance(
        expense_id, int
    ):
        raise ValueError("expense_id must be an integer.")

    if expense_id <= 0:
        raise ValueError("expense_id must be positive.")

    updates = []
    params = []

    if date is not None:
        updates.append("date = ?")
        params.append(validate_date(date))

    if amount is not None:
        updates.append("amount = ?")
        params.append(validate_amount(amount))

    if category is not None:
        category = validate_text(category, "category", 100)

        if not category:
            raise ValueError("Category cannot be empty.")

        updates.append("category = ?")
        params.append(category)

    if subcategory is not None:
        updates.append("subcategory = ?")
        params.append(
            validate_text(subcategory, "subcategory", 100)
        )

    if note is not None:
        updates.append("note = ?")
        params.append(validate_text(note, "note", 2000))

    if not updates:
        return {
            "status": "error",
            "message": "No fields provided to update.",
        }

    params.append(expense_id)

    async with aiosqlite.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
    ) as db:
        table = await ensure_user_table(db, user_id)

        query = (
            f'UPDATE "{table}" '
            f'SET {", ".join(updates)} WHERE id = ?'
        )

        async with db.execute(query, params) as cursor:
            affected = cursor.rowcount

        await db.commit()

    if affected == 0:
        return {
            "status": "error",
            "message": "Expense not found in this user's table.",
        }

    return {
        "status": "ok",
        "message": f"Expense {expense_id} updated successfully.",
    }


# =========================================================
# DELETE EXPENSE
# =========================================================

@mcp.tool()
async def delete_expense(
    user_id: str,
    expense_id: int,
):
    """Delete an expense only from the specified user's table."""

    user_id = validate_user_id(user_id)

    if isinstance(expense_id, bool) or not isinstance(
        expense_id, int
    ):
        raise ValueError("expense_id must be an integer.")

    if expense_id <= 0:
        raise ValueError("expense_id must be positive.")

    async with aiosqlite.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
    ) as db:
        table = await ensure_user_table(db, user_id)

        async with db.execute(
            f'DELETE FROM "{table}" WHERE id = ?',
            (expense_id,),
        ) as cursor:
            affected = cursor.rowcount

        await db.commit()

    if affected == 0:
        return {
            "status": "error",
            "message": "Expense not found in this user's table.",
        }

    return {
        "status": "ok",
        "message": f"Expense {expense_id} deleted successfully.",
    }


# =========================================================
# CATEGORIES RESOURCE
# =========================================================

@mcp.resource(
    "expense://categories",
    mime_type="application/json",
)
async def categories():
    """Read categories.json without blocking the event loop."""

    def read_categories():
        with open(CATEGORIES_PATH, "r", encoding="utf-8") as file:
            return json.load(file)

    return await asyncio.to_thread(read_categories)


# =========================================================
# SERVER ENTRY POINT
# =========================================================

def main():
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
