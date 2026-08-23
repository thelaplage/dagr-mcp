from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Mapping,Protocol

SAM_RELEASE="v0.1.0-alpha.7"
SAM_COMMIT="a5f2c4e"
SCHEMA="dagr.mcp.federation-live-sam.v0.1"

def _digest(v:Mapping[str,object])->str:
 raw=json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); return "sha256:"+hashlib.sha256(raw).hexdigest()

class SamTransport(Protocol):
 def send(self, peer_id:str, operation:str, payload:bytes)->bytes: ...

@dataclass(frozen=True,slots=True)
class SamPeerBinding:
 sam_peer_id:str; counterpedia_node_id:str; authority_effect:str="none"
 def __post_init__(self):
  if not self.sam_peer_id or not self.counterpedia_node_id: raise ValueError("peer/node identity required")
  if self.authority_effect!="none": raise ValueError("SAM identity cannot move authority")

@dataclass(frozen=True,slots=True)
class SamTransferObservation:
 peer_id:str; node_id:str; operation:str; payload_digest:str; response_digest:str; route_succeeded:bool; authority_effect:str="none"; schema_version:str=SCHEMA

def transfer_exact(transport:SamTransport,binding:SamPeerBinding,operation:str,payload:bytes)->SamTransferObservation:
 if not operation: raise ValueError("operation required")
 response=transport.send(binding.sam_peer_id,operation,payload)
 return SamTransferObservation(binding.sam_peer_id,binding.counterpedia_node_id,operation,"sha256:"+hashlib.sha256(payload).hexdigest(),"sha256:"+hashlib.sha256(response).hexdigest(),True)

def parity_digest(artifact_refs:Mapping[str,str])->str:
 """Transport-neutral semantic parity root; SAM routing metadata is excluded."""
 return _digest({"schema":"counterpedia.federation.semantic-parity.v0.1","artifacts":dict(sorted(artifact_refs.items()))})
