from federation_live_sam import SAM_COMMIT,SAM_RELEASE,SamPeerBinding,parity_digest,transfer_exact

class Fake:
 def send(self,peer_id,operation,payload): return payload

def test_pinned_release_and_identity_separation():
 assert SAM_RELEASE=="v0.1.0-alpha.7" and SAM_COMMIT=="a5f2c4e"
 b=SamPeerBinding("sam:peer-a","cp-node:a")
 o=transfer_exact(Fake(),b,"submission.fetch",b"abc")
 assert o.route_succeeded and o.authority_effect=="none"
 assert o.peer_id != o.node_id

def test_semantic_parity_ignores_transport_metadata():
 refs={"submission":"sha256:"+"1"*64,"receipt":"sha256:"+"2"*64}
 assert parity_digest(refs)==parity_digest(dict(reversed(list(refs.items()))))
