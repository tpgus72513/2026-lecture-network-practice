"""Task 1 반복 DNS 해석기의 동작을 검증하는 단위 테스트."""

import unittest

import dns.exception
import dns.flags
import dns.message
import dns.rcode
import dns.rdatatype
import dns.rrset

import task1_resolve


ROOT_1 = "192.0.2.1"
ROOT_2 = "192.0.2.2"


def authoritative_a(query, address, owner=None):
    """질문에 대한 권한 있는 A 응답을 만든다."""
    response = dns.message.make_response(query)
    response.flags |= dns.flags.AA
    owner = owner or query.question[0].name
    response.answer.append(
        dns.rrset.from_text(owner, 300, "IN", "A", address)
    )
    return response


def cname_answer(query, target):
    """질문 이름을 target으로 연결하는 권한 있는 CNAME 응답을 만든다."""
    response = dns.message.make_response(query)
    response.flags |= dns.flags.AA
    response.answer.append(
        dns.rrset.from_text(query.question[0].name, 300, "IN", "CNAME", target)
    )
    return response


def referral(query, zone, nameservers, glue=()):
    """NS 위임과 선택적인 glue A 레코드를 담은 응답을 만든다."""
    response = dns.message.make_response(query)
    response.authority.append(
        dns.rrset.from_text(zone, 300, "IN", "NS", *nameservers)
    )
    for host, address in glue:
        response.additional.append(
            dns.rrset.from_text(host, 300, "IN", "A", address)
        )
    return response


class ScriptedTransport:
    """실제 DNS 전송만 대신하고, 해석기 로직은 그대로 실행한다."""

    def __init__(self, script):
        self.script = script
        self.queries = []

    def __call__(self, query, where, timeout=None):
        self.queries.append((str(query.question[0].name).lower(), where, query))
        action = self.script[(str(query.question[0].name).lower(), where)]
        if isinstance(action, BaseException):
            raise action
        return action(query) if callable(action) else action


class ResolverTests(unittest.TestCase):
    def make_resolver(self, udp, **kwargs):
        return task1_resolve.Resolver(
            roots=[ROOT_1, ROOT_2], udp_query=udp, timeout=0.01, **kwargs
        )

    def test_delegation을_직접_따라가며_RD_비트를_끄고_질의한다(self):
        ns_ip = "203.0.113.53"
        udp = ScriptedTransport({
            ("www.example.", ROOT_1): lambda q: referral(
                q, "example.", ["ns.example."], [("ns.example.", ns_ip)]
            ),
            ("www.example.", ns_ip): lambda q: authoritative_a(q, "203.0.113.80"),
        })

        address, path = self.make_resolver(udp).resolve("www.example")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, ns_ip], path)
        self.assertTrue(all(not query.flags & dns.flags.RD for _, _, query in udp.queries))

    def test_glue가_없으면_NS_이름을_루트부터_해석한다(self):
        ns_ip = "203.0.113.53"
        udp = ScriptedTransport({
            ("www.example.", ROOT_1): lambda q: referral(
                q, "example.", ["ns.example."]
            ),
            ("ns.example.", ROOT_1): lambda q: authoritative_a(q, ns_ip),
            ("www.example.", ns_ip): lambda q: authoritative_a(q, "203.0.113.80"),
        })
        resolver = self.make_resolver(udp)

        address, path = resolver.resolve("www.example")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, ROOT_1, ns_ip], path)
        self.assertEqual(1, resolver.no_glue_lookups)

    def test_루트가_com_위임에_준_gtld_net_glue를_사용한다(self):
        """루트의 bailiwick은 자식 .com이 아니라 부모 루트 영역이다."""
        gtld_ip = "203.0.113.53"
        udp = ScriptedTransport({
            ("www.example.com.", ROOT_1): lambda q: referral(
                q,
                "com.",
                ["a.gtld-servers.net."],
                [("a.gtld-servers.net.", gtld_ip)],
            ),
            ("a.gtld-servers.net.", ROOT_1): dns.exception.Timeout(),
            ("www.example.com.", gtld_ip): lambda q: authoritative_a(
                q, "203.0.113.80"
            ),
        })
        resolver = task1_resolve.Resolver(
            roots=[ROOT_1], udp_query=udp, timeout=0.01
        )

        address, path = resolver.resolve("www.example.com")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, gtld_ip], path)
        self.assertEqual(0, resolver.no_glue_lookups)

    def test_사용할_glue가_있으면_불필요한_NS_보조_조회를_하지_않는다(self):
        com_ip = "203.0.113.10"
        answer_ip = "203.0.113.80"
        udp = ScriptedTransport({
            ("www.example.com.", ROOT_1): lambda q: referral(
                q, "com.", ["ns.com."], [("ns.com.", com_ip)]
            ),
            ("www.example.com.", com_ip): lambda q: referral(
                q,
                "example.com.",
                ["ns1.example.com.", "ns2.outside.net."],
                [("ns1.example.com.", answer_ip)],
            ),
            ("ns2.outside.net.", ROOT_1): dns.exception.Timeout(),
            ("ns2.outside.net.", ROOT_2): dns.exception.Timeout(),
            ("www.example.com.", answer_ip): lambda q: authoritative_a(
                q, "203.0.113.81"
            ),
        })
        resolver = self.make_resolver(udp)

        address, path = resolver.resolve("www.example.com")

        self.assertEqual("203.0.113.81", address)
        self.assertEqual([ROOT_1, com_ip, answer_ip], path)
        self.assertEqual(0, resolver.no_glue_lookups)

    def test_시간_초과가_나면_다음_서버를_시도한다(self):
        udp = ScriptedTransport({
            ("www.example.", ROOT_1): dns.exception.Timeout(),
            ("www.example.", ROOT_2): lambda q: authoritative_a(q, "203.0.113.80"),
        })

        address, path = self.make_resolver(udp).resolve("www.example")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, ROOT_2], path)

    def test_CNAME을_만나면_대상_이름을_루트부터_다시_찾는다(self):
        udp = ScriptedTransport({
            ("alias.example.", ROOT_1): lambda q: cname_answer(q, "real.example."),
            ("real.example.", ROOT_1): lambda q: authoritative_a(q, "203.0.113.81"),
        })

        address, path = self.make_resolver(udp).resolve("alias.example")

        self.assertEqual("203.0.113.81", address)
        self.assertEqual([ROOT_1, ROOT_1], path)

    def test_CNAME_순환을_오류로_끝낸다(self):
        udp = ScriptedTransport({
            ("a.example.", ROOT_1): lambda q: cname_answer(q, "b.example."),
            ("b.example.", ROOT_1): lambda q: cname_answer(q, "a.example."),
        })
        resolver = self.make_resolver(udp)

        with self.assertRaisesRegex(task1_resolve.ResolutionError, "CNAME"):
            resolver.resolve("a.example")

        self.assertEqual([ROOT_1, ROOT_1], resolver.path)

    def test_CNAME_대상이_같은_glue없는_NS를_써도_주소를_재사용한다(self):
        ns_ip = "203.0.113.53"
        udp = ScriptedTransport({
            ("alias.example.", ROOT_1): lambda q: referral(
                q, "example.", ["ns.outside.net."]
            ),
            ("ns.outside.net.", ROOT_1): lambda q: authoritative_a(q, ns_ip),
            ("alias.example.", ns_ip): lambda q: cname_answer(q, "real.example."),
            ("real.example.", ROOT_1): lambda q: referral(
                q, "example.", ["ns.outside.net."]
            ),
            ("real.example.", ns_ip): lambda q: authoritative_a(q, "203.0.113.80"),
        })
        resolver = task1_resolve.Resolver(
            roots=[ROOT_1], udp_query=udp, timeout=0.01
        )

        address, path = resolver.resolve("alias.example")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, ROOT_1, ns_ip, ROOT_1, ns_ip], path)
        self.assertEqual(1, resolver.no_glue_lookups)

    def test_무관한_정답과_bailiwick_밖_glue를_사용하지_않는다(self):
        forged_ip = "203.0.113.200"
        com_ip = "203.0.113.10"
        real_ns_ip = "203.0.113.53"

        def unrelated_answer(query):
            response = authoritative_a(query, forged_ip, owner="other.example.")
            return response

        udp = ScriptedTransport({
            ("www.example.com.", ROOT_1): lambda q: referral(
                q, "com.", ["ns.com."], [("ns.com.", com_ip)]
            ),
            ("www.example.com.", com_ip): lambda q: referral(
                q,
                "example.com.",
                ["ns.outside.net."],
                [("ns.outside.net.", forged_ip), ("unrelated.com.", forged_ip)],
            ),
            ("ns.outside.net.", ROOT_1): lambda q: authoritative_a(q, real_ns_ip),
            ("www.example.com.", real_ns_ip): unrelated_answer,
            ("www.example.com.", ROOT_2): lambda q: authoritative_a(q, "203.0.113.80"),
        })

        address, path = self.make_resolver(udp).resolve("www.example.com")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, com_ip, ROOT_1, real_ns_ip, ROOT_2], path)
        self.assertNotIn(forged_ip, path)

    def test_전체_질의_수를_넘기기_전에_중단한다(self):
        class EndlessReferral:
            def __init__(self):
                self.calls = 0

            def __call__(self, query, where, timeout=None):
                self.calls += 1
                next_ip = f"203.0.113.{self.calls}"
                return referral(
                    query,
                    "example.",
                    [f"ns{self.calls}.example."],
                    [(f"ns{self.calls}.example.", next_ip)],
                )

        udp = EndlessReferral()
        resolver = task1_resolve.Resolver(
            roots=[ROOT_1], udp_query=udp, timeout=0.01, max_queries=3
        )

        with self.assertRaisesRegex(task1_resolve.QueryLimitError, "3"):
            resolver.resolve("www.example")

        self.assertEqual(3, udp.calls)
        self.assertEqual(3, len(resolver.path))

    def test_UDP_응답이_잘리면_같은_서버에_TCP로_다시_묻는다(self):
        def truncated(query):
            response = dns.message.make_response(query)
            response.flags |= dns.flags.TC
            return response

        udp = ScriptedTransport({("www.example.", ROOT_1): truncated})
        tcp = ScriptedTransport({
            ("www.example.", ROOT_1): lambda q: authoritative_a(q, "203.0.113.80")
        })
        resolver = task1_resolve.Resolver(
            roots=[ROOT_1], udp_query=udp, tcp_query=tcp, timeout=0.01
        )

        address, path = resolver.resolve("www.example")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, ROOT_1], path)
        self.assertFalse(tcp.queries[0][2].flags & dns.flags.RD)

    def test_권한없는_A와_다른_이름의_A는_정답으로_받지_않는다(self):
        def non_authoritative(query):
            response = dns.message.make_response(query)
            response.answer.append(
                dns.rrset.from_text(query.question[0].name, 300, "IN", "A", "203.0.113.10")
            )
            response.answer.append(
                dns.rrset.from_text("other.example.", 300, "IN", "A", "203.0.113.11")
            )
            return response

        udp = ScriptedTransport({
            ("www.example.", ROOT_1): non_authoritative,
            ("www.example.", ROOT_2): lambda q: authoritative_a(q, "203.0.113.80"),
        })

        address, path = self.make_resolver(udp).resolve("www.example")

        self.assertEqual("203.0.113.80", address)
        self.assertEqual([ROOT_1, ROOT_2], path)

    def test_권한있는_NXDOMAIN은_명확한_오류를_낸다(self):
        def nxdomain(query):
            response = dns.message.make_response(query)
            response.flags |= dns.flags.AA
            response.set_rcode(dns.rcode.NXDOMAIN)
            return response

        udp = ScriptedTransport({("missing.example.", ROOT_1): nxdomain})

        with self.assertRaisesRegex(task1_resolve.ResolutionError, "NXDOMAIN"):
            self.make_resolver(udp).resolve("missing.example")


if __name__ == "__main__":
    unittest.main()
