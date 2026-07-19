from __future__ import annotations
from datetime import datetime
from typing import Any, Mapping, Optional
from ..records import CollectorBatch, EvidenceLevel, ModelObservationRecord, RateLimitWindow, SourceKind, StatusSnapshot, VersionBoundary, stable_id, utc_now
from ..versioning import version_allows
from ._common import as_float, first, make_metadata, official_evidence, parse_timestamp, string

_SUBAGENT_MODEL_BOUNDARY=VersionBoundary(min_inclusive="2.1.205",max_exclusive="3.0.0")
class ClaudeStatusLineAdapter:
    def parse_main(self,payload: Mapping[str,Any],*,collected_at: Optional[datetime]=None)->CollectorBatch:
        observed=collected_at or utc_now(); version=string(payload.get("version")); source=SourceKind.CLAUDE_STATUSLINE
        session=string(payload.get("session_id")); prompt=string(payload.get("prompt_id")); model=string(first(payload,"model.id","model.display_name"))
        workspace=payload.get("workspace") if isinstance(payload.get("workspace"),Mapping) else {}; repo=workspace.get("repo") if isinstance(workspace.get("repo"),Mapping) else {}; pr=payload.get("pr") if isinstance(payload.get("pr"),Mapping) else {}; context=payload.get("context_window") if isinstance(payload.get("context_window"),Mapping) else {}; cost=payload.get("cost") if isinstance(payload.get("cost"),Mapping) else {}; agent=payload.get("agent") if isinstance(payload.get("agent"),Mapping) else {}
        evidence={
            "model.id":official_evidence(source,version,note="documented status-line path; client-visible model label, not serving attestation"),
            "workspace.repo.host":official_evidence(source,version,note="documented status-line path"),
            "workspace.repo.owner":official_evidence(source,version,note="documented status-line path"),
            "workspace.repo.name":official_evidence(source,version,note="documented status-line path"),
            "pr.number":official_evidence(source,version,note="documented status-line path"),
            "pr.url":official_evidence(source,version,note="documented status-line path"),
            "pr.review_state":official_evidence(source,version,note="documented status-line path"),
            "context_window":official_evidence(source,version,note="documented status-line object"),
            "rate_limits":official_evidence(source,version,note="documented status-line object"),
        }
        metadata=make_metadata(source,source_version=version,collected_at=observed,field_evidence=evidence,warnings=("statusline_model_is_not_backend_serving_attestation",) if model else ())
        snapshot=StatusSnapshot(stable_id("status",source.value,session,prompt,observed.isoformat()),observed,session,prompt,"main",None,model,string(repo.get("host")),string(repo.get("owner")),string(repo.get("name")),_optional_int(pr.get("number")),string(pr.get("url")),string(pr.get("review_state")),_optional_int(context.get("context_window_size")),as_float(context.get("used_percentage")),_windows(payload.get("rate_limits")),string(payload.get("permission_mode")),string(agent.get("name")),as_float(cost.get("total_cost_usd")),0,metadata)
        records=[snapshot]
        if model:
            records.append(ModelObservationRecord(stable_id("modelobs",source.value,session,prompt,observed.isoformat(),model),observed,session,prompt,None,None,None,"statusline",None,None,None,model,None,None,"fast" if payload.get("fast_mode") is True else None,_effort(payload.get("effort")),None,None,None,EvidenceLevel.OFFICIAL_SUPPORTED,metadata,string(agent.get("name"))))
        return CollectorBatch(tuple(records))
    def parse_subagents(self,payload: Mapping[str,Any],*,collected_at: Optional[datetime]=None)->CollectorBatch:
        observed=collected_at or utc_now(); version=string(payload.get("version")); source=SourceKind.CLAUDE_SUBAGENT_STATUSLINE; session=string(payload.get("session_id")); prompt=string(payload.get("prompt_id")); tasks=payload.get("tasks") if isinstance(payload.get("tasks"),list) else []
        warnings=[]; records=[]
        for task in tasks:
            if not isinstance(task,Mapping): warnings.append("subagent_statusline_task_not_object"); continue
            agent_id=string(task.get("id")); model=string(task.get("model")); cws=_optional_int(task.get("contextWindowSize"))
            if (model is not None or cws is not None) and not version_allows(version,_SUBAGENT_MODEL_BOUNDARY):
                warnings.append("subagent_model_fields_ignored_before_2.1.205_or_unknown_version"); model=None; cws=None
            evidence={"tasks":official_evidence(source,version,note="documented subagent status-line task array")}
            if model is not None: evidence["tasks.model"]=official_evidence(source,version,min_version="2.1.205",max_version="3.0.0",version_sensitive=True,note="documented version-gated task model; not serving attestation")
            if cws is not None: evidence["tasks.contextWindowSize"]=official_evidence(source,version,min_version="2.1.205",max_version="3.0.0",version_sensitive=True,note="documented version-gated task context size")
            metadata=make_metadata(source,source_version=version,collected_at=observed,field_evidence=evidence,warnings=warnings + (["subagent_statusline_model_is_not_backend_serving_attestation"] if model else []))
            tokens=_optional_int(task.get("tokenCount")); used=min(100.0,max(0.0,tokens/cws*100.0)) if tokens is not None and cws else None
            records.append(StatusSnapshot(stable_id("status",source.value,session,prompt,agent_id,observed.isoformat()),observed,session,prompt,"subagent",agent_id,model,None,None,None,None,None,None,cws,used,(),string(payload.get("permission_mode")),string(task.get("name")),None,0,metadata))
            if model:
                records.append(ModelObservationRecord(stable_id("modelobs",source.value,session,prompt,agent_id,observed.isoformat(),model),observed,session,prompt,None,None,agent_id,"subagent_statusline",None,None,None,None,model,None,None,None,None,None,None,EvidenceLevel.OFFICIAL_DOCUMENTED_VERSION_SENSITIVE,metadata,string(task.get("name"))))
        return CollectorBatch(tuple(records),tuple(dict.fromkeys(warnings)))

def _windows(value):
    if not isinstance(value,Mapping): return ()
    result=[]
    for name,raw in value.items():
        if isinstance(raw,Mapping): result.append(RateLimitWindow(str(name),as_float(first(raw,"used_percentage","used")),parse_timestamp(first(raw,"resets_at","reset_at","reset_time")),string(raw.get("status"))))
    return tuple(result)
def _optional_int(value):
    try: return None if value in (None,"") else int(value)
    except (TypeError,ValueError): return None
def _effort(value): return string(value.get("level")) if isinstance(value,Mapping) else string(value)

__all__=["ClaudeStatusLineAdapter"]
