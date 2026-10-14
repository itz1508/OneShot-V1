"""Prepared-context generation boundary owned by OneShot System.

This stage cannot scan, read sources, or prepare a checklist. The foreground
Worker supplies already inspected sources and a System-owned readiness decision.
"""

from dataclasses import dataclass
from systems.input_context import InputContext
from typing import Any

from capabilities.advisor.tools.checklist import Checklist
from systems.auto_generator import AutoGenerator, Generated, ProviderError
from systems.contracts import GeneratedArtifact


@dataclass(frozen=True)
class PreparedInput:
    """Result of the upstream Scan -> Read -> Prepare responsibilities."""

    sources: tuple[dict[str, Any], ...]
    checklist: Checklist
    objective: str
    context: InputContext | None = None


class Systems:
    """Named System-owned Generate stage; no intake or inspection authority."""

    def __init__(self, generator: AutoGenerator) -> None:
        self._generator = generator

    def generate(self, *, prepared_input: PreparedInput) -> Generated:
        """Generate only from admissible prepared information and validate output."""
        if not isinstance(prepared_input, PreparedInput):
            raise TypeError('Generate requires a PreparedInput from the upstream workflow')
        if not prepared_input.objective.strip():
            raise ProviderError('A prepared System objective is required')
        if not prepared_input.checklist.ready:
            raise ProviderError('Prepared context failed its readiness gate')
        args = (list(prepared_input.sources), prepared_input.checklist, prepared_input.objective)
        # Legacy direct Generate consumers remain compatible. The foreground
        # worker supplies the context snapshot when it actually prepared one.
        if prepared_input.context is None:
            generated = self._generator.run(*args)
        else:
            if prepared_input.context.objective != prepared_input.objective:
                raise ValueError('Prepared objective does not match context snapshot')
            context_sources = prepared_input.context.selected_sources
            actual_sources = tuple((item['id'], item['name'], item['version'], item['sha256'])
                                   for item in prepared_input.sources)
            if context_sources != actual_sources:
                raise ValueError('Prepared context scope does not match inspected sources')
            generated = self._generator.run(*args, context=prepared_input.context)
        # Verify the existing artifact contract without changing its wire shape.
        GeneratedArtifact.model_validate({
            'kind': generated.kind,
            'content': generated.content,
            'provider': generated.provider,
            'limitations': generated.limitations,
        })
        return generated


    def summarize(self, *, prepared_input: PreparedInput) -> Generated:
        """Summary contract is separate from the existing typed artifact path."""
        if not isinstance(prepared_input, PreparedInput):
            raise TypeError('Summary requires the prepared System input')
        if not prepared_input.objective.strip() or not prepared_input.checklist.ready:
            raise ProviderError('Summary requires a prepared, source-grounded objective')
        if prepared_input.context is not None:
            if prepared_input.context.objective != prepared_input.objective:
                raise ValueError('Summary objective conflicts with prepared context')
            identities=tuple((s['id'],s['name'],s['version'],s['sha256'])
                             for s in prepared_input.sources)
            if identities != prepared_input.context.selected_sources:
                raise ValueError('Summary scope conflicts with inspected source versions')
        result=self._generator.summarize(list(prepared_input.sources),
            prepared_input.checklist,prepared_input.objective,
            context=prepared_input.context)
        GeneratedArtifact.model_validate({'kind':result.kind,'content':result.content,
            'provider':result.provider,'limitations':result.limitations})
        return result
