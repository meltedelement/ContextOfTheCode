"""
PythonAnywhere WSGI configuration file.

HOW TO DEPLOY:
1. Upload the entire project to PythonAnywhere (e.g. via git clone or zip upload)
2. In the PythonAnywhere Web tab, set the WSGI configuration file path to this file
3. Fill in the four YOURUSERNAME / YOURPASSWORD / YOURDBNAME placeholders below
4. In the PythonAnywhere Web tab, set the virtualenv path if using one
5. Run `pip install -r requirements.txt` in a PythonAnywhere Bash console
6. Reload the web app

DATABASE SETUP (one-time, in a PythonAnywhere Bash console):
    mysql -u YOURUSERNAME -p -h YOURUSERNAME.mysql.pythonanywhere-services.com
    CREATE DATABASE `YOURUSERNAME$metrics`;
    exit
    Tables are created automatically by SQLAlchemy on first request.
"""

import sys
import os

# Absolute path to the project root on PythonAnywhere
# Adjust if you cloned to a different location
PROJECT_HOME = '/home/YOURUSERNAME/Context-of-the-code-project'

if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# Database connection — get these values from the PythonAnywhere "Databases" tab
os.environ.setdefault('DATABASE_URL', (
    'mysql+pymysql://'
    'YOURUSERNAME:YOURPASSWORD'
    '@YOURUSERNAME.mysql.pythonanywhere-services.com'
    '/YOURUSERNAME$YOURDBNAME'
))

# FLASK_DEBUG must not be "true" in production
os.environ.setdefault('FLASK_DEBUG', 'false')

from server.app import app as application  # noqa: E402 — must be after sys.path setup
