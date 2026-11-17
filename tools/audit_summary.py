"""Print a readable summary of a pip-audit JSON report: python tools/audit_summary.py audit.json"""
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
found = 0
for dep in data.get("dependencies", []):
    for v in dep.get("vulns", []):
        found += 1
        fixes = ", ".join(v.get("fix_versions") or []) or "no fix yet"
        aliases = " ".join(v.get("aliases") or [])
        print(f"{dep['name']} {dep.get('version', '')}: {v['id']} {aliases} -> fixed in {fixes}")
print(f"{found} known vulnerabilities" if found else "No known vulnerabilities")
