"""Only API/record wire shapes. Models are strict and closed, no implicit coercion.

Every field carries an attribute docstring; combined with
``use_attribute_docstrings=True`` on the base ``Contract`` these flow into
``/openapi.json`` as per-field ``description`` entries.
``tests/test_contracts_documented.py`` is the enforcement gate.
"""
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

class Contract(BaseModel):
    """Base for every API/record wire shape — closed, strict, docstring-aware."""

    model_config = ConfigDict(extra='forbid', strict=True, use_attribute_docstrings=True)

ID = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{32}$')]
Name = Annotated[str, StringConstraints(min_length=1, max_length=240)]
Hash = Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{64}$')]

class InputSource(Contract):
    """Attach a new source whose bytes are a UTF-8 string body."""

    action: Literal['INPUT_SOURCE']
    """Discriminator; selects this variant of SourceAction."""
    name: Name
    """User-visible logical name; stable after creation."""
    content: Annotated[str, StringConstraints(max_length=1_000_000)]
    """Original source bytes as a UTF-8 string; stored content-addressed by SHA-256."""

class ImportSource(Contract):
    """Attach a new binary source whose bytes are base64-encoded."""

    action: Literal['IMPORT_SOURCE']
    """Discriminator."""
    name: Name
    """User-visible logical name."""
    content_base64: str = Field(max_length=1_400_000)
    """Base64-encoded original bytes; capped at ~1 MB after decoding."""

class AddSource(Contract):
    """Attach an existing source to this conversation."""

    action: Literal['ADD_SOURCE']
    """Discriminator."""
    source_id: ID
    """Hex id of a source already stored for this operator."""

class ReferenceSource(Contract):
    """Register a bounded HTTPS URL reference for later retrieval."""

    action: Literal['REFERENCE_SOURCE']
    """Discriminator."""
    name: Name
    """User-visible logical name for the reference."""
    url: Annotated[str, StringConstraints(min_length=9,max_length=2048)]
    """Public HTTPS URL; validated by capabilities.researcher.validate_url."""

class RemoveSource(Contract):
    """Detach a source from this conversation; original bytes stay on disk."""

    action: Literal['REMOVE_SOURCE']
    """Discriminator."""
    source_id: ID
    """Hex id of the source link to remove from this conversation."""

class DeleteSource(Contract):
    """Delete a source irrevocably — operator must set confirm_delete=True."""

    action: Literal['DELETE_SOURCE']
    """Discriminator."""
    source_id: ID
    """Hex id of the source to delete."""
    confirm_delete: Literal[True]
    """Mandatory explicit confirmation; a literal True guards against accidental deletion."""

SourceAction = Annotated[Union[InputSource,ImportSource,AddSource,ReferenceSource,RemoveSource,DeleteSource], Field(discriminator='action')]

class ConversationCreate(Contract):
    """POST /api/conversations body."""

    title: Name = 'New conversation'
    """Human-readable title; default lets the operator create without a payload."""

class SessionChange(Contract):
    """PATCH /api/conversations/{cid}/session body."""

    agent_active: bool
    """Whether the Agent chat owns this conversation; blocks System mutations while true."""

class MessageCreate(Contract):
    """POST /api/conversations/{cid}/messages body."""

    idempotency_key: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{6,128}$')] | None = None
    """Optional retry key; identical submissions commit exactly once."""
    channel: Literal['agent','system']
    """Message channel; ``agent`` requires a configured Agent reply operation."""
    content: Annotated[str, StringConstraints(min_length=1,max_length=100_000)]
    """Message body; preserved verbatim including whitespace."""

class AgentReply(Contract):
    """Bounded optional Agent request; source scope is not implicitly forwarded."""

    provider: Literal['openai', 'gemini', 'ollama']
    """Which configured Agent integration should handle this request."""
    content: Annotated[str, StringConstraints(min_length=1, max_length=20000)]
    """User message to the Agent; bounded size for provider cost."""
    idempotency_key: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{6,128}$')]
    """Mandatory retry key; identical request + provider replays return the same reply pair."""

class JobCreate(Contract):
    """POST /api/conversations/{cid}/jobs body — admits a scoped processing job."""

    operation: Literal['auto_generate','inspect_sources','summarize']
    """Which System operation to run against the scoped sources."""
    prompt_message_id: ID
    """Id of an existing persisted System message that supplies the objective."""
    source_ids: list[ID] = Field(min_length=1,max_length=50)
    """Hex ids of the attached sources this job will process; unique and non-empty."""
    expected_versions: dict[str,int]
    """Version each source must still be at when the job commits; prevents stale admissions."""
    idempotency_key: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{6,128}$')]
    """Mandatory retry key; two identical scopes with the same key return the same job id."""
    prompt_asset_id: ID | None = None
    """Optional prompt asset to freeze onto this job (requires prompt_version)."""
    prompt_version: int | str | None = None
    """Prompt version to freeze: integer version_number, hex version id, or 'latest'."""
    prompt_values: dict[str, str] | None = None
    """${name} values resolved and persisted into resolved_variables_json."""
    @model_validator(mode='after')
    def consistent(self):
        if len(set(self.source_ids))!=len(self.source_ids):raise ValueError('Duplicate IDs')
        if set(self.source_ids)!=set(self.expected_versions):raise ValueError('Version keys must match scope')
        if any(isinstance(v,bool) or v<1 for v in self.expected_versions.values()):raise ValueError('Versions must be positive')
        return self

class DraftCreate(Contract):
    """POST /api/conversations/{cid}/drafts body."""

    source_id: ID
    """Hex id of the source this draft refines; original source bytes stay immutable."""
    content: Annotated[str, StringConstraints(max_length=1_000_000)]
    """Initial draft body; stored separately from the original source bytes."""

class DraftUpdate(Contract):
    """PATCH /api/conversations/{cid}/drafts/{did} body."""

    expected_revision: int = Field(ge=1)
    """Revision the client last saw; mismatch returns 409 to prevent lost-update."""
    content: Annotated[str, StringConstraints(max_length=1_000_000)]
    """Replacement draft body; whitespace preserved verbatim."""

class PrepareApply(Contract):
    """POST /api/conversations/{cid}/apply/prepare body."""

    artifact_id: ID
    """Hex id of the generated artifact that will be written to disk on confirm."""
    destination: Annotated[str, StringConstraints(min_length=1,max_length=240)]
    """Relative path under ONESHOT_DATA_DIR/applied; path-traversal guarded."""
    expected_target_sha256: Hash | None = None
    """Optional pre-image hash; present when overwriting a known file, absent on first write."""

class ConfirmApply(Contract):
    """POST /api/conversations/{cid}/apply/confirm body."""

    confirmation_token: ID
    """Hex token returned by /apply/prepare; single-use."""
    confirm_apply: Literal[True]
    """Mandatory explicit confirmation; a literal True guards against accidental writes."""

class GeneratedDocument(Contract):
    """Internal shape for a prepared evidence document before it is persisted as an artifact."""

    document: Annotated[str, StringConstraints(min_length=1,max_length=500_000)]
    """Prepared document body; preserved verbatim so headings and fences stay intact."""
    source_ids_used: list[ID] = Field(min_length=1,max_length=50)
    """Ids of the sources the document was built from; each used source is recorded exactly once."""
    @model_validator(mode='after')
    def unique_ids(self):
        if len(set(self.source_ids_used))!=len(self.source_ids_used):raise ValueError('Duplicate source usage')
        return self


class SummaryOutput(Contract):
    """Operation-specific summary-only output.json contract."""

    summary: Annotated[str, StringConstraints(min_length=1, max_length=100_000)]
    """Model-produced summary text; non-blank required."""

    @model_validator(mode='after')
    def nonblank(self):
        if not self.summary.strip():
            raise ValueError('A summary must contain non-whitespace text')
        return self


class GeneratedArtifact(Contract):
    """Validated existing artifact shape, distinct from a future output.json contract."""

    kind: Literal['evidence_packet', 'model_generated', 'summary']
    """Which generator produced this artifact; evidence_packet is source-grounded, deterministic."""
    content: Annotated[str, StringConstraints(min_length=1)]
    """Rendered artifact body; preserved verbatim."""
    provider: Literal['evidence', 'model']
    """Provider that produced the artifact; must match ``kind`` (evidence <-> evidence_packet)."""
    limitations: tuple[str, ...]
    """Explicit, operator-facing limitations recorded with the artifact (never silently swallowed)."""

    @model_validator(mode='after')
    def matching_mode(self):
        expected = 'evidence' if self.kind == 'evidence_packet' else 'model'
        if self.provider != expected:
            raise ValueError('Generated artifact kind/provider mismatch')
        return self


class ArtifactEvidenceSource(Contract):
    """One source contributing to a generated artifact's evidence bundle."""

    source_id: ID
    """Hex id of the contributing source."""
    name: Name
    """Logical name of the source at the time the artifact was produced."""
    version: int = Field(ge=1)
    """Immutable version the artifact was computed from."""
    sha256: Hash
    """SHA-256 of the original source bytes, independently recorded on the artifact."""
    available: bool
    """Whether those bytes are still readable on disk; false flags a storage incident."""


class ArtifactEvidenceBundle(Contract):
    """GET /api/conversations/{cid}/artifacts/{aid}/evidence response body."""

    artifact_id: ID
    """Hex id of the artifact this bundle belongs to."""
    sources: list[ArtifactEvidenceSource]
    """Every source used to produce the artifact, with hash + version + availability."""


class ArtifactExportRecord(Contract):
    """Typed provenance export, deliberately not summary-only output.json."""

    artifact_id: ID
    """Hex id of the exported artifact."""
    job_id: ID
    """Hex id of the job that produced it; immutable for the export's lifetime."""
    kind: Literal['evidence_packet', 'model_generated', 'summary']
    """Generator kind at the time of export."""
    provider: Literal['evidence', 'model']
    """Provider at the time of export; must match ``kind``."""
    content: Annotated[str, StringConstraints(min_length=1)]
    """Rendered artifact body preserved verbatim."""
    limitations: list[str]
    """Operator-facing limitations recorded alongside the content."""
    sources: list[ArtifactEvidenceSource]
    """Evidence bundle included in the export — SHA-256, name, version, availability per source."""



class PromptVariableDefinition(Contract):
    """Operator-approved variable definition for ${name} resolution."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')]
    """Variable identifier used by ${name} tokens."""
    required: bool = True
    """Operator must supply a value at resolution."""
    description: Annotated[str, StringConstraints(max_length=400)] = ''
    """Short, non-authoritative explanation shown to the operator."""
    max_length: int = Field(default=10_000, ge=1, le=100_000)
    """Upper bound on supplied value length."""


class PromptAssetCreate(Contract):
    """Create a new prompt asset with an initial editable draft."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=120)] = Field(description="Human name; unique within the conversation.")
    content: Annotated[str, StringConstraints(min_length=1, max_length=200_000)] = Field(description="Initial draft content; may reference ${var} tokens.")
    variables: list[PromptVariableDefinition] = Field(default_factory=list, description="Declared variable definitions for the draft.")


class PromptDraftUpdate(Contract):
    """Save the current editable draft (does not publish)."""

    content: Annotated[str, StringConstraints(min_length=1, max_length=200_000)] = Field(description="New draft content; must reference only declared variables.")
    variables: list[PromptVariableDefinition] = Field(default_factory=list, description="Updated variable definitions.")
    expected_revision: int | None = Field(default=None, description="Last-seen revision; conflict (409) when stale.")


class PromptPublish(Contract):
    """Freeze the current draft into a new immutable version."""

    expected_revision: int | None = Field(default=None, description="Last-seen draft revision to publish; 409 on conflict.")


class PromptRestore(Contract):
    """Create a new version whose content copies the referenced historical one."""

    version: int | str = Field(description="A version_number (int) or a version id (hex string).")


class PromptResolve(Contract):
    """Resolve a published version against variable values (does NOT execute)."""

    version: int | str = Field(default='latest', description="'latest', an int version_number, or a version id.")
    values: dict[str, str] = Field(default_factory=dict, description="Variable name -> operator-supplied value.")


class PromptEvaluationCreate(Contract):
    """Queue a structural evaluation of a published version against criteria."""

    version: int | str = Field(default='latest', description="Version to evaluate.")
    criteria: list[dict] = Field(default_factory=list, description="List of structural checks (kind + arguments).")


class PromptOptimizeRequest(Contract):
    """Ask the configured provider to propose an advisory improvement."""

    version: int | str | None = Field(default=None, description="Version to optimize; omit to optimize the current draft.")



class JobReviewBody(Contract):
    """Operator feedback on a committed terminal job (directive §4-B / §6)."""

    decision: Literal['observed_defect','reviewer_expectation','potential_defect','unresolved_decision'] = Field(
        description="Reviewer's claim about the job: an observed defect, a stated expectation, a hypothesis, or an unresolved product decision.")
    required: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description='Required observed behaviour (what the output should have had).')
    prohibited: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description='Prohibited unsupported behaviour (what the output must not claim).')
    reason: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description="Reviewer\'s rationale.")
    limitations: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description='Known limitations the reviewer is aware of.')
    evidence_source_ids: list[ID] = Field(
        default_factory=list,
        description='Source ids in this conversation that support the finding.')
    expected_revision: int | None = Field(
        default=None,
        description='Last-seen review revision; 409 on conflict to prevent silent overwrites.')


class JobEvaluationBody(Contract):
    """Create a job-level evaluation from a review (directive §8)."""

    review_id: ID | None = Field(default=None,
        description='Optional review that motivated this evaluation.')
    status: Literal['proposed','approved'] = Field(default='proposed',
        description="Initial state; approval is a separate transition.")
    criteria: list[dict] = Field(default_factory=list,
        description='Structural criteria (kind + arguments) exercised against the artifact.')


class ImprovementProposalBody(Contract):
    """Advisory correction package (directive §11)."""

    issue_summary: Annotated[str, StringConstraints(min_length=1, max_length=1000)] = Field(
        description='One-sentence statement of the observed issue.')
    affected_responsibility: Annotated[str, StringConstraints(min_length=1, max_length=160)] = Field(
        description='Which System responsibility is affected (e.g. "prompt resolution", "quality check").')
    current_behavior: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description='What the system does today.')
    required_behavior: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description='What the system should do.')
    proposed_correction: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description='Smallest justified change required.')
    risks: Annotated[str, StringConstraints(max_length=4000)] = Field(
        default='', description='Known risks and possible regressions.')
    evidence: dict = Field(default_factory=dict,
        description='Evidence envelope: {job_ids:[], review_ids:[], issue_codes:[]} scoped to this conversation.')
