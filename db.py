# Standard library imports
import os
from pathlib import Path
import uuid
import secrets

# Third-party imports
import apsw
import apsw.bestpractice
from fastmigrate.core import create_db, run_migrations
from fastcore.all import dict2obj

# Apply recommended best practices for APSW
apsw.bestpractice.apply(apsw.bestpractice.recommended)

# Set DB path depending on environment
db_path = Path("data/forward-x402-prod.db") if os.environ.get("PLASH_PRODUCTION") == "1" else Path("data/forward-x402.db")
db_path.parent.mkdir(parents=True, exist_ok=True)
migrations_dir = "migrations"

# Create DB and run migrations
current_version = create_db(db_path)
print(f"DB initialized. Current version: {current_version}")
success = run_migrations(db_path, migrations_dir, verbose=False)
if not success:
    raise Exception("Database migration failed!")

# Database connection
conn = apsw.Connection(str(db_path))


# --- User Functions ---

def ensure_user(user_id, email, name, picture):
    """Insert user if not exists."""
    cur = conn.cursor()
    print(f"Ensuring user {user_id=} {email=} {name=} {picture=}")
    cur.execute(
        "INSERT OR IGNORE INTO users (id, email, name, picture) VALUES (?, ?, ?, ?)",
        (user_id, email, name, picture)
    )
    return cur.getconnection().last_insert_rowid()


def get_user(user_id):
    """Fetch user by ID."""
    cur = conn.cursor()
    cur.execute("SELECT id, email, name, picture FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    return dict2obj({"id": row[0], "email": row[1], "name": row[2], "picture": row[3]})


# --- Email Endpoint Functions ---

def create_email_endpoint(user_id, email, label, base_price):
    """Create a new email endpoint."""
    cur = conn.cursor()
    endpoint_id = str(uuid.uuid4())
    short_url = secrets.token_urlsafe(8)
    cur.execute("""
        INSERT INTO email_endpoints (id, user_id, email, label, short_url, base_price)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (endpoint_id, user_id, email, label, short_url, int(base_price * 1_000_000)))
    return endpoint_id


def list_endpoints_by_user(user_id):
    """List all endpoints for a user."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, email, label, short_url, base_price, is_active, hit_count, payment_count, created_at
        FROM email_endpoints WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))
    return [
        dict2obj({
            "id": row[0], "user_id": row[1], "email": row[2], "label": row[3],
            "short_url": row[4], "base_price": row[5] / 1_000_000, "is_active": row[6],
            "hit_count": row[7], "payment_count": row[8], "created_at": row[9]
        })
        for row in cur.fetchall()
    ]


def get_endpoint_by_short_url(short_url):
    """Get endpoint by short URL (only active ones)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, email, label, short_url, base_price, is_active, hit_count, payment_count, created_at
        FROM email_endpoints
        WHERE short_url = ? AND is_active = TRUE
    """, (short_url,))
    row = cur.fetchone()
    if not row:
        return None
    return dict2obj({
        "id": row[0], "user_id": row[1], "email": row[2], "label": row[3],
        "short_url": row[4], "base_price": row[5] / 1_000_000, "is_active": row[6],
        "hit_count": row[7], "payment_count": row[8], "created_at": row[9]
    })


def update_hit_count(endpoint_id):
    """Increment hit count for an endpoint."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE email_endpoints SET hit_count = hit_count + 1 WHERE id = ?
    """, (endpoint_id,))


def update_pay_count(endpoint_id):
    """Increment payment count for an endpoint."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE email_endpoints SET payment_count = payment_count + 1 WHERE id = ?
    """, (endpoint_id,))
