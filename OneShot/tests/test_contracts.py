from pydantic import ValidationError,TypeAdapter
import pytest
from systems.contracts import *

def test_strict_extra_discriminated():
    adapter=TypeAdapter(SourceAction)
    good=adapter.validate_python({'action':'INPUT_SOURCE','name':'project.md','content':'text'})
    assert isinstance(good,InputSource)
    with pytest.raises(ValidationError):adapter.validate_python({'action':'INPUT_SOURCE','name':'x','content':'x','role':'system'})
    with pytest.raises(ValidationError):adapter.validate_python({'action':'DELETE_SOURCE','source_id':'a'*32,'confirm_delete':False})
    with pytest.raises(ValidationError):adapter.validate_python({'action':'UNKNOWN_SOURCE','name':'a'})

def test_job_scope_strict():
    good={'operation':'auto_generate','source_ids':['a'*32],'expected_versions':{'a'*32:1},'idempotency_key':'unique-key-001','prompt_message_id':'b'*32}
    assert JobCreate.model_validate(good).source_ids
    with pytest.raises(ValidationError):JobCreate.model_validate({**good,'expected_versions':{'b'*32:1}})
    with pytest.raises(ValidationError):JobCreate.model_validate({**good,'expected_versions':{'a'*32:'1'}})
