"""Native account inclusion checks, before any tracker request; no acquisition."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from contextlib import suppress
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.catalogue_metadata import CLI_SHA256, MetadataProbe, MetadataStopError
from src.catalogue_prime_access import classify
from src.catalogue_rate import APIPacer
from src.catalogue_runner import DOCKER_SUPERVISOR, RunnerError, cardinal_argv, download

SOURCE = Path(__file__).resolve().parents[1] / "tools/cardinal-prime-access.cjs"
GTI = re.compile(r"amzn1\.dv\.gti\.[a-fA-F0-9-]{36}")


class PublicState(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, _attrs):
        if tag == "script":
            self.script = True
            self.parts = []

    def handle_data(self, data):
        if self.script:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script:
            self.script = False
            with suppress(ValueError):
                self.documents.append(json.loads("".join(self.parts)))


class SameOrigin(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit

        url = urlsplit(newurl)
        if url.scheme != "https" or url.hostname != "www.primevideo.com" or url.port not in (None, 443) or url.username or url.password:
            raise RunnerError("Prime identifier redirect changed origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def resolve_document(text, item):
    parser = PublicState()
    parser.feed(text)
    matches = set()
    for document in parser.documents:
        if not isinstance(document, dict):
            continue
        preparation = document.get("init", {}).get("preparations", {})
        primary = preparation.get("body", {}).get("atf", {}).get("state", {}).get("self", {})
        asin = preparation.get("head", {}).get("pageMetadata", {}).get("pageTypeId")
        if not isinstance(primary, dict):
            continue
        for key, value in primary.items():
            if not isinstance(value, dict) or not GTI.fullmatch(str(key)) or value.get("gti") != key:
                continue
            if value.get("compactGTI") == item or asin == item:
                matches.add(key)
    if len(matches) != 1:
        raise RunnerError("Prime storefront identifier could not be bound to one canonical title")
    return matches.pop()


class PrimeAccessProbe:
    def __init__(self, settings):
        self.settings = settings
        self.cache = {}
        self.pacer = APIPacer(
            Path(settings["state_dir"]).expanduser() / "api-rate.sqlite3", settings.get("tracker_request_interval_seconds", 10), settings.get("tracker_daily_api_limit", 200)
        )

    def resolve(self, item):
        if GTI.fullmatch(item):
            return item
        if not re.fullmatch(r"[A-Z0-9]{10,26}", item):
            raise RunnerError("Unsupported Prime title identifier")
        self.pacer.acquire("www.primevideo.com")
        with build_opener(SameOrigin()).open(Request("https://www.primevideo.com/detail/" + item, headers={"User-Agent": "Mozilla/5.0"}), timeout=25) as response:
            content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise RunnerError("Prime identifier page exceeded its safety limit")
        return resolve_document(content.decode("utf-8"), item)

    def check(self, candidate):
        key = (candidate["item"], candidate["imdb"], candidate.get("region"))
        if key in self.cache:
            return self.cache[key]
        item = self.resolve(str(candidate["item"]))
        host, mount, _ = MetadataProbe(self.settings)._install()
        source = SOURCE.read_bytes()
        name = "prime-access-" + hashlib.sha256(source).hexdigest()[:20] + ".cjs"
        script = host / name
        if script.exists():
            if script.is_symlink() or script.read_bytes() != source:
                raise RunnerError("Prime access adapter changed unexpectedly")
        else:
            with script.open("xb") as stream:
                script.chmod(0o600)
                stream.write(source)
        token = secrets.token_hex(16)
        request = host / ("prime-request-" + token + ".json")
        output = host / ("prime-result-" + token + ".json")
        settings = {**self.settings, "timeout_seconds": min(self.settings.get("metadata_timeout_seconds", 180), self.settings.get("timeout_seconds", 180))}
        arguments = ["--service", "amazon", "--listitem", item, "--jsonoutput", str(mount / output.name), "--workers", "1"]
        command = cardinal_argv(settings, arguments, "amazon")
        index = command.index(DOCKER_SUPERVISOR) + 2
        cli = self.settings["cardinal_docker"].get("cli", "src/cli.js")
        if not cli.startswith("/"):
            cli = str(mount.__class__(self.settings["cardinal_docker"].get("workdir", "/app/.output")) / cli)
        command[index : index + 1] = [str(mount / name), cli, str(mount / request.name)]
        try:
            with request.open("x") as stream:
                request.chmod(0o600)
                json.dump({"item": item}, stream)
            self.pacer.acquire("native-prime-title-info")
            outcome = download(command, settings["timeout_seconds"])
            if outcome == "uncertain":
                raise MetadataStopError("Prime account check interrupted; this run is stopped")
            if outcome != "succeeded" or not output.is_file() or output.is_symlink() or output.stat().st_size > 128 * 1024:
                raise RunnerError("Native Prime account check failed; inclusion remains unknown")
            data = json.loads(output.read_text())
            if data.get("schema") != 1 or data.get("cli_sha256") != CLI_SHA256 or data.get("service") != "amazon" or data.get("requested") != item:
                raise RunnerError("Prime account adapter contract changed")
            result = classify(data.get("resource"), imdb=candidate["imdb"], item=item, country=data.get("country"), expected_country=candidate.get("region"))
            if result.get("state") == "included":
                result["canonical_item"] = item
            self.cache[key] = result
            return result
        finally:
            request.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
