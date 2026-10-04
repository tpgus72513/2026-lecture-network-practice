#!/usr/bin/env python3
"""Week 3 · Task 2 — Does DNS actually steer you? Measure it.

Textbook §2.4.3 (records) and §2.5 (CDNs).

The lecture claims two things:

    (a) most large sites are served by a CDN, reached through a CNAME chain
    (b) DNS steers each user to a *nearby* replica

Both are testable from your laptop, and one of them is harder to prove than
the slide makes it look. Your job is to produce the evidence and a number.

    python3 task2_steering.py --collect --network campus  # campus 측정 추가
    python3 task2_steering.py --report                    # 보고서 생성

What you have to build
----------------------
1.  For each hostname in SITES, follow the CNAME chain to its end and record
    every hop. `--collect` should leave the raw data in out/chains.json.

2.  Decide, for each site, whether it is served by a **third party**.
    This is the hard part and there is no single right answer:

      - `www.microsoft.com` ends at `akamaiedge.net`     - clearly third party
      - `www.netflix.com`   stops inside `netflix.com`   - own CDN, not third party
      - some sites have no CNAME at all and still sit behind a CDN (anycast)
      - `foo.cloudfront.net` and `foo.s3.amazonaws.com` are both Amazon,
        but they are not the same service

    Write down the rule you used and **defend it in observation.md**. A rule
    that just compares the last two labels will be wrong on at least one of
    the sites below; find which, and say so.

3.  Ask **two different resolvers** for the same name and compare the
    addresses you get back. If DNS really steers by location, a CDN-hosted
    name should answer differently to resolvers sitting in different places.

        RESOLVERS below has your system resolver and two public ones.

    Report: of N CDN-hosted sites, how many returned a different address set
    from a different resolver? Claim (b) predicts most of them. Check it.

Pass condition
--------------
There is no fixed answer. You pass by producing, in out/report.md:

  - the table: site | chain length | final zone | third party? | your rule's verdict
  - the steering number: "X of N sites answered differently to a different resolver"
  - at least one site where your classification rule was wrong, and why
"""
import argparse, ipaddress, json, os, re, uuid
from datetime import datetime, timezone
from pathlib import Path

import dns.exception
import dns.resolver

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

SITES = [
    "www.microsoft.com",     # Akamai, 여러 CNAME hop
    "www.netflix.com",       # 자체 CDN
    "www.adobe.com",
    "www.cnn.com",
    "www.apple.com",
    "www.korea.ac.kr",       # 과제 설명상 비-CDN
    "www.stanford.edu",
    "www.bbc.co.uk",
    "www.spotify.com",
    "www.github.com",
    "www.wikipedia.org",
    "www.nytimes.com",
]

RESOLVERS = {
    "system": None,          # 현재 운영체제의 DNS 설정
    "google": "8.8.8.8",
    "quad9":  "9.9.9.9",
}

DNS_TIMEOUT_SECONDS = 2.0
DNS_LIFETIME_SECONDS = 4.0

# 단순 cloud 사업자가 아니라 CDN 서비스임을 식별할 수 있는 suffix만 둔다.
# amazonaws.com은 일부러 넣지 않았다. S3/ALB 사용만으로 CloudFront가
# 사이트를 제공했다고 볼 수 없기 때문이다.
CDN_PROVIDER_SUFFIXES = {
    "akamaiedge.net": "Akamai",
    "edgekey.net": "Akamai",
    "edgesuite.net": "Akamai",
    "akadns.net": "Akamai",
    "fastly.net": "Fastly",
    "fastlylb.net": "Fastly",
    "cloudfront.net": "Amazon CloudFront",
    "azureedge.net": "Azure CDN",
    "azurefd.net": "Azure Front Door",
    "edgecastcdn.net": "Edgio/Edgecast",
    "netlifyglobalcdn.com": "Netlify",
}
CDN_PROVIDER_SOURCES = {
    "netlifyglobalcdn.com": (
        "https://answers.netlify.com/t/"
        "how-can-i-change-which-netlify-site-my-hostname-is-pointing-to/3259"
    ),
}

# 아래 두 항목은 현재 DNS 응답에서 추측한 사실이 아니라 과제 설명의 전제다.
KNOWN_OWN_CDNS = {"netflix.com": "과제 설명에 명시된 Netflix 자체 CDN"}
KNOWN_NON_CDNS = {"korea.ac.kr": "과제 설명에 명시된 비-CDN 사이트"}
WIKIMEDIA_PROJECTS_SOURCE = (
    "https://wikimediafoundation.org/what-we-do/wikimedia-projects/"
)
KNOWN_SAME_ORGANIZATION = {
    "wikipedia.org": {
        "zones": {"wikipedia.org", "wikimedia.org"},
        "label": "Wikimedia Foundation이 Wikipedia와 Wikimedia 프로젝트를 함께 운영",
        "source": WIKIMEDIA_PROJECTS_SOURCE,
    },
}
MULTI_LABEL_PUBLIC_SUFFIXES = {"ac.kr", "co.kr", "co.uk", "com.au", "co.jp"}


def normalize_addresses(records):
    """유효한 IPv4 주소만 골라 중복을 없애고 숫자 순으로 반환한다.

    DNS 응답은 주소를 반복하거나 CNAME 문자열을 함께 포함할 수 있다.
    A 레코드만 정규화해야 주소 집합 비교가 흔들리지 않는다.
    """
    addresses = set()
    for record in records:
        try:
            address = ipaddress.ip_address(str(record).strip())
        except ValueError:
            continue
        if address.version == 4:
            addresses.add(address)
    return [str(address) for address in sorted(addresses)]


def normalize_hostname(name):
    """DNS 이름을 소문자·마침표 없는 형태로 통일한다."""
    return str(name).strip().rstrip(".").lower()


def query_dns(name, rtype="A", server=None):
    """resolver 한 곳에 질의하고 실패와 정상 빈 응답을 구분한다."""
    resolver = dns.resolver.Resolver(configure=server is None)
    if server:
        resolver.nameservers = [server]
    resolver.timeout = DNS_TIMEOUT_SECONDS
    resolver.lifetime = DNS_LIFETIME_SECONDS

    try:
        answer = resolver.resolve(
            normalize_hostname(name),
            rtype,
            search=False,
            raise_on_no_answer=False,
            lifetime=DNS_LIFETIME_SECONDS,
        )
        records = [item.to_text() if hasattr(item, "to_text") else str(item)
                   for item in answer]
        return {"status": "ok", "records": records}
    except dns.resolver.NoAnswer:
        return {"status": "ok", "records": []}
    except dns.exception.Timeout as exc:
        return {"status": "error", "records": [], "error": f"timeout: {exc}"}
    except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers,
            dns.exception.DNSException, OSError) as exc:
        return {
            "status": "error",
            "records": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def follow_cname_chain(name, query_fn=None, server=None, max_depth=12):
    """레코드 없음과 질의 실패를 구분하며 CNAME을 끝까지 따라간다.

    ``chain``에는 최초 질의 이름도 포함한다. 따라서 ``hops``는 CNAME
    연결 수이며 chain에 든 이름 수보다 하나 작다.
    """
    if query_fn is None:
        query_fn = query_dns

    current = normalize_hostname(name)
    chain = [current]
    seen = {current}

    while True:
        reply = query_fn(current, "CNAME", server)
        if reply.get("status") != "ok":
            return {
                "status": "error",
                "chain": chain,
                "final_hostname": current,
                "hops": len(chain) - 1,
                "error": reply.get("error", "DNS query failed"),
            }

        targets = [normalize_hostname(value) for value in reply.get("records", [])]
        targets = [value for value in targets if value]
        if not targets:
            return {
                "status": "ok",
                "chain": chain,
                "final_hostname": current,
                "hops": len(chain) - 1,
            }

        target = targets[0]
        if target in seen:
            chain.append(target)
            return {
                "status": "loop",
                "chain": chain,
                "final_hostname": current,
                "hops": len(chain) - 1,
                "error": f"CNAME loop closes at {target}",
            }
        if len(chain) - 1 >= max_depth:
            return {
                "status": "depth_limit",
                "chain": chain,
                "final_hostname": current,
                "hops": len(chain) - 1,
                "error": f"CNAME chain exceeded {max_depth} hops",
                "unfollowed_target": target,
            }

        chain.append(target)
        seen.add(target)
        current = target


def dig(name, rtype="A", server=None):
    """기존 호출 방식과 호환되도록 DNS 레코드 목록만 반환한다."""
    reply = query_dns(name, rtype, server)
    return reply["records"] if reply["status"] == "ok" else []


def system_nameservers():
    """현재 network run에서 활성화된 system DNS endpoint를 읽는다."""
    resolver = dns.resolver.Resolver(configure=True)
    return list(dict.fromkeys(str(server) for server in resolver.nameservers))


def collect_site(site, query_fn):
    """사이트 하나의 system-resolver chain과 resolver별 A 집합을 모은다."""
    cname = follow_cname_chain(site, query_fn=query_fn)
    answers = {}
    for resolver_name, server in RESOLVERS.items():
        reply = query_fn(site, "A", server)
        answer = {
            "server": server,
            "status": reply.get("status", "error"),
            "addresses": normalize_addresses(reply.get("records", [])),
        }
        if answer["status"] != "ok":
            answer["error"] = reply.get("error", "DNS query failed")
        answers[resolver_name] = answer
    return {"cname": cname, "answers": answers}


def _write_json_atomic(path, data):
    """새 JSON을 완전히 쓴 뒤에만 기존 파일을 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def collect(network_label="unlabeled", output_path=None, query_fn=None,
            system_nameservers_fn=None):
    """CNAME chain과 resolver별 응답을 ``out/chains.json``에 추가한다.

    호출할 때마다 고유한 run을 append한다. 같은 label을 다시 써도 이전
    측정 증거를 지우지 않는다.
    """
    label = str(network_label).strip()
    if not label:
        raise ValueError("network label must not be empty")
    path = Path(output_path) if output_path else Path(OUT) / "chains.json"
    query_fn = query_fn or query_dns
    system_nameservers_fn = system_nameservers_fn or system_nameservers

    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not isinstance(data.get("runs"), list):
            raise ValueError(f"unsupported chains.json schema in {path}")
    else:
        data = {"schema_version": 1, "sites": list(SITES), "runs": []}

    collected_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    safe_label = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "network"
    run_id = f"{collected_at.replace(':', '').replace('-', '')}--{safe_label}--{uuid.uuid4().hex[:8]}"
    run = {
        "run_id": run_id,
        "network": label,
        "collected_at": collected_at,
        "resolvers": {
            name: {
                "server": server,
                "nameservers": system_nameservers_fn() if name == "system" else [server],
            }
            for name, server in RESOLVERS.items()
        },
        "sites": {site: collect_site(site, query_fn) for site in SITES},
    }
    data["runs"].append(run)
    _write_json_atomic(path, data)
    return run


def registrable_zone(name):
    """이 과제의 site 목록에 필요한 범위에서 eTLD+1을 구한다."""
    labels = normalize_hostname(name).split(".")
    if len(labels) < 2:
        return normalize_hostname(name)
    last_two = ".".join(labels[-2:])
    if last_two in MULTI_LABEL_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def weak_last_two_verdict(site, final_hostname):
    """보고서에서 한계를 분석할 단순 마지막 두 label 규칙이다."""
    site_tail = ".".join(normalize_hostname(site).split(".")[-2:])
    final_tail = ".".join(normalize_hostname(final_hostname).split(".")[-2:])
    return "예" if site_tail != final_tail else "아니오"


def classify_site(site, cname):
    """관측 chain과 출처가 있는 과제 사실로 뒷받침되는 만큼만 판정한다."""
    if cname.get("status") != "ok":
        return {
            "third_party": "불명",
            "cdn_candidate": None,
            "weak_verdict": "불명",
            "weak_mismatch": False,
            "evidence": "CNAME 조회 실패로 판정 보류",
        }

    chain = [normalize_hostname(item) for item in cname.get("chain", [])]
    final_hostname = normalize_hostname(
        cname.get("final_hostname") or (chain[-1] if chain else site)
    )
    site_zone = registrable_zone(site)
    final_zone = registrable_zone(final_hostname)
    weak = weak_last_two_verdict(site, final_hostname)

    provider = None
    provider_suffix = None
    for hostname in chain:
        for suffix, name in CDN_PROVIDER_SUFFIXES.items():
            if hostname == suffix or hostname.endswith("." + suffix):
                provider, provider_suffix = name, suffix
                break
        if provider:
            break

    if provider:
        third_party, candidate = "예", True
        evidence = f"관측 chain의 {provider_suffix} suffix → {provider} CDN"
        if provider_suffix in CDN_PROVIDER_SOURCES:
            evidence += f" ([서비스 문서]({CDN_PROVIDER_SOURCES[provider_suffix]}))"
    elif site_zone in KNOWN_OWN_CDNS:
        third_party, candidate = "아니오", True
        evidence = KNOWN_OWN_CDNS[site_zone]
    elif site_zone in KNOWN_NON_CDNS:
        third_party, candidate = "아니오", False
        evidence = KNOWN_NON_CDNS[site_zone]
    elif (
        site_zone in KNOWN_SAME_ORGANIZATION
        and final_zone in KNOWN_SAME_ORGANIZATION[site_zone]["zones"]
    ):
        third_party, candidate = "아니오", None
        organization = KNOWN_SAME_ORGANIZATION[site_zone]
        evidence = (
            f"관측 final `{final_hostname}`; {organization['label']} "
            f"([공식 출처]({organization['source']}))"
        )
    else:
        third_party, candidate = "불명", None
        evidence = "CNAME 문자열만으로 CDN/소유 관계를 확정할 근거 없음"

    return {
        "third_party": third_party,
        "cdn_candidate": candidate,
        "weak_verdict": weak,
        "weak_mismatch": third_party in {"예", "아니오"} and third_party != weak,
        "evidence": evidence,
        "final_hostname": final_hostname,
        "final_zone": final_zone,
    }


def _latest_runs_by_network(data):
    """원시 이력은 둔 채 network label별 최신 run을 고른다."""
    latest = {}
    for index, run in enumerate(data.get("runs", [])):
        label = str(run.get("network", "unlabeled"))
        latest[label] = (index, run)
    return [item[1] for item in sorted(latest.values(), key=lambda item: item[0])]


def _successful_address_set(answer):
    if not answer or answer.get("status") != "ok":
        return None
    addresses = normalize_addresses(answer.get("addresses", []))
    return tuple(addresses) if addresses else None


def _resolver_identity(run, resolver_name, answer):
    """두 응답을 같은 resolver라고 부를 수 있는 endpoint 식별자를 만든다."""
    metadata = run.get("resolvers", {}).get(resolver_name, {})
    explicit_server = answer.get("server") or metadata.get("server")
    if explicit_server:
        return ("explicit", str(explicit_server))
    nameservers = tuple(sorted(str(item) for item in metadata.get("nameservers", [])))
    return ("system", nameservers) if nameservers else None


def _cname_evidence_for_site(runs, site):
    """나중의 실패는 보존하면서 가장 최근의 성공 chain을 고른다."""
    latest_observation = None
    for run in reversed(runs):
        site_data = run.get("sites", {}).get(site)
        if not site_data:
            continue
        cname = site_data.get("cname", {})
        if latest_observation is None:
            latest_observation = (run, cname)
        if cname.get("status") == "ok":
            return run, cname
    if latest_observation is not None:
        return latest_observation
    return None, {"status": "error", "error": "no observation"}


def analyze_steering(data):
    """오류를 주소 변화로 세지 않고 성공한 주소 집합만 비교한다."""
    runs = _latest_runs_by_network(data)
    classifications = {}
    for site in SITES:
        source_run, cname = _cname_evidence_for_site(runs, site)
        classification = classify_site(site, cname)
        classification["source_network"] = (
            source_run.get("network", "-") if source_run else "-"
        )
        classification["source_run_id"] = (
            source_run.get("run_id", "-") if source_run else "-"
        )
        classification["source_cname"] = cname
        classifications[site] = classification

    candidates = {
        site for site, item in classifications.items()
        if item.get("cdn_candidate") is True
    }
    resolver_comparable, resolver_changed = set(), set()
    network_comparable, network_changed = set(), set()
    broad_network_comparable, broad_network_changed = set(), set()

    for site in candidates:
        for run in runs:
            site_data = run.get("sites", {}).get(site, {})
            sets = [
                value for value in (
                    _successful_address_set(answer)
                    for answer in site_data.get("answers", {}).values()
                ) if value is not None
            ]
            if len(sets) >= 2:
                resolver_comparable.add(site)
                if len(set(sets)) > 1:
                    resolver_changed.add(site)

        resolver_names = set()
        for run in runs:
            resolver_names.update(
                run.get("sites", {}).get(site, {}).get("answers", {}).keys()
            )
        for resolver_name in resolver_names:
            broad_sets = []
            sets_by_identity = {}
            for run in runs:
                answer = (
                    run.get("sites", {}).get(site, {}).get("answers", {})
                    .get(resolver_name)
                )
                value = _successful_address_set(answer)
                if value is not None:
                    broad_sets.append(value)
                    identity = _resolver_identity(run, resolver_name, answer)
                    if identity is not None:
                        sets_by_identity.setdefault(identity, []).append(value)
            if len(broad_sets) >= 2:
                broad_network_comparable.add(site)
                if len(set(broad_sets)) > 1:
                    broad_network_changed.add(site)
            for identity_sets in sets_by_identity.values():
                if len(identity_sets) >= 2:
                    network_comparable.add(site)
                    if len(set(identity_sets)) > 1:
                        network_changed.add(site)

    # B5는 resolver 또는 network 변화 모두를 허용한다. 넓은 network 비교는
    # 유지하되, 위의 엄격한 'network 사이 같은 resolver' 결과와 구분한다.
    combined_comparable = resolver_comparable | broad_network_comparable
    combined_changed = resolver_changed | broad_network_changed
    return {
        "runs": runs,
        "classifications": classifications,
        "cdn_candidates": len(candidates),
        "cdn_candidate_sites": sorted(candidates),
        "resolver_comparable": len(resolver_comparable),
        "resolver_comparable_sites": sorted(resolver_comparable),
        "resolver_changed": len(resolver_changed),
        "resolver_changed_sites": sorted(resolver_changed),
        "network_comparable": len(network_comparable),
        "network_comparable_sites": sorted(network_comparable),
        "network_changed": len(network_changed),
        "network_changed_sites": sorted(network_changed),
        "broad_network_comparable": len(broad_network_comparable),
        "broad_network_comparable_sites": sorted(broad_network_comparable),
        "broad_network_changed": len(broad_network_changed),
        "broad_network_changed_sites": sorted(broad_network_changed),
        "combined_comparable": len(combined_comparable),
        "combined_comparable_sites": sorted(combined_comparable),
        "combined_changed": len(combined_changed),
        "combined_changed_sites": sorted(combined_changed),
        "cname_errors": [
            {
                "network": run.get("network", "unlabeled"),
                "run_id": run.get("run_id", "-"),
                "site": site,
                "status": site_data.get("cname", {}).get("status", "missing"),
                "error": site_data.get("cname", {}).get("error", "unknown error"),
            }
            for run in runs
            for site, site_data in run.get("sites", {}).items()
            if site_data.get("cname", {}).get("status") != "ok"
        ],
    }


def _markdown_cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def report(input_path=None, output_path=None, capture_analysis_path=None):
    """``out/chains.json``을 읽어 ``out/report.md``를 만든다.

    수동 패킷 메모는 ``capture-analysis.md``에 따로 둔다. 보고서를 다시
    만들어도 사람이 확인한 패킷 번호와 byte 수를 덮어쓰지 않는다.
    """
    input_path = Path(input_path) if input_path else Path(OUT) / "chains.json"
    output_path = Path(output_path) if output_path else Path(OUT) / "report.md"
    capture_path = (
        Path(capture_analysis_path) if capture_analysis_path
        else output_path.parent / "capture-analysis.md"
    )
    data = json.loads(input_path.read_text(encoding="utf-8"))
    analysis = analyze_steering(data)
    runs = analysis["runs"]
    network_names = [str(run.get("network", "unlabeled")) for run in runs]

    lines = [
        "# DNS steering 측정 보고서",
        "",
        "## 측정 범위",
        "",
        f"- 비교에 사용한 최신 network run: {', '.join(network_names) or '없음'}",
        f"- 보존된 전체 run 수: {len(data.get('runs', []))}",
        "- 주소는 성공한 A 응답의 중복 없는 집합으로 비교했다. timeout·차단·빈 A 집합은 비교 분모에서 제외했다.",
        "- CNAME chain은 system resolver로 한 번 수집했고, A 주소 집합은 system·Google·Quad9 각각에 질의했다.",
        "",
        "| network | run ID | 수집 시각(UTC) | system resolver endpoints |",
        "|---|---|---|---|",
    ]
    for run in runs:
        system = run.get("resolvers", {}).get("system", {})
        endpoints = ", ".join(system.get("nameservers", [])) or "기록 없음"
        lines.append(
            "| " + " | ".join(_markdown_cell(value) for value in [
                run.get("network", "unlabeled"), run.get("run_id", "-"),
                run.get("collected_at", "-"), endpoints,
            ]) + " |"
        )

    lines.extend([
        "",
        "## CNAME chain과 third-party 판정",
        "",
        "판정 규칙: 관측 chain에 알려진 CDN 서비스 suffix가 있으면 third-party CDN으로 본다. "
        "과제에 명시된 Netflix 자체 CDN과 Korea University 비-CDN은 별도 근거로 처리한다. "
        f"Wikipedia/Wikimedia의 동일 조직 관계는 [Wikimedia Foundation 공식 프로젝트 목록]({WIKIMEDIA_PROJECTS_SOURCE})을 근거로 한다. "
        "그 밖은 CNAME만으로 단정하지 않고 ‘불명’으로 남긴다.",
        "",
        "비교용 약식 규칙(rule verdict)은 원래 이름과 최종 이름의 마지막 두 label이 다르면 ‘예’로 본다. "
        "이 규칙은 `co.uk` 같은 public suffix, 같은 조직의 다른 도메인, no-CNAME anycast를 제대로 다루지 못한다.",
        "",
        "| site | chain length | final zone | chain source network | third-party? | rule verdict | 판정 근거 |",
        "|---|---:|---|---|---|---|---|",
    ])

    mismatches = []
    for site in SITES:
        classification = analysis["classifications"][site]
        cname = classification.get("source_cname", {})
        status = cname.get("status")
        hops = cname.get("hops", "-") if status == "ok" else "오류/미측정"
        final = cname.get("final_hostname", "-") if status == "ok" else "-"
        final_zone = registrable_zone(final) if final != "-" else "-"
        row = [
            site, hops, final_zone, classification["source_network"],
            classification["third_party"], classification["weak_verdict"],
            classification["evidence"],
        ]
        lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
        if classification.get("weak_mismatch"):
            mismatches.append((site, classification))

    lines.extend([
        "",
        "### 약식 규칙이 틀린 관측 사례",
        "",
    ])
    if mismatches:
        for site, item in mismatches:
            lines.append(
                f"- `{site}`: 약식 규칙은 {item['weak_verdict']}, 근거 기반 판정은 "
                f"{item['third_party']}였다. {item['evidence']}"
            )
    else:
        lines.append(
            "- 현재 성공한 관측에서는 근거로 확인 가능한 오분류가 없었다. "
            "측정 전부터 특정 사이트를 오분류라고 쓰지 않았으며, no-CNAME/anycast는 추가 ASN·사업자 근거 없이는 불명으로 남겼다."
        )

    lines.extend([
        "",
        "### network별 CNAME 수집 오류",
        "",
        "아래에는 오류 종류만 요약했다. 전문과 run ID는 [원시 chains.json](chains.json)에 그대로 남아 있다. "
        "이전 network의 성공한 chain을 오류가 난 network의 성공처럼 표시하지 않는다.",
        "",
    ])
    if analysis["cname_errors"]:
        for item in analysis["cname_errors"]:
            error_type = str(item["error"]).split(":", 1)[0].strip() or item["status"]
            lines.append(
                f"- `{item['network']}` / `{item['site']}`: {error_type}"
            )
    else:
        lines.append("- 선택된 최신 network run에는 CNAME 오류가 없었다.")

    lines.extend([
        "",
        "## resolver·network steering 결과",
        "",
        f"- **B5 통합: {analysis['combined_changed']}/{analysis['combined_comparable']}** "
        "측정 가능한 CDN 후보 사이트가 resolver 또는 network 변경 때 다른 주소 집합을 반환했다.",
        f"- 같은 network에서 resolver만 변경: {analysis['resolver_changed']}/{analysis['resolver_comparable']}",
        f"- 동일 endpoint로 확인된 같은 resolver를 network 사이에서 비교: "
        f"{analysis['network_changed']}/{analysis['network_comparable']}",
        f"- resolver label 기준의 넓은 network 환경 비교: "
        f"{analysis['broad_network_changed']}/{analysis['broad_network_comparable']} "
        "(system endpoint가 바뀐 경우를 포함하므로 ‘같은 resolver’ 결과로 해석하지 않음)",
        f"- 관측 chain/과제 근거로 정한 CDN 후보는 {analysis['cdn_candidates']}개였고, "
        f"이 중 비교 가능한 후보는 {analysis['combined_comparable']}개였다.",
        "",
        "주소 집합 차이는 DNS 응답 선택이 달랐다는 증거다. replica가 물리적으로 더 가까웠다는 직접 증거는 아니다. "
        "Google·Quad9도 anycast이므로 resolver IP만 보고 실제 질의 지점을 멀다고 단정할 수 없다.",
        "",
        "## Part A 패킷 분석",
        "",
        "원문: [capture-analysis.md](capture-analysis.md)",
        "",
    ])
    if capture_path.exists():
        capture_text = capture_path.read_text(encoding="utf-8").strip()
        lines.append(capture_text or "캡처 분석 파일이 비어 있다.")
    else:
        lines.append(
            "캡처 분석 대기 중: delegation/answer 패킷 번호(A3), 최대 DNS response byte 수와 큰 이유(A4)를 "
            "`out/capture-analysis.md`에 기록한 뒤 `--report`를 다시 실행한다."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip() + "\n"
    output_path.write_text(text, encoding="utf-8")
    return text


def build_parser():
    parser = argparse.ArgumentParser(
        description="CNAME chain과 resolver별 A 주소 집합을 네트워크별로 수집합니다."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--collect", action="store_true", help="새 측정 run 추가")
    action.add_argument("--report", action="store_true", help="저장된 run 보고서 생성")
    parser.add_argument(
        "--network", metavar="LABEL",
        help="현재 네트워크 이름(예: campus, phone-hotspot)",
    )
    return parser


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    if a.collect:
        if not a.network or not a.network.strip():
            p.error("--collect에는 --network LABEL이 필요합니다")
        run = collect(a.network)
        print(f"saved {run['run_id']} ({run['network']}) -> {os.path.join(OUT, 'chains.json')}")
    elif a.report:
        report()
        print(f"wrote {os.path.join(OUT, 'report.md')}")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
