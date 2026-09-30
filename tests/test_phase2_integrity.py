import sqlite3
import pytest

def test_students_table_schema_has_new_columns(app):
    """Test: Additive schema migration adds status, ocr_trans_id, trans_id_source, payment_phash, email_status, checked_in_at, ticket_secret."""
    with sqlite3.connect('students.db') as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(students)")
        columns = {row[1] for row in cursor.fetchall()}

    expected_columns = {
        'public_token',
        'status',
        'ocr_trans_id',
        'trans_id_source',
        'payment_phash',
        'email_status',
        'checked_in_at',
        'ticket_secret'
    }
    missing = expected_columns - columns
    assert not missing, f"Missing columns in students table: {missing}"
