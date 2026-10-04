#!/usr/bin/env python3
"""Week 3 · Task 1 — 직접 만드는 반복(iterative) DNS 해석기.

재귀 DNS 서버에 일을 맡기지 않고 루트 서버에서 출발해 위임을 직접
따라간다. 모든 질의는 RD(Recursion Desired) 비트를 끈다.

    python3 task1_resolve.py www.korea.ac.kr
    python3 task1_resolve.py www.korea.ac.kr --json
    python3 task1_resolve.py --verify
"""

import argparse
import json
import shutil
import subprocess
import sys

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdatatype


# 모든 해석은 여기에서 시작한다.
ROOT_SERVERS = [
    "198.41.0.4",       # a.root-servers.net
    "199.9.14.201",     # b.root-servers.net
    "192.33.4.12",      # c.root-servers.net
]

# 원래 과제의 dig 비교 대상을 그대로 둔다.
VERIFY_NAMES = [
    ("www.korea.ac.kr", "stable"),
    ("dns.google", "stable"),
    ("en.wikipedia.org", "stable"),
    ("www.stanford.edu", "stable"),
    ("www.microsoft.com", "cdn"),
]


class ResolutionError(RuntimeError):
    """DNS 이름을 끝까지 해석하지 못했을 때 발생한다."""


class QueryLimitError(ResolutionError):
    """한 번의 resolve 호출에 허용된 전체 질의 수를 넘었다."""


class DepthLimitError(ResolutionError):
    """위임 또는 CNAME을 따라가는 깊이 제한을 넘었다."""


class AuthoritativeError(ResolutionError):
    """권한 서버가 NXDOMAIN 또는 NODATA를 확정해 응답했다."""


class Resolver:
    """루트부터 권한 서버까지 위임을 직접 따라가는 IPv4 해석기.

    ``resolve(name)``은 ``(address, path)``를 반환한다. ``path``에는 실패한
    시도, glue가 없어 수행한 NS 이름 조회, 잘린 UDP 응답 뒤의 TCP 재질의가
    실제 발생 순서대로 모두 들어간다.

    테스트에서는 UDP/TCP 전송 함수만 주입할 수 있다. 해석 로직과 DNS
    메시지 처리는 운영 코드 그대로 실행된다.
    """

    def __init__(
        self,
        timeout=2.0,
        max_queries=100,
        max_depth=32,
        roots=None,
        udp_query=None,
        tcp_query=None,
    ):
        if timeout <= 0:
            raise ValueError("timeout은 0보다 커야 합니다")
        if max_queries <= 0:
            raise ValueError("max_queries는 0보다 커야 합니다")
        if max_depth < 0:
            raise ValueError("max_depth는 0 이상이어야 합니다")

        self.timeout = timeout
        self.max_queries = max_queries
        self.max_depth = max_depth
        self.roots = list(ROOT_SERVERS if roots is None else roots)
        if not self.roots:
            raise ValueError("적어도 하나의 루트 서버가 필요합니다")
        self._udp_query = udp_query or dns.query.udp
        self._tcp_query = tcp_query or dns.query.tcp

        self.path = []
        self.trace = []
        self.no_glue_lookups = 0
        self.query_count = 0
        self._visited = set()
        self._cname_chain = set()
        self._ns_address_cache = {}

    def resolve(self, name):
        """name의 IPv4 주소와 실제로 물어본 서버 경로를 반환한다."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("해석할 DNS 이름을 입력해야 합니다")

        try:
            qname = dns.name.from_text(name.strip()).derelativize(dns.name.root)
        except (dns.exception.DNSException, UnicodeError) as error:
            raise ValueError(f"올바르지 않은 DNS 이름입니다: {name!r}") from error

        # Resolver 인스턴스를 다시 사용해도 이전 실행 기록이 섞이지 않는다.
        self.path = []
        self.trace = []
        self.no_glue_lookups = 0
        self.query_count = 0
        self._visited = set()
        self._cname_chain = {self._name_key(qname)}
        self._ns_address_cache = {}

        address = self._walk(qname, self.roots, depth=0,
                             authority_zone=dns.name.root)
        return address, list(self.path)

    def _walk(self, qname, servers, depth, authority_zone):
        """servers를 차례로 시험하며 정답 또는 다음 위임을 찾는다."""
        if depth > self.max_depth:
            raise DepthLimitError(
                f"최대 탐색 깊이 {self.max_depth}를 넘었습니다: {qname}"
            )

        last_error = None
        for server in self._unique(servers):
            visit_key = (self._name_key(qname), server)
            if visit_key in self._visited:
                self.trace.append(
                    f"순환 방지: qname={qname} server={server} 재질의 생략"
                )
                continue
            self._visited.add(visit_key)

            try:
                response = self._ask(qname, server)
            except QueryLimitError:
                raise
            except (dns.exception.DNSException, OSError, EOFError) as error:
                last_error = error
                self.trace.append(
                    f"전송 실패: qname={qname} server={server} "
                    f"error={type(error).__name__}"
                )
                continue

            rcode = response.rcode()
            if rcode == dns.rcode.NXDOMAIN:
                if response.flags & dns.flags.AA:
                    self.trace.append(
                        f"권한 있는 NXDOMAIN: qname={qname} server={server}"
                    )
                    raise AuthoritativeError(f"NXDOMAIN: {qname}")
                self.trace.append(
                    f"권한 없는 NXDOMAIN 무시: qname={qname} server={server}"
                )
                continue
            if rcode != dns.rcode.NOERROR:
                self.trace.append(
                    f"사용 불가 응답: qname={qname} server={server} "
                    f"rcode={dns.rcode.to_text(rcode)}"
                )
                continue

            answer = self._exact_answer(response, qname, dns.rdatatype.A)
            if answer is not None:
                if response.flags & dns.flags.AA:
                    address = answer[0].address
                    self.trace.append(
                        f"권한 있는 A: qname={qname} address={address} "
                        f"server={server}"
                    )
                    return address
                self.trace.append(
                    f"권한 없는 A 무시: qname={qname} server={server}"
                )

            cname = self._exact_answer(response, qname, dns.rdatatype.CNAME)
            if cname is not None and response.flags & dns.flags.AA:
                target = cname[0].target
                if not target.is_absolute():
                    target = target.derelativize(qname.parent())
                target_key = self._name_key(target)
                self.trace.append(
                    f"CNAME: {qname} -> {target}; 루트부터 다시 탐색"
                )
                if target_key in self._cname_chain:
                    raise ResolutionError(
                        f"CNAME 순환을 발견했습니다: {qname} -> {target}"
                    )
                self._cname_chain.add(target_key)
                return self._walk(
                    target, self.roots, depth + 1, dns.name.root
                )

            referral = self._find_referral(response, qname)
            if referral is not None:
                zone, ns_names = referral
                glued, missing = self._referral_candidates(
                    qname, authority_zone, ns_names, response
                )
                if glued:
                    self.trace.append(
                        f"위임: qname={qname} zone={zone} "
                        f"glue_servers={','.join(glued)}"
                    )
                    try:
                        return self._walk(qname, glued, depth + 1, zone)
                    except (QueryLimitError, AuthoritativeError):
                        raise
                    except ResolutionError as error:
                        last_error = error
                        self.trace.append(
                            f"glue 위임 경로 실패: qname={qname} zone={zone} "
                            f"error={error}"
                        )

                # 쓸 수 있는 glue가 모두 실패한 뒤에만 추가 NS 조회 비용을 낸다.
                for ns_name, reason in missing:
                    ns_address = self._resolve_ns_address(
                        qname, ns_name, reason, depth
                    )
                    if ns_address is None:
                        continue
                    self.trace.append(
                        f"위임: qname={qname} zone={zone} "
                        f"resolved_ns={ns_name} address={ns_address}"
                    )
                    try:
                        return self._walk(
                            qname, [ns_address], depth + 1, zone
                        )
                    except (QueryLimitError, AuthoritativeError):
                        raise
                    except ResolutionError as error:
                        last_error = error
                        self.trace.append(
                            f"NS 위임 경로 실패: qname={qname} ns={ns_name} "
                            f"error={error}"
                        )

                self.trace.append(
                    f"사용 가능한 위임 주소 없음: qname={qname} "
                    f"zone={zone} server={server}"
                )
                continue

            if response.flags & dns.flags.AA and self._has_soa(response):
                self.trace.append(
                    f"권한 있는 NODATA: qname={qname} server={server}"
                )
                raise AuthoritativeError(f"NODATA(A 레코드 없음): {qname}")

            self.trace.append(
                f"관련 정답이나 위임 없음: qname={qname} server={server}"
            )

        detail = f"; 마지막 오류={last_error}" if last_error else ""
        raise ResolutionError(f"해석 가능한 서버 경로가 없습니다: {qname}{detail}")

    def _ask(self, qname, server):
        """RD를 끈 A 질의를 보내고, 잘린 UDP 응답은 TCP로 다시 받는다."""
        query = dns.message.make_query(qname, dns.rdatatype.A)
        query.flags &= ~dns.flags.RD
        response = self._send(self._udp_query, query, qname, server, "UDP")
        if response.flags & dns.flags.TC:
            self.trace.append(
                f"UDP 잘림(TC=1): qname={qname} server={server}; TCP 재질의"
            )
            response = self._send(self._tcp_query, query, qname, server, "TCP")
        return response

    def _send(self, transport, query, qname, server, protocol):
        """질의 한 번을 전체 예산과 실제 경로에 기록한 뒤 전송한다."""
        if self.query_count >= self.max_queries:
            raise QueryLimitError(
                f"최대 질의 수 {self.max_queries}에 도달했습니다: {qname}"
            )
        self.query_count += 1
        self.path.append(server)
        self.trace.append(
            f"질의: qname={qname} server={server} transport={protocol} "
            f"count={self.query_count}/{self.max_queries}"
        )
        return transport(query, server, timeout=self.timeout)

    def _referral_candidates(self, qname, authority_zone, ns_names, response):
        """현재 권한 영역이 보증할 수 있는 glue와 나머지 NS를 나눈다."""
        glued = []
        missing = []
        for ns_name in ns_names:
            glue = self._additional_a(response, ns_name)
            # bailiwick은 위임받는 자식 영역이 아니라 응답한 서버의 권한
            # 영역이다. 루트가 .com과 함께 주는 *.gtld-servers.net glue도
            # 이 기준으로 안전하게 사용할 수 있다.
            in_bailiwick = ns_name.is_subdomain(authority_zone)
            if glue and in_bailiwick:
                self.trace.append(
                    f"glue 사용: qname={qname} ns={ns_name} "
                    f"addresses={','.join(glue)}"
                )
                glued.extend(glue)
                continue

            reason = "없음"
            if glue and not in_bailiwick:
                reason = "bailiwick 밖이라 무시"
            missing.append((ns_name, reason))
        return self._unique(glued), missing

    def _resolve_ns_address(self, qname, ns_name, reason, depth):
        """필요할 때만 NS 이름을 루트부터 찾고 성공한 주소를 재사용한다."""
        key = self._name_key(ns_name)
        cached = self._ns_address_cache.get(key)
        if cached is not None:
            self.trace.append(
                f"NS 주소 캐시 사용: qname={qname} ns={ns_name} "
                f"address={cached}"
            )
            return cached

        self.no_glue_lookups += 1
        self.trace.append(
            f"glue 없음: qname={qname} ns={ns_name} reason={reason}; "
            "NS 이름을 루트부터 해석"
        )
        try:
            address = self._walk(
                ns_name, self.roots, depth + 1, dns.name.root
            )
        except QueryLimitError:
            raise
        except ResolutionError as error:
            self.trace.append(
                f"NS 이름 해석 실패: ns={ns_name} error={error}"
            )
            return None

        self._ns_address_cache[key] = address
        return address

    @staticmethod
    def _exact_answer(response, qname, rdtype):
        """answer 섹션에서 질문 이름과 형식이 모두 같은 RRset만 찾는다."""
        for rrset in response.answer:
            if rrset.rdtype == rdtype and rrset.name == qname:
                return rrset
        return None

    @staticmethod
    def _find_referral(response, qname):
        """질문 이름을 포함하는 가장 구체적인 NS 위임을 고른다."""
        candidates = []
        for rrset in response.authority:
            if rrset.rdtype != dns.rdatatype.NS:
                continue
            if not qname.is_subdomain(rrset.name):
                continue
            candidates.append((len(rrset.name.labels), rrset))
        if not candidates:
            return None

        _, rrset = max(candidates, key=lambda item: item[0])
        return rrset.name, [record.target for record in rrset]

    @staticmethod
    def _additional_a(response, owner):
        """additional 섹션에서 정확히 owner에 해당하는 IPv4 glue만 꺼낸다."""
        addresses = []
        for rrset in response.additional:
            if rrset.rdtype == dns.rdatatype.A and rrset.name == owner:
                addresses.extend(record.address for record in rrset)
        return addresses

    @staticmethod
    def _has_soa(response):
        """권한 있는 부정 응답의 근거가 되는 SOA가 있는지 확인한다."""
        return any(
            rrset.rdtype == dns.rdatatype.SOA for rrset in response.authority
        )

    @staticmethod
    def _name_key(name):
        return name.canonicalize().to_text()

    @staticmethod
    def _unique(items):
        """입력 순서를 유지하며 중복을 제거한다."""
        return list(dict.fromkeys(items))


# ------------------------------------------------------------------- harness
def dig_answer(name):
    """원래 과제처럼 dig +short의 A 결과를 비교용으로 돌려준다."""
    if not shutil.which("dig"):
        raise RuntimeError(
            "dig 명령을 찾을 수 없습니다. --verify에는 dig 설치가 필요합니다."
        )
    result = subprocess.run(
        ["dig", "+short", name, "A"], capture_output=True, text=True
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"종료 코드 {result.returncode}"
        raise RuntimeError(f"dig 실행에 실패했습니다: {detail}")
    return [line for line in result.stdout.split() if line and line[0].isdigit()]


def verify(timeout=2.0, max_queries=100):
    """다섯 이름의 결과를 원래 dig 기반 비교 방식으로 검증한다."""
    resolver, failures = Resolver(timeout=timeout, max_queries=max_queries), 0
    for name, kind in VERIFY_NAMES:
        try:
            address, path = resolver.resolve(name)
            expected = dig_answer(name)
        except Exception as error:
            print(f"  FAIL  {name:<22} {error}")
            failures += 1
            continue

        if address in expected:
            note = ""
        elif kind == "cdn":
            note = "  <- differs, but this name is CDN-hosted. Explain it."
        else:
            note = "  <- should have matched"
            failures += 1
        print(
            f"  {'FAIL' if note.endswith('matched') else 'ok  '}  {name:<22} "
            f"you={address:<16} dig={','.join(expected) or '-'}   "
            f"hops={len(path)}{note}"
        )
    print(f"\n  {len(VERIFY_NAMES) - failures}/{len(VERIFY_NAMES)} ok")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?", default="www.korea.ac.kr")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--max-queries", type=int, default=100)
    parser.add_argument(
        "--json", action="store_true", help="주소, 경로, 추적 정보를 JSON으로 출력"
    )
    args = parser.parse_args()

    if args.verify:
        if args.json:
            parser.error("--json은 --verify와 함께 사용할 수 없습니다")
        sys.exit(verify(args.timeout, args.max_queries))

    resolver = Resolver(timeout=args.timeout, max_queries=args.max_queries)
    address, path = resolver.resolve(args.name)
    if args.json:
        print(json.dumps({
            "name": args.name,
            "address": address,
            "path": path,
            "trace": resolver.trace,
            "no_glue_lookups": resolver.no_glue_lookups,
            "query_count": resolver.query_count,
        }, ensure_ascii=False, indent=2))
        return

    for index, server in enumerate(path, 1):
        print(f"  {index}. asked {server}")
    print(f"\n  {args.name} -> {address}")


if __name__ == "__main__":
    main()
