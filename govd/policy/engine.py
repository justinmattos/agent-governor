from dataclasses import dataclass, field
from typing import Optional

ALLOW = "allow"
ASK = "ask"
BLOCK = "block"
DENY = "deny"

_SEVERITY = {ALLOW: 0, ASK: 1, BLOCK: 2, DENY: 3}


@dataclass
class Event:
    agent: str
    event: str
    tool: Optional[str]
    raw_tool_name: str
    input: dict
    cwd: str
    session_id: str
    meta: dict = field(default_factory=dict)


@dataclass
class Decision:
    decision: str = ALLOW
    reason: str = ""
    context: str = ""
    rule: str = ""


@dataclass
class Ctx:
    locks: object
    plans: object = None


class Engine:
    def __init__(self, rules):
        self.rules = rules

    def evaluate(self, event, ctx):
        verdict = Decision()
        contexts = []
        matched = []
        for rule in self.rules:
            try:
                if not rule.applies(event):
                    continue
                d = rule.evaluate(event, ctx)
            except Exception as exc:
                d = None
                matched.append(f"{rule.name}!error:{exc}")
            if d is None:
                continue
            matched.append(rule.name)
            if d.context:
                contexts.append(d.context)
            if _SEVERITY.get(d.decision, 0) > _SEVERITY.get(verdict.decision, 0):
                verdict = d
        verdict.context = "\n\n".join(contexts)
        verdict.rule = ",".join(matched)
        return verdict
