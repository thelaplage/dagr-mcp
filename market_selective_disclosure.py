from dataclasses import dataclass

@dataclass(frozen=True)
class DisclosureRule:
    audience:str
    fields:tuple[str,...]

@dataclass(frozen=True)
class SelectiveDisclosureEnvelope:
    object_id:str
    object_digest:str
    audience:str
    disclosed:dict
    redacted_fields:tuple[str,...]
    authority_effect:str="none"

FORBIDDEN={"authorization","authorized","admitted","trusted","standing","secret","private_key"}

def disclose(*, object_id:str, object_digest:str, payload:dict, rule:DisclosureRule)->SelectiveDisclosureEnvelope:
    allowed=set(rule.fields)-FORBIDDEN
    disclosed={k:payload[k] for k in sorted(allowed) if k in payload}
    redacted=tuple(sorted(k for k in payload if k not in disclosed))
    return SelectiveDisclosureEnvelope(object_id,object_digest,rule.audience,disclosed,redacted)
