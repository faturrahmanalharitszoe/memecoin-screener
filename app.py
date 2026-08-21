"""Flask entrypoint for PaaS (Render/Vercel/Heroku) - re-export dari dashboard_app.py"""
from dashboard_app import app

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
