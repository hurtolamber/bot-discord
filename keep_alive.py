# keep_alive.py
from flask import Flask
from threading import Thread
import os, logging

logging.getLogger("werkzeug").setLevel(logging.ERROR)
app = Flask(__name__)

@app.get("/")
def root():
    return "OK", 200

@app.get("/health")
def health():
    return {"status": "ok"}, 200

def _run():
    port_env = os.environ.get("PORT")
    if not port_env:
        # Pas sur Render: ne rien lancer (pour le local)
        return
    app.run(host="0.0.0.0", port=int(port_env))

def keep_alive():
    Thread(target=_run, daemon=True).start()
