"""Generate the profile dashboard from public GitHub data. Python standard library only."""

import collections
import datetime as dt
import html
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OWNER = "tiagoperrupato"
TEAM_REPOS = ["AndreiQP/hackathon-unicamp-2026", "AndreiQP/mc906-kaggle-retinopathy", "FastFoodly/FastFoodly"]
EXCLUDE = {OWNER, f"{OWNER}.github.io"}
# Report programming languages separately from notebook JSON, markup, styles and documents.
NON_CODE = {"Jupyter Notebook", "HTML", "CSS", "SCSS", "Less", "TeX", "PostScript", "Markdown", "SVG"}


def graphql(query, **variables):
    for attempt in range(3):
        result = subprocess.run(
            ["gh", "api", "graphql", "--input", "-"],
            input=json.dumps({"query": query, "variables": variables}),
            capture_output=True, text=True, timeout=45,
        )
        if result.returncode == 0:
            break
        if attempt == 2:
            raise RuntimeError(result.stderr or result.stdout)
        time.sleep(2 ** attempt)
    data = json.loads(result.stdout)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def collect():
    # Only public, original owned repositories; selected team projects are added explicitly.
    repos, cursor = [], None
    while True:
        connection = graphql('''query($owner:String!,$cursor:String) {
          user(login:$owner) { repositories(first:100,after:$cursor,
            ownerAffiliations:OWNER,privacy:PUBLIC,isFork:false) {
            nodes {name nameWithOwner} pageInfo {hasNextPage endCursor}
          } }
        }''', owner=OWNER, cursor=cursor)["user"]["repositories"]
        repos.extend(r["nameWithOwner"] for r in connection["nodes"] if r["name"] not in EXCLUDE)
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]

    # Filter every contribution group to public repositories, even when run locally
    # with an account that can access private work. No private names are written.
    activity = graphql('''query($owner:String!) { user(login:$owner) {
      contributionsCollection {
        startedAt endedAt
        commitContributionsByRepository(maxRepositories:100) {
          repository {isPrivate}
          contributions(first:100) {pageInfo {hasNextPage} nodes {occurredAt commitCount}}
        }
        issueContributionsByRepository(maxRepositories:100) {
          repository {isPrivate} contributions {totalCount}
        }
        pullRequestContributionsByRepository(maxRepositories:100) {
          repository {isPrivate} contributions {totalCount}
        }
        pullRequestReviewContributionsByRepository(maxRepositories:100) {
          repository {isPrivate} contributions {totalCount}
        }
        repositoryContributions(first:100) {
          pageInfo {hasNextPage} nodes {repository {isPrivate}}
        }
      }
    } }''', owner=OWNER)["user"]["contributionsCollection"]
    commits, daily = 0, collections.Counter()
    for group in activity["commitContributionsByRepository"]:
        if group["repository"]["isPrivate"]:
            continue
        if group["contributions"]["pageInfo"]["hasNextPage"]:
            raise RuntimeError("More than 100 active commit days in one repository; add pagination before publishing.")
        for day in group["contributions"]["nodes"]:
            commits += day["commitCount"]
            daily[day["occurredAt"][:10]] += day["commitCount"]
    counts = {"Commits": commits}
    for label, field in [("Pull requests", "pullRequestContributionsByRepository"),
                         ("Issues", "issueContributionsByRepository"),
                         ("Reviews", "pullRequestReviewContributionsByRepository")]:
        counts[label] = sum(g["contributions"]["totalCount"] for g in activity[field] if not g["repository"]["isPrivate"])
    if activity["repositoryContributions"]["pageInfo"]["hasNextPage"]:
        raise RuntimeError("Repository contributions need pagination.")
    counts["Contributions"] = sum(counts.values()) + sum(
        not n["repository"]["isPrivate"] for n in activity["repositoryContributions"]["nodes"])

    languages, colors, technologies = collections.Counter(), {}, set()
    evidence = {}
    paths = ["requirements.txt", "pyproject.toml", "package.json", "app/package.json",
             "frontend/package.json", "docker-compose.yml", "Dockerfile"]
    aliases = "\n".join(f'f{i}:object(expression:"HEAD:{p}") {{... on Blob {{text}}}}' for i, p in enumerate(paths))
    for full_name in sorted(set(repos + TEAM_REPOS)):
        owner, name = full_name.split("/")
        repository = graphql('''query($owner:String!,$name:String!) {
          repository(owner:$owner,name:$name) { isPrivate
            languages(first:100,orderBy:{field:SIZE,direction:DESC}) {
              totalSize pageInfo {hasNextPage} edges {size node {name color}}
            }
        ''' + aliases + "} }", owner=owner, name=name)["repository"]
        if repository is None or repository["isPrivate"]:
            raise RuntimeError(f"Expected a public project: {full_name}")
        if repository["languages"]["pageInfo"]["hasNextPage"]:
            raise RuntimeError("Language results need pagination.")
        for edge in repository["languages"]["edges"]:
            language = edge["node"]["name"]
            if language in NON_CODE:
                continue
            languages[language] += edge["size"]
            colors[language] = edge["node"]["color"] or "#8b949e"
        manifests = "\n".join(repository[f"f{i}"]["text"] or "" for i in range(len(paths)) if repository[f"f{i}"])
        rules = {"PyTorch": r"(?im)^\s*[\"']?torch(?:[\s\[<=>~\"']|$)",
                 "scikit-learn": r"\bscikit-learn\b", "Streamlit": r"\bstreamlit\b",
                 "FastAPI": r"\bfastapi\b", "React": r'"react"\s*:',
                 "Docker": r"(?m)^services\s*:|^FROM\s+",
                 "Transformers": r"\btransformers\b", "Pandas": r"\bpandas\b"}
        for technology, pattern in rules.items():
            if re.search(pattern, manifests, re.IGNORECASE):
                technologies.add(technology)
                evidence.setdefault(technology, []).append(full_name)
    return counts, daily, languages, colors, sorted(technologies), evidence, sorted(set(repos + TEAM_REPOS))


def text(x, y, value, size=14, fill="text", weight=400):
    return f'<text x="{x}" y="{y}" class="{fill}" font-size="{size}" font-weight="{weight}">{html.escape(str(value))}</text>'


def svg(body, dark, title, description):
    palette = ("#0d1117", "#30363d", "#e6edf3", "#919ba7", "#8ed9bf") if dark else ("#ffffff", "#d1d9e0", "#1f2328", "#59636e", "#18735d")
    bg, border, ink, muted, accent = palette
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="400" height="260" viewBox="0 0 400 260" role="img" aria-labelledby="title desc">
<title id="title">{html.escape(title)}</title><desc id="desc">{html.escape(description)}</desc>
<style>text{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.text{{fill:{ink}}}.muted{{fill:{muted}}}.accent{{fill:{accent}}}</style>
<rect x=".5" y=".5" width="399" height="259" rx="12" fill="{bg}" stroke="{border}"/>{body}</svg>'''


def render(counts, daily, languages, colors, technologies, evidence, repos):
    today = dt.datetime.now(dt.timezone.utc).date()
    out = ROOT / "assets" / "dashboard"
    out.mkdir(parents=True, exist_ok=True)
    activity = text(22, 31, "Public activity", 18, weight=600) + text(22, 52, "LAST 12 MONTHS", 10, "muted", 600)
    for (label, x, y) in [("Contributions", 22, 90), ("Commits", 212, 90), ("Pull requests", 22, 155), ("Reviews", 212, 155)]:
        activity += text(x, y, f"{counts[label]:,}", 27, weight=650) + text(x, y + 21, label, 12, "muted")
    activity += text(22, 207, "Commit activity · last 30 days", 11, "muted")
    values = [daily[(today - dt.timedelta(days=29-i)).isoformat()] for i in range(30)]
    peak = max(values) or 1
    for i, value in enumerate(values):
        height = 3 + 23 * value / peak
        activity += f'<rect x="{22+i*12}" y="{239-height:.1f}" width="8" height="{height:.1f}" rx="2" fill="#5ab89a" opacity="{1 if value else .2}"/>'
    language_card = text(22, 31, "Programming languages", 18, weight=600) + text(22, 52, "PUBLIC PROJECTS · CODE SIZE", 10, "muted", 600)
    total = sum(languages.values())
    top = languages.most_common(5)
    other = total - sum(v for _, v in top)
    if other:
        top.append(("Other", other))
    for i, (language, size) in enumerate(top):
        y, pct = 81 + i * 28, size / total * 100
        language_card += text(22, y, language, 12) + text(330, y, f"{pct:.1f}%", 11, "muted")
        language_card += f'<rect x="22" y="{y+6}" width="350" height="4" rx="2" fill="#8b949e" opacity=".15"/>'
        language_card += f'<rect x="22" y="{y+6}" width="{max(2,350*pct/100):.2f}" height="4" rx="2" fill="{colors.get(language,"#8b949e")}"/>'
    language_card += text(22, 245, f"{len(repos)} repositories · includes team projects", 10, "muted")
    for dark in [False, True]:
        theme = "dark" if dark else "light"
        (out / f"activity-{theme}.svg").write_text(svg(activity, dark, "Public GitHub activity", ", ".join(f"{k}: {v}" for k,v in counts.items())))
        (out / f"languages-{theme}.svg").write_text(svg(language_card, dark, "Languages in public repositories", ", ".join(f"{k}: {v/total*100:.1f}%" for k,v in top)))
    pictures = []
    for card, alt in [("activity", "Public contributions, commits, pull requests and reviews over the last 12 months"),
                      ("languages", "Languages by code size across public repositories, including team projects")]:
        pictures.append(f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/dashboard/{card}-dark.svg"><img src="assets/dashboard/{card}-light.svg" alt="{alt}" width="400"></picture>')
    block = "\n\n".join([
        " ".join(pictures),
        "**Tools found in public projects**<br>\n" + " · ".join(f"`{t}`" for t in technologies),
        f'<sub>Updated {today.isoformat()} UTC · Refreshes daily · <a href="https://github.com/{OWNER}/{OWNER}/actions/workflows/dashboard.yml">Update status ↗</a></sub>',

    ])
    readme = ROOT / "README.md"
    content = readme.read_text()
    start, end = "<!-- DASHBOARD:START -->", "<!-- DASHBOARD:END -->"
    content = content.split(start)[0].rstrip() + "\n\n" + start + "\n" + block + "\n" + end + "\n"
    readme.write_text(content)
    print(json.dumps({"counts": counts, "languages": dict(languages), "technology_evidence": evidence}, indent=2))


if __name__ == "__main__":
    render(*collect())
