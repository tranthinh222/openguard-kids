import dns.flags
import dns.message
import dns.rdatatype
import dns.rrset

# Explicit supported hosts, not arbitrary domains containing "google".
GOOGLE_HOSTS = {prefix + name for prefix in ('', 'www.') for name in
                ('google.com', 'google.com.vn', 'google.co.uk', 'google.fr', 'google.de', 'google.co.jp', 'google.com.au')}


def rewrite(query, host, resolver):
    if host not in GOOGLE_HOSTS:
        return None
    response = dns.message.make_response(query)
    response.flags |= dns.flags.RA
    question = query.question[0]
    # HTTPS/SVCB records can carry alternate addresses; omit them under SafeSearch.
    if question.rdtype not in {dns.rdatatype.A, dns.rdatatype.AAAA}:
        return response
    target = 'forcesafesearch.google.com.'
    answer = resolver.resolve(dns.message.make_query(target, question.rdtype))
    if answer.rcode():
        response.set_rcode(answer.rcode())
        return response
    response.answer.append(dns.rrset.from_text(question.name, 60, 'IN', 'CNAME', target))
    response.answer.extend(answer.answer)
    return response
