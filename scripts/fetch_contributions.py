#!/usr/bin/env python3
"""Refresh data/contributions.json (calendar + featured repo stats) via GraphQL.

Needs GH_TOKEN (or GITHUB_TOKEN) in the environment. The default Actions token
sees public contributions only; use a PAT with read:user in the PROFILE_TOKEN
secret to include private ones.
"""
import datetime as dt, json, os, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    sys.exit("set GH_TOKEN")

repos = [f["repo"] for f in P.get("featured", [])]
frag = "description stargazerCount forkCount url primaryLanguage{name color}"
q = ('query{user(login:"%s"){contributionsCollection{contributionCalendar{totalContributions '
     'weeks{contributionDays{date contributionCount}}}}}' % P["login"])
for i, r in enumerate(repos):
    o, n = r.split("/")
    q += f' r{i}:repository(owner:"{o}",name:"{n}"){{{frag}}}'
q += "}"

req = urllib.request.Request(
    "https://api.github.com/graphql", data=json.dumps({"query": q}).encode(),
    headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json", "User-Agent": "profile-cards"})
with urllib.request.urlopen(req, timeout=30) as resp:
    body = json.load(resp)
d = body.get("data")
if not d or not d.get("user"):
    sys.exit(f"GraphQL failed: {body.get('errors')}")
for e in body.get("errors") or []:
    print("warning:", e.get("message"), file=sys.stderr)

weeks = d["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
days = [{"date": x["date"], "count": x["contributionCount"]} for w in weeks for x in w["contributionDays"]]
out = {"login": P["login"], "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
       "days": days, "repos": {r: d.get(f"r{i}") or {} for i, r in enumerate(repos)}}
(ROOT / "data").mkdir(exist_ok=True)
(ROOT / "data" / "contributions.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(f"{len(days)} days, {len(repos)} repos")
