
import asyncio
import os
from contextlib import asynccontextmanager

import aiosqlite
from fastmcp import FastMCP


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "expenses.db")
CATEGORIES_PATH = os.path.join(BASE_DIR, "categories.json")

DB_TIMEOUT = 10.0


async def init_db():
    """Initialize the database asynchronously during application startup."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
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
        await db.commit()


@asynccontextmanager
async def app_lifespan(server):
    """Initialize the database before accepting requests."""
    await init_db()
    yield {}


mcp = FastMCP("ExpenseTracker", lifespan=app_lifespan)


@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
):
    """Add a new expense entry to the database."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            """
            INSERT INTO expenses
                (date, amount, category, subcategory, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (date, amount, category, subcategory, note),
        )
        await db.commit()
        expense_id = cursor.lastrowid
        await cursor.close()

    return {"status": "ok", "id": expense_id}


@mcp.tool()
async def list_expenses(start_date: str, end_date: str):
    """List expenses within an inclusive date range."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE date BETWEEN ? AND ?
            ORDER BY id ASC
            """,
            (start_date, end_date),
        ) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]


@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: str | None = None,
):
    """Summarize expenses by category within an inclusive date range."""
    query = """
        SELECT category, SUM(amount) AS total_amount
        FROM expenses
        WHERE date BETWEEN ? AND ?
    """
    params = [start_date, end_date]

    if category:
        query += " AND category = ?"
        params.append(category)

    query += " GROUP BY category ORDER BY category ASC"

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]


@mcp.tool()
async def update_expense(
    expense_id: int,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None = None,
):
    """Update specified fields of an existing expense."""
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
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if not updates:
        return {
            "status": "error",
            "message": "No fields provided to update",
        }

    params.append(expense_id)
    query = (
        f"UPDATE expenses SET {', '.join(updates)} WHERE id = ?"
    )

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(query, params)
        await db.commit()
        affected = cursor.rowcount
        await cursor.close()

    if affected == 0:
        return {
            "status": "error",
            "message": f"Expense ID {expense_id} not found",
        }

    return {
        "status": "ok",
        "message": f"Expense {expense_id} updated successfully",
    }


@mcp.tool()
async def delete_expense(expense_id: int):
    """Delete an expense entry using its ID."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            "DELETE FROM expenses WHERE id = ?",
            (expense_id,),
        )
        await db.commit()
        affected = cursor.rowcount
        await cursor.close()

    if affected == 0:
        return {
            "status": "error",
            "message": f"Expense ID {expense_id} not found",
        }

    return {
        "status": "ok",
        "message": f"Expense {expense_id} deleted successfully",
    }


@mcp.resource("expense://categories", mime_type="application/json")
async def categories():
    """Read the current categories JSON file without blocking the event loop."""
    def read_categories():
        with open(CATEGORIES_PATH, "r", encoding="utf-8") as file:
            return file.read()

    return await asyncio.to_thread(read_categories)


def main():
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
