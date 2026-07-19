from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, os, subprocess
from importlib.resources import files
from pathlib import Path
from typing import Iterable, Mapping, Optional
from .collectors import ClaudeHookAdapter, ClaudeOTelAdapter, ClaudeStatusLineAdapter, ClaudeTranscriptAdapter
from .records import SCHEMA_VERSION

_SAFE_ENV_KEYS={"PATH","LANG","LC_ALL","LC_CTYPE","TERM","TMPDIR","TEMP","TMP"}
_LAB_MARKER=".claude-code-data-kit-lab"
_LAB_MARKER_CONTENT="claude-code-data-kit-lab-v1\n"

@dataclass(frozen=True,slots=True)
class ClaudeLabSpec:
    root_dir: Path
    claude_version: str
    @property
    def home_dir(self): return self.root_dir/"home"
    @property
    def config_dir(self): return self.root_dir/"claude-config"
    @property
    def project_dir(self): return self.root_dir/"project"
    @property
    def npm_prefix(self): return self.root_dir/"npm"
    @property
    def fixture_dir(self): return self.root_dir/"fixtures"
    @property
    def marker_path(self): return self.root_dir/_LAB_MARKER
    @property
    def managed_paths(self): return (self.home_dir,self.config_dir,self.project_dir,self.npm_prefix,self.fixture_dir)
    @property
    def claude_binary(self): return self.npm_prefix/"bin"/"claude"
    def _is_managed_existing_root(self,root):
        try: children={c.name:c for c in root.iterdir()}
        except OSError as exc: raise ValueError("lab root cannot be inspected") from exc
        allowed={_LAB_MARKER,"home","claude-config","project","npm","fixtures"}
        if set(children)-allowed: return False
        marker=children.get(_LAB_MARKER)
        if marker is None or marker.is_symlink() or not marker.is_file(): return False
        try:
            if marker.read_text(encoding="utf-8") != _LAB_MARKER_CONTENT: return False
        except OSError: return False
        return all(p.exists() and p.is_dir() and not p.is_symlink() for p in self.managed_paths)
    def validate(self):
        root=self.root_dir.expanduser().resolve()
        if self.root_dir.expanduser().is_symlink(): raise ValueError("lab root must not be a symlink")
        home=Path.home().resolve(); real_claude=(home/".claude").resolve(); protected=(home,real_claude)
        if root==Path("/"): raise ValueError("lab root must not be filesystem root")
        if any(root==p or root in p.parents or p in root.parents for p in protected): raise ValueError("lab root must not overlap or contain the real HOME/Claude config")
        if root.exists() and not root.is_dir(): raise ValueError("lab root must be a directory")
        if root.exists() and any(root.iterdir()) and not self._is_managed_existing_root(root): raise ValueError("lab root contains unmanaged content")
        from .versioning import SemVer
        SemVer.parse(self.claude_version)
    def prepare(self):
        self.validate()
        for path in self.managed_paths: path.mkdir(parents=True,exist_ok=True)
        self.marker_path.write_text(_LAB_MARKER_CONTENT,encoding="utf-8")
        (self.project_dir/"README.md").write_text("# Synthetic Claude Code lab\n",encoding="utf-8")
    def environment(self,base: Optional[Mapping[str,str]]=None):
        self.validate(); source={k:v for k,v in dict(base or os.environ).items() if k in _SAFE_ENV_KEYS}
        source.update({"HOME":str(self.home_dir),"CLAUDE_CONFIG_DIR":str(self.config_dir),"DISABLE_AUTOUPDATER":"1","DISABLE_AUTO_UPDATE":"1","CLAUDE_CODE_ENABLE_TELEMETRY":"0","CLAUDE_CODE_ENABLE_ENHANCED_TRACING":"0","CLAUDE_CODE_ENHANCED_TRACING":"0","CLAUDE_CODE_DISABLE_AUTOUPDATER":"1","CLAUDE_CODE_DISABLE_AUTO_UPDATE":"1","OTEL_TRACES_EXPORTER":"none","OTEL_METRICS_EXPORTER":"none","OTEL_LOGS_EXPORTER":"none","OTEL_LOG_USER_PROMPTS":"0","OTEL_LOG_ASSISTANT_RESPONSES":"0","OTEL_LOG_TOOL_DETAILS":"0","OTEL_LOG_TOOL_CONTENT":"0","OTEL_LOG_RAW_API_BODIES":"0","NO_COLOR":"1"})
        source["PATH"]=f"{self.npm_prefix/'bin'}{os.pathsep}{source.get('PATH','')}"; return source
    def install_command(self): return ("npm","install","--global","--prefix",str(self.npm_prefix),f"@anthropic-ai/claude-code@{self.claude_version}")
    def version_command(self): return (str(self.claude_binary),"--version")
    def help_command(self): return (str(self.claude_binary),"--help")
    def unauthenticated_probe_command(self): return (str(self.claude_binary),"--bare","--tools","","-p","Synthetic lab connectivity check. Return LAB only.","--output-format","json","--no-session-persistence")

@dataclass(frozen=True,slots=True)
class LabCommandResult:
    command: tuple[str,...]; returncode:int; stdout_sha256:str; stderr_sha256:str; stdout_bytes:int; stderr_bytes:int; timed_out:bool=False
class ClaudeLabRunner:
    def __init__(self,spec): self.spec=spec
    def run(self,command: Iterable[str],*,timeout_seconds=30):
        self.spec.prepare(); cmd=tuple(command)
        try:
            done=subprocess.run(cmd,cwd=self.spec.project_dir,env=self.spec.environment(),capture_output=True,timeout=timeout_seconds,check=False)
            return _result(cmd,done.returncode,done.stdout,done.stderr,False)
        except subprocess.TimeoutExpired as exc: return _result(cmd,124,exc.stdout or b"",exc.stderr or b"",True)
        except OSError as exc: return _result(cmd,127,b"",str(exc).encode("utf-8", errors="replace"),False)
    def install(self,*,allow_network=False):
        if not allow_network: raise PermissionError("network installation requires explicit allow_network=True")
        return self.run(self.spec.install_command(),timeout_seconds=180)
    def probe_unauthenticated_error_path(self,*,allow_network=False):
        if not allow_network: raise PermissionError("unauthenticated network probe requires explicit allow_network=True")
        return self.run(self.spec.unauthenticated_probe_command(),timeout_seconds=30)

def synthetic_check(spec: ClaudeLabSpec):
    spec.prepare(); root=files("claude_code_data_kit").joinpath("_fixtures")
    load=lambda name: json.loads(root.joinpath(name).read_text(encoding="utf-8"))
    batches=[ClaudeHookAdapter().parse_event(load("hook_agent_posttooluse.json"),source_version=spec.claude_version),ClaudeOTelAdapter().parse_event(load("otel_api_request.json")),ClaudeStatusLineAdapter().parse_main(load("statusline_main.json")),ClaudeStatusLineAdapter().parse_subagents(load("statusline_subagents.json")),ClaudeTranscriptAdapter().parse_jsonl(root.joinpath("transcript_2_1_214.jsonl").read_text(encoding="utf-8"),source_version=spec.claude_version)]
    result={"fixture_source":"package-resource","records":sum(len(b.records) for b in batches),"warnings":sorted({w for b in batches for w in b.warnings}),"schema_version":SCHEMA_VERSION,"version":spec.claude_version}
    (spec.fixture_dir/"synthetic-check.json").write_text(json.dumps(result,sort_keys=True)+"\n",encoding="utf-8")
    return result

def write_synthetic_fixture(path: Path,payload: object): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def _result(command,returncode,stdout,stderr,timed_out): return LabCommandResult(command,returncode,hashlib.sha256(stdout).hexdigest(),hashlib.sha256(stderr).hexdigest(),len(stdout),len(stderr),timed_out)

__all__=["ClaudeLabSpec","LabCommandResult","ClaudeLabRunner","synthetic_check","write_synthetic_fixture"]
