from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence
from .records import ModelIntentRecord, ModelObservationRecord, RoutingAssessment, RoutingClassification, stable_id

@dataclass(frozen=True, slots=True)
class RoutingEvidence:
    intents: tuple[ModelIntentRecord, ...]
    observations: tuple[ModelObservationRecord, ...]

class DarioSeizer:
    """Classify structured client-visible model evidence without claiming backend attestation."""
    def assess(self, intents: Iterable[ModelIntentRecord], observations: Iterable[ModelObservationRecord], *, request_id: Optional[str]=None, prompt_id: Optional[str]=None, agent_id: Optional[str]=None, agent_name: Optional[str]=None) -> RoutingAssessment:
        intent_list = tuple(sorted(intents, key=lambda x:(x.observed_at,x.record_id)))
        obs_list = tuple(sorted(observations, key=lambda x:(x.observed_at,x.record_id)))
        scoped_i = self._scope_intents(intent_list, None, prompt_id, agent_id)
        scoped_o = self._scope_observations(obs_list, None, prompt_id, agent_id, agent_name)
        request_ids = {x.request_id for x in (*scoped_i,*scoped_o) if x.request_id}
        if request_id is None and len(request_ids) > 1:
            raise ValueError("request_id is required when assessing multiple request scopes")
        selected_request = request_id or _first(request_ids)
        selected_o = self._scope_observations(scoped_o, selected_request, prompt_id, agent_id, agent_name)
        derived_prompt = prompt_id or _first(x.prompt_id for x in selected_o)
        derived_agent = agent_id or _first(x.agent_id for x in selected_o)
        derived_name = agent_name or _first(x.agent_name for x in selected_o)
        scoped_o = self._scope_observations(selected_o, selected_request, derived_prompt, derived_agent, derived_name)
        scoped_i = self._scope_intents(intent_list, selected_request, derived_prompt, derived_agent)
        session_id = _first([x.session_id for x in scoped_o] + [x.session_id for x in scoped_i])
        prompt_id = derived_prompt or _first(x.prompt_id for x in scoped_i)
        request_id = selected_request or _first(x.request_id for x in scoped_i)
        agent_id = derived_agent or _first(x.agent_id for x in scoped_i)
        intent = scoped_i[-1] if scoped_i else None
        requested = _first(([intent.selected_model if intent else None, intent.requested_alias if intent else None] + [x.request_declared_model for x in scoped_o]))
        resolved = _first(([intent.client_resolved_model if intent else None] + [x.subagent_resolved_model for x in scoped_o] + [x.statusline_model for x in scoped_o] + [x.request_declared_model for x in scoped_o]))
        reported_values = _unique(x.response_reported_model for x in scoped_o)
        usage_values = _unique(x.usage_reported_model for x in scoped_o)
        reported = reported_values[-1] if len(reported_values)==1 else None
        usage = usage_values[-1] if len(usage_values)==1 else None
        warnings = ["backend_serving_identity_not_independently_verifiable"]
        fallback_reason = _first(x.fallback_reason for x in scoped_o)
        server_fallback = any(x.server_fallback_hop is True for x in scoped_o)
        switch_reason = intent.switch_reason if intent else None
        is_subagent = bool(agent_id) or any(_is_subagent(x) for x in scoped_o)
        if len(reported_values)>1 or len(usage_values)>1:
            classification, confidence, match = RoutingClassification.AMBIGUOUS, .35, None
            warnings.append("conflicting_reported_model_labels")
        elif fallback_reason or server_fallback:
            classification, confidence = RoutingClassification.DOCUMENTED_FALLBACK, (.95 if server_fallback else .85)
            match = _equivalent(resolved or requested, reported or usage)
            warnings.append("fallback_classification_requires_explicit_structured_signal")
        elif switch_reason and switch_reason != "subagent_model_override":
            classification, confidence = RoutingClassification.CLIENT_SWITCH, .9
            match = _equivalent(resolved or requested, reported or usage)
        elif is_subagent and (requested or resolved or reported or usage):
            classification, confidence = RoutingClassification.SUBAGENT_SCOPE, (.9 if resolved else .7)
            match = _equivalent(resolved or requested, reported or usage)
            warnings.append("subagent_model_difference_is_not_main_session_fallback")
        elif _is_alias(requested) and resolved and requested != resolved and _equivalent(requested,resolved,True):
            classification, confidence = RoutingClassification.ALIAS_RESOLUTION, .9
            match = _equivalent(resolved, reported or usage)
            warnings.append("alias_resolution_is_not_fallback")
        elif not any((requested,resolved,reported,usage)):
            classification, confidence, match = RoutingClassification.COLLECTOR_GAP, .1, None
            warnings.append("no_model_identity_evidence")
        elif reported is None and usage is None:
            classification, confidence, match = RoutingClassification.COLLECTOR_GAP, .3, None
            warnings.append("missing_response_or_usage_model_evidence")
        else:
            match = _equivalent(resolved or requested, reported or usage)
            if match is True:
                classification, confidence = RoutingClassification.EXTERNALLY_REPORTED_MATCH, (.95 if request_id else .8)
            elif match is False:
                classification, confidence = RoutingClassification.OBSERVED_MODEL_MISMATCH, .8
                warnings.append("mismatch_has_no_documented_cause")
            else:
                classification, confidence = RoutingClassification.UNVERIFIABLE_BACKEND_ROUTING, .25
        sources = tuple(dict.fromkeys([x.metadata.source for x in scoped_i] + [x.metadata.source for x in scoped_o]))
        return RoutingAssessment(
            assessment_id=stable_id("routing",session_id,prompt_id,request_id,agent_id,requested,resolved,reported,usage,classification.value),
            session_id=session_id,prompt_id=prompt_id,request_id=request_id,agent_id=agent_id,
            requested_model=requested,resolved_model=resolved,reported_model=reported,usage_model=usage,
            serving_model=None,classification=classification,confidence=confidence,evidence_sources=sources,
            externally_reported_match=match,backend_attestation_available=False,warnings=tuple(dict.fromkeys(warnings)),agent_name=derived_name,
        )
    def _scope_intents(self, items: Sequence[ModelIntentRecord], request_id, prompt_id, agent_id):
        out=list(items)
        if prompt_id is not None: out=[x for x in out if x.prompt_id==prompt_id]
        if agent_id is not None: out=[x for x in out if x.agent_id==agent_id]
        if request_id is not None:
            exact=[x for x in out if x.request_id==request_id]
            unscoped=[x for x in out if x.request_id is None]
            out=exact or unscoped
        return tuple(out)
    def _scope_observations(self, items: Sequence[ModelObservationRecord], request_id, prompt_id, agent_id, agent_name):
        out=list(items)
        if prompt_id is not None: out=[x for x in out if x.prompt_id==prompt_id]
        if agent_id is not None: out=[x for x in out if x.agent_id==agent_id]
        if agent_name is not None: out=[x for x in out if x.agent_name==agent_name]
        if request_id is not None: out=[x for x in out if x.request_id==request_id]
        return tuple(out)

class RoutingAccumulator:
    def __init__(self, engine: Optional[DarioSeizer]=None):
        self._engine=engine or DarioSeizer(); self._intents={}; self._observations={}
    def ingest_intent(self, record): self._intents[record.record_id]=record
    def ingest_observation(self, record): self._observations[record.record_id]=record
    def assessment(self, **kwargs): return self._engine.assess(self._intents.values(),self._observations.values(),**kwargs)

_MAIN={"main","primary","root"}
def _is_subagent(x):
    name=x.agent_name.strip().lower() if x.agent_name else None
    return bool((name and name not in _MAIN) or x.agent_id or x.subagent_resolved_model or x.query_source in {"agent","subagent","subagent_statusline"})
def _first(values):
    for v in values:
        if v: return v
    return None
def _unique(values): return list(dict.fromkeys(v for v in values if v))
def _is_alias(value):
    if not value: return False
    v=value.lower().strip(); return v in {"opus","sonnet","haiku","fable","best","default","inherit","opusplan"} or v.endswith("[1m]")
def _family(value):
    if not value: return None
    low=value.lower()
    if low=="opusplan": return "opusplan"
    for token in ("opus","sonnet","haiku","fable"):
        if token in low: return token
    return low
def _equivalent(left,right,allow_alias_resolution=False):
    if not left or not right: return None
    if left==right: return True
    if not allow_alias_resolution or not _is_alias(left): return False
    return _family(left)==_family(right)

__all__=["RoutingEvidence","DarioSeizer","RoutingAccumulator"]
