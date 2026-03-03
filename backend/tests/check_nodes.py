import json, urllib.request
base='http://localhost:8000'
reqs=json.load(urllib.request.urlopen(base+'/api/traces/requests?limit=500'))
branched=0
for r in reqs:
    d=json.load(urllib.request.urlopen(base+f"/api/traces/{r['trace_id']}"))
    pc={}
    for s in d.get("spans", []):
        p=s.get("parent_span_id")
        if p: pc[p]=pc.get(p,0)+1
    if any(c>1 for c in pc.values()):
        branched+=1
        print("BRANCHED request_id:", d["request_id"], "trace_id:", d["trace_id"])
print("total branched traces:", branched)