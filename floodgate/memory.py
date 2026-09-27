"""Owner-bound GBrain pages and attributed, bounded graph context.

The configured client must point at one dedicated personal brain. The owner
record detects accidental reuse; it is not a replacement for server credentials.
Only application-managed pages/edges enter model context. GBrain remains the
source of truth, including after this Python process restarts.
"""
from collections import defaultdict, deque
import hashlib
import json
import math
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid


OWNER_ROOT = "floodgate/owner"
START, END = "<!-- floodgate:start -->", "<!-- floodgate:end -->"
DATA = re.compile(r"<!-- floodgate:data\n(.*?)\n-->", re.S)
STOP = set("a an and are as at be build by do finish for from i in is it me my of on or prepare research task the this to use with work working".split())


class PersonalMemoryError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _Budget:
    """Soft deadline between calls; an in-flight call uses the client's timeout."""
    def __init__(self):
        self.calls = 0
        self.deadline = time.monotonic() + 4.0

    def tick(self):
        if self.calls >= 24 or time.monotonic() >= self.deadline:
            raise PersonalMemoryError("context_budget_exceeded")
        self.calls += 1


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def _tokens(value):
    return {t for t in re.findall(r"[\w]+", value.casefold()) if len(t) > 1 and t not in STOP}


def _task(value):
    return " ".join(value.casefold().split())


def canonical_url(value):
    """Keep resource-identifying fields, remove fragments/tracking/credentials."""
    if not value:
        return ""
    p = urlsplit(value)
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        raise ValueError("memory URLs must be http or https")
    host = p.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if p.port and (p.scheme.lower(), p.port) not in (("http", 80), ("https", 443)):
        host += f":{p.port}"
    omitted = {"fbclid", "gclid", "token", "access_token", "api_key", "auth", "session", "code"}
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.casefold().startswith("utm_") and k.casefold() not in omitted]
    return urlunsplit((p.scheme.lower(), host, p.path or "/", urlencode(query), ""))


def _block(data):
    # JSON strings cannot terminate the managed comment, even for hostile titles.
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e")
    return f"{START}\n# {data['title']}\n\n{data['body']}\n\n<!-- floodgate:data\n{payload}\n-->\n{END}"


def _decode(page):
    if not isinstance(page, dict):
        raise PersonalMemoryError("invalid_page_payload")
    content = page.get("content")
    if not isinstance(content, str) or len(content) > 100_000:
        raise PersonalMemoryError("invalid_page_content")
    matches = DATA.findall(content)
    if len(matches) != 1:
        raise PersonalMemoryError("invalid_page_markers")
    try:
        data = json.loads(matches[0])
    except (ValueError, TypeError):
        raise PersonalMemoryError("invalid_page_json") from None
    if not isinstance(data, dict) or data.get("version") != 1:
        raise PersonalMemoryError("invalid_page_version")
    if any(not isinstance(data.get(k), str) for k in ("owner_id", "key", "title", "kind", "body")) or not isinstance(data.get("metadata"), dict):
        raise PersonalMemoryError("invalid_page_fields")
    return data


def _rows(payload, key):
    rows = payload.get(key) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise PersonalMemoryError("invalid_tool_response")
    return [row for row in rows if isinstance(row, dict)]


class PersonalMemory:
    def __init__(self, client, owner_id):
        if not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 200:
            raise ValueError("owner_id must be a configured, nonempty ID")
        self.client, self.owner_id = client, owner_id.strip()
        self.prefix = f"floodgate/{_hash(self.owner_id)}/"
        self.tag = f"floodgate-owner-{_hash(self.owner_id)}"
        self.revision = 0
        self._available, self._error = True, None
        existing = self._get(OWNER_ROOT, missing=True)
        if existing is None:
            self._write(OWNER_ROOT, self._data("_owner", "Floodgate brain owner", "owner", "Dedicated personal brain.", {}), None)
        else:
            self._owned(existing, OWNER_ROOT)

    def status(self):
        return {"enabled": True, "available": self._available, "owner_id": self.owner_id,
                "revision": self.revision, "error": self._error}

    def _call(self, name, args, budget=None):
        if budget:
            budget.tick()
        try:
            result = self.client.call(name, args)
            if isinstance(result, dict) and result.get("error"):
                error = result["error"]
                raise PersonalMemoryError(error.get("code", "gbrain_error") if isinstance(error, dict) else str(error))
            receipt = result.get("write_request", {}) if isinstance(result, dict) else {}
            state = result.get("state") if isinstance(result, dict) else None
            if state not in (None, "committed") or (receipt and receipt.get("state") not in (None, "committed")):
                raise PersonalMemoryError("write_not_committed")
            self._available, self._error = True, None
            return result
        except Exception as exc:
            self._available, self._error = False, getattr(exc, "code", None) or "memory_unavailable"
            raise

    def _slug(self, key):
        if key == "_owner" or key == OWNER_ROOT:
            return OWNER_ROOT
        if not isinstance(key, str) or not key.strip() or len(key) > 4096:
            raise ValueError("node key must be a nonempty string")
        if key.startswith("floodgate/"):
            if not key.startswith(self.prefix):
                raise PersonalMemoryError("foreign_owner")
            return key
        readable = re.sub(r"[^a-z0-9]+", "-", key.casefold()).strip("-")[:48] or "node"
        return f"{self.prefix}{readable}-{_hash(key)}"

    def _get(self, slug, missing=False, budget=None):
        if slug != OWNER_ROOT and not slug.startswith(self.prefix):
            raise PersonalMemoryError("foreign_owner")
        try:
            return self._call("get_page", {"slug": slug, "include_content": True}, budget)
        except Exception as exc:
            if missing and getattr(exc, "code", "") in ("page_not_found", "not_found"):
                self._available, self._error = True, None
                return None
            raise

    def _owned(self, page, slug):
        try:
            data = _decode(page)
        except PersonalMemoryError as exc:
            self._available, self._error = False, exc.code
            raise
        if data["owner_id"] != self.owner_id:
            self._available, self._error = False, "foreign_owner"
            raise PersonalMemoryError("foreign_owner")
        if page.get("slug", slug) != slug or page.get("resolved_slug", slug) != slug:
            raise PersonalMemoryError("unexpected_page_alias")
        if self._slug(data["key"]) != slug:
            raise PersonalMemoryError("invalid_node_identity")
        return {**data, "slug": slug}

    def _data(self, key, title, kind, body, metadata):
        if any(not isinstance(v, str) or "<!-- floodgate:" in v or "<!-- /floodgate:" in v for v in (key, title, kind, body)):
            raise ValueError("node fields must be strings without reserved memory markers")
        if not title.strip() or not kind.strip() or len(title) > 300 or len(kind) > 80 or len(body) > 8000:
            raise ValueError("invalid node title, kind, or body length")
        metadata = {} if metadata is None else metadata
        if not isinstance(metadata, dict) or len(json.dumps(metadata, allow_nan=False)) > 8000:
            raise ValueError("metadata must be a small JSON object")
        return {"version": 1, "owner_id": self.owner_id, "key": key, "title": title,
                "kind": kind, "body": body, "metadata": metadata}

    def _write(self, slug, data, previous):
        block = _block(data)
        args = {"slug": slug}
        if previous is not None:
            old = self._owned(previous, slug)
            if all(old.get(k) == v for k, v in data.items()):
                return
            content = previous["content"]
            if content.count(START) != 1 or content.count(END) != 1 or not previous.get("revision"):
                raise PersonalMemoryError("unsafe_page_update")
            start, end = content.index(START), content.index(END) + len(END)
            if end <= start:
                raise PersonalMemoryError("unsafe_page_update")
            content = content[:start] + block + content[end:]
            # Edit only our managed block/title; retain canonical timeline/notes.
            if content.startswith("---\n"):
                fence = content.find("\n---", 4)
                if fence > 0:
                    header = re.sub(r"(?m)^title:.*$", lambda _: "title: " + json.dumps(data["title"]), content[:fence])
                    content = header + content[fence:]
            args["expected_revision"] = previous["revision"]
        else:
            content = f"---\ntitle: {json.dumps(data['title'])}\ntype: note\ntags: [{self.tag}]\n---\n\n{block}\n"
        args["content"] = content
        args["request_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(args, sort_keys=True)))
        self._call("put_page", args)
        self.revision += 1

    def upsert_node(self, key, title, kind, body, metadata=None):
        slug = self._slug(key)
        if slug == OWNER_ROOT:
            raise ValueError("owner root is reserved")
        previous = self._get(slug, missing=True)
        original_key = self._owned(previous, slug)["key"] if previous is not None else key
        self._write(slug, self._data(original_key, title, kind, body, metadata), previous)
        return slug

    def connect(self, from_key, to_key, relation, provenance):
        if not isinstance(relation, str) or not relation.strip() or len(relation) > 100 or not isinstance(provenance, str) or not provenance.strip() or len(provenance) > 1000:
            raise ValueError("connections require a relation and explicit provenance")
        source, target = self._slug(from_key), self._slug(to_key)
        self._owned(self._get(source), source)
        self._owned(self._get(target), target)
        context = json.dumps({"version": 1, "owner_id": self.owner_id,
                              "relation": relation, "provenance": provenance}, sort_keys=True)
        # Custom relation vocabulary lives in context, not an undeclared link_type.
        self._call("add_link", {"from": source, "to": target, "context": context,
                                "link_source": "floodgate-" + _hash(relation)})
        self.revision += 1

    def record_task(self, task):
        if not isinstance(task, str) or not task.strip() or len(task) > 1000:
            raise ValueError("task must be nonempty and at most 1000 characters")
        key = "task:" + _task(task)
        self.upsert_node(key, task[:300], "task", task,
                         {"task": _task(task), "provenance": "Owner explicitly set this task."})
        self.connect("_owner", key, "stated_task", "Owner explicitly set this task.")

    def record_override(self, task, url, title, label=0.0):
        if isinstance(label, bool) or not isinstance(label, (int, float)) or not math.isfinite(label) or not 0 <= label <= 1:
            raise ValueError("label must be a finite probability between 0 and 1")
        url = canonical_url(url)
        if not url:
            raise ValueError("override requires a URL")
        self.record_task(task)
        page_key, correction_key = "page:" + url, "correction:" + _task(task) + "|" + url
        self.upsert_node(page_key, (title or url)[:300], "resource", url, {"url": url})
        self.upsert_node(correction_key, f"Correction: {title or url}"[:300], "correction",
                         f"The owner rated this page {label:g} distraction for this exact task.",
                         {"task": _task(task), "url": url, "label": label, "provenance": "Owner explicitly corrected Floodgate."})
        self.connect("task:" + _task(task), correction_key, "has_correction", "Owner explicitly corrected Floodgate.")
        self.connect(correction_key, page_key, "judges_page", "Owner explicitly corrected Floodgate.")

    def context(self, task, url="", title="", limit=8):
        limit = max(0, min(int(limit), 16))
        result = {"owner_id": self.owner_id, "evidence": [], "paths": [], "revision": self.revision, "truncated": False}
        if limit == 0 or not isinstance(task, str) or not task.strip():
            return result
        budget, nodes = _Budget(), {}
        task_tokens = _tokens(task)
        page_url = canonical_url(url) if url else ""

        def get(slug):
            if slug not in nodes:
                page = self._get(slug, missing=True, budget=budget)
                if page is not None:
                    nodes[slug] = self._owned(page, slug)
            return nodes.get(slug)

        def evidence(node, match):
            if len(result["evidence"]) >= limit or any(e["slug"] == node["slug"] for e in result["evidence"]):
                return
            result["evidence"].append({k: node[k] for k in ("slug", "key", "title", "kind", "metadata")} | {"body": node["body"][:1000], "match": match})

        try:
            self._owned(self._get(OWNER_ROOT, budget=budget), OWNER_ROOT)
            if page_url:
                correction = get(self._slug("correction:" + _task(task) + "|" + page_url))
                if correction and correction["kind"] == "correction" and correction["metadata"].get("task") == _task(task) and correction["metadata"].get("url") == page_url:
                    evidence(correction, "explicit correction for this exact task and page")
            pages = _rows(self._call("list_pages", {"tag": self.tag, "limit": 80, "sort": "slug"}, budget), "pages")[:80]
            candidates = [(len(task_tokens & _tokens(str(p.get("title", "")))), p.get("slug")) for p in pages]
            candidates = [(score, slug) for score, slug in candidates if score and isinstance(slug, str) and slug.startswith(self.prefix)]
            if not candidates and task_tokens:
                hits = _rows(self._call("search", {"query": task[:300], "limit": 6}, budget), "results")[:6]
                candidates = [(1, h["slug"]) for h in hits if isinstance(h.get("slug"), str) and h["slug"].startswith(self.prefix)]
            anchors = []
            for _, slug in sorted(candidates, key=lambda x: (-x[0], x[1]))[:6]:
                node = get(slug)
                if not node or node["kind"] in ("correction", "owner"):
                    continue
                terms = _tokens(node["title"] + " " + node["body"] + " " + json.dumps(node["metadata"].get("keywords", [])))
                score = len(task_tokens & terms)
                if score:
                    anchors.append((node["kind"] == "project", node["kind"] != "task", score, slug))
            anchors.sort(reverse=True)
            for _, _, _, anchor in anchors[:2]:
                evidence(nodes[anchor], "matches the current task")
                raw_edges = _rows(self._call("traverse_graph", {"slug": anchor, "depth": 3, "direction": "both"}, budget), "paths")
                adjacency = defaultdict(list)
                for raw in raw_edges[:256]:
                    source, target = raw.get("from_slug"), raw.get("to_slug")
                    if not all(isinstance(s, str) and s.startswith(self.prefix) for s in (source, target)):
                        continue
                    try:
                        data = json.loads(raw.get("context", ""))
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(data, dict) or data.get("version") != 1 or data.get("owner_id") != self.owner_id or not all(isinstance(data.get(k), str) and data[k].strip() for k in ("relation", "provenance")):
                        continue
                    edge = {"from": source, "to": target, "relation": data["relation"][:100], "provenance": data["provenance"][:1000]}
                    adjacency[source].append((target, edge))
                    adjacency[target].append((source, edge))
                queue, seen, connected = deque([(anchor, [anchor], [])]), {anchor}, []
                while queue:
                    current, path, edges = queue.popleft()
                    try:
                        node = get(current)
                    except PersonalMemoryError as exc:
                        if exc.code != "context_budget_exceeded":
                            raise
                        result["truncated"] = True
                        break
                    if not node:
                        continue
                    lexical = bool(task_tokens & _tokens(node["title"] + " " + node["body"]))
                    if current != anchor and (node["kind"] in ("project", "task", "correction", "owner", "preference") and not lexical):
                        continue  # Unrelated preferences/projects cannot bridge to resources.
                    if current != anchor and node["kind"] not in ("person", "task", "correction", "owner") and (node["kind"] != "preference" or lexical):
                        exact_url = bool(page_url and node["metadata"].get("url") == page_url)
                        connected.append((exact_url, node["kind"] == "resource", len(path), current, path, edges))
                    if len(edges) < 3 and node["kind"] != "correction":
                        for target, edge in sorted(adjacency[current], key=lambda x: x[0]):
                            if target not in seen:
                                seen.add(target)
                                queue.append((target, path + [target], edges + [edge]))
                for _, _, _, target, path, edges in sorted(connected, key=lambda x: (-x[0], -x[1], x[2], x[3])):
                    if len(result["evidence"]) >= limit or len(result["paths"]) >= limit:
                        break
                    reason = f"Connected to task anchor {nodes[anchor]['title']} through {len(edges)} attributed graph edges."
                    evidence(nodes[target], reason)
                    result["paths"].append({"slugs": path, "titles": [nodes[s]["title"] for s in path],
                                            "nodes": [{"slug": s, "title": nodes[s]["title"], "kind": nodes[s]["kind"],
                                                       "body": nodes[s]["body"][:400]} for s in path],
                                            "edges": edges, "reason": reason})
                if result["truncated"]:
                    break
        except PersonalMemoryError as exc:
            if exc.code != "context_budget_exceeded":
                raise
            result["truncated"] = True
        return result
