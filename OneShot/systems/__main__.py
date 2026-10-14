"""Starts fail-closed, single-worker instance on a single host."""
import uvicorn
from systems.api import create_app
from systems.settings import Settings
if __name__=='__main__':uvicorn.run(create_app(Settings.from_env()),host='127.0.0.1',port=8787)
