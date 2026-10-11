
import os
import json
import hmac
import asyncio
from pathlib import Path

import aiosqlite
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request


# ==================================================
# CONFIGURATION
# ==================================================

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "expenses.db"
CATEGORIES_PATH = BASE_DIR / "categories.json"

mcp = FastMCP("ExpenseTracker")


# ==================================================
# AUTHENTICATION
# ==================================================

def get_user_tokens():
    """
    Load bearer tokens from the environment.

    Example:
    USER_TOKENS_JSON='{"token_A":"user_A","token_B":"user_B"}'
    """
    raw = os.getenv("USER_TOKENS_JSON", "")
    if not raw:
        raise RuntimeError(
            "USER_TOKENS_JSON is not configured."
        )

    tokens = json.loads(raw)

    if not isinstance(tokens, dict) or not tokens:
        raise RuntimeError(
            "USER_TOKENS_JSON must contain a non-empty JSON object."
        )

    if not all(
        isinstance(token, str)
        and token
        and isinstance(user_id, str)
        and user_id
        for token, user_id in tokens.items()
    ):
        raise RuntimeError(
            "Each token must map to a non-empty user ID."
        )

    return tokens


def get_authenticated_user_id() -> str:
    """
    Resolve the current user from the HTTP bearer token.
    Never accept a user ID supplied as a tool argument.
    """
    request = get_http_request()
    authorization = request.headers.get("authorization", "")

    scheme, separator, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not separator or not token:
        raise PermissionError(
            "Missing or invalid bearer authentication header."
        )

    for configured_token, user_id in get_user_tokens().items():
        if hmac.compare_digest(token, configured_token):
            return user_id

    raise PermissionError("Invalid authentication token.")


# ==================================================
# DATABASE INITIALIZATION
# ==================================================

async def init_db():
    """Create the table or migrate the existing table."""

    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)

        async with db.execute("PRAGMA table_info(expenses)") as cursor:
            columns = [
                row[1] for row in await cursor.fetchall()
            ]

        # Add user_id to an existing database without deleting its data.
        if "user_id" not in columns:
            await db.execute(
                "ALTER TABLE expenses ADD COLUMN user_id TEXT"
            )

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_expenses_user_date
            ON expenses(user_id, date)
        """)

        await db.commit()


# ==================================================
# ADD EXPENSE
# ==================================================

@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = ""
):
    """Add an expense to the authenticated user's account."""

    user_id = get_authenticated_user_id()

    if amount <= 0:
        return {
            "status": "error",
            "message": "Amount must be positive."
        }

    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        cursor = await db.execute(
            """
            INSERT INTO expenses
                (user_id, date, amount, category, subcategory, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, date, amount, category, subcategory, note)
        )

        await db.commit()

        return {
            "status": "ok",
            "id": cursor.lastrowid
        }


# ==================================================
# LIST EXPENSES
# ==================================================

@mcp.tool()
async def list_expenses(start_date: str, end_date: str):
    """List the current user's expenses within an inclusive date range."""

    user_id = get_authenticated_user_id()

    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE user_id = ?
              AND date BETWEEN ? AND ?
            ORDER BY id ASC
            """,
            (user_id, start_date, end_date)
        ) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]


# ==================================================
# SUMMARIZE EXPENSES
# ==================================================

@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: str | None = None
):
    """Summarize the current user's expenses by category."""

    user_id = get_authenticated_user_id()

    query = """
        SELECT category, SUM(amount) AS total_amount
        FROM expenses
        WHERE user_id = ?
          AND date BETWEEN ? AND ?
    """

    params = [user_id, start_date, end_date]

    if category:
        query += " AND category = ?"
        params.append(category)

    query += " GROUP BY category ORDER BY category ASC"

    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]


# ==================================================
# UPDATE EXPENSE
# ==================================================

@mcp.tool()
async def update_expense(
    expense_id: int,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None = None
):
    """Update an expense belonging to the authenticated user."""

    user_id = get_authenticated_user_id()

    if amount is not None and amount <= 0:
        return {
            "status": "error",
            "message": "Amount must be positive."
        }

    fields = {
        "date": date,
        "amount": amount,
        "category": category,
        "subcategory": subcategory,
        "note": note
    }

    updates = []
    params = []

    for field, value in fields.items():
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if not updates:
        return {
            "status": "error",
            "message": "No fields provided to update."
        }

    params.extend([expense_id, user_id])

    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        cursor = await db.execute(
            f"""
            UPDATE expenses
            SET {", ".join(updates)}
            WHERE id = ? AND user_id = ?
            """,
            params
        )

        await db.commit()

        if cursor.rowcount == 0:
            return {
                "status": "error",
                "message": "Expense not found for this user."
            }

        return {
            "status": "ok",
            "message": "Expense updated successfully."
        }


# ==================================================
# DELETE EXPENSE
# ==================================================

@mcp.tool()
async def delete_expense(expense_id: int):
    """Delete an expense belonging to the authenticated user."""

    user_id = get_authenticated_user_id()

    async with aiosqlite.connect(DB_PATH, timeout=10) as db:
        cursor = await db.execute(
            """
            DELETE FROM expenses
            WHERE id = ? AND user_id = ?
            """,
            (expense_id, user_id)
        )

        await db.commit()

        if cursor.rowcount == 0:
            return {
                "status": "error",
                "message": "Expense not found for this user."
            }

        return {
            "status": "ok",
            "message": "Expense deleted successfully."
        }


# ==================================================
# CATEGORIES RESOURCE
# ==================================================

@mcp.resource("expense://categories", mime_type="application/json")
async def categories():
    """Return the current contents of categories.json."""

    return await asyncio.to_thread(
        CATEGORIES_PATH.read_text,
        encoding="utf-8"
    )


# ==================================================
# START SERVER
# ==================================================

if __name__ == "__main__":
    asyncio.run(init_db())

    mcp.run(
        transport="http",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8000"))
    )
