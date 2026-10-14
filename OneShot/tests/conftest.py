import pytest
from fastapi.testclient import TestClient
from systems.api import create_app
from systems.settings import Settings
TOKEN='test_secret_key_for_oneshot_very_long_12345'
@pytest.fixture
def setup(tmp_path):
    settings=Settings(tmp_path,TOKEN)
    app=create_app(settings,auto_worker=False)
    with TestClient(app) as c:
        c.headers.update({'Authorization':'Bearer '+TOKEN})
        yield c,app
@pytest.fixture
def conversation(setup):
    c,app=setup
    resp=c.post('/api/conversations',json={'title':'session'})
    assert resp.status_code==201,resp.text
    return c,app,resp.json()['id']
