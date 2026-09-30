"""WSGI Production Entrypoint for Smart Event Registration Authenticator."""
import os
from app import app, init_db, ensure_test_images

# Initialize database schema and migrations
init_db()
ensure_test_images()

# Expose WSGI application callable for Gunicorn, Waitress, uWSGI
application = app

if __name__ == '__main__':
    from waitress import serve
    port = int(os.getenv('PORT', 5000))
    print(f"Starting production server on http://0.0.0.0:{port} via Waitress...")
    serve(application, host='0.0.0.0', port=port)
